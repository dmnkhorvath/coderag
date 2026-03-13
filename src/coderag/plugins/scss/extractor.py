"""SCSS AST extractor for CodeRAG.

Uses tree-sitter-scss to parse SCSS/Sass source files and extract
knowledge-graph nodes and edges. SCSS is a superset of CSS, so this
extractor handles all CSS constructs plus SCSS-specific features:
variables, mixins, functions, placeholders, @use/@forward, nesting.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import tree_sitter
import tree_sitter_scss as tsscss

from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionError,
    ExtractionResult,
    Node,
    NodeKind,
    UnresolvedReference,
    compute_content_hash,
    generate_node_id,
)
from coderag.core.registry import ASTExtractor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

import warnings as _warnings

_warnings.filterwarnings("ignore", category=DeprecationWarning, module="tree_sitter")

_SCSS_LANGUAGE = tree_sitter.Language(tsscss.language())


def _child_by_type(node, type_name: str):
    """Find first child with given type (tree-sitter CSS/SCSS has no field names)."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _get_declaration_value_text(decl_node, source: bytes) -> str:
    """Get the value text from a declaration node (everything after property_name)."""
    found_prop = False
    parts = []
    for child in decl_node.children:
        if child.type == "property_name":
            found_prop = True
            continue
        if found_prop and child.type not in (":", ";"):
            parts.append(_node_text(child, source))
    return " ".join(parts)


def _get_declaration_value_node(decl_node):
    """Get the first value node from a declaration (after property_name and colon)."""
    found_colon = False
    for child in decl_node.children:
        if child.type == ":":
            found_colon = True
            continue
        if found_colon and child.type != ";":
            return child
    return None


# Regex patterns
_VAR_REFERENCE_RE = re.compile(r"var\(\s*(--[\w-]+)")
_CUSTOM_PROP_RE = re.compile(r"^--[\w-]+$")
_SCSS_VAR_RE = re.compile(r"^\$[\w-]+$")
_NAMESPACED_VAR_RE = re.compile(r"([\w-]+)\.\$(\w[\w-]*)")
_USE_AS_RE = re.compile(r"""@use\s+['"]([^'"]+)['"]\s+as\s+(\*|[\w-]+)""")
_FORWARD_RE = re.compile(r"""@forward\s+['"]([^'"]+)['"]""")
_EXTEND_PLACEHOLDER_RE = re.compile(r"@extend\s+%([\w-]+)")
_ANIMATION_NAME_RE = re.compile(r"animation(?:-name)?\s*:\s*([\w-]+)")

# Built-in SCSS functions to skip
_BUILTIN_FUNCTIONS = frozenset(
    {
        "rgb",
        "rgba",
        "hsl",
        "hsla",
        "red",
        "green",
        "blue",
        "mix",
        "lighten",
        "darken",
        "saturate",
        "desaturate",
        "grayscale",
        "complement",
        "invert",
        "alpha",
        "opacity",
        "adjust-hue",
        "adjust-color",
        "scale-color",
        "change-color",
        "ie-hex-str",
        "unquote",
        "quote",
        "str-length",
        "str-insert",
        "str-index",
        "str-slice",
        "to-upper-case",
        "to-lower-case",
        "percentage",
        "round",
        "ceil",
        "floor",
        "abs",
        "min",
        "max",
        "random",
        "unit",
        "unitless",
        "comparable",
        "length",
        "nth",
        "set-nth",
        "join",
        "append",
        "zip",
        "index",
        "list-separator",
        "is-bracketed",
        "map-get",
        "map-merge",
        "map-remove",
        "map-keys",
        "map-values",
        "map-has-key",
        "type-of",
        "inspect",
        "variable-exists",
        "global-variable-exists",
        "function-exists",
        "mixin-exists",
        "content-exists",
        "get-function",
        "call",
        "unique-id",
        "if",
        "feature-exists",
        "selector-nest",
        "selector-append",
        "selector-extend",
        "selector-replace",
        "selector-unify",
        "is-superselector",
        "simple-selectors",
        "selector-parse",
        # CSS built-in functions
        "url",
        "var",
        "calc",
        "env",
        "attr",
        "counter",
        "counters",
        "linear-gradient",
        "radial-gradient",
        "conic-gradient",
        "repeating-linear-gradient",
        "repeating-radial-gradient",
        "image-set",
        "cross-fade",
        "element",
        "translate",
        "translateX",
        "translateY",
        "translateZ",
        "rotate",
        "rotateX",
        "rotateY",
        "rotateZ",
        "scale",
        "scaleX",
        "scaleY",
        "scaleZ",
        "skew",
        "skewX",
        "skewY",
        "matrix",
        "matrix3d",
        "perspective",
        "cubic-bezier",
        "steps",
        "clamp",
        "minmax",
        "repeat",
        "fit-content",
        "color",
        "color-mix",
        "oklch",
        "oklab",
        "lab",
        "lch",
        "light-dark",
    }
)

