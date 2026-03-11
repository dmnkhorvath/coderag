"""PHP AST Extractor using tree-sitter.

Extracts nodes and edges from PHP source files by walking the
tree-sitter AST. Handles classes, interfaces, traits, enums,
functions, methods, properties, constants, namespaces, and imports.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import tree_sitter
import tree_sitter_php

from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionError,
    ExtractionResult,
    Node,
    NodeKind,
    UnresolvedReference,
    generate_node_id,
    compute_content_hash,
)
from coderag.core.registry import ASTExtractor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _child_by_field(node: tree_sitter.Node, field: str) -> tree_sitter.Node | None:
    """Return the first child with the given field name."""
    return node.child_by_field_name(field)


def _children_of_type(node: tree_sitter.Node, *types: str) -> list[tree_sitter.Node]:
    """Return all direct children matching any of the given types."""
    return [c for c in node.children if c.type in types]


def _node_text(node: tree_sitter.Node | None, source: bytes) -> str:
    """Extract UTF-8 text for a node."""
    if node is None:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_preceding_docblock(node: tree_sitter.Node, source: bytes) -> str | None:
    """Find a doc-comment immediately preceding *node*."""
    prev = node.prev_named_sibling
    if prev is not None and prev.type == "comment":
        text = _node_text(prev, source)
        if text.startswith("/**"):
            return text
    return None


def _visibility(node: tree_sitter.Node, source: bytes) -> str:
    """Extract visibility modifier from a declaration node."""
    for child in node.children:
        if child.type == "visibility_modifier":
            return _node_text(child, source)
    return "public"  # PHP default


def _is_static(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a declaration has the static modifier."""
    for child in node.children:
        if child.type == "static_modifier":
            return True
        if _node_text(child, source) == "static":
            return True
    return False


