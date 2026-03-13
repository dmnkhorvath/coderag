"""CSS AST extractor for CodeRAG.

Uses tree-sitter-css to parse CSS source files and extract
knowledge-graph nodes and edges.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import tree_sitter
import tree_sitter_css as tscss

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

# Pre-compile the CSS language and create a thread-local parser factory
_CSS_LANGUAGE = tree_sitter.Language(tscss.language())


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
_ANIMATION_NAME_RE = re.compile(r"animation(?:-name)?\s*:\s*([\w-]+)")
_URL_PATH_RE = re.compile(r"""url\(['"]?([^'")]+)['"]?\)""")

# Skip thresholds
_MAX_FILE_SIZE = 500 * 1024  # 500KB
_MAX_SINGLE_LINE_SIZE = 10 * 1024  # 10KB


class _CSSExtractionContext:
    """Mutable state passed through the CSS extraction walk."""

    __slots__ = (
        "file_path",
        "source",
        "file_node_id",
        "nodes",
        "edges",
        "errors",
        "unresolved",
        "custom_props",
        "keyframes_names",
    )

    def __init__(
        self,
        file_path: str,
        source: bytes,
        file_node_id: str,
    ) -> None:
        self.file_path = file_path
        self.source = source
        self.file_node_id = file_node_id
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.errors: list[ExtractionError] = []
        self.unresolved: list[UnresolvedReference] = []
        # Track definitions for intra-file resolution
        self.custom_props: dict[str, str] = {}  # --name -> node_id
        self.keyframes_names: dict[str, str] = {}  # name -> node_id


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    """Extract text content of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _is_minified(source: bytes) -> bool:
    """Detect minified CSS (single-line files > threshold)."""
    first_newline = source.find(b"\n")
    if first_newline == -1:
        return len(source) > _MAX_SINGLE_LINE_SIZE
    # Check if first line is very long (minified)
    return first_newline > _MAX_SINGLE_LINE_SIZE