# Skip thresholds
_MAX_FILE_SIZE = 500 * 1024  # 500KB
_MAX_SINGLE_LINE_SIZE = 10 * 1024  # 10KB


class _SCSSExtractionContext:
    """Mutable state passed through the SCSS extraction walk."""

    __slots__ = (
        "file_path",
        "source",
        "source_text",
        "file_node_id",
        "nodes",
        "edges",
        "errors",
        "unresolved",
        "custom_props",
        "keyframes_names",
        "scss_variables",
        "scss_mixins",
        "scss_functions",
        "scss_placeholders",
        "use_namespaces",
    )

    def __init__(
        self,
        file_path: str,
        source: bytes,
        file_node_id: str,
    ) -> None:
        self.file_path = file_path
        self.source = source
        self.source_text = source.decode("utf-8", errors="replace")
        self.file_node_id = file_node_id
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.errors: list[ExtractionError] = []
        self.unresolved: list[UnresolvedReference] = []
        # CSS custom properties
        self.custom_props: dict[str, str] = {}  # --name -> node_id
        self.keyframes_names: dict[str, str] = {}  # name -> node_id
        # SCSS definitions
        self.scss_variables: dict[str, str] = {}  # $name -> node_id
        self.scss_mixins: dict[str, str] = {}  # name -> node_id
        self.scss_functions: dict[str, str] = {}  # name -> node_id
        self.scss_placeholders: dict[str, str] = {}  # name -> node_id
        # @use namespace tracking: namespace -> module_path
        self.use_namespaces: dict[str, str] = {}


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    """Extract text content of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _is_minified(source: bytes) -> bool:
    """Detect minified CSS/SCSS."""
    first_newline = source.find(b"\n")
    if first_newline == -1:
        return len(source) > _MAX_SINGLE_LINE_SIZE
    return first_newline > _MAX_SINGLE_LINE_SIZE


class SCSSExtractor(ASTExtractor):
    """Extracts nodes and edges from SCSS files using tree-sitter."""

    def __init__(self) -> None:
        self._parser = tree_sitter.Parser(_SCSS_LANGUAGE)

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Extract nodes and edges from an SCSS source file."""
        t0 = time.perf_counter()

        if len(source) > _MAX_FILE_SIZE:
            return ExtractionResult(
                file_path=file_path,
                language="scss",
                errors=[
                    ExtractionError(
                        file_path=file_path,
                        line_number=None,
                        message=f"File too large ({len(source)} bytes), skipped",
                        severity="warning",
                    )
                ],
                parse_time_ms=(time.perf_counter() - t0) * 1000,
            )

        if _is_minified(source):
            return ExtractionResult(
                file_path=file_path,
                language="scss",
                errors=[
                    ExtractionError(
                        file_path=file_path,
                        line_number=None,
                        message="Minified SCSS detected, skipped",
                        severity="warning",
                    )
                ],
                parse_time_ms=(time.perf_counter() - t0) * 1000,
            )

        tree = self._parser.parse(source)
        root = tree.root_node

        file_node_id = generate_node_id(file_path, 1, NodeKind.FILE, file_path)
        file_node = Node(
            id=file_node_id,
            kind=NodeKind.FILE,
            name=file_path.rsplit("/", 1)[-1],
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=root.end_point[0] + 1,
            language="scss",
            content_hash=compute_content_hash(source),
        )

        ctx = _SCSSExtractionContext(file_path, source, file_node_id)
        ctx.nodes.append(file_node)

        self._collect_errors(root, file_path, ctx.errors)

        # First pass: extract @use/@forward for namespace tracking
        self._extract_use_forward_regex(ctx)

        # Walk the stylesheet
        self._walk_stylesheet(root, ctx)

        # Second pass: resolve intra-file references
        self._resolve_intra_file_refs(ctx)

        elapsed = (time.perf_counter() - t0) * 1000
        return ExtractionResult(
            file_path=file_path,
            language="scss",
            nodes=ctx.nodes,
            edges=ctx.edges,
            unresolved_references=ctx.unresolved,
            errors=ctx.errors,
            parse_time_ms=elapsed,
        )

    def supported_node_kinds(self) -> frozenset[NodeKind]:
        return frozenset(
            {
                NodeKind.FILE,
                # CSS kinds
                NodeKind.CSS_CLASS,
                NodeKind.CSS_ID,
                NodeKind.CSS_VARIABLE,
                NodeKind.CSS_KEYFRAMES,
                NodeKind.CSS_MEDIA_QUERY,
                NodeKind.CSS_LAYER,
                NodeKind.CSS_FONT_FACE,
                NodeKind.IMPORT,
                # SCSS kinds
                NodeKind.SCSS_VARIABLE,
                NodeKind.SCSS_MIXIN,
                NodeKind.SCSS_FUNCTION,
                NodeKind.SCSS_PLACEHOLDER,
            }
        )

    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        return frozenset(
            {
                EdgeKind.CONTAINS,
                EdgeKind.IMPORTS,
                EdgeKind.CSS_USES_VARIABLE,
                EdgeKind.CSS_MEDIA_CONTAINS,
                EdgeKind.CSS_LAYER_CONTAINS,
                EdgeKind.CSS_KEYFRAMES_USED_BY,
                EdgeKind.SCSS_INCLUDES_MIXIN,
                EdgeKind.SCSS_EXTENDS,
                EdgeKind.SCSS_USES_VARIABLE,
                EdgeKind.SCSS_USES_FUNCTION,
                EdgeKind.SCSS_FORWARDS,
                EdgeKind.SCSS_NESTS,
            }
        )

    # -- Error collection ---------------------------------------------------

    def _collect_errors(
        self,
        node: tree_sitter.Node,
        file_path: str,
        errors: list[ExtractionError],
    ) -> None:
        if node.type == "ERROR" or node.is_missing:
            errors.append(
                ExtractionError(
                    file_path=file_path,
                    line_number=node.start_point[0] + 1,
                    message=f"Parse error at line {node.start_point[0] + 1}",
                    node_type=node.type,
                )
            )
        for child in node.children:
            self._collect_errors(child, file_path, errors)

    # -- Regex-based @use/@forward extraction --------------------------------

    def _extract_use_forward_regex(self, ctx: _SCSSExtractionContext) -> None:
        """Extract @use and @forward statements using regex.

        tree-sitter-scss has issues parsing `@use ... as namespace`,
        so we use regex as a reliable fallback for namespace tracking.
        """
        for match in _USE_AS_RE.finditer(ctx.source_text):
            module_path = match.group(1)
            namespace = match.group(2)
            if namespace != "*":
                ctx.use_namespaces[namespace] = module_path
            # Also track the default namespace (last segment of path)
            default_ns = module_path.rsplit("/", 1)[-1].lstrip("_")
            if default_ns.endswith((".scss", ".sass", ".css")):
                default_ns = default_ns.rsplit(".", 1)[0]
            if namespace == "*":
                ctx.use_namespaces["*"] = module_path
            else:
                ctx.use_namespaces[namespace] = module_path

    # -- Stylesheet walk ----------------------------------------------------

    def _walk_stylesheet(
        self,
        root: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
    ) -> None:
        for child in root.children:
            self._handle_node(child, ctx, ctx.file_node_id)

    def _handle_node(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Dispatch a node to the appropriate handler."""
        ntype = node.type
        if ntype == "rule_set":
            self._handle_rule_set(node, ctx, parent_id)
        elif ntype == "declaration":
            self._handle_declaration(node, ctx, parent_id)
        elif ntype == "import_statement":
            self._handle_import(node, ctx, parent_id)
        elif ntype == "use_statement":
            self._handle_use(node, ctx, parent_id)
        elif ntype == "forward_statement":
            self._handle_forward(node, ctx, parent_id)
        elif ntype == "mixin_statement":
            self._handle_mixin_def(node, ctx, parent_id)
        elif ntype == "function_statement":
            self._handle_function_def(node, ctx, parent_id)
        elif ntype == "include_statement":
            self._handle_include(node, ctx, parent_id)
        elif ntype == "extend_statement":
            self._handle_extend(node, ctx, parent_id)
        elif ntype == "keyframes_statement":
            self._handle_keyframes(node, ctx, parent_id)
        elif ntype == "media_statement":
            self._handle_media(node, ctx, parent_id)
        elif ntype == "at_rule":
            self._handle_at_rule(node, ctx, parent_id)
        elif ntype == "for_statement":
            self._handle_control_block(node, ctx, parent_id)
        elif ntype == "each_statement":
            self._handle_control_block(node, ctx, parent_id)
        elif ntype == "while_statement":
            self._handle_control_block(node, ctx, parent_id)
        elif ntype == "if_statement":
            self._handle_control_block(node, ctx, parent_id)
        elif ntype == "ERROR":
            # Try regex-based extraction from ERROR nodes
            self._handle_error_node(node, ctx, parent_id)

    # -- Rule set handling --------------------------------------------------

    def _handle_rule_set(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        selectors_node = _child_by_type(node, "selectors")
        _child_by_type(node, "block")

        selector_ids: list[str] = []
        if selectors_node is not None:
            selector_ids = self._extract_selectors(
                selectors_node,
                node,
                ctx,
                parent_id,
            )

        # Collect all walkable children from block AND ERROR nodes
        walkable_children: list[tree_sitter.Node] = []
        for child in node.children:
            if child.type == "block":
                walkable_children.extend(child.children)
            elif child.type == "ERROR":
                # ERROR nodes may contain valid statements (tree-sitter-scss limitation)
                walkable_children.extend(child.children)

        for child in walkable_children:
            if child.type == "rule_set":
                # Nested rule - create nesting edges
                self._handle_nested_rule(
                    child,
                    ctx,
                    parent_id,
                    selector_ids,
                )
            elif child.type == "declaration":
                self._handle_declaration(child, ctx, parent_id)
            elif child.type in (
                "include_statement",
                "extend_statement",
                "mixin_statement",
                "function_statement",
                "for_statement",
                "each_statement",
                "while_statement",
                "if_statement",
            ):
                self._handle_node(child, ctx, parent_id)
            elif child.type == "ERROR":
                self._handle_error_node(child, ctx, parent_id)

    def _extract_selectors(
        self,
        selectors_node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> list[str]:
        """Walk selector tree and return IDs of created selector nodes."""
        ids: list[str] = []
        self._walk_for_selectors(
            selectors_node,
            rule_node,
            ctx,
            parent_id,
            ids,
        )
        return ids

    def _walk_for_selectors(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
        ids: list[str],
    ) -> None:
        if node.type == "class_selector":
            nid = self._handle_class_selector(node, rule_node, ctx, parent_id)
            if nid:
                ids.append(nid)
        elif node.type == "id_selector":
            nid = self._handle_id_selector(node, rule_node, ctx, parent_id)
            if nid:
                ids.append(nid)
        elif node.type == "placeholder":
            nid = self._handle_placeholder_def(node, rule_node, ctx, parent_id)
            if nid:
                ids.append(nid)

        for child in node.children:
            self._walk_for_selectors(child, rule_node, ctx, parent_id, ids)

    def _handle_class_selector(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> str | None:
        text = _node_text(node, ctx.source)
        # Skip nesting selectors like &__child
        if text.startswith("&"):
            return None
        name = text.lstrip(".")
        if not name:
            return None

        line = node.start_point[0] + 1
        node_id = generate_node_id(ctx.file_path, line, NodeKind.CSS_CLASS, name)

        source_text = _node_text(rule_node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_CLASS,
                name=f".{name}",
                qualified_name=f".{name}",
                file_path=ctx.file_path,
                start_line=rule_node.start_point[0] + 1,
                end_line=rule_node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        return node_id

    def _handle_id_selector(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> str | None:
        text = _node_text(node, ctx.source)
        name = text.lstrip("#")
        if not name:
            return None

        line = node.start_point[0] + 1
        node_id = generate_node_id(ctx.file_path, line, NodeKind.CSS_ID, name)

        source_text = _node_text(rule_node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_ID,
                name=f"#{name}",
                qualified_name=f"#{name}",
                file_path=ctx.file_path,
                start_line=rule_node.start_point[0] + 1,
                end_line=rule_node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        return node_id

    def _handle_placeholder_def(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> str | None:
        """Handle %placeholder selector definition."""
        # placeholder node has children: % and identifier
        name = None
        for child in node.children:
            if child.type == "identifier":
                name = _node_text(child, ctx.source)
                break
        if not name:
            text = _node_text(node, ctx.source)
            name = text.lstrip("%")
        if not name:
            return None

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.SCSS_PLACEHOLDER,
            name,
        )

        source_text = _node_text(rule_node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.SCSS_PLACEHOLDER,
                name=f"%{name}",
                qualified_name=f"%{name}",
                file_path=ctx.file_path,
                start_line=rule_node.start_point[0] + 1,
                end_line=rule_node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.scss_placeholders[name] = node_id
        return node_id

    def _handle_nested_rule(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
        parent_selector_ids: list[str],
    ) -> list[str]:
        """Handle a nested rule_set and create SCSS_NESTS edges."""
        selectors_node = _child_by_type(node, "selectors")
        block_node = _child_by_type(node, "block")

        child_ids: list[str] = []
        if selectors_node is not None:
            child_ids = self._extract_selectors(
                selectors_node,
                node,
                ctx,
                parent_id,
            )

        # Create nesting edges from parent selectors to child selectors
        for pid in parent_selector_ids:
            for cid in child_ids:
                ctx.edges.append(
                    Edge(
                        source_id=pid,
                        target_id=cid,
                        kind=EdgeKind.SCSS_NESTS,
                        confidence=1.0,
                        line_number=node.start_point[0] + 1,
                    )
                )

        # Walk nested block
        if block_node is not None:
            for child in block_node.children:
                if child.type == "rule_set":
                    self._handle_nested_rule(child, ctx, parent_id, child_ids)
                elif child.type == "declaration":
                    self._handle_declaration(child, ctx, parent_id)
                elif child.type in (
                    "include_statement",
                    "extend_statement",
                    "for_statement",
                    "each_statement",
                    "while_statement",
                    "if_statement",
                ):
                    self._handle_node(child, ctx, parent_id)
                elif child.type == "ERROR":
                    self._handle_error_node(child, ctx, parent_id)

        return child_ids

    # -- Declaration handling -----------------------------------------------

    def _handle_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        prop_node = _child_by_type(node, "property_name")
        if prop_node is None:
            return

        prop_name = _node_text(prop_node, ctx.source).strip()

        # SCSS variable definition: $variable: value
        if prop_name.startswith("$"):
            self._handle_scss_variable_def(node, prop_name, ctx, parent_id)
            return

        # CSS custom property: --variable: value
        if _CUSTOM_PROP_RE.match(prop_name):
            self._handle_custom_property(node, prop_name, ctx, parent_id)
            return

        # Scan value for references
        self._scan_value_for_refs(node, prop_name, ctx)

    def _handle_scss_variable_def(
        self,
        node: tree_sitter.Node,
        var_name: str,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Create an SCSS_VARIABLE node for a $variable definition."""
        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.SCSS_VARIABLE,
            var_name,
        )

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.SCSS_VARIABLE,
                name=var_name,
                qualified_name=var_name,
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.scss_variables[var_name] = node_id

        # Scan the value side for variable references
        self._scan_value_for_refs(node, var_name, ctx)

    def _handle_custom_property(
        self,
        node: tree_sitter.Node,
        prop_name: str,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_VARIABLE,
            prop_name,
        )

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_VARIABLE,
                name=prop_name,
                qualified_name=prop_name,
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.custom_props[prop_name] = node_id

    def _scan_value_for_refs(
        self,
        decl_node: tree_sitter.Node,
        prop_name: str,
        ctx: _SCSSExtractionContext,
    ) -> None:
        """Scan a declaration value for variable, function, and animation refs."""
        # Walk the value subtree for variable and call_expression nodes
        self._walk_for_value_refs(decl_node, ctx)

        # Also check for animation-name references
        if prop_name in ("animation", "animation-name"):
            value_node = _get_declaration_value_node(decl_node)
            if value_node:
                value_text = _node_text(value_node, ctx.source)
                self._extract_animation_ref(value_text, decl_node, ctx)

    def _walk_for_value_refs(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
    ) -> None:
        """Recursively walk for variable and function references in values."""
        if node.type == "variable":
            var_name = _node_text(node, ctx.source)
            if _SCSS_VAR_RE.match(var_name):
                line = node.start_point[0] + 1
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=ctx.file_node_id,
                        reference_name=var_name,
                        reference_kind=EdgeKind.SCSS_USES_VARIABLE,
                        line_number=line,
                        context={"type": "scss_var_reference"},
                    )
                )
        elif node.type == "call_expression":
            self._handle_function_call(node, ctx)
        elif node.type == "plain_value":
            # Check for namespaced variable references: namespace.$var
            text = _node_text(node, ctx.source)
            for match in _NAMESPACED_VAR_RE.finditer(text):
                ns = match.group(1)
                var = match.group(2)
                line = node.start_point[0] + 1
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=ctx.file_node_id,
                        reference_name=f"${var}",
                        reference_kind=EdgeKind.SCSS_USES_VARIABLE,
                        line_number=line,
                        context={
                            "type": "scss_namespaced_var",
                            "namespace": ns,
                        },
                    )
                )
            # Check for var() references
            for match in _VAR_REFERENCE_RE.finditer(text):
                var_name = match.group(1)
                line = node.start_point[0] + 1
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=ctx.file_node_id,
                        reference_name=var_name,
                        reference_kind=EdgeKind.CSS_USES_VARIABLE,
                        line_number=line,
                        context={"type": "css_var_reference"},
                    )
                )

        for child in node.children:
            self._walk_for_value_refs(child, ctx)

    def _handle_function_call(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
    ) -> None:
        """Handle a function call in a value expression."""
        fn_name_node = None
        for child in node.children:
            if child.type == "function_name":
                fn_name_node = child
                break

        if fn_name_node is None:
            return

        fn_name = _node_text(fn_name_node, ctx.source).strip()

        # Skip built-in functions
        if fn_name.lower() in _BUILTIN_FUNCTIONS:
            # But still check var() for CSS variable references
            if fn_name == "var":
                args_text = _node_text(node, ctx.source)
                for match in _VAR_REFERENCE_RE.finditer(args_text):
                    var_name = match.group(1)
                    line = node.start_point[0] + 1
                    ctx.unresolved.append(
                        UnresolvedReference(
                            source_node_id=ctx.file_node_id,
                            reference_name=var_name,
                            reference_kind=EdgeKind.CSS_USES_VARIABLE,
                            line_number=line,
                            context={"type": "css_var_reference"},
                        )
                    )
            return

        line = node.start_point[0] + 1
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.file_node_id,
                reference_name=fn_name,
                reference_kind=EdgeKind.SCSS_USES_FUNCTION,
                line_number=line,
                context={"type": "scss_function_call"},
            )
        )

    def _extract_animation_ref(
        self,
        value_text: str,
        decl_node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
    ) -> None:
        css_anim_keywords = {
            "none",
            "initial",
            "inherit",
            "unset",
            "revert",
            "ease",
            "linear",
            "ease-in",
            "ease-out",
            "ease-in-out",
            "infinite",
            "alternate",
            "reverse",
            "normal",
            "forwards",
            "backwards",
            "both",
            "running",
            "paused",
        }
        tokens = value_text.strip().split()
        for token in tokens:
            clean = token.rstrip(",;")
            if clean and clean not in css_anim_keywords and not clean[0].isdigit():
                if re.match(r"^[\d.]+(?:s|ms)$", clean):
                    continue
                if clean.startswith("$"):
                    continue  # SCSS variable, handled elsewhere
                line = decl_node.start_point[0] + 1
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=ctx.file_node_id,
                        reference_name=clean,
                        reference_kind=EdgeKind.CSS_KEYFRAMES_USED_BY,
                        line_number=line,
                        context={"type": "animation_name_reference"},
                    )
                )
                break

    # -- @use handling ------------------------------------------------------

    def _handle_use(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @use statement."""
        line = node.start_point[0] + 1
        # Extract path from string_value child
        path = self._extract_string_value(node, ctx.source)
        if not path:
            # Fallback: regex on full text
            text = _node_text(node, ctx.source)
            m = re.search(r"""@use\s+['"]([^'"]+)['"]""", text)
            if m:
                path = m.group(1)
        if not path:
            return

        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.IMPORT,
            f"@use {path}",
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.IMPORT,
                name=f"@use '{path}'",
                qualified_name=f"@use '{path}'",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=_node_text(node, ctx.source),
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=node_id,
                reference_name=path,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"type": "scss_use"},
            )
        )

    # -- @forward handling --------------------------------------------------

    def _handle_forward(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @forward statement."""
        line = node.start_point[0] + 1
        path = self._extract_string_value(node, ctx.source)
        if not path:
            text = _node_text(node, ctx.source)
            m = _FORWARD_RE.search(text)
            if m:
                path = m.group(1)
        if not path:
            return

        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.IMPORT,
            f"@forward {path}",
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.IMPORT,
                name=f"@forward '{path}'",
                qualified_name=f"@forward '{path}'",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=_node_text(node, ctx.source),
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=node_id,
                reference_name=path,
                reference_kind=EdgeKind.SCSS_FORWARDS,
                line_number=line,
                context={"type": "scss_forward"},
            )
        )

    # -- @import handling ---------------------------------------------------

    def _handle_import(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @import statement (legacy SCSS import)."""
        line = node.start_point[0] + 1
        path = self._extract_string_value(node, ctx.source)
        if not path:
            # Try call_expression for url()
            for child in node.children:
                if child.type == "call_expression":
                    text = _node_text(child, ctx.source)
                    m = re.search(r"""url\(['"]?([^'")]+)['"]?\)""", text)
                    if m:
                        path = m.group(1)
                        break
        if not path:
            return

        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.IMPORT,
            path,
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.IMPORT,
                name=path,
                qualified_name=path,
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=_node_text(node, ctx.source),
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=node_id,
                reference_name=path,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"type": "scss_import_legacy"},
            )
        )

    # -- @mixin handling ----------------------------------------------------

    def _handle_mixin_def(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @mixin definition."""
        name = None
        params_text = None
        for child in node.children:
            if child.type == "identifier":
                name = _node_text(child, ctx.source)
            elif child.type == "parameters":
                params_text = _node_text(child, ctx.source)

        if not name:
            return

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.SCSS_MIXIN,
            name,
        )

        display_name = f"@mixin {name}"
        if params_text:
            display_name += params_text

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.SCSS_MIXIN,
                name=display_name,
                qualified_name=f"@mixin {name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.scss_mixins[name] = node_id

        # Walk mixin body for nested definitions
        block_node = None
        for child in node.children:
            if child.type == "block":
                block_node = child
                break
        if block_node:
            for child in block_node.children:
                if child.type in ("declaration", "rule_set"):
                    self._handle_node(child, ctx, node_id)

    # -- @function handling -------------------------------------------------

    def _handle_function_def(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @function definition."""
        name = None
        params_text = None
        for child in node.children:
            if child.type == "identifier":
                name = _node_text(child, ctx.source)
            elif child.type == "parameters":
                params_text = _node_text(child, ctx.source)

        if not name:
            return

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.SCSS_FUNCTION,
            name,
        )

        display_name = f"@function {name}"
        if params_text:
            display_name += params_text

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.SCSS_FUNCTION,
                name=display_name,
                qualified_name=f"@function {name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.scss_functions[name] = node_id

    # -- @include handling --------------------------------------------------

    def _handle_include(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @include mixin-name."""
        name = None
        for child in node.children:
            if child.type == "identifier":
                name = _node_text(child, ctx.source)
                break

        if not name:
            return

        line = node.start_point[0] + 1
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.file_node_id,
                reference_name=name,
                reference_kind=EdgeKind.SCSS_INCLUDES_MIXIN,
                line_number=line,
                context={"type": "scss_include"},
            )
        )

    # -- @extend handling ---------------------------------------------------

    def _handle_extend(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @extend .class or @extend %placeholder."""
        line = node.start_point[0] + 1
        target_name = None
        target_type = None

        for child in node.children:
            if child.type == "class_selector":
                target_name = _node_text(child, ctx.source)
                target_type = "class"
                break
            elif child.type == "placeholder":
                name_part = None
                for gc in child.children:
                    if gc.type == "identifier":
                        name_part = _node_text(gc, ctx.source)
                        break
                if name_part:
                    target_name = f"%{name_part}"
                else:
                    target_name = _node_text(child, ctx.source)
                target_type = "placeholder"
                break

        if not target_name:
            # Fallback: regex on full text
            text = _node_text(node, ctx.source)
            m = _EXTEND_PLACEHOLDER_RE.search(text)
            if m:
                target_name = f"%{m.group(1)}"
                target_type = "placeholder"
            else:
                m = re.search(r"@extend\s+(\.\S+)", text)
                if m:
                    target_name = m.group(1)
                    target_type = "class"

        if not target_name:
            return

        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.file_node_id,
                reference_name=target_name,
                reference_kind=EdgeKind.SCSS_EXTENDS,
                line_number=line,
                context={"type": f"scss_extend_{target_type or 'unknown'}"},
            )
        )

    # -- @keyframes handling ------------------------------------------------

    def _handle_keyframes(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        name_node = None
        for child in node.children:
            if child.type in ("keyframes_name", "identifier"):
                name_node = child
                break

        if name_node is None:
            return

        name = _node_text(name_node, ctx.source).strip()
        if not name:
            return

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_KEYFRAMES,
            name,
        )

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_KEYFRAMES,
                name=f"@keyframes {name}",
                qualified_name=f"@keyframes {name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.keyframes_names[name] = node_id

    # -- @media handling ----------------------------------------------------

    def _handle_media(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        condition_parts = []
        block_node = None
        for child in node.children:
            if child.type == "block":
                block_node = child
                break
            elif child.type not in ("@media", ";"):
                condition_parts.append(_node_text(child, ctx.source))

        condition = " ".join(condition_parts).strip() or "(unknown)"

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_MEDIA_QUERY,
            condition,
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_MEDIA_QUERY,
                name=f"@media {condition}",
                qualified_name=f"@media {condition}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        if block_node is not None:
            for child in block_node.children:
                self._handle_node(child, ctx, node_id)

    # -- @layer / @font-face handling ---------------------------------------

    def _handle_at_rule(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        keyword_node = None
        for child in node.children:
            if child.type == "at_keyword":
                keyword_node = child
                break

        if keyword_node is None:
            return

        keyword = _node_text(keyword_node, ctx.source).strip()
        if keyword == "@layer":
            self._handle_layer(node, ctx, parent_id)
        elif keyword == "@font-face":
            self._handle_font_face(node, ctx, parent_id)

    def _handle_layer(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        name = None
        block_node = None
        for child in node.children:
            if child.type == "keyword_query":
                name = _node_text(child, ctx.source).strip()
            elif child.type == "block":
                block_node = child

        if not name:
            name = "(anonymous)"

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_LAYER,
            name,
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_LAYER,
                name=f"@layer {name}",
                qualified_name=f"@layer {name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        if block_node is not None:
            for child in block_node.children:
                self._handle_node(child, ctx, node_id)

    def _handle_font_face(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        font_name = "(unnamed)"
        block_node = None
        for child in node.children:
            if child.type == "block":
                block_node = child
                break

        if block_node is not None:
            for child in block_node.children:
                if child.type == "declaration":
                    prop = _child_by_type(child, "property_name")
                    if prop and _node_text(prop, ctx.source).strip() == "font-family":
                        val = _get_declaration_value_node(child)
                        if val:
                            font_name = _node_text(val, ctx.source).strip().strip("'\"")
                            break

        line = node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_FONT_FACE,
            font_name,
        )

        source_text = _node_text(node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_FONT_FACE,
                name=f"@font-face {font_name}",
                qualified_name=f"@font-face {font_name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="scss",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

    # -- Control flow blocks ------------------------------------------------

    def _handle_control_block(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @for, @each, @while, @if blocks - walk their children."""
        for child in node.children:
            if child.type == "block":
                for gc in child.children:
                    self._handle_node(gc, ctx, parent_id)
            elif child.type == "else_clause":
                for gc in child.children:
                    if gc.type == "block":
                        for ggc in gc.children:
                            self._handle_node(ggc, ctx, parent_id)

    # -- ERROR node handling ------------------------------------------------

    def _handle_error_node(
        self,
        node: tree_sitter.Node,
        ctx: _SCSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Try to extract useful info from ERROR nodes using regex."""
        text = _node_text(node, ctx.source)
        line = node.start_point[0] + 1

        # Check for @extend %placeholder (common ERROR case)
        m = _EXTEND_PLACEHOLDER_RE.search(text)
        if m:
            target_name = f"%{m.group(1)}"
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=ctx.file_node_id,
                    reference_name=target_name,
                    reference_kind=EdgeKind.SCSS_EXTENDS,
                    line_number=line,
                    context={"type": "scss_extend_placeholder"},
                )
            )
            return

        # Check for @include in ERROR nodes
        m = re.search(r"@include\s+([\w-]+)", text)
        if m:
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=ctx.file_node_id,
                    reference_name=m.group(1),
                    reference_kind=EdgeKind.SCSS_INCLUDES_MIXIN,
                    line_number=line,
                    context={"type": "scss_include_from_error"},
                )
            )

    # -- Utility methods ----------------------------------------------------

    def _extract_string_value(
        self,
        node: tree_sitter.Node,
        source: bytes,
    ) -> str | None:
        """Extract path from a string_value child node."""
        for child in node.children:
            if child.type == "string_value":
                text = _node_text(child, source)
                return text.strip("'\"").strip()
        return None

    # -- Intra-file resolution ----------------------------------------------

    def _resolve_intra_file_refs(
        self,
        ctx: _SCSSExtractionContext,
    ) -> None:
        """Resolve references within the same file."""
        remaining: list[UnresolvedReference] = []
        for ref in ctx.unresolved:
            resolved = False
            kind = ref.reference_kind

            if kind == EdgeKind.SCSS_USES_VARIABLE:
                target_id = ctx.scss_variables.get(ref.reference_name)
                if target_id:
                    ctx.edges.append(
                        Edge(
                            source_id=ref.source_node_id,
                            target_id=target_id,
                            kind=EdgeKind.SCSS_USES_VARIABLE,
                            confidence=0.9,
                            line_number=ref.line_number,
                        )
                    )
                    resolved = True

            elif kind == EdgeKind.CSS_USES_VARIABLE:
                target_id = ctx.custom_props.get(ref.reference_name)
                if target_id:
                    ctx.edges.append(
                        Edge(
                            source_id=ref.source_node_id,
                            target_id=target_id,
                            kind=EdgeKind.CSS_USES_VARIABLE,
                            confidence=0.9,
                            line_number=ref.line_number,
                        )
                    )
                    resolved = True

            elif kind == EdgeKind.SCSS_INCLUDES_MIXIN:
                target_id = ctx.scss_mixins.get(ref.reference_name)
                if target_id:
                    ctx.edges.append(
                        Edge(
                            source_id=ref.source_node_id,
                            target_id=target_id,
                            kind=EdgeKind.SCSS_INCLUDES_MIXIN,
                            confidence=0.9,
                            line_number=ref.line_number,
                        )
                    )
                    resolved = True

            elif kind == EdgeKind.SCSS_USES_FUNCTION:
                target_id = ctx.scss_functions.get(ref.reference_name)
                if target_id:
                    ctx.edges.append(
                        Edge(
                            source_id=ref.source_node_id,
                            target_id=target_id,
                            kind=EdgeKind.SCSS_USES_FUNCTION,
                            confidence=0.9,
                            line_number=ref.line_number,
                        )
                    )
                    resolved = True

            elif kind == EdgeKind.SCSS_EXTENDS:
                name = ref.reference_name
                if name.startswith("%"):
                    target_id = ctx.scss_placeholders.get(name.lstrip("%"))
                    if target_id:
                        ctx.edges.append(
                            Edge(
                                source_id=ref.source_node_id,
                                target_id=target_id,
                                kind=EdgeKind.SCSS_EXTENDS,
                                confidence=0.9,
                                line_number=ref.line_number,
                            )
                        )
                        resolved = True

            elif kind == EdgeKind.CSS_KEYFRAMES_USED_BY:
                target_id = ctx.keyframes_names.get(ref.reference_name)
                if target_id:
                    ctx.edges.append(
                        Edge(
                            source_id=ref.source_node_id,
                            target_id=target_id,
                            kind=EdgeKind.CSS_KEYFRAMES_USED_BY,
                            confidence=0.85,
                            line_number=ref.line_number,
                        )
                    )
                    resolved = True

            if not resolved:
                remaining.append(ref)

        ctx.unresolved = remaining
