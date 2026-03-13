"""TypeScript AST extractor — tree-sitter based.

Extracts knowledge-graph nodes and edges from TypeScript source files.
Handles both .ts and .tsx files with the appropriate grammar.
Supports all JavaScript constructs plus TypeScript-specific features:
interfaces, type aliases, enums, decorators, abstract classes,
implements clauses, type annotations, and generics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import tree_sitter
import tree_sitter_typescript as tsts

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _child_by_field(node: tree_sitter.Node, field_name: str) -> tree_sitter.Node | None:
    """Return the first child with the given field name."""
    return node.child_by_field_name(field_name)


def _children_of_type(node: tree_sitter.Node, *types: str) -> list[tree_sitter.Node]:
    """Return all direct children matching any of the given types."""
    return [c for c in node.children if c.type in types]


def _node_text(node: tree_sitter.Node | None, source: bytes) -> str:
    """Extract UTF-8 text for a node."""
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _find_preceding_docblock(node: tree_sitter.Node, source: bytes) -> str | None:
    """Find a JSDoc comment immediately preceding *node*."""
    prev = node.prev_named_sibling
    if prev is not None and prev.type == "comment":
        text = _node_text(prev, source)
        if text.startswith("/**"):
            return text
    return None


def _is_async(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a function/method has the async keyword."""
    for child in node.children:
        txt = _node_text(child, source)
        if txt == "async":
            return True
        if child.type in ("formal_parameters", "statement_block", "("):
            break
    return False