class CSSExtractor(ASTExtractor):
    """Extracts nodes and edges from CSS files using tree-sitter."""

    def __init__(self) -> None:
        self._parser = tree_sitter.Parser(_CSS_LANGUAGE)

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Extract nodes and edges from a CSS source file."""
        t0 = time.perf_counter()

        # Skip oversized or minified files
        if len(source) > _MAX_FILE_SIZE:
            return ExtractionResult(
                file_path=file_path,
                language="css",
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
                language="css",
                errors=[
                    ExtractionError(
                        file_path=file_path,
                        line_number=None,
                        message="Minified CSS detected, skipped",
                        severity="warning",
                    )
                ],
                parse_time_ms=(time.perf_counter() - t0) * 1000,
            )

        # Parse the file
        tree = self._parser.parse(source)
        root = tree.root_node

        # Create file node
        file_node_id = generate_node_id(file_path, 1, NodeKind.FILE, file_path)
        file_node = Node(
            id=file_node_id,
            kind=NodeKind.FILE,
            name=file_path.rsplit("/", 1)[-1],
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=root.end_point[0] + 1,
            language="css",
            content_hash=compute_content_hash(source),
        )

        ctx = _CSSExtractionContext(file_path, source, file_node_id)
        ctx.nodes.append(file_node)

        # Collect parse errors
        self._collect_errors(root, file_path, ctx.errors)

        # Walk the stylesheet
        self._walk_stylesheet(root, ctx)

        # Second pass: resolve var() references and animation-name references
        self._resolve_intra_file_refs(ctx)

        elapsed = (time.perf_counter() - t0) * 1000
        return ExtractionResult(
            file_path=file_path,
            language="css",
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
                NodeKind.CSS_CLASS,
                NodeKind.CSS_ID,
                NodeKind.CSS_VARIABLE,
                NodeKind.CSS_KEYFRAMES,
                NodeKind.CSS_MEDIA_QUERY,
                NodeKind.CSS_LAYER,
                NodeKind.CSS_FONT_FACE,
                NodeKind.IMPORT,
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

    # -- Stylesheet walk ----------------------------------------------------

    def _walk_stylesheet(
        self,
        root: tree_sitter.Node,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Walk top-level stylesheet children."""
        for child in root.children:
            self._handle_top_level(child, ctx, ctx.file_node_id)

    def _handle_top_level(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Dispatch top-level CSS nodes."""
        ntype = node.type
        if ntype == "rule_set":
            self._handle_rule_set(node, ctx, parent_id)
        elif ntype == "import_statement":
            self._handle_import(node, ctx, parent_id)
        elif ntype == "keyframes_statement":
            self._handle_keyframes(node, ctx, parent_id)
        elif ntype == "media_statement":
            self._handle_media(node, ctx, parent_id)
        elif ntype == "at_rule":
            self._handle_at_rule(node, ctx, parent_id)

    # -- Rule set handling --------------------------------------------------

    def _handle_rule_set(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Extract selectors and declarations from a rule_set."""
        selectors_node = _child_by_type(node, "selectors")
        block_node = _child_by_type(node, "block")

        if selectors_node is not None:
            self._extract_selectors(selectors_node, node, ctx, parent_id)

        if block_node is not None:
            self._extract_declarations(block_node, node, ctx)

    def _extract_selectors(
        self,
        selectors_node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Walk selector tree to find class and id selectors."""
        self._walk_for_selectors(selectors_node, rule_node, ctx, parent_id)

    def _walk_for_selectors(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Recursively find class_selector and id_selector nodes."""
        if node.type == "class_selector":
            self._handle_class_selector(node, rule_node, ctx, parent_id)
        elif node.type == "id_selector":
            self._handle_id_selector(node, rule_node, ctx, parent_id)

        for child in node.children:
            self._walk_for_selectors(child, rule_node, ctx, parent_id)

    def _handle_class_selector(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Create a CSS_CLASS node from a class_selector."""
        text = _node_text(node, ctx.source)
        # class_selector text includes the dot: .container
        name = text.lstrip(".")
        if not name:
            return

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
                language="css",
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

    def _handle_id_selector(
        self,
        node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Create a CSS_ID node from an id_selector."""
        text = _node_text(node, ctx.source)
        name = text.lstrip("#")
        if not name:
            return

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
                language="css",
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

    # -- Declaration handling -----------------------------------------------

    def _extract_declarations(
        self,
        block_node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Extract custom property definitions and var() references from declarations."""
        for child in block_node.children:
            if child.type == "declaration":
                self._handle_declaration(child, rule_node, ctx)

    def _handle_declaration(
        self,
        decl_node: tree_sitter.Node,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Handle a CSS declaration (property: value)."""
        prop_node = _child_by_type(decl_node, "property_name")
        if prop_node is None:
            return

        prop_name = _node_text(prop_node, ctx.source).strip()

        # Check for custom property definition: --variable-name
        if _CUSTOM_PROP_RE.match(prop_name):
            self._handle_custom_property(decl_node, prop_name, ctx)

        # Scan value for var() references
        value_node = _get_declaration_value_node(decl_node)
        if value_node is not None:
            value_text = _node_text(value_node, ctx.source)
            for match in _VAR_REFERENCE_RE.finditer(value_text):
                var_name = match.group(1)
                line = decl_node.start_point[0] + 1
                # Create unresolved reference for cross-file resolution
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=ctx.file_node_id,
                        reference_name=var_name,
                        reference_kind=EdgeKind.CSS_USES_VARIABLE,
                        line_number=line,
                        context={"type": "css_var_reference"},
                    )
                )

            # Check for animation-name references
            if prop_name in ("animation", "animation-name"):
                self._extract_animation_ref(value_text, decl_node, ctx)

    def _handle_custom_property(
        self,
        decl_node: tree_sitter.Node,
        prop_name: str,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Create a CSS_VARIABLE node for a custom property definition."""
        line = decl_node.start_point[0] + 1
        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.CSS_VARIABLE,
            prop_name,
        )

        source_text = _node_text(decl_node, ctx.source)
        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.CSS_VARIABLE,
                name=prop_name,
                qualified_name=prop_name,
                file_path=ctx.file_path,
                start_line=line,
                end_line=decl_node.end_point[0] + 1,
                language="css",
                source_text=source_text if len(source_text) < 2000 else None,
            )
        )
        ctx.edges.append(
            Edge(
                source_id=ctx.file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        # Track for intra-file resolution
        ctx.custom_props[prop_name] = node_id

    def _extract_animation_ref(
        self,
        value_text: str,
        decl_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Extract animation-name references to @keyframes."""
        # Simple heuristic: first word-like token that isn't a CSS keyword
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
                # Check if it looks like a duration/timing (e.g., 0.3s, 200ms)
                if re.match(r"^[\d.]+(?:s|ms)$", clean):
                    continue
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
                break  # Only first animation name

    # -- @import handling ---------------------------------------------------

    def _handle_import(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @import statement."""
        line = node.start_point[0] + 1
        import_path = self._extract_import_path(node, ctx.source)
        if not import_path:
            return

        node_id = generate_node_id(
            ctx.file_path,
            line,
            NodeKind.IMPORT,
            import_path,
        )

        ctx.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.IMPORT,
                name=import_path,
                qualified_name=import_path,
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="css",
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
        # Create unresolved import reference
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=node_id,
                reference_name=import_path,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"type": "css_import"},
            )
        )

    def _extract_import_path(
        self,
        node: tree_sitter.Node,
        source: bytes,
    ) -> str | None:
        """Extract the path from an @import statement."""
        for child in node.children:
            if child.type == "call_expression":
                # url('path') or url("path")
                text = _node_text(child, source)
                match = _URL_PATH_RE.search(text)
                if match:
                    return match.group(1)
            elif child.type == "string_value":
                text = _node_text(child, source)
                return text.strip("'\"")
        return None

    # -- @keyframes handling ------------------------------------------------

    def _handle_keyframes(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @keyframes statement."""
        name_node = _child_by_type(node, "keyframes_name")
        if name_node is None:
            # Try second child (after @keyframes keyword)
            for child in node.children:
                if child.type == "keyframes_name":
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
                language="css",
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
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @media statement."""
        # Extract the media condition
        condition_parts = []
        block_node = None
        for child in node.children:
            if child.type == "block":
                block_node = child
                break
            elif child.type not in ("@media", ";"):
                condition_parts.append(_node_text(child, ctx.source))

        condition = " ".join(condition_parts).strip()
        if not condition:
            condition = "(unknown)"

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
                language="css",
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

        # Walk nested rules inside the media block
        if block_node is not None:
            for child in block_node.children:
                if child.type == "rule_set":
                    self._handle_rule_set(child, ctx, node_id)
                    # Also create media_contains edges for selectors
                    self._create_media_contains_edges(child, ctx, node_id)

    def _create_media_contains_edges(
        self,
        rule_node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        media_id: str,
    ) -> None:
        """Create CSS_MEDIA_CONTAINS edges for selectors inside @media."""
        selectors_node = _child_by_type(rule_node, "selectors")
        if selectors_node is None:
            return
        # Find the most recently added selector nodes from this rule
        rule_line = rule_node.start_point[0] + 1
        for node in ctx.nodes:
            if node.kind in (NodeKind.CSS_CLASS, NodeKind.CSS_ID) and node.start_line == rule_line:
                ctx.edges.append(
                    Edge(
                        source_id=media_id,
                        target_id=node.id,
                        kind=EdgeKind.CSS_MEDIA_CONTAINS,
                        confidence=1.0,
                        line_number=rule_line,
                    )
                )

    # -- @layer / @font-face handling (via at_rule) -------------------------

    def _handle_at_rule(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle generic at-rules (@layer, @font-face, etc.)."""
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
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @layer rule."""
        # Extract layer name
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
                language="css",
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

        # Walk nested rules inside the layer block
        if block_node is not None:
            for child in block_node.children:
                if child.type == "rule_set":
                    self._handle_rule_set(child, ctx, node_id)
                    # Create layer_contains edges
                    rule_line = child.start_point[0] + 1
                    for n in ctx.nodes:
                        if n.kind in (NodeKind.CSS_CLASS, NodeKind.CSS_ID) and n.start_line == rule_line:
                            ctx.edges.append(
                                Edge(
                                    source_id=node_id,
                                    target_id=n.id,
                                    kind=EdgeKind.CSS_LAYER_CONTAINS,
                                    confidence=1.0,
                                    line_number=rule_line,
                                )
                            )

    def _handle_font_face(
        self,
        node: tree_sitter.Node,
        ctx: _CSSExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle @font-face rule."""
        # Extract font-family name from declarations
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
                language="css",
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

    # -- Intra-file resolution ----------------------------------------------

    def _resolve_intra_file_refs(
        self,
        ctx: _CSSExtractionContext,
    ) -> None:
        """Resolve var() and animation-name references within the same file."""
        remaining: list[UnresolvedReference] = []
        for ref in ctx.unresolved:
            resolved = False
            if ref.reference_kind == EdgeKind.CSS_USES_VARIABLE:
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
            elif ref.reference_kind == EdgeKind.CSS_KEYFRAMES_USED_BY:
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
