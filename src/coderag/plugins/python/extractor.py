"""Python AST extractor for CodeRAG.

Uses tree-sitter-python to parse Python source files and extract
knowledge-graph nodes and edges.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import tree_sitter
import tree_sitter_python as tspython

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")

_DUNDER_RE = re.compile(r"^__[a-z][a-z0-9_]*__$")

_ABC_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})

_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})

_TRIPLE_QUOTES = ('"""', "'''")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _child_by_field(node: tree_sitter.Node, field: str) -> tree_sitter.Node | None:
    """Return the first child with the given field name, or None."""
    return node.child_by_field_name(field)


def _children_of_type(
    node: tree_sitter.Node,
    *types: str,
) -> list[tree_sitter.Node]:
    """Return all direct children whose type is in *types*."""
    return [c for c in node.children if c.type in types]


def _find_docstring(body_node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract a docstring from the first statement of a block."""
    if body_node is None:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw = _node_text(sub, source)
                    for delim in _TRIPLE_QUOTES:
                        if raw.startswith(delim) and raw.endswith(delim):
                            return raw[3:-3].strip()
                    if len(raw) >= 2:
                        return raw[1:-1].strip()
            break
        elif child.type == "comment":
            continue
        else:
            break
    return None


def _get_decorators(
    node: tree_sitter.Node,
    source: bytes,
) -> list[dict[str, str]]:
    """Extract decorator info from a decorated_definition parent."""
    decorators: list[dict[str, str]] = []
    parent = node.parent
    if parent is not None and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                text = _node_text(child, source).lstrip("@").strip()
                name = text.split("(")[0].strip()
                decorators.append({"name": name, "text": text})
    return decorators


def _extract_type_annotation(
    node: tree_sitter.Node | None,
    source: bytes,
) -> str | None:
    """Extract a type annotation string from a type node."""
    if node is None:
        return None
    return _node_text(node, source)


def _extract_parameters(
    params_node: tree_sitter.Node | None,
    source: bytes,
) -> list[dict[str, str | None]]:
    """Extract function parameters with names, types, and defaults."""
    if params_node is None:
        return []
    result: list[dict[str, str | None]] = []
    for child in params_node.children:
        if child.type in (
            "identifier",
            "typed_parameter",
            "default_parameter",
            "typed_default_parameter",
            "list_splat_pattern",
            "dictionary_splat_pattern",
        ):
            param: dict[str, str | None] = {
                "name": None,
                "type": None,
                "default": None,
            }
            if child.type == "identifier":
                param["name"] = _node_text(child, source)
            elif child.type == "typed_parameter":
                name_node = child.children[0] if child.children else None
                if name_node:
                    param["name"] = _node_text(name_node, source)
                type_node = _child_by_field(child, "type")
                if type_node:
                    param["type"] = _node_text(type_node, source)
            elif child.type == "default_parameter":
                name_node = _child_by_field(child, "name")
                if name_node:
                    param["name"] = _node_text(name_node, source)
                value_node = _child_by_field(child, "value")
                if value_node:
                    param["default"] = _node_text(value_node, source)
            elif child.type == "typed_default_parameter":
                name_node = _child_by_field(child, "name")
                if name_node:
                    param["name"] = _node_text(name_node, source)
                type_node = _child_by_field(child, "type")
                if type_node:
                    param["type"] = _node_text(type_node, source)
                value_node = _child_by_field(child, "value")
                if value_node:
                    param["default"] = _node_text(value_node, source)
            elif child.type == "list_splat_pattern":
                for sub in child.children:
                    if sub.type == "identifier":
                        param["name"] = "*" + _node_text(sub, source)
                        break
            elif child.type == "dictionary_splat_pattern":
                for sub in child.children:
                    if sub.type == "identifier":
                        param["name"] = "**" + _node_text(sub, source)
                        break
            if param["name"]:
                result.append(param)
    return result


def _get_base_classes(
    node: tree_sitter.Node,
    source: bytes,
) -> list[str]:
    """Extract base class names from a class_definition argument_list."""
    bases: list[str] = []
    arg_list = None
    for child in node.children:
        if child.type == "argument_list":
            arg_list = child
            break
    if arg_list is None:
        return bases
    for child in arg_list.children:
        if child.type in ("identifier", "attribute"):
            bases.append(_node_text(child, source))
    return bases


def _is_abc_class(bases: list[str]) -> bool:
    for b in bases:
        short = b.rsplit(".", 1)[-1]
        if short in _ABC_BASES:
            return True
    return False


def _is_enum_class(bases: list[str]) -> bool:
    for b in bases:
        short = b.rsplit(".", 1)[-1]
        if short in _ENUM_BASES:
            return True
    return False


def _has_decorator(decorators: list[dict[str, str]], name: str) -> bool:
    for d in decorators:
        if d["name"] == name or d["name"].endswith("." + name):
            return True
    return False


# ---------------------------------------------------------------------------
# Extraction context
# ---------------------------------------------------------------------------


class _ExtractionContext:
    """Mutable state passed through the extraction walk."""

    __slots__ = (
        "file_path",
        "source",
        "file_node_id",
        "nodes",
        "edges",
        "errors",
        "unresolved",
        "import_map",
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
        self.import_map: dict[str, str] = {}

    def resolve_name(self, name: str) -> str:
        """Resolve a short name via the import map."""
        top = name.split(".")[0]
        if top in self.import_map:
            return self.import_map[top] + name[len(top) :]
        return name


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class PythonExtractor(ASTExtractor):
    """Extract knowledge-graph nodes and edges from Python source files."""

    _SUPPORTED_NODE_KINDS = frozenset(
        {
            NodeKind.FILE,
            NodeKind.CLASS,
            NodeKind.INTERFACE,
            NodeKind.ENUM,
            NodeKind.FUNCTION,
            NodeKind.METHOD,
            NodeKind.PROPERTY,
            NodeKind.VARIABLE,
            NodeKind.CONSTANT,
            NodeKind.IMPORT,
            NodeKind.DECORATOR,
            NodeKind.TYPE_ALIAS,
        }
    )

    _SUPPORTED_EDGE_KINDS = frozenset(
        {
            EdgeKind.CONTAINS,
            EdgeKind.EXTENDS,
            EdgeKind.IMPLEMENTS,
            EdgeKind.CALLS,
            EdgeKind.IMPORTS,
            EdgeKind.INSTANTIATES,
            EdgeKind.HAS_TYPE,
            EdgeKind.RETURNS_TYPE,
            EdgeKind.DEPENDS_ON,
        }
    )

    def __init__(self) -> None:
        lang = tree_sitter.Language(tspython.language())
        self._parser = tree_sitter.Parser(lang)

    # -- ASTExtractor interface ---------------------------------------------

    def supported_node_kinds(self) -> frozenset[NodeKind]:
        return self._SUPPORTED_NODE_KINDS

    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        return self._SUPPORTED_EDGE_KINDS

    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Parse source and return nodes + edges."""
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
                    line_number=0,
                    message=f"tree-sitter parse failed: {exc}",
                    node_type="module",
                )
            )
            return ExtractionResult(
                nodes=nodes,
                edges=edges,
                errors=errors,
                unresolved=unresolved,
                parse_time_ms=(time.perf_counter() - t0) * 1000,
                content_hash=compute_content_hash(source),
            )

        self._collect_errors(tree.root_node, file_path, errors)

        file_node = Node(
            id=generate_node_id(file_path, 1, NodeKind.FILE, file_path),
            kind=NodeKind.FILE,
            name=file_path.rsplit("/", 1)[-1],
            start_line=1,
            qualified_name=file_path,
            file_path=file_path,
            end_line=tree.root_node.end_point[0] + 1,
            language="python",
            metadata={"content_hash": compute_content_hash(source)},
        )
        nodes.append(file_node)

        ctx = _ExtractionContext(
            file_path=file_path,
            source=source,
            file_node_id=file_node.id,
            nodes=nodes,
            edges=edges,
            errors=errors,
            unresolved=unresolved,
        )

        self._walk_module(tree.root_node, ctx)

        elapsed = (time.perf_counter() - t0) * 1000
        return ExtractionResult(
            file_path=file_path,
            language="python",
            nodes=nodes,
            edges=edges,
            unresolved_references=unresolved,
            errors=errors,
            parse_time_ms=elapsed,
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

    # -- Module walk --------------------------------------------------------

    def _walk_module(
        self,
        root: tree_sitter.Node,
        ctx: _ExtractionContext,
    ) -> None:
        for child in root.children:
            self._handle_top_level(child, ctx, ctx.file_node_id, "")

    def _handle_top_level(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
    ) -> None:
        ntype = node.type
        if ntype == "import_statement":
            self._handle_import(node, ctx, parent_id)
        elif ntype == "import_from_statement":
            self._handle_import_from(node, ctx, parent_id)
        elif ntype == "function_definition":
            self._handle_function(node, ctx, parent_id, scope, is_method=False)
        elif ntype == "class_definition":
            self._handle_class(node, ctx, parent_id, scope)
        elif ntype == "decorated_definition":
            self._handle_decorated(node, ctx, parent_id, scope)
        elif ntype == "expression_statement":
            self._handle_expression_statement(node, ctx, parent_id, scope)
        elif ntype == "type_alias_statement":
            self._handle_type_alias(node, ctx, parent_id, scope)
        elif ntype == "if_statement":
            self._handle_if_statement(node, ctx, parent_id, scope)

    # -- Import handling ----------------------------------------------------

    def _handle_import(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        for child in node.children:
            if child.type == "dotted_name":
                name = _node_text(child, ctx.source)
                alias = name.rsplit(".", 1)[-1]
                self._create_import_node(
                    ctx,
                    parent_id,
                    node,
                    name,
                    alias,
                    is_relative=False,
                    level=0,
                )
            elif child.type == "aliased_import":
                orig = None
                alias_node = None
                for sub in child.children:
                    if sub.type == "dotted_name" and orig is None:
                        orig = _node_text(sub, ctx.source)
                    elif sub.type == "identifier":
                        alias_node = sub
                if orig:
                    alias = _node_text(alias_node, ctx.source) if alias_node else orig.rsplit(".", 1)[-1]
                    self._create_import_node(
                        ctx,
                        parent_id,
                        node,
                        orig,
                        alias,
                        is_relative=False,
                        level=0,
                    )

    def _handle_import_from(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
    ) -> None:
        module_name = ""
        is_relative = False
        level = 0

        for child in node.children:
            if child.type == "dotted_name" and not module_name:
                module_name = _node_text(child, ctx.source)
            elif child.type == "relative_import":
                is_relative = True
                text = _node_text(child, ctx.source)
                level = len(text) - len(text.lstrip("."))
                rest = text.lstrip(".")
                if rest:
                    module_name = rest

        # Collect imported names after the 'import' keyword
        imported_names: list[tuple[str, str]] = []
        found_import_kw = False
        for child in node.children:
            if child.type == "import":
                found_import_kw = True
                continue
            if not found_import_kw:
                continue
            if child.type == "dotted_name":
                name = _node_text(child, ctx.source)
                imported_names.append((name, name.rsplit(".", 1)[-1]))
            elif child.type == "aliased_import":
                orig = None
                alias_name = None
                for sub in child.children:
                    if sub.type == "dotted_name" and orig is None:
                        orig = _node_text(sub, ctx.source)
                    elif sub.type == "identifier":
                        alias_name = _node_text(sub, ctx.source)
                if orig:
                    imported_names.append((orig, alias_name or orig.rsplit(".", 1)[-1]))
            elif child.type == "wildcard_import":
                imported_names.append(("*", "*"))

        for orig_name, alias in imported_names:
            if module_name:
                fqn = f"{module_name}.{orig_name}" if orig_name != "*" else f"{module_name}.*"
            else:
                fqn = orig_name
            prefix = "." * level if is_relative else ""
            import_path = f"{prefix}{fqn}"
            self._create_import_node(
                ctx,
                parent_id,
                node,
                import_path,
                alias,
                is_relative=is_relative,
                level=level,
            )

    def _create_import_node(
        self,
        ctx: _ExtractionContext,
        parent_id: str,
        node: tree_sitter.Node,
        fqn: str,
        alias: str,
        is_relative: bool,
        level: int,
    ) -> None:
        line = node.start_point[0] + 1
        import_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.IMPORT, fqn),
            kind=NodeKind.IMPORT,
            name=alias,
            qualified_name=fqn,
            file_path=ctx.file_path,
            start_line=line,
            end_line=node.end_point[0] + 1,
            language="python",
            metadata={
                "alias": alias,
                "fqn": fqn,
                "is_relative": is_relative,
                "level": level,
            },
        )
        ctx.nodes.append(import_node)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=import_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )
        ctx.import_map[alias] = fqn
        ctx.unresolved.append(
            UnresolvedReference(
                source_node_id=import_node.id,
                reference_name=fqn,
                reference_kind=EdgeKind.IMPORTS,
                line_number=line,
                context={"is_relative": is_relative, "level": level},
            )
        )

    # -- Class handling -----------------------------------------------------

    def _handle_class(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = f"{scope}.{name}" if scope else name
        line = node.start_point[0] + 1

        bases = _get_base_classes(node, ctx.source)
        decorators = _get_decorators(node, ctx.source)
        is_abc = _is_abc_class(bases)
        is_enum = _is_enum_class(bases)
        is_dataclass = _has_decorator(decorators, "dataclass")

        if is_enum:
            kind = NodeKind.ENUM
        elif is_abc:
            kind = NodeKind.INTERFACE
        else:
            kind = NodeKind.CLASS

        body = _child_by_field(node, "body")
        docstring = _find_docstring(body, ctx.source)

        class_node = Node(
            id=generate_node_id(ctx.file_path, line, kind, name),
            kind=kind,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="python",
            docblock=docstring,
            source_text=_node_text(node, ctx.source),
            metadata={
                "bases": bases,
                "decorators": [d["name"] for d in decorators],
                "is_dataclass": is_dataclass,
                "is_abstract": is_abc,
                "is_enum": is_enum,
            },
        )
        ctx.nodes.append(class_node)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=class_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        for dec in decorators:
            self._create_decorator_node(ctx, class_node.id, node, dec, line)

        for base_name in bases:
            resolved = ctx.resolve_name(base_name)
            short = base_name.rsplit(".", 1)[-1]
            edge_kind = EdgeKind.IMPLEMENTS if short in _ABC_BASES else EdgeKind.EXTENDS
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=class_node.id,
                    reference_name=resolved,
                    reference_kind=edge_kind,
                    line_number=line,
                )
            )

        if body is not None:
            self._walk_class_body(body, ctx, class_node.id, qname, bases)

    def _walk_class_body(
        self,
        body: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
        bases: list[str],
    ) -> None:
        for child in body.children:
            ntype = child.type
            if ntype == "function_definition":
                self._handle_function(
                    child,
                    ctx,
                    class_id,
                    class_qname,
                    is_method=True,
                )
            elif ntype == "decorated_definition":
                self._handle_decorated(
                    child,
                    ctx,
                    class_id,
                    class_qname,
                    in_class=True,
                )
            elif ntype == "expression_statement":
                self._handle_class_assignment(
                    child,
                    ctx,
                    class_id,
                    class_qname,
                    bases,
                )
            elif ntype == "class_definition":
                self._handle_class(child, ctx, class_id, class_qname)

    def _handle_class_assignment(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        class_id: str,
        class_qname: str,
        bases: list[str],
    ) -> None:
        for child in node.children:
            if child.type == "assignment":
                self._process_assignment(
                    child,
                    ctx,
                    class_id,
                    class_qname,
                    is_class_level=True,
                    is_enum=_is_enum_class(bases),
                )

    # -- Function / Method handling ------------------------------------------

    def _handle_function(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
        is_method: bool = False,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = f"{scope}.{name}" if scope else name
        line = node.start_point[0] + 1

        is_async = any(c.type == "async" for c in node.children)

        params_node = _child_by_field(node, "parameters")
        params = _extract_parameters(params_node, ctx.source)

        return_type_node = _child_by_field(node, "return_type")
        return_type = _extract_type_annotation(return_type_node, ctx.source)

        decorators = _get_decorators(node, ctx.source)

        is_property = _has_decorator(decorators, "property")
        is_staticmethod = _has_decorator(decorators, "staticmethod")
        is_classmethod = _has_decorator(decorators, "classmethod")
        is_abstractmethod = _has_decorator(decorators, "abstractmethod")

        if is_property:
            kind = NodeKind.PROPERTY
        elif is_method:
            kind = NodeKind.METHOD
        else:
            kind = NodeKind.FUNCTION

        has_self = False
        has_cls = False
        if params and is_method:
            first_param = params[0]["name"]
            if first_param == "self":
                has_self = True
            elif first_param == "cls":
                has_cls = True

        if name.startswith("__") and not name.endswith("__"):
            visibility = "private"
        elif name.startswith("_"):
            visibility = "protected"
        else:
            visibility = "public"

        body = _child_by_field(node, "body")
        docstring = _find_docstring(body, ctx.source)

        func_node = Node(
            id=generate_node_id(ctx.file_path, line, kind, name),
            kind=kind,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="python",
            docblock=docstring,
            source_text=_node_text(node, ctx.source),
            metadata={
                "async": is_async,
                "static": is_staticmethod,
                "classmethod": is_classmethod,
                "abstractmethod": is_abstractmethod,
                "property": is_property,
                "visibility": visibility,
                "has_self": has_self,
                "has_cls": has_cls,
                "parameters": params,
                "return_type": return_type,
                "decorators": [d["name"] for d in decorators],
            },
        )
        ctx.nodes.append(func_node)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=func_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        for dec in decorators:
            self._create_decorator_node(ctx, func_node.id, node, dec, line)

        if return_type:
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=func_node.id,
                    reference_name=ctx.resolve_name(return_type),
                    reference_kind=EdgeKind.RETURNS_TYPE,
                    line_number=line,
                )
            )

        for p in params:
            if p["type"]:
                ctx.unresolved.append(
                    UnresolvedReference(
                        source_node_id=func_node.id,
                        reference_name=ctx.resolve_name(p["type"]),
                        reference_kind=EdgeKind.HAS_TYPE,
                        line_number=line,
                        context={"parameter": p["name"]},
                    )
                )

        if body is not None:
            self._scan_calls(body, ctx, func_node.id)

    # -- Decorated definitions -----------------------------------------------

    def _handle_decorated(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
        in_class: bool = False,
    ) -> None:
        for child in node.children:
            if child.type == "function_definition":
                self._handle_function(
                    child,
                    ctx,
                    parent_id,
                    scope,
                    is_method=in_class,
                )
            elif child.type == "class_definition":
                self._handle_class(child, ctx, parent_id, scope)

    # -- Expression statements -----------------------------------------------

    def _handle_expression_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
    ) -> None:
        for child in node.children:
            if child.type == "assignment":
                self._process_assignment(
                    child,
                    ctx,
                    parent_id,
                    scope,
                    is_class_level=False,
                    is_enum=False,
                )

    def _process_assignment(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
        is_class_level: bool,
        is_enum: bool,
    ) -> None:
        left = _child_by_field(node, "left")
        if left is None and node.children:
            left = node.children[0]
        if left is None:
            return

        type_node = _child_by_field(node, "type")
        type_ann = _extract_type_annotation(type_node, ctx.source) if type_node else None

        right = _child_by_field(node, "right")
        if right is None:
            for i, child in enumerate(node.children):
                if child.type == "=" and i + 1 < len(node.children):
                    right = node.children[i + 1]
                    break

        if left.type == "identifier":
            name = _node_text(left, ctx.source)
            self._create_variable_node(
                ctx,
                parent_id,
                node,
                name,
                scope,
                type_ann,
                right,
                is_class_level,
                is_enum,
            )
        elif left.type == "pattern_list":
            for sub in left.children:
                if sub.type == "identifier":
                    name = _node_text(sub, ctx.source)
                    self._create_variable_node(
                        ctx,
                        parent_id,
                        node,
                        name,
                        scope,
                        None,
                        None,
                        is_class_level,
                        is_enum,
                    )

    def _create_variable_node(
        self,
        ctx: _ExtractionContext,
        parent_id: str,
        node: tree_sitter.Node,
        name: str,
        scope: str,
        type_ann: str | None,
        value_node: tree_sitter.Node | None,
        is_class_level: bool,
        is_enum: bool,
    ) -> None:
        line = node.start_point[0] + 1
        qname = f"{scope}.{name}" if scope else name

        if is_enum and is_class_level:
            kind = NodeKind.CONSTANT
        elif _UPPER_RE.match(name) and not is_class_level:
            kind = NodeKind.CONSTANT
        elif type_ann and "TypeAlias" in type_ann:
            kind = NodeKind.TYPE_ALIAS
        else:
            kind = NodeKind.VARIABLE

        value_text = None
        if value_node is not None:
            value_text = _node_text(value_node, ctx.source)
            if len(value_text) > 200:
                value_text = value_text[:200] + "..."

        var_node = Node(
            id=generate_node_id(ctx.file_path, line, kind, name),
            kind=kind,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="python",
            metadata={
                "type_annotation": type_ann,
                "value": value_text,
                "is_class_level": is_class_level,
                "is_dunder": bool(_DUNDER_RE.match(name)),
            },
        )
        ctx.nodes.append(var_node)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=var_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

        if type_ann:
            ctx.unresolved.append(
                UnresolvedReference(
                    source_node_id=var_node.id,
                    reference_name=ctx.resolve_name(type_ann),
                    reference_kind=EdgeKind.HAS_TYPE,
                    line_number=line,
                )
            )

    # -- Type alias handling ------------------------------------------------

    def _handle_type_alias(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
    ) -> None:
        name_node = _child_by_field(node, "name")
        if name_node is None:
            return
        name = _node_text(name_node, ctx.source)
        qname = f"{scope}.{name}" if scope else name
        line = node.start_point[0] + 1

        value_node = _child_by_field(node, "value")
        value_text = _node_text(value_node, ctx.source) if value_node else None

        alias_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.TYPE_ALIAS, name),
            kind=NodeKind.TYPE_ALIAS,
            name=name,
            start_line=line,
            qualified_name=qname,
            file_path=ctx.file_path,
            end_line=node.end_point[0] + 1,
            language="python",
            metadata={"value": value_text},
        )
        ctx.nodes.append(alias_node)
        ctx.edges.append(
            Edge(
                source_id=parent_id,
                target_id=alias_node.id,
                kind=EdgeKind.CONTAINS,
                confidence=1.0,
                line_number=line,
            )
        )

    # -- Decorator node creation --------------------------------------------

    def _create_decorator_node(
        self,
        ctx: _ExtractionContext,
        target_id: str,
        node: tree_sitter.Node,
        dec: dict[str, str],
        line: int,
    ) -> None:
        dec_node = Node(
            id=generate_node_id(ctx.file_path, line, NodeKind.DECORATOR, dec["name"]),
            kind=NodeKind.DECORATOR,
            name=dec["name"],
            start_line=line,
            qualified_name=dec["name"],
            file_path=ctx.file_path,
            end_line=line,
            language="python",
            metadata={"text": dec["text"]},
        )
        ctx.nodes.append(dec_node)
        ctx.edges.append(
            Edge(
                source_id=dec_node.id,
                target_id=target_id,
                kind=EdgeKind.DEPENDS_ON,
                confidence=1.0,
                line_number=line,
            )
        )

    # -- if TYPE_CHECKING handling ------------------------------------------

    def _handle_if_statement(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        parent_id: str,
        scope: str,
    ) -> None:
        condition = _child_by_field(node, "condition")
        if condition is None:
            return
        cond_text = _node_text(condition, ctx.source)
        if cond_text not in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
            return
        consequence = _child_by_field(node, "consequence")
        if consequence is not None:
            for child in consequence.children:
                self._handle_top_level(child, ctx, parent_id, scope)

    # -- Call scanning ------------------------------------------------------

    def _scan_calls(
        self,
        node: tree_sitter.Node,
        ctx: _ExtractionContext,
        caller_id: str,
    ) -> None:
        """Recursively scan for function/method calls and instantiations."""
        if node.type == "call":
            func_node = _child_by_field(node, "function")
            if func_node is not None:
                call_text = _node_text(func_node, ctx.source)
                base_name = call_text.rsplit(".", 1)[-1]
                if base_name and base_name[0].isupper() and not base_name.isupper():
                    resolved = ctx.resolve_name(call_text)
                    ctx.unresolved.append(
                        UnresolvedReference(
                            source_node_id=caller_id,
                            reference_name=resolved,
                            reference_kind=EdgeKind.INSTANTIATES,
                            line_number=node.start_point[0] + 1,
                        )
                    )
                else:
                    resolved = ctx.resolve_name(call_text)
                    ctx.unresolved.append(
                        UnresolvedReference(
                            source_node_id=caller_id,
                            reference_name=resolved,
                            reference_kind=EdgeKind.CALLS,
                            line_number=node.start_point[0] + 1,
                            context={
                                "call_type": "member" if "." in call_text else "function",
                            },
                        )
                    )

        for child in node.children:
            self._scan_calls(child, ctx, caller_id)
