"""JavaScript AST Extractor using tree-sitter.

Extracts nodes and edges from JavaScript source files by walking the
tree-sitter AST. Handles classes, functions, arrow functions, methods,
properties, variables, constants, imports (ESM + CJS), exports,
and JSX components.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import tree_sitter
import tree_sitter_javascript as tsjs

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
        # Stop after we pass keywords into the body
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


def _extract_parameters(node: tree_sitter.Node, source: bytes) -> list[dict[str, str]]:
    """Extract parameter info from formal_parameters."""
    params_node = _child_by_field(node, "parameters")
    if params_node is None:
        for child in node.children:
            if child.type == "formal_parameters":
                params_node = child
                break
    if params_node is None:
        return []

    params: list[dict[str, str]] = []
    for child in params_node.children:
        if child.type == "identifier":
            params.append({"name": _node_text(child, source)})
        elif child.type == "assignment_pattern":
            left = _child_by_field(child, "left")
            right = _child_by_field(child, "right")
            if left is not None:
                p: dict[str, str] = {"name": _node_text(left, source)}
                if right is not None:
                    p["default"] = _node_text(right, source)
                params.append(p)
        elif child.type == "rest_pattern":
            for gc in child.children:
                if gc.type == "identifier":
                    params.append({"name": "..." + _node_text(gc, source)})
                    break
        elif child.type == "object_pattern":
            params.append({"name": _node_text(child, source), "destructured": "true"})
        elif child.type == "array_pattern":
            params.append({"name": _node_text(child, source), "destructured": "true"})
    return params


def _is_pascal_case(name: str) -> bool:
    """Check if a name is PascalCase (used for component detection)."""
    return bool(name) and name[0].isupper() and not name.isupper()


def _contains_jsx(node: tree_sitter.Node) -> bool:
    """Check if a node's subtree contains JSX elements."""
    if node.type in ("jsx_element", "jsx_self_closing_element", "jsx_fragment"):
        return True
    for child in node.children:
        if _contains_jsx(child):
            return True
    return False


def _get_method_kind(node: tree_sitter.Node, source: bytes) -> str:
    """Determine method kind: constructor, getter, setter, or method."""
    for child in node.children:
        txt = _node_text(child, source)
        if txt == "get" and child.type != "property_identifier":
            return "getter"
        if txt == "set" and child.type != "property_identifier":
            return "setter"
        if child.type == "property_identifier":
            if _node_text(child, source) == "constructor":
                return "constructor"
            break
    return "method"


# ---------------------------------------------------------------------------
# Extraction context (mutable state bag)
# ---------------------------------------------------------------------------


@dataclass
class _ExtractionContext:
    """Mutable state passed through the extraction walk."""

    file_path: str
    source: bytes
    file_node_id: str
    nodes: list[Node]
    edges: list[Edge]
    errors: list[ExtractionError]
    unresolved: list[UnresolvedReference]
    # Map of imported names: local_name -> import_source
    import_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JavaScriptExtractor
# ---------------------------------------------------------------------------


