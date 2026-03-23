"""Rust AST extractor for CodeRAG."""

from __future__ import annotations

import logging
import os
import time

import tree_sitter
import tree_sitter_rust as tsrust

from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionError,
    ExtractionResult,
    Node,
    NodeKind,
    UnresolvedReference,
    generate_node_id,
)
from coderag.core.registry import ASTExtractor

logger = logging.getLogger(__name__)


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode(errors="replace")


def _find_doc_comment(node: tree_sitter.Node, source: bytes) -> str | None:
    comments: list[str] = []
    prev = node.prev_sibling
    while prev and prev.type == "line_comment":
        text = _node_text(prev, source).strip()
        if text.startswith("///"):
            comments.insert(0, text[3:].strip())
        elif text.startswith("//"):
            comments.insert(0, text[2:].strip())
        prev = prev.prev_sibling
    return "\n".join(c for c in comments if c) if comments else None


def _walk(node: tree_sitter.Node):
    yield node
    for child in node.children:
        yield from _walk(child)


class RustExtractor(ASTExtractor):
    """Extracts nodes and edges from Rust source files."""

    def __init__(self) -> None:
        self._language = tree_sitter.Language(tsrust.language())
        self._parser = tree_sitter.Parser(self._language)

    def supported_node_kinds(self) -> frozenset[NodeKind]:
        return frozenset(
            {
                NodeKind.FILE,
                NodeKind.PACKAGE,
                NodeKind.CLASS,
                NodeKind.INTERFACE,
                NodeKind.FUNCTION,
                NodeKind.METHOD,
                NodeKind.PROPERTY,
                NodeKind.CONSTANT,
                NodeKind.IMPORT,
                NodeKind.TYPE_ALIAS,
            }
        )

    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        return frozenset(
            {
                EdgeKind.CONTAINS,
                EdgeKind.IMPLEMENTS,
                EdgeKind.CALLS,
                EdgeKind.IMPORTS,
                EdgeKind.HAS_TYPE,
                EdgeKind.RETURNS_TYPE,
                EdgeKind.EXTENDS,
            }
        )

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        start_time = time.perf_counter()
        nodes: list[Node] = []
        edges: list[Edge] = []
        unresolved: list[UnresolvedReference] = []
        errors: list[ExtractionError] = []

        try:
            tree = self._parser.parse(source)
            root = tree.root_node
            file_node = Node(
                id=generate_node_id(file_path, 1, NodeKind.FILE, file_path),
                kind=NodeKind.FILE,
                name=os.path.basename(file_path),
                qualified_name=file_path,
                file_path=file_path,
                start_line=1,
                end_line=root.end_point[0] + 1,
                language="rust",
            )
            nodes.append(file_node)
            self._extract_declarations(root, source, file_path, file_node.id, nodes, edges, unresolved)
        except Exception as e:
            logger.exception("Error extracting Rust AST for %s", file_path)
            errors.append(ExtractionError(file_path=file_path, line_number=1, message=str(e)))

        elapsed = int((time.perf_counter() - start_time) * 1000)
        return ExtractionResult(
            file_path,
            "rust",
            nodes=nodes,
            edges=edges,
            unresolved_references=unresolved,
            errors=errors,
            parse_time_ms=elapsed,
        )

    def _extract_declarations(
        self,
        root: tree_sitter.Node,
        source: bytes,
        file_path: str,
        parent_id: str,
        nodes: list[Node],
        edges: list[Edge],
        unresolved: list[UnresolvedReference],
    ) -> None:
        known_types: dict[str, str] = {}
        module_name = os.path.splitext(os.path.basename(file_path))[0]

        for child in root.children:
            if child.type == "mod_item":
                name_node = child.child_by_field_name("name")
                if not name_node:
                    continue
                module_name = _node_text(name_node, source)
                mod_node = Node(
                    id=generate_node_id(file_path, child.start_point[0] + 1, NodeKind.PACKAGE, module_name),
                    kind=NodeKind.PACKAGE,
                    name=module_name,
                    qualified_name=module_name,
                    file_path=file_path,
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    language="rust",
                    docblock=_find_doc_comment(child, source),
                    source_text=_node_text(child, source),
                )
                nodes.append(mod_node)
                edges.append(Edge(parent_id, mod_node.id, EdgeKind.CONTAINS, 1.0, child.start_point[0] + 1))

        container_id = parent_id
        for child in root.children:
            if child.type == "use_declaration":
                self._extract_import(child, source, file_path, container_id, nodes, edges)
            elif child.type == "struct_item":
                self._extract_struct(
                    child, source, file_path, container_id, module_name, nodes, edges, unresolved, known_types
                )
            elif child.type == "enum_item":
                self._extract_enum(child, source, file_path, container_id, module_name, nodes, edges, known_types)
            elif child.type == "trait_item":
                self._extract_trait(
                    child, source, file_path, container_id, module_name, nodes, edges, unresolved, known_types
                )
            elif child.type == "impl_item":
                self._extract_impl(
                    child, source, file_path, container_id, module_name, nodes, edges, unresolved, known_types
                )
            elif child.type == "function_item":
                self._extract_function(child, source, file_path, container_id, module_name, nodes, edges, unresolved)
            elif child.type in {"const_item", "static_item"}:
                self._extract_constant(child, source, file_path, container_id, module_name, nodes, edges)
            elif child.type == "type_item":
                self._extract_type_alias(child, source, file_path, container_id, module_name, nodes, edges)

    def _extract_import(self, node, source, file_path, parent_id, nodes, edges):
        arg = node.child_by_field_name("argument")
        if not arg:
            return
        path_str = _node_text(arg, source)
        imp_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.IMPORT, path_str),
            kind=NodeKind.IMPORT,
            name=path_str.split("::")[-1],
            qualified_name=path_str,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            source_text=_node_text(node, source),
        )
        nodes.append(imp_node)
        edges.append(Edge(parent_id, imp_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))

    def _extract_struct(self, node, source, file_path, parent_id, module_name, nodes, edges, unresolved, known_types):
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        struct_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.CLASS, qname),
            kind=NodeKind.CLASS,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            docblock=_find_doc_comment(node, source),
            source_text=_node_text(node, source),
        )
        nodes.append(struct_node)
        known_types[name] = struct_node.id
        edges.append(Edge(parent_id, struct_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        if body_node:
            for field in body_node.children:
                if field.type != "field_declaration":
                    continue
                fname = field.child_by_field_name("name")
                ftype = field.child_by_field_name("type")
                if fname:
                    prop_name = _node_text(fname, source)
                    prop_qname = f"{qname}.{prop_name}"
                    prop_node = Node(
                        id=generate_node_id(file_path, field.start_point[0] + 1, NodeKind.PROPERTY, prop_qname),
                        kind=NodeKind.PROPERTY,
                        name=prop_name,
                        qualified_name=prop_qname,
                        file_path=file_path,
                        start_line=field.start_point[0] + 1,
                        end_line=field.end_point[0] + 1,
                        language="rust",
                        source_text=_node_text(field, source),
                    )
                    nodes.append(prop_node)
                    edges.append(Edge(struct_node.id, prop_node.id, EdgeKind.CONTAINS, 1.0, field.start_point[0] + 1))
                    if ftype:
                        unresolved.append(
                            UnresolvedReference(
                                source_node_id=prop_node.id,
                                reference_name=_node_text(ftype, source),
                                reference_kind=EdgeKind.HAS_TYPE,
                                line_number=field.start_point[0] + 1,
                            )
                        )

    def _extract_enum(self, node, source, file_path, parent_id, module_name, nodes, edges, known_types):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        enum_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.CLASS, qname),
            kind=NodeKind.CLASS,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            docblock=_find_doc_comment(node, source),
            source_text=_node_text(node, source),
        )
        nodes.append(enum_node)
        known_types[name] = enum_node.id
        edges.append(Edge(parent_id, enum_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))

    def _extract_trait(self, node, source, file_path, parent_id, module_name, nodes, edges, unresolved, known_types):
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        trait_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.INTERFACE, qname),
            kind=NodeKind.INTERFACE,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            docblock=_find_doc_comment(node, source),
            source_text=_node_text(node, source),
        )
        nodes.append(trait_node)
        known_types[name] = trait_node.id
        edges.append(Edge(parent_id, trait_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        if body_node:
            for child in body_node.children:
                if child.type == "function_signature_item":
                    self._extract_trait_method(child, source, file_path, trait_node.id, qname, nodes, edges, unresolved)

    def _extract_trait_method(self, node, source, file_path, parent_id, trait_qname, nodes, edges, unresolved):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{trait_qname}.{name}"
        method_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.METHOD, qname),
            kind=NodeKind.METHOD,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            source_text=_node_text(node, source),
        )
        nodes.append(method_node)
        edges.append(Edge(parent_id, method_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        ret = node.child_by_field_name("return_type")
        if ret:
            unresolved.append(
                UnresolvedReference(
                    source_node_id=method_node.id,
                    reference_name=_node_text(ret, source),
                    reference_kind=EdgeKind.RETURNS_TYPE,
                    line_number=node.start_point[0] + 1,
                )
            )

    def _extract_impl(self, node, source, file_path, parent_id, module_name, nodes, edges, unresolved, known_types):
        type_node = node.child_by_field_name("type")
        trait_node = node.child_by_field_name("trait")
        body_node = node.child_by_field_name("body")
        if not type_node or not body_node:
            return
        type_name = _node_text(type_node, source)
        target_parent = known_types.get(type_name, parent_id)
        if trait_node:
            unresolved.append(
                UnresolvedReference(
                    source_node_id=known_types.get(type_name, target_parent),
                    reference_name=_node_text(trait_node, source),
                    reference_kind=EdgeKind.IMPLEMENTS,
                    line_number=node.start_point[0] + 1,
                )
            )
        for child in body_node.children:
            if child.type == "function_item":
                self._extract_method(
                    child, source, file_path, target_parent, module_name, type_name, nodes, edges, unresolved
                )

    def _extract_function(self, node, source, file_path, parent_id, module_name, nodes, edges, unresolved):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        func_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.FUNCTION, qname),
            kind=NodeKind.FUNCTION,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            docblock=_find_doc_comment(node, source),
            source_text=_node_text(node, source),
        )
        nodes.append(func_node)
        edges.append(Edge(parent_id, func_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        ret = node.child_by_field_name("return_type")
        if ret:
            unresolved.append(
                UnresolvedReference(
                    source_node_id=func_node.id,
                    reference_name=_node_text(ret, source),
                    reference_kind=EdgeKind.RETURNS_TYPE,
                    line_number=node.start_point[0] + 1,
                )
            )
        body = node.child_by_field_name("body")
        if body:
            self._scan_body_for_calls(body, source, func_node.id, unresolved)

    def _extract_method(self, node, source, file_path, parent_id, module_name, type_name, nodes, edges, unresolved):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{type_name}.{name}" if module_name else f"{type_name}.{name}"
        method_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.METHOD, qname),
            kind=NodeKind.METHOD,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            docblock=_find_doc_comment(node, source),
            source_text=_node_text(node, source),
        )
        nodes.append(method_node)
        edges.append(Edge(parent_id, method_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        ret = node.child_by_field_name("return_type")
        if ret:
            unresolved.append(
                UnresolvedReference(
                    source_node_id=method_node.id,
                    reference_name=_node_text(ret, source),
                    reference_kind=EdgeKind.RETURNS_TYPE,
                    line_number=node.start_point[0] + 1,
                )
            )
        body = node.child_by_field_name("body")
        if body:
            self._scan_body_for_calls(body, source, method_node.id, unresolved)

    def _extract_constant(self, node, source, file_path, parent_id, module_name, nodes, edges):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        const_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.CONSTANT, qname),
            kind=NodeKind.CONSTANT,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            source_text=_node_text(node, source),
        )
        nodes.append(const_node)
        edges.append(Edge(parent_id, const_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))

    def _extract_type_alias(self, node, source, file_path, parent_id, module_name, nodes, edges):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node, source)
        qname = f"{module_name}::{name}" if module_name else name
        alias_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.TYPE_ALIAS, qname),
            kind=NodeKind.TYPE_ALIAS,
            name=name,
            qualified_name=qname,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language="rust",
            source_text=_node_text(node, source),
        )
        nodes.append(alias_node)
        edges.append(Edge(parent_id, alias_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))

    def _scan_body_for_calls(self, body, source, caller_id, unresolved):
        for node in _walk(body):
            if node.type == "call_expression":
                fn_node = node.child_by_field_name("function") or (node.children[0] if node.children else None)
                if fn_node:
                    unresolved.append(
                        UnresolvedReference(
                            source_node_id=caller_id,
                            reference_name=_node_text(fn_node, source),
                            reference_kind=EdgeKind.CALLS,
                            line_number=node.start_point[0] + 1,
                        )
                    )
            elif node.type == "macro_invocation":
                name_node = node.child_by_field_name("macro") or (node.children[0] if node.children else None)
                if name_node:
                    unresolved.append(
                        UnresolvedReference(
                            source_node_id=caller_id,
                            reference_name=_node_text(name_node, source),
                            reference_kind=EdgeKind.CALLS,
                            line_number=node.start_point[0] + 1,
                        )
                    )
