"""Go AST extractor for CodeRAG."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import tree_sitter
import tree_sitter_go as tsgo

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
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

def _find_doc_comment(node: tree_sitter.Node, source: bytes) -> str | None:
    comments = []
    prev = node.prev_sibling
    while prev and prev.type == "comment":
        text = _node_text(prev, source)
        if text.startswith("//"):
            comments.insert(0, text.lstrip("//").strip())
        prev = prev.prev_sibling
    return "\n".join(comments) if comments else None

class GoExtractor(ASTExtractor):
    """Extracts nodes and edges from Go source files."""

    def __init__(self) -> None:
        self._language = tree_sitter.Language(tsgo.language())
        self._parser = tree_sitter.Parser(self._language)
        self._calls_query = tree_sitter.Query(self._language, "(call_expression) @call")

    def supported_node_kinds(self) -> frozenset[NodeKind]:
        return frozenset({
            NodeKind.FILE, NodeKind.PACKAGE, NodeKind.CLASS, NodeKind.INTERFACE,
            NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.PROPERTY, NodeKind.CONSTANT,
            NodeKind.VARIABLE, NodeKind.IMPORT, NodeKind.TYPE_ALIAS,
        })

    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        return frozenset({
            EdgeKind.CONTAINS, EdgeKind.IMPLEMENTS, EdgeKind.CALLS, EdgeKind.IMPORTS,
            EdgeKind.HAS_TYPE, EdgeKind.RETURNS_TYPE, EdgeKind.DEPENDS_ON, EdgeKind.EXTENDS,
        })

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
                kind=NodeKind.FILE, name=os.path.basename(file_path), qualified_name=file_path,
                file_path=file_path, start_line=1, end_line=root.end_point[0] + 1, language="go",
            )
            nodes.append(file_node)

            self._extract_declarations(root, source, file_path, file_node.id, nodes, edges, unresolved)

        except Exception as e:
            logger.exception("Error extracting Go AST for %s", file_path)
            errors.append(ExtractionError(file_path=file_path, line_number=1, message=str(e)))

        elapsed = int((time.perf_counter() - start_time) * 1000)
        return ExtractionResult(
            file_path, "go", nodes=nodes, edges=edges,
            unresolved_references=unresolved, errors=errors, parse_time_ms=elapsed,
        )

    def _extract_declarations(
        self, root: tree_sitter.Node, source: bytes, file_path: str, parent_id: str,
        nodes: list[Node], edges: list[Edge], unresolved: list[UnresolvedReference]
    ) -> None:
        pkg_name = ""
        for child in root.children:
            if child.type == "package_clause":
                pkg_id_node = next((c for c in child.children if c.type == "package_identifier"), None)
                if pkg_id_node:
                    pkg_name = _node_text(pkg_id_node, source)
                    pkg_node = Node(
                        id=generate_node_id(file_path, child.start_point[0] + 1, NodeKind.PACKAGE, pkg_name),
                        kind=NodeKind.PACKAGE, name=pkg_name, qualified_name=pkg_name, file_path=file_path,
                        start_line=child.start_point[0] + 1, end_line=child.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(child, source),
                    )
                    nodes.append(pkg_node)
                    edges.append(Edge(parent_id, pkg_node.id, EdgeKind.CONTAINS, 1.0, child.start_point[0] + 1))
                    parent_id = pkg_node.id
                    break

        for child in root.children:
            if child.type == "import_declaration":
                self._extract_imports(child, source, file_path, parent_id, nodes, edges)
            elif child.type == "type_declaration":
                self._extract_types(child, source, file_path, parent_id, pkg_name, nodes, edges, unresolved)
            elif child.type == "function_declaration":
                self._extract_function(child, source, file_path, parent_id, pkg_name, nodes, edges, unresolved)
            elif child.type == "method_declaration":
                self._extract_method(child, source, file_path, parent_id, pkg_name, nodes, edges, unresolved)
            elif child.type == "const_declaration":
                self._extract_const(child, source, file_path, parent_id, pkg_name, nodes, edges)
            elif child.type == "var_declaration":
                self._extract_var(child, source, file_path, parent_id, pkg_name, nodes, edges)

    def _extract_imports(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str,
        nodes: list[Node], edges: list[Edge]
    ) -> None:
        def process_spec(spec: tree_sitter.Node):
            path_node = spec.child_by_field_name("path")
            if not path_node: return
            path_str = _node_text(path_node, source).strip('"`')
            alias_node = spec.child_by_field_name("name")
            alias = _node_text(alias_node, source) if alias_node else None
            name = alias if alias and alias != "." else path_str.split("/")[-1]

            imp_node = Node(
                id=generate_node_id(file_path, spec.start_point[0] + 1, NodeKind.IMPORT, name),
                kind=NodeKind.IMPORT, name=name, qualified_name=path_str, file_path=file_path,
                start_line=spec.start_point[0] + 1, end_line=spec.end_point[0] + 1, language="go",
                metadata={"alias": alias} if alias else {},
            )
            nodes.append(imp_node)
            edges.append(Edge(parent_id, imp_node.id, EdgeKind.CONTAINS, 1.0, spec.start_point[0] + 1))

        for child in node.children:
            if child.type == "import_spec": process_spec(child)
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec": process_spec(spec)

    def _extract_types(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, pkg_name: str,
        nodes: list[Node], edges: list[Edge], unresolved: list[UnresolvedReference]
    ) -> None:
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if not name_node or not type_node: continue
                name = _node_text(name_node, source)
                qname = f"{pkg_name}.{name}" if pkg_name else name
                
                if type_node.type == "struct_type":
                    struct_node = Node(
                        id=generate_node_id(file_path, child.start_point[0] + 1, NodeKind.CLASS, qname),
                        kind=NodeKind.CLASS, name=name, qualified_name=qname, file_path=file_path,
                        start_line=child.start_point[0] + 1, end_line=child.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(node, source), source_text=_node_text(child, source),
                    )
                    nodes.append(struct_node)
                    edges.append(Edge(parent_id, struct_node.id, EdgeKind.CONTAINS, 1.0, child.start_point[0] + 1))
                    self._extract_struct_fields(type_node, source, file_path, struct_node.id, qname, nodes, edges, unresolved)
                elif type_node.type == "interface_type":
                    iface_node = Node(
                        id=generate_node_id(file_path, child.start_point[0] + 1, NodeKind.INTERFACE, qname),
                        kind=NodeKind.INTERFACE, name=name, qualified_name=qname, file_path=file_path,
                        start_line=child.start_point[0] + 1, end_line=child.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(node, source), source_text=_node_text(child, source),
                    )
                    nodes.append(iface_node)
                    edges.append(Edge(parent_id, iface_node.id, EdgeKind.CONTAINS, 1.0, child.start_point[0] + 1))
            elif child.type == "type_alias":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qname = f"{pkg_name}.{name}" if pkg_name else name
                    alias_node = Node(
                        id=generate_node_id(file_path, child.start_point[0] + 1, NodeKind.TYPE_ALIAS, qname),
                        kind=NodeKind.TYPE_ALIAS, name=name, qualified_name=qname, file_path=file_path,
                        start_line=child.start_point[0] + 1, end_line=child.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(node, source), source_text=_node_text(child, source),
                    )
                    nodes.append(alias_node)
                    edges.append(Edge(parent_id, alias_node.id, EdgeKind.CONTAINS, 1.0, child.start_point[0] + 1))

    def _extract_struct_fields(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, struct_qname: str,
        nodes: list[Node], edges: list[Edge], unresolved: list[UnresolvedReference]
    ) -> None:
        field_list = next((c for c in node.children if c.type == "field_declaration_list"), None)
        if not field_list: return
        for field in field_list.children:
            if field.type == "field_declaration":
                name_node = field.child_by_field_name("name")
                type_node = field.child_by_field_name("type")
                if name_node:
                    name = _node_text(name_node, source)
                    qname = f"{struct_qname}.{name}"
                    prop_node = Node(
                        id=generate_node_id(file_path, field.start_point[0] + 1, NodeKind.PROPERTY, qname),
                        kind=NodeKind.PROPERTY, name=name, qualified_name=qname, file_path=file_path,
                        start_line=field.start_point[0] + 1, end_line=field.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(field, source), source_text=_node_text(field, source),
                    )
                    nodes.append(prop_node)
                    edges.append(Edge(parent_id, prop_node.id, EdgeKind.CONTAINS, 1.0, field.start_point[0] + 1))
                elif type_node:
                    type_name = _node_text(type_node, source)
                    unresolved.append(UnresolvedReference(
                        source_node_id=parent_id,
                        reference_name=type_name,
                        reference_kind=EdgeKind.EXTENDS,
                        line_number=field.start_point[0] + 1,
                    ))

    def _extract_function(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, pkg_name: str,
        nodes: list[Node], edges: list[Edge], unresolved: list[UnresolvedReference]
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node: return
        name = _node_text(name_node, source)
        qname = f"{pkg_name}.{name}" if pkg_name else name
        func_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.FUNCTION, qname),
            kind=NodeKind.FUNCTION, name=name, qualified_name=qname, file_path=file_path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1, language="go",
            docblock=_find_doc_comment(node, source), source_text=_node_text(node, source),
        )
        nodes.append(func_node)
        edges.append(Edge(parent_id, func_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        
        body = node.child_by_field_name("body")
        if body: self._scan_body_for_calls(body, source, func_node.id, unresolved)

    def _extract_method(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, pkg_name: str,
        nodes: list[Node], edges: list[Edge], unresolved: list[UnresolvedReference]
    ) -> None:
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")
        if not name_node or not receiver_node: return
        name = _node_text(name_node, source)
        
        receiver_type = ""
        for param_decl in receiver_node.children:
            if param_decl.type == "parameter_declaration":
                type_node = param_decl.child_by_field_name("type")
                if type_node:
                    receiver_type = _node_text(type_node, source).lstrip("*")
                    break
                    
        qname = f"{pkg_name}.{receiver_type}.{name}" if pkg_name and receiver_type else f"{receiver_type}.{name}"
        method_node = Node(
            id=generate_node_id(file_path, node.start_point[0] + 1, NodeKind.METHOD, qname),
            kind=NodeKind.METHOD, name=name, qualified_name=qname, file_path=file_path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1, language="go",
            docblock=_find_doc_comment(node, source), source_text=_node_text(node, source),
            metadata={"receiver": receiver_type}
        )
        nodes.append(method_node)
        edges.append(Edge(parent_id, method_node.id, EdgeKind.CONTAINS, 1.0, node.start_point[0] + 1))
        
        body = node.child_by_field_name("body")
        if body: self._scan_body_for_calls(body, source, method_node.id, unresolved)

    def _extract_const(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, pkg_name: str,
        nodes: list[Node], edges: list[Edge]
    ) -> None:
        for spec in node.children:
            if spec.type == "const_spec":
                name_node = spec.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qname = f"{pkg_name}.{name}" if pkg_name else name
                    const_node = Node(
                        id=generate_node_id(file_path, spec.start_point[0] + 1, NodeKind.CONSTANT, qname),
                        kind=NodeKind.CONSTANT, name=name, qualified_name=qname, file_path=file_path,
                        start_line=spec.start_point[0] + 1, end_line=spec.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(node, source), source_text=_node_text(spec, source),
                    )
                    nodes.append(const_node)
                    edges.append(Edge(parent_id, const_node.id, EdgeKind.CONTAINS, 1.0, spec.start_point[0] + 1))

    def _extract_var(
        self, node: tree_sitter.Node, source: bytes, file_path: str, parent_id: str, pkg_name: str,
        nodes: list[Node], edges: list[Edge]
    ) -> None:
        for spec in node.children:
            if spec.type == "var_spec":
                name_node = spec.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qname = f"{pkg_name}.{name}" if pkg_name else name
                    var_node = Node(
                        id=generate_node_id(file_path, spec.start_point[0] + 1, NodeKind.VARIABLE, qname),
                        kind=NodeKind.VARIABLE, name=name, qualified_name=qname, file_path=file_path,
                        start_line=spec.start_point[0] + 1, end_line=spec.end_point[0] + 1, language="go",
                        docblock=_find_doc_comment(node, source), source_text=_node_text(spec, source),
                    )
                    nodes.append(var_node)
                    edges.append(Edge(parent_id, var_node.id, EdgeKind.CONTAINS, 1.0, spec.start_point[0] + 1))

    def _scan_body_for_calls(
        self, body_node: tree_sitter.Node, source: bytes, caller_id: str,
        unresolved: list[UnresolvedReference]
    ) -> None:
        cursor = tree_sitter.QueryCursor(self._calls_query)
        for _, captures in cursor.matches(body_node):
            for capture in captures.get("call", []):
                func_node = capture.child_by_field_name("function")
                if func_node:
                    func_name = _node_text(func_node, source)
                    unresolved.append(UnresolvedReference(
                        source_node_id=caller_id,
                        reference_name=func_name,
                        reference_kind=EdgeKind.CALLS,
                        line_number=capture.start_point[0] + 1,
                    ))