def _is_abstract(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a declaration has the abstract modifier."""
    for child in node.children:
        if child.type == "abstract_modifier" or _node_text(child, source) == "abstract":
            return True
    return False


def _is_final(node: tree_sitter.Node, source: bytes) -> bool:
    """Check if a declaration has the final modifier."""
    for child in node.children:
        if child.type == "final_modifier" or _node_text(child, source) == "final":
            return True
    return False


def _extract_return_type(node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract the return type annotation from a function/method."""
    # In tree-sitter PHP, return type follows ":" after formal_parameters
    found_colon = False
    for child in node.children:
        if child.type == ":" or _node_text(child, source) == ":":
            found_colon = True
            continue
        if found_colon and child.type in (
            "named_type", "primitive_type", "nullable_type",
            "union_type", "intersection_type", "optional_type",
        ):
            return _node_text(child, source)
        if child.type in ("compound_statement", ";"):
            break
    return None


def _extract_parameters(node: tree_sitter.Node, source: bytes) -> list[dict[str, str]]:
    """Extract parameter info from formal_parameters."""
    params_node = _child_by_field(node, "parameters")
    if params_node is None:
        # fallback: find formal_parameters child
        for child in node.children:
            if child.type == "formal_parameters":
                params_node = child
                break
    if params_node is None:
        return []

    result: list[dict[str, str]] = []
    for param in _children_of_type(params_node, "simple_parameter", "variadic_parameter", "property_promotion_parameter"):
        info: dict[str, str] = {}
        for child in param.children:
            if child.type == "variable_name":
                info["name"] = _node_text(child, source).lstrip("$")
            elif child.type in ("named_type", "primitive_type", "nullable_type",
                                "union_type", "intersection_type", "optional_type"):
                info["type"] = _node_text(child, source)
        result.append(info)
    return result


def _qualified_name(namespace: str, name: str) -> str:
    """Build a fully-qualified name."""
    if namespace:
        return f"{namespace}\\{name}"
    return name


# ---------------------------------------------------------------------------
# PHPExtractor
# ---------------------------------------------------------------------------

class PHPExtractor(ASTExtractor):
    """Extract knowledge-graph nodes and edges from PHP source files."""

    _SUPPORTED_NODE_KINDS = frozenset({
        NodeKind.FILE,
        NodeKind.NAMESPACE,
        NodeKind.CLASS,
        NodeKind.INTERFACE,
        NodeKind.TRAIT,
        NodeKind.ENUM,
        NodeKind.METHOD,
        NodeKind.FUNCTION,
        NodeKind.PROPERTY,
        NodeKind.CONSTANT,
        NodeKind.IMPORT,
    })

    _SUPPORTED_EDGE_KINDS = frozenset({
        EdgeKind.CONTAINS,
        EdgeKind.EXTENDS,
        EdgeKind.IMPLEMENTS,
        EdgeKind.USES_TRAIT,
        EdgeKind.CALLS,
        EdgeKind.IMPORTS,
        EdgeKind.INSTANTIATES,
        EdgeKind.HAS_TYPE,
        EdgeKind.RETURNS_TYPE,
    })

    def __init__(self) -> None:
        lang = tree_sitter.Language(tree_sitter_php.language_php())
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
            errors.append(ExtractionError(
                file_path=file_path,
                line_number=None,
                message=f"tree-sitter parse failed: {exc}",
                severity="error",
            ))
            return ExtractionResult(
                file_path=file_path,
                language="php",
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
            language="php",
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
            language="php",
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
            errors.append(ExtractionError(
                file_path=file_path,
                line_number=node.start_point[0] + 1,
                message=f"Parse {'missing' if node.is_missing else 'error'} near: "
                        f"{_node_text(node, source)[:80]!r}",
                severity="warning",
                node_type=node.type,
            ))
        for child in node.children:
            self._collect_errors(child, file_path, source, errors)

    def _walk_program(self, root: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        """Walk top-level program children."""
        ns_node_id: str | None = None  # Track namespace node for parenting
        for child in root.children:
            try:
                if child.type == "namespace_definition":
                    self._handle_namespace(child, ctx)
                    # After handling namespace, use its node id as parent
                    # for subsequent declarations (PHP namespace without braces)
                    if ctx.nodes:
                        for n in reversed(ctx.nodes):
                            if n.kind == NodeKind.NAMESPACE:
                                ns_node_id = n.id
                                break
                    continue
                # Use namespace node as parent if we're inside a namespace
                parent_id = ns_node_id if ns_node_id else ctx.file_node_id
                if child.type == "namespace_use_declaration":
                    self._handle_use_declaration(child, ctx, parent_id)
                elif child.type == "class_declaration":
                    self._handle_class(child, ctx, parent_id, ctx.namespace)
                elif child.type == "interface_declaration":
                    self._handle_interface(child, ctx, parent_id, ctx.namespace)
                elif child.type == "trait_declaration":
                    self._handle_trait(child, ctx, parent_id, ctx.namespace)
                elif child.type == "enum_declaration":
                    self._handle_enum(child, ctx, parent_id, ctx.namespace)
                elif child.type == "function_definition":
                    self._handle_function(child, ctx, parent_id, ctx.namespace)
                elif child.type == "const_declaration":
                    self._handle_const(child, ctx, parent_id, ctx.namespace)
            except Exception as exc:
                ctx.errors.append(ExtractionError(
                file_path=ctx.file_path,
                line_number=child.start_point[0] + 1,
                    message=f"Extraction error in {child.type}: {exc}",
                    severity="warning",
                    node_type=child.type,
                ))

    # -- Namespace ----------------------------------------------------------

    def _handle_namespace(self, node: tree_sitter.Node, ctx: _ExtractionContext) -> None:
        name_node = None
        for child in node.children:
            if child.type == "namespace_name":
                name_node = child
                break
        ns_name = _node_text(name_node, ctx.source) if name_node else ""
        ctx.namespace = ns_name

        ns_node = Node(
            id=generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.NAMESPACE, ns_name),
            kind=NodeKind.NAMESPACE,
            name=ns_name,
            qualified_name=ns_name,
            file_path=ctx.file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="php",
        )
        ctx.nodes.append(ns_node)
        ctx.edges.append(Edge(
            source_id=ctx.file_node_id,
            target_id=ns_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=node.start_point[0] + 1,
        ))

        # Walk namespace body
        body = _child_by_field(node, "body")
        if body is not None:
            for child in body.children:
                self._dispatch_declaration(child, ctx, ns_node.id, ns_name)
        else:
            # Namespace without braces — rest of file belongs to it.
            # _walk_program will handle subsequent declarations using
            # ctx.namespace and ctx.namespace_node_id set above.
            pass

    def _dispatch_declaration(
        self,
        child: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        """Dispatch a declaration node to the appropriate handler."""
        try:
            if child.type == "namespace_use_declaration":
                self._handle_use_declaration(child, ctx, parent_id)
            elif child.type == "class_declaration":
                self._handle_class(child, ctx, parent_id, namespace)
            elif child.type == "interface_declaration":
                self._handle_interface(child, ctx, parent_id, namespace)
            elif child.type == "trait_declaration":
                self._handle_trait(child, ctx, parent_id, namespace)
            elif child.type == "enum_declaration":
                self._handle_enum(child, ctx, parent_id, namespace)
            elif child.type == "function_definition":
                self._handle_function(child, ctx, parent_id, namespace)
            elif child.type == "const_declaration":
                self._handle_const(child, ctx, parent_id, namespace)
        except Exception as exc:
            ctx.errors.append(ExtractionError(
            file_path=ctx.file_path,
            line_number=child.start_point[0] + 1,
                message=f"Extraction error in {child.type}: {exc}",
                severity="warning",
                node_type=child.type,
            ))

    # -- Use declarations (imports) -----------------------------------------

    def _handle_use_declaration(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        """Handle `use Foo\\Bar;` and `use Foo\\Bar as Baz;`."""
        for clause in _children_of_type(node, "namespace_use_clause"):
            qname_node = None
            alias_node = None
            for child in clause.children:
                if child.type == "qualified_name":
                    qname_node = child
                elif child.type == "namespace_aliasing_clause":
                    for ac in child.children:
                        if ac.type == "name":
                            alias_node = ac

            if qname_node is None:
                # Fallback: look for namespace_name directly
                for child in clause.children:
                    if child.type == "namespace_name":
                        qname_node = child
                        break
                if qname_node is None:
                    continue

            fqn = _node_text(qname_node, ctx.source)
            short_name = fqn.rsplit("\\\\", 1)[-1] if "\\\\" in fqn else fqn.rsplit("\\", 1)[-1]
            alias = _node_text(alias_node, ctx.source) if alias_node else short_name

            import_node = Node(
                id=generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.IMPORT, fqn),
                kind=NodeKind.IMPORT,
                name=alias,
                qualified_name=fqn,
                file_path=ctx.file_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="php",
                metadata={"alias": alias, "fqn": fqn},
            )
            ctx.nodes.append(import_node)
            ctx.edges.append(Edge(
                source_id=parent_id,
                target_id=import_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=node.start_point[0] + 1,
            ))
            # Store mapping for later resolution
            ctx.use_map[alias] = fqn
            # Create IMPORTS edge (unresolved — target is the FQN)
            ctx.unresolved.append(UnresolvedReference(
                source_node_id=import_node.id,
                reference_name=fqn,
                reference_kind=EdgeKind.IMPORTS,
                line_number=node.start_point[0] + 1,
            ))

    # -- Class --------------------------------------------------------------

    def _handle_class(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = _qualified_name(namespace, name)
        line = node.start_point[0] + 1

        class_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.CLASS, name),
            kind=NodeKind.CLASS,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
            metadata={
                "abstract": _is_abstract(node, ctx.source),
                "final": _is_final(node, ctx.source),
            },
        )
        ctx.nodes.append(class_node)
        ctx.edges.append(Edge(
            source_id=parent_id,
            target_id=class_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        # Extends
        base = _child_by_field(node, "base_clause")
        if base is None:
            for child in node.children:
                if child.type == "base_clause":
                    base = child
                    break
        if base is not None:
            for child in base.children:
                if child.type == "name" or child.type == "qualified_name":
                    parent_name = _node_text(child, ctx.source)
                    resolved = ctx.resolve_name(parent_name)
                    ctx.unresolved.append(UnresolvedReference(
                        source_node_id=class_node.id,
                        reference_name=resolved,
                        reference_kind=EdgeKind.EXTENDS,
                        line_number=base.start_point[0] + 1,
                    ))

        # Implements
        impl_clause = None
        for child in node.children:
            if child.type == "class_interface_clause":
                impl_clause = child
                break
        if impl_clause is not None:
            for child in impl_clause.children:
                if child.type == "name" or child.type == "qualified_name":
                    iface_name = _node_text(child, ctx.source)
                    resolved = ctx.resolve_name(iface_name)
                    ctx.unresolved.append(UnresolvedReference(
                        source_node_id=class_node.id,
                        reference_name=resolved,
                        reference_kind=EdgeKind.IMPLEMENTS,
                        line_number=impl_clause.start_point[0] + 1,
                    ))

        # Walk class body
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "declaration_list":
                    body = child
                    break
        if body is not None:
            self._walk_class_body(body, ctx, class_node.id, qname)

    # -- Interface ----------------------------------------------------------

    def _handle_interface(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = _qualified_name(namespace, name)
        line = node.start_point[0] + 1

        iface_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.INTERFACE, name),
            kind=NodeKind.INTERFACE,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
        )
        ctx.nodes.append(iface_node)
        ctx.edges.append(Edge(
            source_id=parent_id,
            target_id=iface_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        # Extends (interfaces can extend multiple interfaces)
        base = _child_by_field(node, "base_clause")
        if base is None:
            for child in node.children:
                if child.type == "base_clause":
                    base = child
                    break
        if base is not None:
            for child in base.children:
                if child.type in ("name", "qualified_name"):
                    parent_name = _node_text(child, ctx.source)
                    resolved = ctx.resolve_name(parent_name)
                    ctx.unresolved.append(UnresolvedReference(
                        source_node_id=iface_node.id,
                        reference_name=resolved,
                        reference_kind=EdgeKind.EXTENDS,
                        line_number=base.start_point[0] + 1,
                    ))

        # Walk interface body
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "declaration_list":
                    body = child
                    break
        if body is not None:
            self._walk_class_body(body, ctx, iface_node.id, qname)

    # -- Trait --------------------------------------------------------------

    def _handle_trait(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = _qualified_name(namespace, name)
        line = node.start_point[0] + 1

        trait_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.TRAIT, name),
            kind=NodeKind.TRAIT,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
        )
        ctx.nodes.append(trait_node)
        ctx.edges.append(Edge(
            source_id=parent_id,
            target_id=trait_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "declaration_list":
                    body = child
                    break
        if body is not None:
            self._walk_class_body(body, ctx, trait_node.id, qname)

    # -- Enum ---------------------------------------------------------------

    def _handle_enum(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = _qualified_name(namespace, name)
        line = node.start_point[0] + 1

        enum_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.ENUM, name),
            kind=NodeKind.ENUM,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
        )
        ctx.nodes.append(enum_node)
        ctx.edges.append(Edge(
            source_id=parent_id,
            target_id=enum_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        # Implements
        for child in node.children:
            if child.type == "class_interface_clause":
                for ic in child.children:
                    if ic.type in ("name", "qualified_name"):
                        iface_name = _node_text(ic, ctx.source)
                        resolved = ctx.resolve_name(iface_name)
                        ctx.unresolved.append(UnresolvedReference(
                            source_node_id=enum_node.id,
                            reference_name=resolved,
                            reference_kind=EdgeKind.IMPLEMENTS,
                            line_number=child.start_point[0] + 1,
                        ))

        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type in ("declaration_list", "enum_declaration_list"):
                    body = child
                    break
        if body is not None:
            self._walk_class_body(body, ctx, enum_node.id, qname)

    # -- Function (standalone) ----------------------------------------------

    def _handle_function(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = _qualified_name(namespace, name)
        line = node.start_point[0] + 1

        params = _extract_parameters(node, ctx.source)
        ret_type = _extract_return_type(node, ctx.source)

        func_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.FUNCTION, name),
            kind=NodeKind.FUNCTION,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
            metadata={
                "parameters": params,
                "return_type": ret_type,
            },
        )
        ctx.nodes.append(func_node)
        ctx.edges.append(Edge(
            source_id=parent_id,
            target_id=func_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        # Scan body for calls
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "compound_statement":
                    body = child
                    break
        if body is not None:
            self._scan_calls(body, ctx, func_node.id)

    # -- Constant (top-level) -----------------------------------------------

    def _handle_const(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        namespace: str,
    ) -> None:
        for child in node.children:
            if child.type == "const_element":
                name_node = _child_by_field(child, "name")
                if name_node is None:
                    for gc in child.children:
                        if gc.type == "name":
                            name_node = gc
                            break
                if name_node is None:
                    continue
                name = _node_text(name_node, ctx.source)
                qname = _qualified_name(namespace, name)
                line = child.start_point[0] + 1

                const_node = Node(
                id=generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.CONSTANT, name),
                kind=NodeKind.CONSTANT,
                name=name,
                start_line=node.start_point[0] + 1,
                    qualified_name=qname,
                    file_path=ctx.file_path,
                    end_line=child.end_point[0] + 1,
                    language="php",
                )
                ctx.nodes.append(const_node)
                ctx.edges.append(Edge(
                    source_id=parent_id,
                    target_id=const_node.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line,
                ))

    # -- Class body members -------------------------------------------------

    def _walk_class_body(
        self,
        body: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> None:
        """Walk a declaration_list inside a class/interface/trait/enum."""
        for child in body.children:
            try:
                if child.type == "method_declaration":
                    self._handle_method(child, ctx, class_id, class_qname)
                elif child.type == "property_declaration":
                    self._handle_property(child, ctx, class_id, class_qname)
                elif child.type == "use_declaration":
                    self._handle_trait_use(child, ctx, class_id)
                elif child.type in ("const_declaration", "class_constant_declaration"):
                    self._handle_class_const(child, ctx, class_id, class_qname)
            except Exception as exc:
                ctx.errors.append(ExtractionError(
                file_path=ctx.file_path,
                line_number=child.start_point[0] + 1,
                    message=f"Error in class member {child.type}: {exc}",
                    severity="warning",
                    node_type=child.type,
                ))

    def _handle_method(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = f"{class_qname}::{name}"
        line = node.start_point[0] + 1

        params = _extract_parameters(node, ctx.source)
        ret_type = _extract_return_type(node, ctx.source)

        method_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.METHOD, name),
            kind=NodeKind.METHOD,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="php",
            docblock=_find_preceding_docblock(node, ctx.source),
            source_text=_node_text(node, ctx.source),
            metadata={
                "visibility": _visibility(node, ctx.source),
                "static": _is_static(node, ctx.source),
                "abstract": _is_abstract(node, ctx.source),
                "parameters": params,
                "return_type": ret_type,
            },
        )
        ctx.nodes.append(method_node)
        ctx.edges.append(Edge(
            source_id=class_id,
            target_id=method_node.id,
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=line,
        ))

        # Scan body for calls
        body = _child_by_field(node, "body")
        if body is None:
            for child in node.children:
                if child.type == "compound_statement":
                    body = child
                    break
        if body is not None:
            self._scan_calls(body, ctx, method_node.id)

    def _handle_property(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> None:
        vis = _visibility(node, ctx.source)
        static = _is_static(node, ctx.source)
        prop_type = None
        for child in node.children:
            if child.type in ("named_type", "primitive_type", "nullable_type",
                              "union_type", "intersection_type", "optional_type"):
                prop_type = _node_text(child, ctx.source)
                break

        for child in node.children:
            if child.type == "property_element":
                var_node = None
                for gc in child.children:
                    if gc.type == "variable_name":
                        var_node = gc
                        break
                if var_node is None:
                    continue
                name = _node_text(var_node, ctx.source).lstrip("$")
                qname = f"{class_qname}::${name}"
                line = child.start_point[0] + 1

                prop_node_obj = Node(
                    id=generate_node_id(ctx.file_path, child.start_point[0] + 1, NodeKind.PROPERTY, name),
            kind=NodeKind.PROPERTY,
            name=name,
            start_line=child.start_point[0] + 1,
                    qualified_name=qname,
                    file_path=ctx.file_path,
                    end_line=child.end_point[0] + 1,
                    language="php",
                    metadata={
                        "visibility": vis,
                        "static": static,
                        "type": prop_type,
                    },
                )
                ctx.nodes.append(prop_node_obj)
                ctx.edges.append(Edge(
                    source_id=class_id,
                    target_id=prop_node_obj.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line,
                ))

    def _handle_trait_use(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
    ) -> None:
        """Handle `use TraitName;` inside a class body."""
        for child in node.children:
            if child.type in ("name", "qualified_name"):
                trait_name = _node_text(child, ctx.source)
                resolved = ctx.resolve_name(trait_name)
                ctx.unresolved.append(UnresolvedReference(
                    source_node_id=class_id,
                    reference_name=resolved,
                    reference_kind=EdgeKind.USES_TRAIT,
                    line_number=node.start_point[0] + 1,
                ))

    def _handle_class_const(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
    ) -> None:
        for child in node.children:
            if child.type == "const_element":
                name_node = _child_by_field(child, "name")
                if name_node is None:
                    for gc in child.children:
                        if gc.type == "name":
                            name_node = gc
                            break
                if name_node is None:
                    continue
                name = _node_text(name_node, ctx.source)
                qname = f"{class_qname}::{name}"
                line = child.start_point[0] + 1

                const_node = Node(
                id=generate_node_id(ctx.file_path, node.start_point[0] + 1, NodeKind.CONSTANT, name),
                kind=NodeKind.CONSTANT,
                name=name,
                start_line=node.start_point[0] + 1,
                    qualified_name=qname,
                    file_path=ctx.file_path,
                    end_line=child.end_point[0] + 1,
                    language="php",
                    metadata={"visibility": _visibility(node, ctx.source)},
                )
                ctx.nodes.append(const_node)
                ctx.edges.append(Edge(
                    source_id=class_id,
                    target_id=const_node.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line,
                ))

    # -- Call scanning ------------------------------------------------------

    def _scan_calls(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        caller_id: str,
    ) -> None:
        """Recursively scan for function/method calls and new expressions."""
        if node.type == "function_call_expression":
            func_node = _child_by_field(node, "function")
            if func_node is None and node.children:
                func_node = node.children[0]
            if func_node is not None:
                call_name = _node_text(func_node, ctx.source)
                resolved = ctx.resolve_name(call_name)
                ctx.unresolved.append(UnresolvedReference(
                    source_node_id=caller_id,
                    reference_name=resolved,
                    reference_kind=EdgeKind.CALLS,
                    line_number=node.start_point[0] + 1,
                ))

        elif node.type == "member_call_expression":
            name_node = _child_by_field(node, "name")
            if name_node is not None:
                method_name = _node_text(name_node, ctx.source)
                # We record the method name; resolution happens later
                ctx.unresolved.append(UnresolvedReference(
                    source_node_id=caller_id,
                    reference_name=method_name,
                    reference_kind=EdgeKind.CALLS,
                    line_number=node.start_point[0] + 1,
                    context={"call_type": "member"},
                ))

        elif node.type == "scoped_call_expression":
            scope_node = _child_by_field(node, "scope")
            name_node = _child_by_field(node, "name")
            if scope_node is not None and name_node is not None:
                scope_name = _node_text(scope_node, ctx.source)
                method_name = _node_text(name_node, ctx.source)
                resolved = ctx.resolve_name(scope_name)
                ctx.unresolved.append(UnresolvedReference(
                    source_node_id=caller_id,
                    reference_name=f"{resolved}::{method_name}",
                    reference_kind=EdgeKind.CALLS,
                    line_number=node.start_point[0] + 1,
                    context={"call_type": "static"},
                ))

        elif node.type == "object_creation_expression":
            for child in node.children:
                if child.type in ("name", "qualified_name"):
                    class_name = _node_text(child, ctx.source)
                    resolved = ctx.resolve_name(class_name)
                    ctx.unresolved.append(UnresolvedReference(
                        source_node_id=caller_id,
                        reference_name=resolved,
                        reference_kind=EdgeKind.INSTANTIATES,
                        line_number=node.start_point[0] + 1,
                    ))
                    break

        # Recurse into children
        for child in node.children:
            self._scan_calls(child, ctx, caller_id)


# ---------------------------------------------------------------------------
# Extraction context (mutable state bag)
# ---------------------------------------------------------------------------

class _ExtractionContext:
    """Mutable state passed through the extraction walk."""

    __slots__ = (
        "file_path", "source", "file_node_id",
        "nodes", "edges", "errors", "unresolved",
        "namespace", "use_map",
    )

    def __init__(
        self,
        file_path: str,
        source: bytes,
        file_node_id: str,
        nodes: list[Node],
        edges: list[Edge],
        errors: list[ExtractionError],
        unresolved: list[UnresolvedReference],
    ) -> None:
        self.file_path = file_path
        self.source = source
        self.file_node_id = file_node_id
        self.nodes = nodes
        self.edges = edges
        self.errors = errors
        self.unresolved = unresolved
        self.namespace: str = ""
        self.use_map: dict[str, str] = {}  # alias -> FQN

    def resolve_name(self, name: str) -> str:
        """Attempt to resolve a short name via the use-map."""
        # Already fully qualified
        if name.startswith("\\"):
            return name.lstrip("\\")
        # Check use map
        first_part = name.split("\\")[0]
        if first_part in self.use_map:
            rest = name[len(first_part):]
            return self.use_map[first_part] + rest
        # Relative to current namespace
        if self.namespace:
            return f"{self.namespace}\\{name}"
        return name