class JavaScriptExtractor(ASTExtractor):
    """Extract knowledge-graph nodes and edges from JavaScript source files."""

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
        }
    )

    def __init__(self) -> None:
        lang = tree_sitter.Language(tsjs.language())
        self._parser = tree_sitter.Parser(lang)

    # -- ASTExtractor interface ---------------------------------------------

    def supported_node_kinds(self) -> frozenset[NodeKind]:
        return self._SUPPORTED_NODE_KINDS

    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        return self._SUPPORTED_EDGE_KINDS

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Parse *source* and return nodes + edges."""
        t0 = time.perf_counter()
        nodes: list[Node] = []
        edges: list[Edge] = []
        errors: list[ExtractionError] = []
        unresolved: list[UnresolvedReference] = []

        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            errors.append(
                ExtractionError(
                    file_path=file_path,
                    line_number=None,
                    message=f"tree-sitter parse failed: {exc}",
                    severity="error",
                )
            )
            return ExtractionResult(
                file_path=file_path,
                language="javascript",
                errors=errors,
                parse_time_ms=(time.perf_counter() - t0) * 1000,
            )

        # Collect tree-sitter errors
        self._collect_errors(tree.root_node, file_path, source, errors)

        # Create FILE node
        file_node = Node(
            id=generate_node_id(file_path, 1, NodeKind.FILE, file_path),
            kind=NodeKind.FILE,
            name=file_path.rsplit("/", 1)[-1],
            qualified_name=file_path,
            file_path=file_path,
            start_line=1,
            end_line=tree.root_node.end_point[0] + 1,
            language="javascript",
            content_hash=compute_content_hash(source),
        )
        nodes.append(file_node)

        # Walk the AST
        ctx = _ExtractionContext(
            file_path=file_path,
            source=source,
            file_node_id=file_node.id,
            nodes=nodes,
            edges=edges,
            errors=errors,
            unresolved=unresolved,
        )
        self._walk_program(tree.root_node, ctx)

        elapsed = (time.perf_counter() - t0) * 1000
        return ExtractionResult(
            file_path=file_path,
            language="javascript",
            nodes=nodes,
            edges=edges,
            unresolved_references=unresolved,
            errors=errors,
            parse_time_ms=elapsed,
        )

    # -- Tree walking -------------------------------------------------------

    def _collect_errors(
        self,
        node: tree_sitter.Node,
        file_path: str,
        source: bytes,
        errors: list[ExtractionError],
    ) -> None:
        """Recursively collect ERROR / MISSING nodes."""
        if node.type == "ERROR" or node.is_missing:
            errors.append(
                ExtractionError(
                    file_path=file_path,
                    line_number=node.start_point[0] + 1,
                    message=f"Parse {'missing' if node.is_missing else 'error'} near: "
                    f"{_node_text(node, source)[:80]!r}",
                    severity="warning",
                    node_type=node.type,
                )
            )
        for child in node.children:
            self._collect_errors(child, file_path, source, errors)

    def _walk_program(self, root: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Walk top-level program children."""
        for child in root.children:
            try:
                self._dispatch_top_level(child, ctx, ctx.file_node_id)
            except Exception as exc:
                ctx.errors.append(
                    ExtractionError(
                        file_path=ctx.file_path,
                        line_number=child.start_point[0] + 1,
                        message=f"Extraction error in {child.type}: {exc}",
                        severity="warning",
                        node_type=child.type,
                    )
                )

    def _dispatch_top_level(
        self,
        child: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        """Dispatch a top-level AST node to the appropriate handler."""
        if child.type == "import_statement":
            self._handle_import_statement(child, ctx, parent_id)
        elif child.type == "export_statement":
            self._handle_export_statement(child, ctx, parent_id)
        elif child.type == "class_declaration":
            self._handle_class(child, ctx, parent_id)
        elif child.type == "function_declaration":
            self._handle_function_declaration(child, ctx, parent_id)
        elif child.type == "lexical_declaration":
            self._handle_lexical_declaration(child, ctx, parent_id)
        elif child.type == "variable_declaration":
            self._handle_variable_declaration(child, ctx, parent_id)
        elif child.type == "expression_statement":
            self._handle_expression_statement(child, ctx, parent_id)

    # -- Imports (ESM) ------------------------------------------------------

    def _handle_import_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle ES module import statements.

        Patterns:
          import foo from './bar'           (default import)
          import { foo, bar } from './baz'  (named imports)
          import * as ns from './qux'       (namespace import)
          import './side-effect'             (side-effect import)
        """
        source_node = _child_by_field(node, "source")
        if source_node is None:
            for child in node.children:
                if child.type == "string":
                    source_node = child
                    break
        if source_node is None:
            return

        import_source = _node_text(source_node, ctx.source).strip("''\"")
        line = node.start_point[0] + 1

        # Collect specifiers
        specifiers: list[dict[str, str]] = []
        for child in node.children:
            if child.type == "import_clause":
                self._extract_import_specifiers(child, ctx, specifiers)

        # Side-effect import (no specifiers)
        if not specifiers:
            import_nd = Node(
                id=generate_node_id(ctx.file_path, line, NodeKind.IMPORT, import_source),
                kind=NodeKind.IMPORT,
                name=import_source,
                qualified_name=import_source,
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="javascript",
                source_text=_node_text(node, ctx.source),
                metadata={"source": import_source, "kind": "side-effect"},
            )
            ctx.nodes.append(import_nd)
            ctx.edges.append(
                Edge(
                    source_id=parent_id,
                    target_id=import_nd.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line,
                )
            )
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=ctx.file_node_id,
                    reference_name=import_source,
                    reference_kind=EdgeKind.IMPORTS,
                    line_number=line,
                    context={"import_kind": "side-effect"},
                )
            )
            return

        # Create import nodes for each specifier
        for spec in specifiers:
            local_name = spec.get("local", spec.get("imported", import_source))
            imported_name = spec.get("imported", local_name)
            import_kind = spec.get("kind", "named")

            import_nd = Node(
                id=generate_node_id(ctx.file_path, line, NodeKind.IMPORT, local_name),
                kind=NodeKind.IMPORT,
                name=local_name,
                qualified_name=f"{import_source}/{imported_name}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="javascript",
                source_text=_node_text(node, ctx.source),
                metadata={
                    "source": import_source,
                    "imported_name": imported_name,
                    "local_name": local_name,
                    "kind": import_kind,
                },
            )
            ctx.nodes.append(import_nd)
            ctx.edges.append(
                Edge(
                    source_id=parent_id,
                    target_id=import_nd.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line,
                )
            )
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=ctx.file_node_id,
                    reference_name=import_source,
                    reference_kind=EdgeKind.IMPORTS,
                    line_number=line,
                    context={
                        "import_kind": import_kind,
                        "imported_name": imported_name,
                        "local_name": local_name,
                    },
                )
            )
            ctx.import_map[local_name] = import_source

    def _extract_import_specifiers(
        self,
        clause: tree_sitter.Node,
        ctx: _ExtractionContext,
        specifiers: list[dict[str, str]],
    ) -> None:
        """Extract specifiers from an import_clause node."""
        for child in clause.children:
            if child.type == "identifier":
                # Default import: import Foo from '...'
                name = _node_text(child, ctx.source)
                specifiers.append(
                    {
                        "local": name,
                        "imported": "default",
                        "kind": "default",
                    }
                )
            elif child.type == "named_imports":
                for spec in child.children:
                    if spec.type == "import_specifier":
                        imported_node = _child_by_field(spec, "name")
                        alias_node = _child_by_field(spec, "alias")
                        if imported_node is None:
                            for gc in spec.children:
                                if gc.type == "identifier":
                                    imported_node = gc
                                    break
                        if imported_node is not None:
                            imported = _node_text(imported_node, ctx.source)
                            local = _node_text(alias_node, ctx.source) if alias_node else imported
                            specifiers.append(
                                {
                                    "local": local,
                                    "imported": imported,
                                    "kind": "named",
                                }
                            )
            elif child.type == "namespace_import":
                for gc in child.children:
                    if gc.type == "identifier":
                        name = _node_text(gc, ctx.source)
                        specifiers.append(
                            {
                                "local": name,
                                "imported": "*",
                                "kind": "namespace",
                            }
                        )
                        break

    # -- Exports ------------------------------------------------------------

    def _handle_export_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle export statements (default, named, re-export)."""
        line = node.start_point[0] + 1
        is_default = any(_node_text(c, ctx.source) == "default" for c in node.children)

        # Check for re-export: export { ... } from '...';
        source_node = _child_by_field(node, "source")
        if source_node is None:
            for child in node.children:
                if child.type == "string":
                    source_node = child
                    break

        if source_node is not None:
            re_src = _node_text(source_node, ctx.source).strip("''\"")
            self._handle_reexport(node, ctx, parent_id, re_src)
            return

        # Handle exported declarations
        for child in node.children:
            exported_node_id: str | None = None

            if child.type == "class_declaration":
                exported_node_id = self._handle_class(child, ctx, parent_id)
            elif child.type == "class":
                exported_node_id = self._handle_class(child, ctx, parent_id, default_name="default")
            elif child.type == "function_declaration":
                exported_node_id = self._handle_function_declaration(child, ctx, parent_id)
            elif child.type == "function":
                exported_node_id = self._handle_function_declaration(child, ctx, parent_id, default_name="default")
            elif child.type == "lexical_declaration":
                exported_node_id = self._handle_lexical_declaration(child, ctx, parent_id)
            elif child.type == "variable_declaration":
                exported_node_id = self._handle_variable_declaration(child, ctx, parent_id)
            elif child.type == "export_clause":
                self._handle_export_clause(child, ctx, is_default)
                continue
            elif is_default and child.type == "arrow_function":
                exported_node_id = self._handle_arrow_function(child, ctx, parent_id, var_name="default")
            elif is_default and child.type == "identifier":
                # export default someVar;
                name = _node_text(child, ctx.source)
                export_nd = Node(
                    id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, "default"),
                    kind=NodeKind.EXPORT,
                    name="default",
                    qualified_name=f"{ctx.file_path}/default",
                    file_path=ctx.file_path,
                    start_line=line,
                    end_line=node.end_point[0] + 1,
                    language="javascript",
                    source_text=_node_text(node, ctx.source),
                    metadata={"is_default": True, "local_name": name},
                )
                ctx.nodes.append(export_nd)
                ctx.edges.append(
                    Edge(
                        source_id=ctx.file_node_id,
                        target_id=export_nd.id,
                        kind=EdgeKind.EXPORTS,
                        confidence=1.0,
                        line_number=line,
                        metadata={"is_default": True},
                    )
                )
                continue
            elif is_default and child.type not in ("default", "export", ";"):
                # export default <expression>;
                export_nd = Node(
                    id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, "default"),
                    kind=NodeKind.EXPORT,
                    name="default",
                    qualified_name=f"{ctx.file_path}/default",
                    file_path=ctx.file_path,
                    start_line=line,
                    end_line=node.end_point[0] + 1,
                    language="javascript",
                    source_text=_node_text(node, ctx.source),
                    metadata={"is_default": True, "expression_type": child.type},
                )
                ctx.nodes.append(export_nd)
                ctx.edges.append(
                    Edge(
                        source_id=ctx.file_node_id,
                        target_id=export_nd.id,
                        kind=EdgeKind.EXPORTS,
                        confidence=1.0,
                        line_number=line,
                        metadata={"is_default": True},
                    )
                )
                continue
            else:
                continue

            # Create EXPORTS edge for exported declarations
            if exported_node_id is not None:
                ctx.edges.append(
                    Edge(
                        source_id=ctx.file_node_id,
                        target_id=exported_node_id,
                        kind=EdgeKind.EXPORTS,
                        confidence=1.0,
                        line_number=line,
                        metadata={"is_default": is_default},
                    )
                )

    def _handle_export_clause(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        is_default: bool,
    ) -> None:
        """Handle export { foo, bar as baz }."""
        line = node.start_point[0] + 1
        for child in node.children:
            if child.type == "export_specifier":
                name_node = _child_by_field(child, "name")
                alias_node = _child_by_field(child, "alias")
                if name_node is None:
                    for gc in child.children:
                        if gc.type == "identifier":
                            name_node = gc
                            break
                if name_node is not None:
                    local_name = _node_text(name_node, ctx.source)
                    exported_name = _node_text(alias_node, ctx.source) if alias_node else local_name
                    export_nd = Node(
                        id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, exported_name),
                        kind=NodeKind.EXPORT,
                        name=exported_name,
                        qualified_name=f"{ctx.file_path}/{exported_name}",
                        file_path=ctx.file_path,
                        start_line=line,
                        end_line=child.end_point[0] + 1,
                        language="javascript",
                        metadata={
                            "local_name": local_name,
                            "exported_name": exported_name,
                        },
                    )
                    ctx.nodes.append(export_nd)
                    ctx.edges.append(
                        Edge(
                            source_id=ctx.file_node_id,
                            target_id=export_nd.id,
                            kind=EdgeKind.EXPORTS,
                            confidence=1.0,
                            line_number=line,
                        )
                    )

    def _handle_reexport(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        source_path: str,
    ) -> None:
        """Handle re-export: export { foo } from './bar' or export * from './bar'."""
        line = node.start_point[0] + 1

        # Check for export * from '...';
        has_star = any(_node_text(c, ctx.source) == "*" for c in node.children)
        if has_star:
            ns_name = None
            for child in node.children:
                if child.type == "namespace_export":
                    for gc in child.children:
                        if gc.type == "identifier":
                            ns_name = _node_text(gc, ctx.source)
                            break

            export_name = ns_name or "*"
            export_nd = Node(
                id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, f"re:{source_path}"),
                kind=NodeKind.EXPORT,
                name=export_name,
                qualified_name=f"{ctx.file_path}/re:{source_path}",
                file_path=ctx.file_path,
                start_line=line,
                end_line=node.end_point[0] + 1,
                language="javascript",
                source_text=_node_text(node, ctx.source),
                metadata={"source": source_path, "kind": "namespace-reexport"},
            )
            ctx.nodes.append(export_nd)
            ctx.edges.append(
                Edge(
                    source_id=ctx.file_node_id,
                    target_id=export_nd.id,
                    kind=EdgeKind.RE_EXPORTS,
                    confidence=1.0,
                    line_number=line,
                    metadata={"source": source_path},
                )
            )
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=ctx.file_node_id,
                    reference_name=source_path,
                    reference_kind=EdgeKind.IMPORTS,
                    line_number=line,
                    context={"import_kind": "reexport"},
                )
            )
            return

        # Named re-exports: export { foo, bar } from '...';
        for child in node.children:
            if child.type == "export_clause":
                for spec in child.children:
                    if spec.type == "export_specifier":
                        name_node = _child_by_field(spec, "name")
                        alias_node = _child_by_field(spec, "alias")
                        if name_node is None:
                            for gc in spec.children:
                                if gc.type == "identifier":
                                    name_node = gc
                                    break
                        if name_node is not None:
                            imported = _node_text(name_node, ctx.source)
                            exported = _node_text(alias_node, ctx.source) if alias_node else imported
                            export_nd = Node(
                                id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, exported),
                                kind=NodeKind.EXPORT,
                                name=exported,
                                qualified_name=f"{ctx.file_path}/{exported}",
                                file_path=ctx.file_path,
                                start_line=line,
                                end_line=spec.end_point[0] + 1,
                                language="javascript",
                                metadata={
                                    "source": source_path,
                                    "imported_name": imported,
                                    "kind": "reexport",
                                },
                            )
                            ctx.nodes.append(export_nd)
                            ctx.edges.append(
                                Edge(
                                    source_id=ctx.file_node_id,
                                    target_id=export_nd.id,
                                    kind=EdgeKind.RE_EXPORTS,
                                    confidence=1.0,
                                    line_number=line,
                                    metadata={"source": source_path},
                                )
                            )

        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.file_node_id,
                reference_name=source_path,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"import_kind": "reexport"},
            )
        )

    # -- Classes ------------------------------------------------------------

    def _handle_class(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        default_name: str | None = None,
    ) -> str | None:
        """Handle class_declaration or class expression. Returns node id."""
        name_node = _child_by_field(node, "name")
        name = _node_text(name_node, ctx.source) if name_node else default_name
        if not name:
            return None

        line = node.start_point[0] + 1
        qname = f"{ctx.file_path}/{name}"
        docstring = _find_preceding_docblock(node, ctx.source)

        class_nd = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.CLASS, name),
            kind=NodeKind.CLASS,
            name=name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            docblock=docstring,
            content_hash=compute_content_hash(ctx.source[node.start_byte : node.end_byte]),
        )
        ctx.nodes.append(class_nd)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=class_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        # Superclass (extends)
        heritage_node = _child_by_field(node, "superclass")
        # Also try class_heritage child
        if heritage_node is None:
            for child in node.children:
                if child.type == "class_heritage":
                    for gc in child.children:
                        if gc.type == "identifier" or gc.type == "member_expression":
                            heritage_node = gc
                            break
                    break

        if heritage_node is not None:
            superclass = _node_text(heritage_node, ctx.source)
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=class_nd.id,
                    reference_name=superclass,
                    reference_kind=EdgeKind.EXTENDS,
                    line_number=line,
                    context={"superclass": superclass},
                )
            )
            class_nd.metadata["superclass"] = superclass

        # Walk class body
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "class_body":
                    body = child
                    break

        if body is not None:
            for member in body.children:
                try:
                    if member.type == "method_definition":
                        self._handle_method(member, ctx, class_nd.id, qname)
                    elif member.type in (
                        "field_definition",
                        "public_field_definition",
                    ):
                        self._handle_property(member, ctx, class_nd.id, qname)
                except Exception as exc:
                    ctx.errors.append(
                        ExtractionError(
                            file_path=ctx.file_path,
                            line_number=member.start_point[0] + 1,
                            message=f"Error in class member {member.type}: {exc}",
                            severity="warning",
                            node_type=member.type,
                        )
                    )

        # Scan class body for calls/instantiations
        if body is not None:
            self._scan_calls(body, ctx, class_nd.id)

        return class_nd.id

    # -- Methods -----------------------------------------------------------

    def _handle_method(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> str | None:
        """Handle method_definition inside a class body."""
        name_node = _child_by_field(node, "name")
        if name_node is None:
            for child in node.children:
                if child.type == "property_identifier":
                    name_node = child
                    break
        if name_node is None:
            return None

        name = _node_text(name_node, ctx.source)
        line = node.start_point[0] + 1
        qname = f"{class_qname}.{name}"
        docstring = _find_preceding_docblock(node, ctx.source)

        # Detect modifiers
        is_static = False
        is_async = False
        is_getter = False
        is_setter = False
        for child in node.children:
            text = _node_text(child, ctx.source)
            if text == "static":
                is_static = True
            elif text == "async":
                is_async = True
            elif text == "get":
                is_getter = True
            elif text == "set":
                is_setter = True

        # Extract parameters
        params_node = _child_by_field(node, "parameters")
        if params_node is None:
            for child in node.children:
                if child.type == "formal_parameters":
                    params_node = child
                    break
        parameters = _extract_parameters(params_node, ctx.source) if params_node else []

        method_nd = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.METHOD, qname),
            kind=NodeKind.METHOD,
            name=name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            docblock=docstring,
            content_hash=compute_content_hash(ctx.source[node.start_byte : node.end_byte]),
            metadata={
                "is_static": is_static,
                "is_async": is_async,
                "is_getter": is_getter,
                "is_setter": is_setter,
                "parameters": parameters,
            },
        )
        ctx.nodes.append(method_nd)
        ctx.edges.append(
            Edge(
                source_id=class_id,
                target_id=method_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        # Scan method body for calls
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "statement_block":
                    body = child
                    break
        if body is not None:
            self._scan_calls(body, ctx, method_nd.id)

        return method_nd.id

    # -- Properties --------------------------------------------------------

    def _handle_property(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> str | None:
        """Handle field_definition / public_field_definition in class body."""
        name_node = _child_by_field(node, "property")
        if name_node is None:
            for child in node.children:
                if child.type == "property_identifier":
                    name_node = child
                    break
        if name_node is None:
            return None

        name = _node_text(name_node, ctx.source)
        line = node.start_point[0] + 1
        qname = f"{class_qname}.{name}"

        is_static = any(_node_text(c, ctx.source) == "static" for c in node.children)

        prop_nd = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.PROPERTY, qname),
            kind=NodeKind.PROPERTY,
            name=name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            metadata={"is_static": is_static},
        )
        ctx.nodes.append(prop_nd)
        ctx.edges.append(
            Edge(
                source_id=class_id,
                target_id=prop_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        return prop_nd.id

    # -- Functions ---------------------------------------------------------

    def _handle_function_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        default_name: str | None = None,
    ) -> str | None:
        """Handle function_declaration or function expression."""
        name_node = _child_by_field(node, "name")
        name = _node_text(name_node, ctx.source) if name_node else default_name
        if not name:
            return None

        line = node.start_point[0] + 1
        qname = f"{ctx.file_path}/{name}"
        docstring = _find_preceding_docblock(node, ctx.source)

        is_async = any(_node_text(c, ctx.source) == "async" for c in node.children)
        is_generator = any(_node_text(c, ctx.source) == "*" for c in node.children)

        # Extract parameters
        params_node = _child_by_field(node, "parameters")
        if params_node is None:
            for child in node.children:
                if child.type == "formal_parameters":
                    params_node = child
                    break
        parameters = _extract_parameters(params_node, ctx.source) if params_node else []

        # Detect JSX component (PascalCase + returns JSX)
        is_component = name[0:1].isupper() and self._body_contains_jsx(node)
        kind = NodeKind.COMPONENT if is_component else NodeKind.FUNCTION

        func_nd = Node(
            id=generate_node_id(ctx.file_path, line, kind, name),
            kind=kind,
            name=name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            docblock=docstring,
            content_hash=compute_content_hash(ctx.source[node.start_byte : node.end_byte]),
            metadata={
                "is_async": is_async,
                "is_generator": is_generator,
                "parameters": parameters,
            },
        )
        ctx.nodes.append(func_nd)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=func_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        # Scan body for calls
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "statement_block":
                    body = child
                    break
        if body is not None:
            self._scan_calls(body, ctx, func_nd.id)

        return func_nd.id

    # -- Arrow functions ---------------------------------------------------

    def _handle_arrow_function(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        var_name: str,
    ) -> str | None:
        """Handle arrow_function assigned to a variable."""
        line = node.start_point[0] + 1
        qname = f"{ctx.file_path}/{var_name}"

        is_async = any(_node_text(c, ctx.source) == "async" for c in node.children)

        # Extract parameters
        params_node = _child_by_field(node, "parameters")
        if params_node is None:
            for child in node.children:
                if child.type == "formal_parameters":
                    params_node = child
                    break
                elif child.type == "identifier":
                    # Single param without parens: x => ...
                    params_node = None
                    break
        parameters = _extract_parameters(params_node, ctx.source) if params_node else []

        # Detect JSX component
        is_component = var_name[0:1].isupper() and self._body_contains_jsx(node)
        kind = NodeKind.COMPONENT if is_component else NodeKind.FUNCTION

        func_nd = Node(
            id=generate_node_id(ctx.file_path, line, kind, var_name),
            kind=kind,
            name=var_name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            content_hash=compute_content_hash(ctx.source[node.start_byte : node.end_byte]),
            metadata={
                "is_async": is_async,
                "is_arrow": True,
                "parameters": parameters,
            },
        )
        ctx.nodes.append(func_nd)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=func_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        # Scan body for calls
        body = _child_by_field(node, "body")
        if body is not None:
            self._scan_calls(body, ctx, func_nd.id)

        return func_nd.id

    # -- Variable / Lexical declarations -----------------------------------

    def _handle_lexical_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> str | None:
        """Handle const/let declarations at module scope."""
        # Determine if const or let
        is_const = any(_node_text(c, ctx.source) == "const" for c in node.children)
        last_id: str | None = None

        for child in node.children:
            if child.type == "variable_declarator":
                last_id = self._handle_variable_declarator(child, ctx, parent_id, is_const=is_const)
        return last_id

    def _handle_variable_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> str | None:
        """Handle var declarations at module scope."""
        last_id: str | None = None
        for child in node.children:
            if child.type == "variable_declarator":
                last_id = self._handle_variable_declarator(child, ctx, parent_id, is_const=False)
        return last_id

    def _handle_variable_declarator(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        is_const: bool,
    ) -> str | None:
        """Handle a single variable_declarator."""
        name_node = _child_by_field(node, "name")
        if name_node is None:
            for child in node.children:
                if child.type == "identifier":
                    name_node = child
                    break
        if name_node is None:
            return None

        name = _node_text(name_node, ctx.source)
        line = node.start_point[0] + 1

        # Check if value is a function/arrow/class
        value_node = _child_by_field(node, "value")
        if value_node is None:
            for child in node.children:
                if child.type not in ("identifier", "=", ";"):
                    if child != name_node:
                        value_node = child
                        break

        if value_node is not None:
            if value_node.type == "arrow_function":
                return self._handle_arrow_function(value_node, ctx, parent_id, var_name=name)
            elif value_node.type == "function":
                return self._handle_function_declaration(value_node, ctx, parent_id, default_name=name)
            elif value_node.type == "class":
                return self._handle_class(value_node, ctx, parent_id, default_name=name)
            elif value_node.type == "call_expression":
                # Check for require() calls
                req_source = self._extract_require_source(value_node, ctx)
                if req_source is not None:
                    return self._handle_require(node, ctx, parent_id, name, req_source)

        # Plain variable or constant
        kind = NodeKind.CONSTANT if is_const else NodeKind.VARIABLE
        qname = f"{ctx.file_path}/{name}"

        var_nd = Node(
            id=generate_node_id(ctx.file_path, line, kind, name),
            kind=kind,
            name=name,
            qualified_name=qname,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="javascript",
            source_text=_node_text(node, ctx.source),
            metadata={"is_const": is_const},
        )
        ctx.nodes.append(var_nd)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=var_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        return var_nd.id

    # -- CommonJS require() ------------------------------------------------

    def _extract_require_source(
        self,
        call_node: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> str | None:
        """If *call_node* is `require('..')`  return the source string, else None."""
        func_node = _child_by_field(call_node, "function")
        if func_node is None:
            for child in call_node.children:
                if child.type == "identifier":
                    func_node = child
                    break
        if func_node is None or _node_text(func_node, ctx.source) != "require":
            return None

        args_node = _child_by_field(call_node, "arguments")
        if args_node is None:
            for child in call_node.children:
                if child.type == "arguments":
                    args_node = child
                    break
        if args_node is None:
            return None

        for child in args_node.children:
            if child.type == "string":
                return _node_text(child, ctx.source).strip("''\"")
        return None

    def _handle_require(
        self,
        decl_node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        local_name: str,
        source_path: str,
    ) -> str:
        """Create an IMPORT node for a require() call."""
        line = decl_node.start_point[0] + 1

        import_nd = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.IMPORT, local_name),
            kind=NodeKind.IMPORT,
            name=local_name,
            qualified_name=f"{source_path}/{local_name}",
            file_path=ctx.file_path,
            start_line=line,
            end_line=decl_node.end_point[0] + 1,
            language="javascript",
            source_text=_node_text(decl_node, ctx.source),
            metadata={
                "source": source_path,
                "local_name": local_name,
                "kind": "require",
            },
        )
        ctx.nodes.append(import_nd)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=import_nd.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=ctx.file_node_id,
                reference_name=source_path,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"import_kind": "require", "local_name": local_name},
            )
        )
        ctx.import_map[local_name] = source_path
        return import_nd.id

    # -- Expression statements (module.exports, bare require) ---------------

    def _handle_expression_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle expression_statement at module scope.

        Detects:
          module.exports = ...
          module.exports.foo = ...
          exports.foo = ...
          require('...')
        """
        if not node.children:
            return

        expr = node.children[0]
        line = node.start_point[0] + 1

        # module.exports = ... or exports.foo = ...
        if expr.type == "assignment_expression":
            left = _child_by_field(expr, "left")
            right = _child_by_field(expr, "right")
            if left is not None:
                left_text = _node_text(left, ctx.source)
                if left_text.startswith(("module.exports", "exports.")):
                    # Determine export name
                    if left_text == "module.exports":
                        export_name = "default"
                    else:
                        export_name = left_text.split(".", 2)[-1]

                    export_nd = Node(
                        id=generate_node_id(ctx.file_path, line, NodeKind.EXPORT, export_name),
                        kind=NodeKind.EXPORT,
                        name=export_name,
                        qualified_name=f"{ctx.file_path}/{export_name}",
                        file_path=ctx.file_path,
                        start_line=line,
                        end_line=node.end_point[0] + 1,
                        language="javascript",
                        source_text=_node_text(node, ctx.source),
                        metadata={
                            "kind": "cjs",
                            "is_default": export_name == "default",
                        },
                    )
                    ctx.nodes.append(export_nd)
                    ctx.edges.append(
                        Edge(
                            source_id=ctx.file_node_id,
                            target_id=export_nd.id,
                            kind=EdgeKind.EXPORTS,
                            confidence=1.0,
                            line_number=line,
                        )
                    )

                    # If right side is a class/function, extract it too
                    if right is not None:
                        if right.type == "class":
                            self._handle_class(
                                right,
                                ctx,
                                parent_id,
                                default_name=export_name,
                            )
                        elif right.type == "function":
                            self._handle_function_declaration(
                                right,
                                ctx,
                                parent_id,
                                default_name=export_name,
                            )

        # Bare require() call as expression statement
        elif expr.type == "call_expression":
            req_source = self._extract_require_source(expr, ctx)
            if req_source is not None:
                self._handle_require(
                    node,
                    ctx,
                    parent_id,
                    local_name=req_source.rsplit("/", 1)[-1],
                    source_path=req_source,
                )

    # -- Call / instantiation scanning ------------------------------------

    def _scan_calls(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        owner_id: str,
    ) -> None:
        """Recursively scan *node* for call_expression and new_expression."""
        for child in node.children:
            try:
                if child.type == "call_expression":
                    self._handle_call_expression(child, ctx, owner_id)
                elif child.type == "new_expression":
                    self._handle_new_expression(child, ctx, owner_id)
                # Recurse into blocks but skip nested function/class bodies
                elif child.type not in (
                    "function_declaration",
                    "function",
                    "arrow_function",
                    "class_declaration",
                    "class",
                ):
                    self._scan_calls(child, ctx, owner_id)
            except Exception:
                pass  # best-effort scanning

    def _handle_call_expression(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        owner_id: str,
    ) -> None:
        """Extract a CALLS edge (or DYNAMIC_IMPORTS for import())."""
        func_node = _child_by_field(node, "function")
        if func_node is None:
            for child in node.children:
                if child.type not in ("arguments", "(", ")"):
                    func_node = child
                    break
        if func_node is None:
            return

        line = node.start_point[0] + 1
        callee = _node_text(func_node, ctx.source)

        # Dynamic import: import('./module')
        if func_node.type == "import":
            args_node = _child_by_field(node, "arguments")
            if args_node is None:
                for child in node.children:
                    if child.type == "arguments":
                        args_node = child
                        break
            if args_node is not None:
                for child in args_node.children:
                    if child.type == "string":
                        mod_path = _node_text(child, ctx.source).strip("''\"")
                        ctx.unresolved.append(
                            UnresolvedReference(
                                source_node_id=owner_id,
                                reference_name=mod_path,
                                reference_kind=EdgeKind.DYNAMIC_IMPORTS,
                                line_number=line,
                                context={"kind": "dynamic_import"},
                            )
                        )
                        break
            # Also recurse into arguments
            if args_node is not None:
                self._scan_calls(args_node, ctx, owner_id)
            return

        # Skip require() - already handled
        if callee == "require":
            return

        # Regular function call
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=owner_id,
                reference_name=callee,
                reference_kind=EdgeKind.CALLS,
                line_number=line,
                context={"callee": callee},
            )
        )

        # Recurse into arguments
        args_node = _child_by_field(node, "arguments")
        if args_node is None:
            for child in node.children:
                if child.type == "arguments":
                    args_node = child
                    break
        if args_node is not None:
            self._scan_calls(args_node, ctx, owner_id)

    def _handle_new_expression(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        owner_id: str,
    ) -> None:
        """Extract an INSTANTIATES edge for `new ClassName()`."""
        constructor_node = _child_by_field(node, "constructor")
        if constructor_node is None:
            for child in node.children:
                if child.type in ("identifier", "member_expression"):
                    constructor_node = child
                    break
        if constructor_node is None:
            return

        class_name = _node_text(constructor_node, ctx.source)
        line = node.start_point[0] + 1

        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=owner_id,
                reference_name=class_name,
                reference_kind=EdgeKind.INSTANTIATES,
                line_number=line,
                context={"class_name": class_name},
            )
        )

    # -- JSX detection -----------------------------------------------------

    def _body_contains_jsx(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* (or its body) contains JSX elements."""
        _JSX_TYPES = frozenset(
            {
                "jsx_element",
                "jsx_self_closing_element",
                "jsx_fragment",
            }
        )
        stack: list[tree_sitter.Node] = [node]
        while stack:
            current = stack.pop()
            if current.type in _JSX_TYPES:
                return True
            # Don't recurse into nested function/class definitions
            if current != node and current.type in (
                "function_declaration",
                "function",
                "arrow_function",
                "class_declaration",
                "class",
            ):
                continue
            stack.extend(current.children)
        return False
