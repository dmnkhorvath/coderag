"""FastAPI framework detector for CodeRAG.

Detects FastAPI-specific patterns including routes, APIRouter,
dependency injection (Depends), Pydantic models, middleware,
WebSocket endpoints, background tasks, and exception handlers
from already-parsed AST nodes and source code.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from coderag.core.models import (
    Edge,
    EdgeKind,
    FrameworkPattern,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.core.registry import FrameworkDetector

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────

# FastAPI route decorators: @app.get('/path'), @router.post('/path')
_ROUTE_RE = re.compile(
    r"@(?P<obj>\w+)\.(?P<method>get|post|put|delete|patch|options|head|trace)"
    r"\s*\(\s*[\'\"](?P<path>[^\'\"]*)[\'\"]\s*"
    r"(?:,\s*response_model\s*=\s*(?P<response_model>[\w\.\[\]]+))?",
    re.MULTILINE,
)

# WebSocket decorator: @app.websocket('/ws')
_WEBSOCKET_RE = re.compile(
    r"@(?P<obj>\w+)\.websocket\s*\(\s*[\'\"](?P<path>[^\'\"]*)[\'\"]\s*\)",
    re.MULTILINE,
)

# APIRouter creation: router = APIRouter(prefix='/api')
_APIROUTER_RE = re.compile(
    r"(?P<var>\w+)\s*=\s*APIRouter\s*\("
    r"(?:\s*prefix\s*=\s*[\'\"](?P<prefix>[^\'\"]*)[\'\"])?"
    r"(?:\s*,\s*tags\s*=\s*\[(?P<tags>[^\]]+)\])?",
    re.MULTILINE,
)

# Depends() usage in function parameters
_DEPENDS_RE = re.compile(
    r"(?P<param>\w+)\s*(?::\s*[\w\.\[\]]+\s*)?=\s*Depends\s*\(\s*(?P<dep>[\w\.]+)\s*\)",
    re.MULTILINE,
)

# Pydantic BaseModel / BaseSettings classes
_PYDANTIC_BASES = {
    "BaseModel",
    "BaseSettings",
    "BaseConfig",
}

# Pydantic field types
_PYDANTIC_FIELD_RE = re.compile(
    r"^\s*(?P<field_name>\w+)\s*:\s*(?P<field_type>[\w\[\],\s\.\|]+)"
    r"(?:\s*=\s*(?:Field\s*\(|[^\n]+))?",
    re.MULTILINE,
)

# FastAPI middleware: @app.middleware('http') or app.add_middleware()
_MIDDLEWARE_DECORATOR_RE = re.compile(
    r"@(?P<obj>\w+)\.middleware\s*\(\s*[\'\"](?P<type>[^\'\"]+)[\'\"]\s*\)",
    re.MULTILINE,
)

_ADD_MIDDLEWARE_RE = re.compile(
    r"(?P<obj>\w+)\.add_middleware\s*\(\s*(?P<cls>[\w\.]+)",
    re.MULTILINE,
)

# Exception handler: @app.exception_handler(HTTPException)
_EXCEPTION_HANDLER_RE = re.compile(
    r"@(?P<obj>\w+)\.exception_handler\s*\(\s*(?P<exc>[\w\.]+)\s*\)",
    re.MULTILINE,
)

# app.include_router()
_INCLUDE_ROUTER_RE = re.compile(
    r"(?P<app>\w+)\.include_router\s*\(\s*(?P<router>[\w\.]+)"
    r"(?:\s*,\s*prefix\s*=\s*[\'\"](?P<prefix>[^\'\"]*)[\'\"])?"
    r"(?:\s*,\s*tags\s*=\s*\[(?P<tags>[^\]]+)\])?",
    re.MULTILINE,
)

# BackgroundTasks parameter
_BACKGROUND_TASKS_RE = re.compile(
    r"(?P<param>\w+)\s*:\s*BackgroundTasks",
    re.MULTILINE,
)

# FastAPI app creation: FastAPI()
_FASTAPI_APP_RE = re.compile(
    r"(?P<var>\w+)\s*=\s*FastAPI\s*\(",
    re.MULTILINE,
)


class FastAPIDetector(FrameworkDetector):
    """Detect FastAPI framework patterns in Python projects."""

    @property
    def framework_name(self) -> str:
        return "fastapi"

    def detect_framework(self, project_root: str) -> bool:
        """Check for fastapi in dependency files."""
        dep_files = [
            "requirements.txt",
            "requirements/base.txt",
            "requirements/production.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "Pipfile",
        ]
        for dep_file in dep_files:
            fpath = os.path.join(project_root, dep_file)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read().lower()
                    if "fastapi" in content:
                        return True
                except OSError:
                    continue

        # Check common entry points for FastAPI import
        for entry in ["main.py", "app.py", "app/__init__.py", "src/main.py"]:
            fpath = os.path.join(project_root, entry)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                    if "from fastapi import" in content or "import fastapi" in content:
                        return True
                except OSError:
                    continue

        return False

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file FastAPI patterns from source code."""
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        func_nodes = [n for n in nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]

        # ── Route detection ───────────────────────────────────
        route_nodes: list[Node] = []
        route_edges: list[Edge] = []

        for match in _ROUTE_RE.finditer(source_text):
            obj_name = match.group("obj")
            http_method = match.group("method").upper()
            path = match.group("path")
            response_model = match.group("response_model")
            line_no = source_text[: match.start()].count("\n") + 1

            metadata: dict[str, Any] = {
                "framework": "fastapi",
                "http_method": http_method,
                "url_pattern": path,
                "bound_to": obj_name,
            }
            if response_model:
                metadata["response_model"] = response_model

            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, f"{http_method}:{path}"),
                kind=NodeKind.ROUTE,
                name=f"{http_method} {path}",
                qualified_name=f"{http_method} {path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata=metadata,
            )
            route_nodes.append(route_node)

            # Find handler function below decorator
            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            if handler:
                route_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=handler.id,
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={
                            "framework": "fastapi",
                            "http_method": http_method,
                            "url_pattern": path,
                        },
                    )
                )

                # Detect Depends() in handler parameters
                dep_patterns = self._detect_depends_in_func(
                    handler,
                    source_text,
                    file_path,
                )
                route_edges.extend(dep_patterns)

        if route_nodes:
            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="routes",
                    nodes=route_nodes,
                    edges=route_edges,
                    metadata={"route_count": len(route_nodes)},
                )
            )

        # ── WebSocket detection ───────────────────────────────
        for match in _WEBSOCKET_RE.finditer(source_text):
            obj_name = match.group("obj")
            path = match.group("path")
            line_no = source_text[: match.start()].count("\n") + 1

            ws_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, f"WS:{path}"),
                kind=NodeKind.ROUTE,
                name=f"WS {path}",
                qualified_name=f"WS {path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "http_method": "WEBSOCKET",
                    "url_pattern": path,
                    "protocol": "websocket",
                    "bound_to": obj_name,
                },
            )

            ws_edges: list[Edge] = []
            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            if handler:
                ws_edges.append(
                    Edge(
                        source_id=ws_node.id,
                        target_id=handler.id,
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={"framework": "fastapi", "protocol": "websocket"},
                    )
                )

            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="websocket",
                    nodes=[ws_node],
                    edges=ws_edges,
                    metadata={"path": path},
                )
            )

        # ── APIRouter detection ───────────────────────────────
        for match in _APIROUTER_RE.finditer(source_text):
            var_name = match.group("var")
            prefix = match.group("prefix") or ""
            tags_str = match.group("tags")
            line_no = source_text[: match.start()].count("\n") + 1

            tags: list[str] = []
            if tags_str:
                tags = [t.strip().strip("'\"") for t in tags_str.split(",")]

            router_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MODULE, f"router:{var_name}"),
                kind=NodeKind.MODULE,
                name=var_name,
                qualified_name=f"fastapi.router:{var_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "component_type": "api_router",
                    "variable_name": var_name,
                    "prefix": prefix,
                    "tags": tags,
                },
            )
            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="api_router",
                    nodes=[router_node],
                    edges=[],
                    metadata={"router_name": var_name, "prefix": prefix},
                )
            )

        # ── Pydantic model detection ──────────────────────────
        for cls in class_nodes:
            bases = self._extract_bases(cls, source_text)
            base_shorts = {b.rsplit(".", 1)[-1] for b in bases}

            if base_shorts & _PYDANTIC_BASES:
                pattern = self._detect_pydantic_model(cls, source_text, file_path)
                if pattern:
                    patterns.append(pattern)

        # ── Middleware detection ───────────────────────────────
        mw_nodes: list[Node] = []

        # @app.middleware('http') decorator
        for match in _MIDDLEWARE_DECORATOR_RE.finditer(source_text):
            mw_type = match.group("type")
            line_no = source_text[: match.start()].count("\n") + 1

            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            handler_name = handler.name if handler else f"middleware@L{line_no}"

            mw_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MIDDLEWARE, handler_name),
                kind=NodeKind.MIDDLEWARE,
                name=handler_name,
                qualified_name=f"fastapi.middleware:{handler_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=handler.end_line if handler else line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "middleware_type": mw_type,
                },
            )
            mw_nodes.append(mw_node)

        # app.add_middleware(CORSMiddleware, ...)
        for match in _ADD_MIDDLEWARE_RE.finditer(source_text):
            mw_cls = match.group("cls")
            line_no = source_text[: match.start()].count("\n") + 1
            mw_name = mw_cls.rsplit(".", 1)[-1]

            mw_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MIDDLEWARE, mw_name),
                kind=NodeKind.MIDDLEWARE,
                name=mw_name,
                qualified_name=f"fastapi.middleware:{mw_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "middleware_class": mw_cls,
                    "middleware_type": "add_middleware",
                },
            )
            mw_nodes.append(mw_node)

        if mw_nodes:
            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="middleware",
                    nodes=mw_nodes,
                    edges=[],
                    metadata={"middleware_count": len(mw_nodes)},
                )
            )

        # ── Exception handler detection ───────────────────────
        for match in _EXCEPTION_HANDLER_RE.finditer(source_text):
            exc_type = match.group("exc")
            line_no = source_text[: match.start()].count("\n") + 1

            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            handler_name = handler.name if handler else f"exc_handler_{exc_type}"

            eh_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.FUNCTION, f"exc_handler:{exc_type}"),
                kind=NodeKind.FUNCTION,
                name=handler_name,
                qualified_name=f"fastapi.exception_handler:{exc_type}",
                file_path=file_path,
                start_line=line_no,
                end_line=handler.end_line if handler else line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "component_type": "exception_handler",
                    "exception_type": exc_type,
                },
            )
            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="exception_handler",
                    nodes=[eh_node],
                    edges=[],
                    metadata={"exception_type": exc_type},
                )
            )

        # ── Background tasks detection ────────────────────────
        bg_funcs: list[str] = []
        for match in _BACKGROUND_TASKS_RE.finditer(source_text):
            bg_funcs.append(match.group("param"))

        if bg_funcs:
            patterns.append(
                FrameworkPattern(
                    framework_name="fastapi",
                    pattern_type="background_tasks",
                    nodes=[],
                    edges=[],
                    metadata={"background_task_params": bg_funcs},
                )
            )

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file FastAPI patterns.

        - Router inclusion chain (app.include_router())
        - Dependency injection tree
        - Pydantic model inheritance chains
        """
        patterns: list[FrameworkPattern] = []

        project_root = self._infer_project_root(store)
        if not project_root:
            return patterns

        # Router inclusion chain
        router_pattern = self._extract_router_inclusions(store, project_root)
        if router_pattern:
            patterns.append(router_pattern)

        # Dependency injection tree
        di_pattern = self._build_dependency_tree(store)
        if di_pattern:
            patterns.append(di_pattern)

        # Pydantic model inheritance
        inheritance_pattern = self._detect_pydantic_inheritance(store)
        if inheritance_pattern:
            patterns.append(inheritance_pattern)

        return patterns

    # ── Private helpers ───────────────────────────────────────

    def _infer_project_root(self, store: Any) -> str | None:
        """Infer project root from stored file paths."""
        nodes = store.find_nodes(kind=NodeKind.FILE, limit=5)
        if not nodes:
            return None
        for node in nodes:
            abs_path = os.path.abspath(node.file_path)
            parts = abs_path.split(os.sep)
            for i in range(len(parts), 0, -1):
                candidate = os.sep.join(parts[:i])
                for entry in ["main.py", "app.py", "requirements.txt", "pyproject.toml"]:
                    if os.path.isfile(os.path.join(candidate, entry)):
                        return candidate
        return None

    def _find_func_near_line(
        self,
        line_no: int,
        func_nodes: list[Node],
        file_path: str,
    ) -> Node | None:
        """Find the function defined closest after the given line."""
        closest = None
        closest_dist = float("inf")
        for fn in func_nodes:
            if fn.file_path == file_path and fn.start_line >= line_no:
                dist = fn.start_line - line_no
                if dist < closest_dist and dist <= 5:
                    closest = fn
                    closest_dist = dist
        return closest

    def _extract_bases(self, cls: Node, source_text: str) -> list[str]:
        """Extract base class names from source around the class definition line."""
        lines = source_text.splitlines()
        if cls.start_line < 1 or cls.start_line > len(lines):
            return []

        class_header = ""
        for i in range(cls.start_line - 1, min(cls.start_line + 4, len(lines))):
            class_header += lines[i]
            if ":" in lines[i]:
                break

        match = re.search(r"class\s+\w+\s*\(([^)]+)\)", class_header)
        if not match:
            return []

        bases_str = match.group(1)
        bases = [b.strip() for b in bases_str.split(",") if b.strip()]
        return bases

    def _get_class_source(self, cls: Node, source_text: str) -> str:
        """Extract source text for a class node."""
        if cls.source_text:
            return cls.source_text
        lines = source_text.splitlines()
        start = max(0, cls.start_line - 1)
        end = min(len(lines), cls.end_line)
        return "\n".join(lines[start:end])

    def _detect_depends_in_func(
        self,
        func: Node,
        source_text: str,
        file_path: str,
    ) -> list[Edge]:
        """Detect Depends() usage in a function's parameters."""
        edges: list[Edge] = []
        lines = source_text.splitlines()
        start = max(0, func.start_line - 1)
        end = min(len(lines), func.start_line + 10)  # Check first ~10 lines of func
        func_header = "\n".join(lines[start:end])

        for match in _DEPENDS_RE.finditer(func_header):
            dep_name = match.group("dep")
            dep_short = dep_name.rsplit(".", 1)[-1]

            edges.append(
                Edge(
                    source_id=func.id,
                    target_id=f"__unresolved__:dep:{dep_short}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.85,
                    line_number=func.start_line,
                    metadata={
                        "framework": "fastapi",
                        "dependency": dep_name,
                        "injection_type": "Depends",
                    },
                )
            )

        return edges

    # ── Pydantic model detection ──────────────────────────────

    def _detect_pydantic_model(
        self,
        cls: Node,
        source_text: str,
        file_path: str,
    ) -> FrameworkPattern | None:
        """Detect Pydantic model and its fields."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        model_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.MODEL, cls.name),
            kind=NodeKind.MODEL,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="python",
            metadata={
                "framework": "fastapi",
                "original_class_id": cls.id,
                "model_type": "pydantic",
            },
        )
        new_nodes.append(model_node)

        # Detect fields from class body
        class_source = self._get_class_source(cls, source_text)
        for match in _PYDANTIC_FIELD_RE.finditer(class_source):
            field_name = match.group("field_name")
            field_type = match.group("field_type").strip()

            # Skip class-level keywords and dunder methods
            if field_name.startswith("_") or field_name in (
                "class",
                "def",
                "return",
                "if",
                "else",
                "for",
                "while",
                "model_config",
                "Config",
            ):
                continue

            line_no = cls.start_line + class_source[: match.start()].count("\n")

            prop_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.PROPERTY, f"{cls.name}.{field_name}"),
                kind=NodeKind.PROPERTY,
                name=field_name,
                qualified_name=f"{cls.qualified_name}.{field_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "fastapi",
                    "field_type": field_type,
                    "pydantic_field": True,
                },
            )
            new_nodes.append(prop_node)
            new_edges.append(
                Edge(
                    source_id=model_node.id,
                    target_id=prop_node.id,
                    kind=EdgeKind.CONTAINS,
                    confidence=1.0,
                    line_number=line_no,
                    metadata={"framework": "fastapi"},
                )
            )

        return FrameworkPattern(
            framework_name="fastapi",
            pattern_type="model",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"model_name": cls.qualified_name, "model_type": "pydantic"},
        )

    # ── Global pattern helpers ────────────────────────────────

    def _extract_router_inclusions(
        self,
        store: Any,
        project_root: str,
    ) -> FrameworkPattern | None:
        """Extract router inclusion chain from source files."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        for root, _dirs, files in os.walk(project_root):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    continue

                if "include_router" not in content:
                    continue

                rel_path = os.path.relpath(fpath, project_root)

                for match in _INCLUDE_ROUTER_RE.finditer(content):
                    app_var = match.group("app")
                    router_var = match.group("router")
                    prefix = match.group("prefix") or ""
                    tags_str = match.group("tags")
                    line_no = content[: match.start()].count("\n") + 1

                    tags: list[str] = []
                    if tags_str:
                        tags = [t.strip().strip("'\"") for t in tags_str.split(",")]

                    inc_node = Node(
                        id=generate_node_id(rel_path, line_no, NodeKind.MODULE, f"include:{router_var}"),
                        kind=NodeKind.MODULE,
                        name=f"include({router_var})",
                        qualified_name=f"fastapi.include_router:{router_var}",
                        file_path=rel_path,
                        start_line=line_no,
                        end_line=line_no,
                        language="python",
                        metadata={
                            "framework": "fastapi",
                            "component_type": "router_inclusion",
                            "app_variable": app_var,
                            "router_variable": router_var,
                            "prefix": prefix,
                            "tags": tags,
                        },
                    )
                    new_nodes.append(inc_node)

                    # Try to find the router module node in store
                    router_nodes = store.find_nodes(
                        kind=NodeKind.MODULE,
                        name_pattern=router_var,
                        limit=10,
                    )
                    for rn in router_nodes:
                        if "api_router" in rn.metadata.get("component_type", ""):
                            new_edges.append(
                                Edge(
                                    source_id=inc_node.id,
                                    target_id=rn.id,
                                    kind=EdgeKind.DEPENDS_ON,
                                    confidence=0.80,
                                    line_number=line_no,
                                    metadata={
                                        "framework": "fastapi",
                                        "relationship": "includes_router",
                                    },
                                )
                            )
                            break

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="fastapi",
            pattern_type="router_inclusions",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"inclusion_count": len(new_nodes)},
        )

    def _build_dependency_tree(self, store: Any) -> FrameworkPattern | None:
        """Build dependency injection tree from Depends() edges."""
        # Find all DEPENDS_ON edges with fastapi framework metadata

        # Find all function nodes that might be dependencies
        func_nodes = store.find_nodes(kind=NodeKind.FUNCTION, language="python", limit=500)

        # Build a name → id map for resolution
        func_map: dict[str, str] = {}
        for fn in func_nodes:
            func_map[fn.name] = fn.id

        # Find all route nodes with fastapi framework
        route_nodes = store.find_nodes(kind=NodeKind.ROUTE, limit=500)
        for route in route_nodes:
            if route.metadata.get("framework") != "fastapi":
                continue

            # Check edges from the handler function
            # This is handled per-file, but we can resolve unresolved deps here

        # Resolve unresolved dependency references
        # This would require iterating edges, which the store API may not support directly
        # For now, return None — the per-file detection handles most cases
        return None

    def _detect_pydantic_inheritance(self, store: Any) -> FrameworkPattern | None:
        """Detect Pydantic model inheritance chains."""
        new_edges: list[Edge] = []

        model_nodes = store.find_nodes(kind=NodeKind.MODEL, language="python", limit=500)
        pydantic_models = [m for m in model_nodes if m.metadata.get("model_type") == "pydantic"]

        if len(pydantic_models) < 2:
            return None

        # Build name → id map
        model_map: dict[str, str] = {}
        for m in pydantic_models:
            model_map[m.name] = m.id

        # Check class nodes for inheritance from other Pydantic models
        class_nodes = store.find_nodes(kind=NodeKind.CLASS, language="python", limit=500)
        for cls in class_nodes:
            # Check if this class has a corresponding pydantic model
            if cls.name not in model_map:
                continue

            # Read the file to check bases
            try:
                with open(cls.file_path, encoding="utf-8") as f:
                    source_text = f.read()
            except OSError:
                continue

            bases = self._extract_bases(cls, source_text)
            for base in bases:
                base_short = base.rsplit(".", 1)[-1]
                if base_short in model_map and base_short != cls.name:
                    new_edges.append(
                        Edge(
                            source_id=model_map[cls.name],
                            target_id=model_map[base_short],
                            kind=EdgeKind.EXTENDS,
                            confidence=0.90,
                            metadata={
                                "framework": "fastapi",
                                "relationship": "pydantic_inheritance",
                            },
                        )
                    )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="fastapi",
            pattern_type="pydantic_inheritance",
            nodes=[],
            edges=new_edges,
            metadata={"inheritance_count": len(new_edges)},
        )