def _is_static(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a class member has the static keyword."""
    for child in node.children:
        if _node_text(child, source) == "static":
            return True
        if child.type in ("property_identifier", "formal_parameters", "("):
            break
    return False


def _is_generator(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a function is a generator (function*)."""
    text = _node_text(node, source)
    paren = text.find("(")
    if paren == -1:
        return False
    return "*" in text[:paren]


def _extract_parameters(node: tree_sitter.Node | None, source: bytes) -> list[dict[str, str]]:
    """Extract parameter info from formal_parameters."""
    if node is None:
        return []
    params: list[dict[str, str]] = []
    for child in node.children:
        if child.type == "identifier":
            params.append({"name": _node_text(child, source)})
        elif child.type in ("required_parameter", "optional_parameter"):
            # TS-specific parameter types
            p: dict[str, str] = {}
            pattern = _child_by_field(child, "pattern")
            if pattern is not None:
                p["name"] = _node_text(pattern, source)
            else:
                # Fallback: first identifier child
                for sub in child.children:
                    if sub.type == "identifier":
                        p["name"] = _node_text(sub, source)
                        break
            # Type annotation
            type_ann = _child_by_field(child, "type")
            if type_ann is not None:
                p["type"] = _node_text(type_ann, source).lstrip(": ").strip()
            # Default value
            value = _child_by_field(child, "value")
            if value is not None:
                p["default"] = _node_text(value, source)
            if child.type == "optional_parameter":
                p["optional"] = "true"
            if p.get("name"):
                params.append(p)
        elif child.type == "assignment_pattern":
            left = _child_by_field(child, "left")
            right = _child_by_field(child, "right")
            if left is not None:
                p2: dict[str, str] = {"name": _node_text(left, source)}
                if right is not None:
                    p2["default"] = _node_text(right, source)
                params.append(p2)
        elif child.type == "rest_pattern":
            for sub in child.children:
                if sub.type == "identifier":
                    params.append({"name": "..." + _node_text(sub, source)})
                    break
    return params


def _get_access_modifier(node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract accessibility modifier (public/private/protected) from a class member."""
    for child in node.children:
        if child.type == "accessibility_modifier":
            return _node_text(child, source)
        # Stop once we hit the name or body
        if child.type in ("property_identifier", "formal_parameters", "("):
            break
    return None


def _is_readonly(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a class member has the readonly modifier."""
    for child in node.children:
        if _node_text(child, source) == "readonly":
            return True
        if child.type in ("property_identifier", "formal_parameters"):
            break
    return False


def _is_abstract_member(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a class member has the abstract modifier."""
    for child in node.children:
        if _node_text(child, source) == "abstract":
            return True
        if child.type in ("property_identifier", "formal_parameters"):
            break
    return False


def _is_override(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a class member has the override modifier."""
    for child in node.children:
        if child.type == "override_modifier":
            return True
        if child.type in ("property_identifier", "formal_parameters"):
            break
    return False


def _extract_type_annotation(node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract type annotation from a node (parameter, property, variable)."""
    type_node = _child_by_field(node, "type")
    if type_node is not None:
        text = _node_text(type_node, source)
        return text.lstrip(": ").strip() if text else None
    # Fallback: look for type_annotation child
    for child in node.children:
        if child.type == "type_annotation":
            text = _node_text(child, source)
            return text.lstrip(": ").strip() if text else None
    return None


def _extract_return_type(node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract return type annotation from a function/method."""
    ret = _child_by_field(node, "return_type")
    if ret is not None:
        text = _node_text(ret, source)
        return text.lstrip(": ").strip() if text else None
    # Fallback: look for type_annotation after formal_parameters
    found_params = False
    for child in node.children:
        if child.type == "formal_parameters":
            found_params = True
            continue
        if found_params and child.type == "type_annotation":
            text = _node_text(child, source)
            return text.lstrip(": ").strip() if text else None
        if found_params and child.type in ("statement_block", "{"):
            break
    return None


def _extract_type_parameters(node: tree_sitter.Node, source: bytes) -> list[str]:
    """Extract generic type parameter names from type_parameters."""
    tp = _child_by_field(node, "type_parameters")
    if tp is None:
        for child in node.children:
            if child.type == "type_parameters":
                tp = child
                break
    if tp is None:
        return []
    result: list[str] = []
    for child in tp.children:
        if child.type == "type_parameter":
            name_node = _child_by_field(child, "name")
            if name_node is not None:
                result.append(_node_text(name_node, source))
    return result


def _extract_decorators(node: tree_sitter.Node, source: bytes) -> list[dict[str, str]]:
    """Extract decorator information from a decorated node."""
    decorators: list[dict[str, str]] = []
    for child in node.children:
        if child.type == "decorator":
            dec_info: dict[str, str] = {}
            for sub in child.children:
                if sub.type == "identifier":
                    dec_info["name"] = _node_text(sub, source)
                    dec_info["kind"] = "simple"
                elif sub.type == "call_expression":
                    func = _child_by_field(sub, "function")
                    if func is not None:
                        dec_info["name"] = _node_text(func, source)
                    args = _child_by_field(sub, "arguments")
                    if args is not None:
                        dec_info["args"] = _node_text(args, source)
                    dec_info["kind"] = "factory"
                elif sub.type == "member_expression":
                    dec_info["name"] = _node_text(sub, source)
                    dec_info["kind"] = "member"
            if dec_info.get("name"):
                decorators.append(dec_info)
        elif child.type not in ("comment",):
            # Stop once we pass decorators
            if child.type in (
                "class",
                "class_body",
                "identifier",
                "type_identifier",
                "type_parameters",
                "class_heritage",
                "abstract",
                "export",
                "default",
            ):
                break
    return decorators


# ---------------------------------------------------------------------------
# Extraction context
# ---------------------------------------------------------------------------


@dataclass
class _ExtractionContext:
    """Mutable state carried through a single file extraction."""

    file_path: str = ""
    source: bytes = b""
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[ExtractionError] = field(default_factory=list)
    unresolved: list[UnresolvedReference] = field(default_factory=list)
    # Stack of qualified-name prefixes (e.g. ["src/app.ts", "MyClass"])
    scope_stack: list[str] = field(default_factory=list)
    # Track exported names for EXPORTS edges
    default_export_name: str | None = None
    named_exports: set[str] = field(default_factory=set)
    # Track import bindings: local_name -> (module_path, original_name)
    import_bindings: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Track all defined names for call resolution
    defined_names: dict[str, str] = field(default_factory=dict)  # name -> node_id

    @property
    def current_scope(self) -> str:
        return "/".join(self.scope_stack)

    def qualified(self, name: str) -> str:
        if self.scope_stack:
            return f"{self.current_scope}/{name}"
        return name

    def add_node(self, node: Node) -> None:
        self.nodes.append(node)
        self.defined_names[node.name] = node.id

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def add_error(self, message: str, line: int = 0) -> None:
        self.errors.append(
            ExtractionError(
                file_path=self.file_path,
                line_number=line,
                message=message,
                severity="error",
            )
        )


# ---------------------------------------------------------------------------
# TypeScript extractor
# ---------------------------------------------------------------------------


class TypeScriptExtractor(ASTExtractor):
    """Extract knowledge-graph nodes and edges from TypeScript source.

    Handles both ``.ts`` and ``.tsx`` files by selecting the appropriate
    tree-sitter grammar at parse time.
    """

    _SUPPORTED_NODE_KINDS = frozenset(
        {
            NodeKind.FILE,
            NodeKind.MODULE,
            NodeKind.CLASS,
            NodeKind.METHOD,
            NodeKind.PROPERTY,
            NodeKind.FUNCTION,
            NodeKind.VARIABLE,
            NodeKind.CONSTANT,
            NodeKind.IMPORT,
            NodeKind.EXPORT,
            NodeKind.COMPONENT,
            # TypeScript-specific
            NodeKind.INTERFACE,
            NodeKind.TYPE_ALIAS,
            NodeKind.ENUM,
            NodeKind.DECORATOR,
        }
    )

    _SUPPORTED_EDGE_KINDS = frozenset(
        {
            EdgeKind.CONTAINS,
            EdgeKind.EXTENDS,
            EdgeKind.IMPORTS,
            EdgeKind.EXPORTS,
            EdgeKind.RE_EXPORTS,
            EdgeKind.CALLS,
            EdgeKind.INSTANTIATES,
            EdgeKind.DYNAMIC_IMPORTS,
            # TypeScript-specific
            EdgeKind.IMPLEMENTS,
            EdgeKind.HAS_TYPE,
            EdgeKind.RETURNS_TYPE,
            EdgeKind.IMPORTS_TYPE,
            EdgeKind.RENDERS,
            EdgeKind.DEPENDS_ON,
        }
    )

    # -- ASTExtractor interface: supported kinds ----------------------------

    def supported_node_kinds(self) -> frozenset:
        return self._SUPPORTED_NODE_KINDS

    def supported_edge_kinds(self) -> frozenset:
        return self._SUPPORTED_EDGE_KINDS

    def __init__(self) -> None:
        # Lazily initialised parsers (one per grammar)
        self._parser_ts: tree_sitter.Parser | None = None
        self._parser_tsx: tree_sitter.Parser | None = None
        self._lang_ts: tree_sitter.Language | None = None
        self._lang_tsx: tree_sitter.Language | None = None

    # -- Grammar helpers ----------------------------------------------------

    def _ensure_parsers(self) -> None:
        if self._parser_ts is None:
            self._lang_ts = tree_sitter.Language(tsts.language_typescript())
            self._parser_ts = tree_sitter.Parser(self._lang_ts)
        if self._parser_tsx is None:
            self._lang_tsx = tree_sitter.Language(tsts.language_tsx())
            self._parser_tsx = tree_sitter.Parser(self._lang_tsx)

    def _parser_for(self, file_path: str) -> tree_sitter.Parser:
        self._ensure_parsers()
        if file_path.endswith(".tsx"):
            assert self._parser_tsx is not None
            return self._parser_tsx
        assert self._parser_ts is not None
        return self._parser_ts

    # -- ASTExtractor interface ---------------------------------------------

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Parse *source* and extract all nodes / edges."""
        t0 = time.perf_counter()
        ctx = _ExtractionContext(file_path=file_path, source=source)
        ctx.scope_stack.append(file_path)

        # Create FILE node
        file_node = Node(
            id=generate_node_id(file_path, 1, NodeKind.FILE, file_path),
            kind=NodeKind.FILE,
            name=file_path.rsplit("/", 1)[-1],
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=0,  # filled below
            language="typescript",
            content_hash=compute_content_hash(source),
        )

        parser = self._parser_for(file_path)
        tree = parser.parse(source)
        root = tree.root_node

        if root.has_error:
            ctx.add_error("Tree-sitter reported parse errors", line=1)

        from dataclasses import replace as _dc_replace

        file_node = _dc_replace(file_node, end_line=root.end_point[0] + 1)
        ctx.add_node(file_node)

        # Walk top-level statements
        self._visit_children(root, ctx)

        elapsed = (time.perf_counter() - t0) * 1000
        return ExtractionResult(
            file_path=file_path,
            language="typescript",
            nodes=ctx.nodes,
            edges=ctx.edges,
            errors=ctx.errors,
            unresolved_references=ctx.unresolved,
            parse_time_ms=elapsed,
        )

    # -- Dispatch -----------------------------------------------------------

    def _visit_children(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Walk children and dispatch to specialised visitors."""
        for child in node.children:
            self._visit(child, ctx)

    def _visit(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:  # noqa: C901
        """Dispatch a single AST node to the appropriate handler."""
        ntype = node.type
        try:
            # -- Imports -----------------------------------------------
            if ntype == "import_statement":
                self._visit_import(node, ctx)
            # -- Exports -----------------------------------------------
            elif ntype == "export_statement":
                self._visit_export(node, ctx)
            # -- Classes -----------------------------------------------
            elif ntype in ("class_declaration", "abstract_class_declaration"):
                self._visit_class(node, ctx)
            # -- Interfaces --------------------------------------------
            elif ntype == "interface_declaration":
                self._visit_interface(node, ctx)
            # -- Type aliases ------------------------------------------
            elif ntype == "type_alias_declaration":
                self._visit_type_alias(node, ctx)
            # -- Enums -------------------------------------------------
            elif ntype == "enum_declaration":
                self._visit_enum(node, ctx)
            # -- Functions ---------------------------------------------
            elif ntype in ("function_declaration", "generator_function_declaration"):
                self._visit_function(node, ctx)
            # -- Variable declarations ---------------------------------
            elif ntype == "lexical_declaration":
                self._visit_lexical_declaration(node, ctx)
            elif ntype == "variable_declaration":
                self._visit_lexical_declaration(node, ctx)
            # -- Expression statements (calls, assignments) ------------
            elif ntype == "expression_statement":
                self._visit_expression_statement(node, ctx)
            # -- Ambient / declare statements --------------------------
            elif ntype == "ambient_declaration":
                self._visit_ambient_declaration(node, ctx)
            # -- Module declaration (declare module "x" { ... }) -------
            elif ntype == "module":
                self._visit_module_declaration(node, ctx)
        except Exception as exc:
            ctx.add_error(
                f"Error visiting {ntype}: {exc}",
                line=node.start_point[0] + 1,
            )

    # ===================================================================
    # IMPORTS
    # ===================================================================

    def _visit_import(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle import_statement.

        Patterns:
          import "module"                          (side-effect)
          import defaultExport from "module"
          import { a, b as c } from "module"
          import * as ns from "module"
          import type { Foo } from "module"        (TS type-only)
          import { type Foo, Bar } from "module"   (TS inline type)
          const x = require("module")              (CJS - handled in expression_statement)
        """
        source = ctx.source
        source_node = _child_by_field(node, "source")
        if source_node is None:
            # Could be `import type = require(...)` or similar
            return
        module_path = _node_text(source_node, source).strip("\"''`")
        if not module_path:
            return

        # Detect type-only import: `import type { ... } from "..."`
        full_text = _node_text(node, source)
        is_type_only = full_text.lstrip().startswith("import type ")

        # Collect imported names
        imported_names: list[dict[str, str]] = []
        has_default = False

        for child in node.children:
            # Default import: `import Foo from "..."`
            if child.type == "identifier" and not has_default:
                name = _node_text(child, source)
                if name not in ("from", "import", "type", "as"):
                    imported_names.append({"name": name, "alias": name, "kind": "default"})
                    has_default = True
                    ctx.import_bindings[name] = (module_path, "default")

            # Namespace import: `import * as ns from "..."`
            elif child.type == "namespace_import":
                for sub in child.children:
                    if sub.type == "identifier":
                        ns_name = _node_text(sub, source)
                        imported_names.append({"name": "*", "alias": ns_name, "kind": "namespace"})
                        ctx.import_bindings[ns_name] = (module_path, "*")

            # Named imports: `import { a, b as c } from "..."`
            elif child.type == "named_imports":
                for spec in child.children:
                    if spec.type == "import_specifier":
                        spec_name = ""
                        spec_alias = ""
                        is_spec_type = False
                        parts = []
                        for s in spec.children:
                            txt = _node_text(s, source)
                            if txt == "type" and s.type == "identifier" and not spec_name:
                                is_spec_type = True
                                continue
                            if s.type in ("identifier", "type_identifier"):
                                parts.append(txt)
                        if len(parts) >= 2:
                            spec_name = parts[0]
                            spec_alias = parts[-1]
                        elif len(parts) == 1:
                            spec_name = parts[0]
                            spec_alias = parts[0]
                        if spec_name:
                            kind = "type" if (is_type_only or is_spec_type) else "named"
                            imported_names.append(
                                {
                                    "name": spec_name,
                                    "alias": spec_alias,
                                    "kind": kind,
                                }
                            )
                            ctx.import_bindings[spec_alias] = (module_path, spec_name)

        # Create IMPORT node
        edge_kind = EdgeKind.IMPORTS_TYPE if is_type_only else EdgeKind.IMPORTS
        generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.VARIABLE, f"import:{module_path}")

        # Create unresolved reference for the module
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.nodes[0].id if ctx.nodes else "",
                reference_name=module_path,
                reference_kind=EdgeKind.IMPORTS_TYPE if is_type_only else EdgeKind.IMPORTS,
                line_number=node.start_point[0] + 1,
                context={
                    "imported_names": imported_names,
                    "is_type_only": is_type_only,
                },
            )
        )

        # Create edges for each imported name
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        for imp in imported_names:
            imp_kind = EdgeKind.IMPORTS_TYPE if imp.get("kind") == "type" else edge_kind
            ctx.add_edge(
                Edge(
                    source_id=file_node_id,
                    target_id=f"unresolved:{module_path}:{imp['name']}",
                    kind=imp_kind,
                    confidence=0.9,
                    metadata={
                        "module_path": module_path,
                        "imported_name": imp["name"],
                        "local_alias": imp["alias"],
                        "is_type_only": is_type_only or imp.get("kind") == "type",
                    },
                )
            )

    # ===================================================================
    # EXPORTS
    # ===================================================================

    def _visit_export(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle export_statement.

        Patterns:
          export default expression
          export default class/function ...
          export { a, b as c }
          export { a, b } from "module"   (re-export)
          export * from "module"          (re-export all)
          export type { Foo }             (TS type export)
          export class/function/interface/type/enum ...
        """
        source = ctx.source
        _node_text(node, source)
        is_default = False
        is_type_export = False
        source_module: str | None = None

        # Check for re-export source
        source_node = _child_by_field(node, "source")
        if source_node is not None:
            source_module = _node_text(source_node, source).strip("\"''`")

        # Check for default / type keywords
        for child in node.children:
            txt = _node_text(child, source)
            if txt == "default":
                is_default = True
            if txt == "type" and child.type == "identifier":
                is_type_export = True

        file_node_id = ctx.nodes[0].id if ctx.nodes else ""

        # Re-export: export { ... } from "module" or export * from "module"
        if source_module is not None:
            # Collect re-exported names
            reexported: list[dict[str, str]] = []
            for child in node.children:
                if child.type == "export_clause":
                    for spec in child.children:
                        if spec.type == "export_specifier":
                            parts = []
                            for s in spec.children:
                                if s.type in ("identifier", "type_identifier"):
                                    parts.append(_node_text(s, source))
                            if len(parts) >= 2:
                                reexported.append({"name": parts[0], "alias": parts[-1]})
                            elif len(parts) == 1:
                                reexported.append({"name": parts[0], "alias": parts[0]})
                elif child.type == "namespace_export" or _node_text(child, source) == "*":
                    reexported.append({"name": "*", "alias": "*"})

            # Create unresolved reference for re-export
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=file_node_id,
                    reference_name=source_module,
                    reference_kind=EdgeKind.IMPORTS,
                    line_number=node.start_point[0] + 1,
                    context={"reexported_names": reexported},
                )
            )

            for re in reexported:
                ctx.add_edge(
                    Edge(
                        source_id=file_node_id,
                        target_id=f"unresolved:{source_module}:{re['name']}",
                        kind=EdgeKind.EXPORTS,
                        confidence=0.9,
                        metadata={
                            "source_module": source_module,
                            "original_name": re["name"],
                            "exported_as": re["alias"],
                            "is_reexport": True,
                        },
                    )
                )
            return

        # Named export clause: export { a, b as c }
        for child in node.children:
            if child.type == "export_clause":
                for spec in child.children:
                    if spec.type == "export_specifier":
                        parts = []
                        for s in spec.children:
                            if s.type in ("identifier", "type_identifier"):
                                parts.append(_node_text(s, source))
                        if parts:
                            local_name = parts[0]
                            exported_name = parts[-1] if len(parts) > 1 else local_name
                            ctx.named_exports.add(exported_name)
                            # Link to defined node if known
                            target = ctx.defined_names.get(local_name, f"unresolved:local:{local_name}")
                            ctx.add_edge(
                                Edge(
                                    source_id=file_node_id,
                                    target_id=target,
                                    kind=EdgeKind.EXPORTS,
                                    confidence=0.9,
                                    metadata={
                                        "exported_name": exported_name,
                                        "local_name": local_name,
                                        "is_type_export": is_type_export,
                                    },
                                )
                            )
                return

        # Inline export: export class/function/interface/type/enum ...
        for child in node.children:
            if child.type in (
                "class_declaration",
                "abstract_class_declaration",
                "function_declaration",
                "generator_function_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "lexical_declaration",
                "variable_declaration",
            ):
                # Visit the declaration normally
                self._visit(child, ctx)
                # Mark as exported
                if ctx.nodes and len(ctx.nodes) > 1:
                    last_node = ctx.nodes[-1]
                    if is_default:
                        ctx.default_export_name = last_node.name
                        last_node = Node(
                            **{
                                **last_node.__dict__,
                                "metadata": {**last_node.metadata, "is_default_export": True},
                            }
                        )
                        ctx.nodes[-1] = last_node
                    else:
                        ctx.named_exports.add(last_node.name)
                    ctx.add_edge(
                        Edge(
                            source_id=file_node_id,
                            target_id=last_node.id,
                            kind=EdgeKind.EXPORTS,
                            confidence=0.95,
                            metadata={
                                "exported_name": "default" if is_default else last_node.name,
                                "is_default": is_default,
                                "is_type_export": is_type_export,
                            },
                        )
                    )
                return

        # Default export of expression: export default someVar
        if is_default:
            for child in node.children:
                if child.type == "identifier":
                    name = _node_text(child, source)
                    if name not in ("export", "default", "type"):
                        ctx.default_export_name = name
                        target = ctx.defined_names.get(name, f"unresolved:local:{name}")
                        ctx.add_edge(
                            Edge(
                                source_id=file_node_id,
                                target_id=target,
                                kind=EdgeKind.EXPORTS,
                                confidence=0.9,
                                metadata={
                                    "exported_name": "default",
                                    "local_name": name,
                                    "is_default": True,
                                },
                            )
                        )
                        return

    # ===================================================================
    # CLASSES (including abstract)
    # ===================================================================

    def _visit_class(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle class_declaration and abstract_class_declaration."""
        source = ctx.source
        is_abstract = node.type == "abstract_class_declaration"

        # Name
        name_node = _child_by_field(node, "name")
        if name_node is None:
            # Anonymous class expression — skip
            return
        class_name = _node_text(name_node, source)
        if not class_name:
            return

        qualified = ctx.qualified(class_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.CLASS, class_name)

        # Decorators
        decorators = _extract_decorators(node, source)

        # Type parameters (generics)
        type_params = _extract_type_parameters(node, source)

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        # Build metadata
        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])
        meta: dict[str, Any] = {}
        if is_abstract:
            meta["is_abstract"] = True
        if decorators:
            meta["decorators"] = decorators
        if type_params:
            meta["type_parameters"] = type_params

        class_node = Node(
            id=node_id,
            kind=NodeKind.CLASS,
            name=class_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(class_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Decorator edges
        # Heritage: extends and implements
        self._process_class_heritage(node, node_id, ctx)

        # Class body
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "class_body":
                    body = child
                    break
        if body is not None:
            ctx.scope_stack.append(class_name)
            self._visit_class_body(body, node_id, ctx)
            ctx.scope_stack.pop()

    def _process_class_heritage(
        self,
        node: tree_sitter.Node,
        class_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract extends and implements from class heritage."""
        source = ctx.source
        for child in node.children:
            if child.type == "class_heritage":
                for hc in child.children:
                    # extends clause
                    if hc.type == "extends_clause":
                        for sub in hc.children:
                            if sub.type in ("identifier", "type_identifier", "member_expression"):
                                parent_name = _node_text(sub, source)
                                ctx.add_edge(
                                    Edge(
                                        source_id=class_node_id,
                                        target_id=f"unresolved:class:{parent_name}",
                                        kind=EdgeKind.EXTENDS,
                                        confidence=0.9,
                                        metadata={"parent_class": parent_name},
                                    )
                                )
                                ctx.unresolved.append(
                                    UnresolvedReference(
                                        source_node_id=class_node_id,
                                        reference_name=parent_name,
                                        reference_kind=EdgeKind.EXTENDS,
                                        line_number=hc.start_point[0] + 1,
                                    )
                                )
                                break  # Only one extends in TS

                    # implements clause
                    elif hc.type == "implements_clause":
                        for sub in hc.children:
                            if sub.type in (
                                "type_identifier",
                                "identifier",
                                "generic_type",
                                "member_expression",
                            ):
                                if sub.type == "generic_type":
                                    name_sub = _child_by_field(sub, "name")
                                    iface_name = _node_text(name_sub, source) if name_sub else _node_text(sub, source)
                                else:
                                    iface_name = _node_text(sub, source)
                                ctx.add_edge(
                                    Edge(
                                        source_id=class_node_id,
                                        target_id=f"unresolved:interface:{iface_name}",
                                        kind=EdgeKind.IMPLEMENTS,
                                        confidence=0.9,
                                        metadata={"interface": iface_name},
                                    )
                                )
                                ctx.unresolved.append(
                                    UnresolvedReference(
                                        source_node_id=class_node_id,
                                        reference_name=iface_name,
                                        reference_kind=EdgeKind.IMPLEMENTS,
                                        line_number=hc.start_point[0] + 1,
                                    )
                                )

    def _visit_class_body(
        self,
        body: tree_sitter.Node,
        class_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Walk class body and extract methods, properties, constructors."""
        for child in body.children:
            if child.type in ("method_definition", "method_signature"):
                self._visit_method(child, class_node_id, ctx)
            elif child.type in (
                "public_field_definition",
                "property_definition",
                "property_signature",
            ):
                self._visit_property(child, class_node_id, ctx)
            elif child.type == "abstract_method_signature":
                self._visit_method(child, class_node_id, ctx, force_abstract=True)
            elif child.type == "index_signature":
                # [key: string]: value — skip for now
                pass
            elif child.type == "decorator":
                # Decorators are handled by the next sibling
                pass

    # ===================================================================
    # METHODS
    # ===================================================================

    def _visit_method(
        self,
        node: tree_sitter.Node,
        class_node_id: str,
        ctx: _ExtractionContext,
        force_abstract: bool = False,
    ) -> None:
        """Handle method_definition, method_signature, abstract_method_signature."""
        source = ctx.source

        # Name
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        method_name = _node_text(name_node, source)
        if not method_name:
            return

        qualified = ctx.qualified(method_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.METHOD, method_name)

        # Parameters
        params_node = _child_by_field(node, "parameters")
        params = _extract_parameters(params_node, source)

        # Return type
        return_type = _extract_return_type(node, source)

        # Type parameters
        type_params = _extract_type_parameters(node, source)

        # Modifiers
        is_static = _is_static(node, source)
        is_async_method = _is_async(node, source)
        is_abstract = force_abstract or _is_abstract_member(node, source)
        is_generator = _is_generator(node, source)
        access = _get_access_modifier(node, source)
        is_ro = _is_readonly(node, source)
        is_over = _is_override(node, source)

        # Decorators (check preceding sibling)
        decorators = _extract_decorators(node, source)

        # Getter/setter detection
        kind_text = ""
        for child in node.children:
            txt = _node_text(child, source)
            if txt in ("get", "set") and child.type != "identifier":
                kind_text = txt
                break

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if params:
            meta["parameters"] = params
        if return_type:
            meta["return_type"] = return_type
        if type_params:
            meta["type_parameters"] = type_params
        if is_static:
            meta["is_static"] = True
        if is_async_method:
            meta["is_async"] = True
        if is_abstract:
            meta["is_abstract"] = True
        if is_generator:
            meta["is_generator"] = True
        if access:
            meta["access"] = access
        if is_ro:
            meta["is_readonly"] = True
        if is_over:
            meta["is_override"] = True
        if kind_text:
            meta["accessor"] = kind_text
        if decorators:
            meta["decorators"] = decorators
        if method_name == "constructor":
            meta["is_constructor"] = True

        method_node = Node(
            id=node_id,
            kind=NodeKind.METHOD,
            name=method_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(method_node)

        # CONTAINS edge from class
        ctx.add_edge(
            Edge(
                source_id=class_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Return type edge
        if return_type:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{return_type}",
                    kind=EdgeKind.RETURNS_TYPE,
                    confidence=0.8,
                    metadata={"return_type": return_type},
                )
            )

        # Decorator edges
        # Scan method body for calls
        body_node = _child_by_field(node, "body")
        if body_node is not None:
            self._scan_calls(body_node, node_id, ctx)
            self._scan_jsx(body_node, node_id, ctx)

    # ===================================================================
    # PROPERTIES
    # ===================================================================

    def _visit_property(
        self,
        node: tree_sitter.Node,
        class_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle public_field_definition, property_definition, property_signature."""
        source = ctx.source

        # Name
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        prop_name = _node_text(name_node, source)
        if not prop_name:
            return

        qualified = ctx.qualified(prop_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.PROPERTY, prop_name)

        # Type annotation
        type_ann = _extract_type_annotation(node, source)

        # Modifiers
        is_static = _is_static(node, source)
        access = _get_access_modifier(node, source)
        is_ro = _is_readonly(node, source)
        is_abstract = _is_abstract_member(node, source)

        # Optional (has ? after name)
        is_optional = False
        for child in node.children:
            if _node_text(child, source) == "?":
                is_optional = True
                break

        # Decorators
        decorators = _extract_decorators(node, source)

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if type_ann:
            meta["type_annotation"] = type_ann
        if is_static:
            meta["is_static"] = True
        if access:
            meta["access"] = access
        if is_ro:
            meta["is_readonly"] = True
        if is_abstract:
            meta["is_abstract"] = True
        if is_optional:
            meta["is_optional"] = True
        if decorators:
            meta["decorators"] = decorators

        # Default value
        value_node = _child_by_field(node, "value")
        if value_node is not None:
            val_text = _node_text(value_node, source)
            if len(val_text) <= 200:
                meta["default_value"] = val_text

        prop_node = Node(
            id=node_id,
            kind=NodeKind.PROPERTY,
            name=prop_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(prop_node)

        # CONTAINS edge from class
        ctx.add_edge(
            Edge(
                source_id=class_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Type edge
        if type_ann:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{type_ann}",
                    kind=EdgeKind.HAS_TYPE,
                    confidence=0.8,
                    metadata={"type": type_ann},
                )
            )

        # Decorator edges

    # ===================================================================
    # INTERFACES (TypeScript-specific)
    # ===================================================================

    def _visit_interface(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle interface_declaration."""
        source = ctx.source

        # Name
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        iface_name = _node_text(name_node, source)
        if not iface_name:
            return

        qualified = ctx.qualified(iface_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.INTERFACE, iface_name)

        # Type parameters
        type_params = _extract_type_parameters(node, source)

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if type_params:
            meta["type_parameters"] = type_params

        iface_node = Node(
            id=node_id,
            kind=NodeKind.INTERFACE,
            name=iface_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(iface_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Extends clause (interfaces can extend multiple interfaces)
        for child in node.children:
            if child.type == "extends_type_clause":
                for sub in child.children:
                    if sub.type in ("type_identifier", "identifier", "generic_type", "member_expression"):
                        if sub.type == "generic_type":
                            name_sub = _child_by_field(sub, "name")
                            parent_name = _node_text(name_sub, source) if name_sub else _node_text(sub, source)
                        else:
                            parent_name = _node_text(sub, source)
                        ctx.add_edge(
                            Edge(
                                source_id=node_id,
                                target_id=f"unresolved:interface:{parent_name}",
                                kind=EdgeKind.EXTENDS,
                                confidence=0.9,
                                metadata={"parent_interface": parent_name},
                            )
                        )
                        ctx.unresolved.append(
                            UnresolvedReference(
                                source_node_id=node_id,
                                reference_name=parent_name,
                                reference_kind=EdgeKind.EXTENDS,
                                line_number=child.start_point[0] + 1,
                            )
                        )

        # Interface body — extract property and method signatures
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type in ("interface_body", "object_type"):
                    body = child
                    break
        if body is not None:
            ctx.scope_stack.append(iface_name)
            self._visit_interface_body(body, node_id, ctx)
            ctx.scope_stack.pop()

    def _visit_interface_body(
        self,
        body: tree_sitter.Node,
        iface_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract members from interface body."""
        for child in body.children:
            if child.type == "property_signature":
                self._visit_interface_property(child, iface_node_id, ctx)
            elif child.type in ("method_signature", "call_signature", "construct_signature"):
                self._visit_interface_method(child, iface_node_id, ctx)
            elif child.type == "index_signature":
                # [key: string]: value — skip
                pass

    def _visit_interface_property(
        self,
        node: tree_sitter.Node,
        iface_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract a property signature from an interface."""
        source = ctx.source
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        prop_name = _node_text(name_node, source)
        if not prop_name:
            return

        qualified = ctx.qualified(prop_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.PROPERTY, prop_name)

        type_ann = _extract_type_annotation(node, source)
        is_optional = any(_node_text(c, source) == "?" for c in node.children)
        is_ro = _is_readonly(node, source)

        meta: dict[str, Any] = {}
        if type_ann:
            meta["type_annotation"] = type_ann
        if is_optional:
            meta["is_optional"] = True
        if is_ro:
            meta["is_readonly"] = True

        prop_node = Node(
            id=node_id,
            kind=NodeKind.PROPERTY,
            name=prop_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            metadata=meta,
        )
        ctx.add_node(prop_node)

        ctx.add_edge(
            Edge(
                source_id=iface_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        if type_ann:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{type_ann}",
                    kind=EdgeKind.HAS_TYPE,
                    confidence=0.8,
                    metadata={"type": type_ann},
                )
            )

    def _visit_interface_method(
        self,
        node: tree_sitter.Node,
        iface_node_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract a method signature from an interface."""
        source = ctx.source
        name_node = _child_by_field(node, "name")
        if name_node is None:
            # call_signature / construct_signature may not have a name
            method_name = "__call__" if node.type == "call_signature" else "__new__"
        else:
            method_name = _node_text(name_node, source)
        if not method_name:
            return

        qualified = ctx.qualified(method_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.METHOD, method_name)

        params_node = _child_by_field(node, "parameters")
        params = _extract_parameters(params_node, source)
        return_type = _extract_return_type(node, source)
        type_params = _extract_type_parameters(node, source)

        meta: dict[str, Any] = {"is_signature": True}
        if params:
            meta["parameters"] = params
        if return_type:
            meta["return_type"] = return_type
        if type_params:
            meta["type_parameters"] = type_params

        method_node = Node(
            id=node_id,
            kind=NodeKind.METHOD,
            name=method_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            metadata=meta,
        )
        ctx.add_node(method_node)

        ctx.add_edge(
            Edge(
                source_id=iface_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        if return_type:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{return_type}",
                    kind=EdgeKind.RETURNS_TYPE,
                    confidence=0.8,
                    metadata={"return_type": return_type},
                )
            )

    # ===================================================================
    # TYPE ALIASES (TypeScript-specific)
    # ===================================================================

    def _visit_type_alias(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle type_alias_declaration: type Foo = ..."""
        source = ctx.source

        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        type_name = _node_text(name_node, source)
        if not type_name:
            return

        qualified = ctx.qualified(type_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.TYPE_ALIAS, type_name)

        # Type parameters
        type_params = _extract_type_parameters(node, source)

        # The type value (right side of =)
        value_node = _child_by_field(node, "value")
        type_value = _node_text(value_node, source) if value_node else ""

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if type_params:
            meta["type_parameters"] = type_params
        if type_value and len(type_value) <= 500:
            meta["type_value"] = type_value

        type_node = Node(
            id=node_id,
            kind=NodeKind.TYPE_ALIAS,
            name=type_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(type_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

    # ===================================================================
    # ENUMS (TypeScript-specific)
    # ===================================================================

    def _visit_enum(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle enum_declaration."""
        source = ctx.source

        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        enum_name = _node_text(name_node, source)
        if not enum_name:
            return

        qualified = ctx.qualified(enum_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.ENUM, enum_name)

        # Check for const enum
        is_const = False
        for child in node.children:
            if _node_text(child, source) == "const":
                is_const = True
                break

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        # Extract members
        members: list[dict[str, str]] = []
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "enum_body":
                    body = child
                    break
        if body is not None:
            for child in body.children:
                if child.type in ("enum_assignment", "property_identifier"):
                    member: dict[str, str] = {}
                    if child.type == "property_identifier":
                        member["name"] = _node_text(child, source)
                    else:
                        name_sub = _child_by_field(child, "name")
                        if name_sub is None:
                            for sub in child.children:
                                if sub.type == "property_identifier":
                                    name_sub = sub
                                    break
                        if name_sub is not None:
                            member["name"] = _node_text(name_sub, source)
                        value_sub = _child_by_field(child, "value")
                        if value_sub is not None:
                            member["value"] = _node_text(value_sub, source)
                    if member.get("name"):
                        members.append(member)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if is_const:
            meta["is_const"] = True
        if members:
            meta["members"] = members

        enum_node = Node(
            id=node_id,
            kind=NodeKind.ENUM,
            name=enum_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(enum_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

    # ===================================================================
    # FUNCTIONS
    # ===================================================================

    def _visit_function(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Handle function_declaration and generator_function_declaration."""
        source = ctx.source

        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        func_name = _node_text(name_node, source)
        if not func_name:
            return

        qualified = ctx.qualified(func_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.FUNCTION, func_name)

        # Parameters
        params_node = _child_by_field(node, "parameters")
        params = _extract_parameters(params_node, source)

        # Return type
        return_type = _extract_return_type(node, source)

        # Type parameters
        type_params = _extract_type_parameters(node, source)

        # Modifiers
        is_async_fn = _is_async(node, source)
        is_gen = node.type == "generator_function_declaration" or _is_generator(node, source)

        # Decorators
        decorators = _extract_decorators(node, source)

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])

        meta: dict[str, Any] = {}
        if params:
            meta["parameters"] = params
        if return_type:
            meta["return_type"] = return_type
        if type_params:
            meta["type_parameters"] = type_params
        if is_async_fn:
            meta["is_async"] = True
        if is_gen:
            meta["is_generator"] = True
        if decorators:
            meta["decorators"] = decorators

        func_node = Node(
            id=node_id,
            kind=NodeKind.FUNCTION,
            name=func_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(func_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Return type edge
        if return_type:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{return_type}",
                    kind=EdgeKind.RETURNS_TYPE,
                    confidence=0.8,
                    metadata={"return_type": return_type},
                )
            )

        # Decorator edges
        # Scan body for calls and JSX
        body_node = _child_by_field(node, "body")
        if body_node is not None:
            self._scan_calls(body_node, node_id, ctx)
            self._scan_jsx(body_node, node_id, ctx)

    # ===================================================================
    # LEXICAL / VARIABLE DECLARATIONS
    # ===================================================================

    def _visit_lexical_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle lexical_declaration (const/let) and variable_declaration (var).

        Also detects arrow functions and class expressions assigned to variables.
        """
        source = ctx.source

        # Determine declaration kind (const, let, var)
        decl_kind = ""
        for child in node.children:
            txt = _node_text(child, source)
            if txt in ("const", "let", "var"):
                decl_kind = txt
                break

        for child in node.children:
            if child.type == "variable_declarator":
                self._visit_variable_declarator(child, decl_kind, ctx)

    def _visit_variable_declarator(
        self,
        node: tree_sitter.Node,
        decl_kind: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle a single variable_declarator."""
        source = ctx.source

        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        var_name = _node_text(name_node, source)
        if not var_name:
            return

        value_node = _child_by_field(node, "value")

        # Type annotation on the variable
        type_ann = _extract_type_annotation(node, source)

        # Check if value is an arrow function or function expression
        if value_node is not None and value_node.type in (
            "arrow_function",
            "function_expression",
            "generator_function",
        ):
            self._visit_arrow_or_func_expr(
                var_name,
                value_node,
                decl_kind,
                type_ann,
                ctx,
            )
            return

        # Check if value is a class expression
        if value_node is not None and value_node.type == "class":
            # Treat as class with the variable name
            self._visit_class_expression(var_name, value_node, ctx)
            return

        # Regular variable / constant
        kind = NodeKind.CONSTANT if decl_kind == "const" else NodeKind.VARIABLE
        qualified = ctx.qualified(var_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, kind, var_name)

        _content_hash = compute_content_hash(source[node.start_byte : node.end_byte])
        meta: dict[str, Any] = {
            "declaration_kind": decl_kind,
        }
        if type_ann:
            meta["type_annotation"] = type_ann

        # Capture short initialiser values
        if value_node is not None:
            val_text = _node_text(value_node, source)
            if len(val_text) <= 200:
                meta["initializer"] = val_text

        # Docstring
        docstring = _find_preceding_docblock(node, source)

        var_node = Node(
            id=node_id,
            kind=kind,
            name=var_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(var_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Type edge
        if type_ann:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{type_ann}",
                    kind=EdgeKind.HAS_TYPE,
                    confidence=0.8,
                    metadata={"type": type_ann},
                )
            )

    def _visit_arrow_or_func_expr(
        self,
        name: str,
        value_node: tree_sitter.Node,
        decl_kind: str,
        type_ann: str | None,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle arrow functions and function expressions assigned to variables."""
        source = ctx.source
        qualified = ctx.qualified(name)
        node_id = generate_node_id(ctx.file_path, value_node.start_point[0] + 1, NodeKind.FUNCTION, name)

        # Parameters
        params_node = _child_by_field(value_node, "parameters")
        params = _extract_parameters(params_node, source)

        # Return type
        return_type = _extract_return_type(value_node, source)

        # Type parameters
        type_params = _extract_type_parameters(value_node, source)

        # Modifiers
        is_async_fn = _is_async(value_node, source)
        is_gen = value_node.type == "generator_function" or _is_generator(value_node, source)

        # Docstring (from the lexical_declaration parent)
        docstring = _find_preceding_docblock(value_node.parent, source) if value_node.parent else None

        _content_hash = compute_content_hash(source[value_node.start_byte : value_node.end_byte])
        meta: dict[str, Any] = {
            "declaration_kind": decl_kind,
            "is_arrow": value_node.type == "arrow_function",
        }
        if params:
            meta["parameters"] = params
        if return_type:
            meta["return_type"] = return_type
        if type_params:
            meta["type_parameters"] = type_params
        if type_ann:
            meta["type_annotation"] = type_ann
        if is_async_fn:
            meta["is_async"] = True
        if is_gen:
            meta["is_generator"] = True

        func_node = Node(
            id=node_id,
            kind=NodeKind.FUNCTION,
            name=name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=value_node.start_point[0] + 1,
            end_line=value_node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(func_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Return type edge
        if return_type:
            ctx.add_edge(
                Edge(
                    source_id=node_id,
                    target_id=f"unresolved:type:{return_type}",
                    kind=EdgeKind.RETURNS_TYPE,
                    confidence=0.8,
                    metadata={"return_type": return_type},
                )
            )

        # Scan body for calls and JSX
        body_node = _child_by_field(value_node, "body")
        if body_node is not None:
            self._scan_calls(body_node, node_id, ctx)
            self._scan_jsx(body_node, node_id, ctx)

    def _visit_class_expression(
        self,
        name: str,
        value_node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle class expressions assigned to variables."""
        source = ctx.source
        qualified = ctx.qualified(name)
        node_id = generate_node_id(ctx.file_path, value_node.start_point[0] + 1, NodeKind.CLASS, name)

        type_params = _extract_type_parameters(value_node, source)
        docstring = _find_preceding_docblock(value_node.parent, source) if value_node.parent else None

        _content_hash = compute_content_hash(source[value_node.start_byte : value_node.end_byte])
        meta: dict[str, Any] = {
            "is_expression": True,
        }
        if type_params:
            meta["type_parameters"] = type_params

        class_node = Node(
            id=node_id,
            kind=NodeKind.CLASS,
            name=name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=value_node.start_point[0] + 1,
            end_line=value_node.end_point[0] + 1,
            language="typescript",
            content_hash=_content_hash,
            docblock=docstring,
            metadata=meta,
        )
        ctx.add_node(class_node)

        # CONTAINS edge from file
        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Heritage
        self._process_class_heritage(value_node, node_id, ctx)

        # Body
        body = _child_by_field(value_node, "body")
        if body is None:
            for child in value_node.children:
                if child.type == "class_body":
                    body = child
                    break
        if body is not None:
            ctx.scope_stack.append(name)
            self._visit_class_body(body, node_id, ctx)
            ctx.scope_stack.pop()

    # ===================================================================
    # EXPRESSION STATEMENTS
    # ===================================================================

    def _visit_expression_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle expression_statement — detect CJS require, module.exports, calls."""
        source = ctx.source
        if not node.children:
            return
        expr = node.children[0]

        # CJS: const x = require("module")
        # This is actually handled in lexical_declaration, but
        # module.exports = ... is an expression_statement
        if expr.type == "assignment_expression":
            left = _child_by_field(expr, "left")
            right = _child_by_field(expr, "right")
            if left is not None and right is not None:
                left_text = _node_text(left, source)
                # module.exports = ...
                if left_text in ("module.exports", "exports"):
                    # This is a CJS default export
                    if right.type == "identifier":
                        name = _node_text(right, source)
                        ctx.default_export_name = name
                        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
                        target = ctx.defined_names.get(name, f"unresolved:local:{name}")
                        ctx.add_edge(
                            Edge(
                                source_id=file_node_id,
                                target_id=target,
                                kind=EdgeKind.EXPORTS,
                                confidence=0.85,
                                metadata={
                                    "exported_name": "default",
                                    "local_name": name,
                                    "is_cjs": True,
                                },
                            )
                        )
                # exports.foo = ...
                elif left_text.startswith("exports."):
                    export_name = left_text.split(".", 1)[1]
                    ctx.named_exports.add(export_name)
                    file_node_id = ctx.nodes[0].id if ctx.nodes else ""
                    ctx.add_edge(
                        Edge(
                            source_id=file_node_id,
                            target_id=f"unresolved:local:{export_name}",
                            kind=EdgeKind.EXPORTS,
                            confidence=0.80,
                            metadata={
                                "exported_name": export_name,
                                "is_cjs": True,
                            },
                        )
                    )

        # Detect top-level calls (e.g., app.use(), router.get())
        if expr.type == "call_expression":
            self._scan_single_call(expr, ctx.nodes[0].id if ctx.nodes else "", ctx)

    # ===================================================================
    # AMBIENT / DECLARE STATEMENTS (TypeScript-specific)
    # ===================================================================

    def _visit_ambient_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle ambient_declaration: declare const/let/var/function/class/enum/..."""
        # Ambient declarations contain the actual declaration as a child
        for child in node.children:
            if child.type in (
                "class_declaration",
                "abstract_class_declaration",
                "function_declaration",
                "function_signature",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "lexical_declaration",
                "variable_declaration",
                "module",
            ):
                self._visit(child, ctx)
                # Mark the last node as ambient/declare
                if len(ctx.nodes) > 1:
                    last = ctx.nodes[-1]
                    new_meta = {**last.metadata, "is_ambient": True}
                    ctx.nodes[-1] = Node(
                        id=last.id,
                        kind=last.kind,
                        name=last.name,
                        qualified_name=last.qualified_name,
                        file_path=last.file_path,
                        start_line=last.start_line,
                        end_line=last.end_line,
                        language=last.language,
                        metadata=new_meta,
                    )
                return

    # ===================================================================
    # MODULE DECLARATIONS (declare module "x" { ... })
    # ===================================================================

    def _visit_module_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        """Handle module (namespace) declarations."""
        source = ctx.source
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        mod_name = _node_text(name_node, source).strip("\"''`")
        if not mod_name:
            return

        qualified = ctx.qualified(mod_name)
        node_id = generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.MODULE, mod_name)

        mod_node = Node(
            id=node_id,
            kind=NodeKind.MODULE,
            name=mod_name,
            qualified_name=qualified,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="typescript",
        )
        ctx.add_node(mod_node)

        file_node_id = ctx.nodes[0].id if ctx.nodes else ""
        ctx.add_edge(
            Edge(
                source_id=file_node_id,
                target_id=node_id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
            )
        )

        # Visit body
        body = _child_by_field(node, "body")
        if body is not None:
            ctx.scope_stack.append(mod_name)
            self._visit_children(body, ctx)
            ctx.scope_stack.pop()

    # ===================================================================
    # CALL SCANNING
    # ===================================================================

    def _scan_calls(
        self,
        node: tree_sitter.Node,
        parent_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Recursively scan a subtree for call expressions and new expressions."""
        if node.type == "call_expression":
            self._scan_single_call(node, parent_id, ctx)
        elif node.type == "new_expression":
            self._scan_new_expression(node, parent_id, ctx)

        for child in node.children:
            # Don't recurse into nested function/class bodies
            if child.type in (
                "arrow_function",
                "function_expression",
                "function_declaration",
                "generator_function_declaration",
                "class_declaration",
                "abstract_class_declaration",
                "class",
            ):
                continue
            self._scan_calls(child, parent_id, ctx)

    def _scan_single_call(
        self,
        node: tree_sitter.Node,
        parent_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract a CALLS edge from a call_expression."""
        source = ctx.source
        func_node = _child_by_field(node, "function")
        if func_node is None:
            return

        callee = _node_text(func_node, source)
        if not callee or len(callee) > 200:
            return

        # Skip common noise
        if callee in ("console.log", "console.warn", "console.error", "console.info", "console.debug"):
            return

        # Detect require() calls
        if callee == "require":
            args = _child_by_field(node, "arguments")
            if args is not None:
                for arg in args.children:
                    if arg.type == "string":
                        module_path = _node_text(arg, source).strip("\"''`")
                        ctx.unresolved.append(
                            UnresolvedReference(
                                source_node_id=parent_id,
                                reference_name=module_path,
                                reference_kind=EdgeKind.IMPORTS,
                                line_number=node.start_point[0] + 1,
                            )
                        )
            return

        # Create CALLS edge
        target = ctx.defined_names.get(callee, f"unresolved:call:{callee}")
        ctx.add_edge(
            Edge(
                source_id=parent_id,
                target_id=target,
                kind=EdgeKind.CALLS,
                confidence=0.75,
                metadata={
                    "callee": callee,
                    "line": node.start_point[0] + 1,
                },
            )
        )

    def _scan_new_expression(
        self,
        node: tree_sitter.Node,
        parent_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract an INSTANTIATES edge from a new expression."""
        source = ctx.source
        constructor = _child_by_field(node, "constructor")
        if constructor is None:
            return
        class_name = _node_text(constructor, source)
        if not class_name or len(class_name) > 200:
            return

        target = ctx.defined_names.get(class_name, f"unresolved:class:{class_name}")
        ctx.add_edge(
            Edge(
                source_id=parent_id,
                target_id=target,
                kind=EdgeKind.INSTANTIATES,
                confidence=0.80,
                metadata={
                    "class_name": class_name,
                    "line": node.start_point[0] + 1,
                },
            )
        )

    # ===================================================================
    # JSX SCANNING
    # ===================================================================

    def _scan_jsx(
        self,
        node: tree_sitter.Node,
        parent_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Recursively scan for JSX elements (component usage)."""
        if node.type in ("jsx_element", "jsx_self_closing_element"):
            self._scan_jsx_element(node, parent_id, ctx)

        for child in node.children:
            # Don't recurse into nested function/class bodies
            if child.type in (
                "arrow_function",
                "function_expression",
                "function_declaration",
                "generator_function_declaration",
                "class_declaration",
                "abstract_class_declaration",
                "class",
            ):
                continue
            self._scan_jsx(child, parent_id, ctx)

    def _scan_jsx_element(
        self,
        node: tree_sitter.Node,
        parent_id: str,
        ctx: _ExtractionContext,
    ) -> None:
        """Extract RENDERS edge from a JSX element."""
        source = ctx.source
        component_name = ""

        if node.type == "jsx_self_closing_element":
            name_node = _child_by_field(node, "name")
            if name_node is not None:
                component_name = _node_text(name_node, source)
        elif node.type == "jsx_element":
            open_tag = _child_by_field(node, "open_tag")
            if open_tag is None:
                for child in node.children:
                    if child.type == "jsx_opening_element":
                        open_tag = child
                        break
            if open_tag is not None:
                name_node = _child_by_field(open_tag, "name")
                if name_node is not None:
                    component_name = _node_text(name_node, source)

        if not component_name:
            return

        # Only track custom components (uppercase first letter)
        if not component_name[0].isupper():
            return

        target = ctx.defined_names.get(component_name, f"unresolved:component:{component_name}")
        ctx.add_edge(
            Edge(
                source_id=parent_id,
                target_id=target,
                kind=EdgeKind.RENDERS,
                confidence=0.85,
                metadata={
                    "component": component_name,
                    "line": node.start_point[0] + 1,
                },
            )
        )

        # Extract props
        props: list[str] = []
        attrs_parent = node
        if node.type == "jsx_element":
            for child in node.children:
                if child.type == "jsx_opening_element":
                    attrs_parent = child
                    break
        for child in attrs_parent.children:
            if child.type == "jsx_attribute":
                for sub in child.children:
                    if sub.type == "property_identifier":
                        props.append(_node_text(sub, source))
                        break
        if props:
            ctx.add_edge(
                Edge(
                    source_id=parent_id,
                    target_id=target,
                    kind=EdgeKind.PASSES_PROP,
                    confidence=0.80,
                    metadata={
                        "component": component_name,
                        "props": props,
                        "line": node.start_point[0] + 1,
                    },
                )
            )
