"""Laravel framework detector for CodeRAG.

Detects Laravel-specific patterns including routes, Eloquent models,
events/listeners, middleware, and service providers.
"""
from __future__ import annotations

import json
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

# ---------------------------------------------------------------------------
# Regex patterns for Laravel route parsing
# ---------------------------------------------------------------------------

_ROUTE_METHOD_RE = re.compile(
    r"""Route\s*::\s*
    (?P<method>get|post|put|patch|delete|options|any|match|resource|apiResource)
    \s*\(
    \s*['"](?P<path>[^'"]+)['"]   # URL path
    \s*,\s*
    (?:
        \[\s*(?P<controller>[^\]]+?)\s*\]  # [Controller::class, 'method']
        |
        ['"](?P<action>[^'"]+)['"]          # 'Controller@method'
        |
        (?P<closure>function\s*\(|static\s+fn\s*\()  # Closure or arrow fn
        |
        (?P<invocable>[A-Z][A-Za-z0-9_\\]*::class)     # Invocable controller
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_ROUTE_NAME_RE = re.compile(
    r"""->\s*name\s*\(\s*['"](?P<name>[^'"]+)['"]\s*\)"""
)

_ROUTE_MIDDLEWARE_RE = re.compile(
    r"""->\s*middleware\s*\(\s*(?:
        \[\s*(?P<list>[^\]]+)\s*\]   # Array form
        |
        ['"](?P<single>[^'"]+)['"]   # String form
    )\s*\)""",
    re.VERBOSE,
)

_ELOQUENT_RELATIONS = {
    "hasOne", "hasMany", "belongsTo", "belongsToMany",
    "hasManyThrough", "hasOneThrough", "morphTo",
    "morphOne", "morphMany", "morphToMany", "morphedByMany",
}

_ELOQUENT_RELATION_RE = re.compile(
    r"\$this\s*->\s*(?P<relation>"
    + "|".join(_ELOQUENT_RELATIONS)
    + r")\s*\(\s*(?P<related>[^)]*)",
)


class LaravelDetector(FrameworkDetector):
    """Detect Laravel framework patterns in PHP projects."""

    @property
    def framework_name(self) -> str:
        return "laravel"

    def detect_framework(self, project_root: str) -> bool:
        """Check for artisan file and laravel/framework in composer.json."""
        artisan = os.path.join(project_root, "artisan")
        if not os.path.isfile(artisan):
            return False

        composer_json = os.path.join(project_root, "composer.json")
        if os.path.isfile(composer_json):
            try:
                with open(composer_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                require = data.get("require", {})
                require_dev = data.get("require-dev", {})
                if "laravel/framework" in require or "laravel/framework" in require_dev:
                    return True
            except (json.JSONDecodeError, OSError):
                pass
        # Artisan exists — still likely Laravel
        return True

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Laravel patterns from already-extracted AST data."""
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        extends_edges = [e for e in edges if e.kind == EdgeKind.EXTENDS]
        extends_map: dict[str, str] = {}
        for edge in extends_edges:
            target = next((n for n in nodes if n.id == edge.target_id), None)
            if target:
                extends_map[edge.source_id] = target.qualified_name
            else:
                extends_map[edge.source_id] = edge.metadata.get("target_name", "")

        for cls in class_nodes:
            parent = extends_map.get(cls.id, "")
            parent_short = parent.rsplit("\\", 1)[-1] if "\\" in parent else parent

            if parent_short in ("Model", "Authenticatable", "Pivot"):
                pattern = self._detect_model(cls, source_text, file_path, nodes)
                if pattern:
                    patterns.append(pattern)
            elif parent_short in ("Event",) or "Events\\" in cls.qualified_name:
                patterns.append(self._make_event_pattern(cls, file_path))
            elif parent_short in ("Listener",) or "Listeners\\" in cls.qualified_name:
                patterns.append(self._make_listener_pattern(cls, file_path))
            elif parent_short == "Middleware" or "Middleware\\" in cls.qualified_name:
                patterns.append(self._make_middleware_pattern(cls, file_path))
            elif parent_short == "ServiceProvider":
                patterns.append(self._make_provider_pattern(cls, file_path))
            elif parent_short == "Controller" or "Controllers\\" in cls.qualified_name:
                patterns.append(self._make_controller_pattern(cls, file_path))

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Laravel patterns (routes, event-listener mappings)."""
        patterns: list[FrameworkPattern] = []

        project_root = self._infer_project_root(store)
        if not project_root:
            logger.warning("Could not infer project root for Laravel detection")
            return patterns

        route_pattern = self._extract_routes(store, project_root)
        if route_pattern:
            patterns.append(route_pattern)

        event_pattern = self._extract_event_listener_mappings(store, project_root)
        if event_pattern:
            patterns.append(event_pattern)

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
                if os.path.isfile(os.path.join(candidate, "artisan")):
                    return candidate
        return None

    def _detect_model(
        self, cls: Node, source_text: str, file_path: str, nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Detect Eloquent model and its relationships."""
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
            language="php",
            metadata={
                "framework": "laravel",
                "original_class_id": cls.id,
                "model_type": "eloquent",
            },
        )
        new_nodes.append(model_node)

        class_source = cls.source_text if cls.source_text else source_text

        for match in _ELOQUENT_RELATION_RE.finditer(class_source):
            relation_type = match.group("relation")
            related_raw = match.group("related").strip()

            related_name = ""
            if "::class" in related_raw:
                related_name = related_raw.split("::class")[0].strip()
            elif related_raw.startswith(("'", '"')):
                related_name = related_raw.strip("'\"")

            if related_name:
                short_name = related_name.rsplit("\\", 1)[-1] if "\\" in related_name else related_name
                new_edges.append(Edge(
                    source_id=model_node.id,
                    target_id=f"__unresolved__:model:{short_name}",
                    kind=EdgeKind.DEPENDS_ON,
                    confidence=0.75,
                    metadata={
                        "relationship_type": relation_type,
                        "related_model": related_name,
                        "framework": "laravel",
                    },
                ))

        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="model",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"model_name": cls.qualified_name},
        )

    def _make_event_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        event_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.EVENT, cls.name),
            kind=NodeKind.EVENT,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="php",
            metadata={"framework": "laravel", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="event",
            nodes=[event_node],
            edges=[],
            metadata={"event_name": cls.qualified_name},
        )

    def _make_listener_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        listener_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.LISTENER, cls.name),
            kind=NodeKind.LISTENER,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="php",
            metadata={"framework": "laravel", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="listener",
            nodes=[listener_node],
            edges=[],
            metadata={"listener_name": cls.qualified_name},
        )

    def _make_middleware_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        mw_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.MIDDLEWARE, cls.name),
            kind=NodeKind.MIDDLEWARE,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="php",
            metadata={"framework": "laravel", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="middleware",
            nodes=[mw_node],
            edges=[],
            metadata={"middleware_name": cls.qualified_name},
        )

    def _make_provider_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        provider_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.PROVIDER, cls.name),
            kind=NodeKind.PROVIDER,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="php",
            metadata={"framework": "laravel", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="provider",
            nodes=[provider_node],
            edges=[],
            metadata={"provider_name": cls.qualified_name},
        )

    def _make_controller_pattern(self, cls: Node, file_path: str) -> FrameworkPattern:
        ctrl_node = Node(
            id=generate_node_id(file_path, cls.start_line, NodeKind.CONTROLLER, cls.name),
            kind=NodeKind.CONTROLLER,
            name=cls.name,
            qualified_name=cls.qualified_name,
            file_path=file_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            language="php",
            metadata={"framework": "laravel", "original_class_id": cls.id},
        )
        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="controller",
            nodes=[ctrl_node],
            edges=[],
            metadata={"controller_name": cls.qualified_name},
        )

    def _extract_routes(
        self, store: Any, project_root: str,
    ) -> FrameworkPattern | None:
        """Parse Laravel route files and create ROUTE nodes + ROUTES_TO edges."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Scan all .php files in routes/ directory (handles non-standard names
        # like api.base.php, web.base.php, etc.)
        routes_dir = os.path.join(project_root, "routes")
        route_files: list[str] = []
        if os.path.isdir(routes_dir):
            for fname in sorted(os.listdir(routes_dir)):
                if fname.endswith(".php") and fname not in ("channels.php", "console.php"):
                    route_files.append(os.path.join(routes_dir, fname))

        for route_file in route_files:
            if not os.path.isfile(route_file):
                continue
            try:
                with open(route_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError as exc:
                logger.warning("Failed to read route file %s: %s", route_file, exc)
                continue

            rel_path = os.path.relpath(route_file, project_root)
            # Detect API prefix from filename (handles api.php, api.base.php, etc.)
            route_basename = os.path.basename(route_file)
            prefix = "/api" if route_basename.startswith("api") else ""

            for match in _ROUTE_METHOD_RE.finditer(content):
                http_method = match.group("method").upper()
                path = match.group("path")
                full_path = f"{prefix}/{path}".replace("//", "/")

                controller_ref = ""
                if match.group("controller"):
                    controller_ref = match.group("controller").strip()
                elif match.group("action"):
                    controller_ref = match.group("action").strip()
                elif match.group("invocable"):
                    # Invocable controller: SomeController::class → __invoke
                    controller_ref = match.group("invocable").replace("::class", "").strip()

                if http_method in ("RESOURCE", "APIRESOURCE"):
                    rn, re_ = self._expand_resource_routes(
                        full_path, controller_ref, rel_path,
                        match.start(), content, store,
                        is_api=(http_method == "APIRESOURCE"),
                    )
                    new_nodes.extend(rn)
                    new_edges.extend(re_)
                    continue

                line_no = content[:match.start()].count("\n") + 1

                route_name = None
                rest_of_line = content[match.end():match.end() + 200]
                name_match = _ROUTE_NAME_RE.search(rest_of_line)
                if name_match:
                    route_name = name_match.group("name")

                middleware: list[str] = []
                mw_match = _ROUTE_MIDDLEWARE_RE.search(rest_of_line)
                if mw_match:
                    if mw_match.group("list"):
                        middleware = [
                            m.strip().strip("'\"")
                            for m in mw_match.group("list").split(",")
                        ]
                    elif mw_match.group("single"):
                        middleware = [mw_match.group("single")]

                route_node = Node(
                    id=generate_node_id(rel_path, line_no, NodeKind.ROUTE, full_path),
                    kind=NodeKind.ROUTE,
                    name=route_name or full_path,
                    qualified_name=f"{http_method} {full_path}",
                    file_path=rel_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="php",
                    metadata={
                        "framework": "laravel",
                        "http_method": http_method,
                        "url_pattern": full_path,
                        "route_name": route_name,
                        "middleware": middleware,
                        "controller_ref": controller_ref,
                    },
                )
                new_nodes.append(route_node)

                if controller_ref:
                    target_id = self._resolve_controller(controller_ref, store)
                    if target_id:
                        new_edges.append(Edge(
                            source_id=route_node.id,
                            target_id=target_id,
                            kind=EdgeKind.ROUTES_TO,
                            confidence=0.85,
                            line_number=line_no,
                            metadata={
                                "framework": "laravel",
                                "http_method": http_method,
                                "url_pattern": full_path,
                            },
                        ))

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="routes",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"route_count": len(new_nodes)},
        )

    def _expand_resource_routes(
        self, base_path: str, controller_ref: str, file_path: str,
        offset: int, content: str, store: Any, is_api: bool = False,
    ) -> tuple[list[Node], list[Edge]]:
        """Expand Route::resource into individual CRUD routes."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        line_no = content[:offset].count("\n") + 1

        resource_name = base_path.rstrip("/").rsplit("/", 1)[-1]
        param = "{" + resource_name.rstrip("s") + "}"

        methods = [
            ("GET", base_path, "index"),
            ("POST", base_path, "store"),
            ("GET", f"{base_path}/{param}", "show"),
            ("PUT", f"{base_path}/{param}", "update"),
            ("DELETE", f"{base_path}/{param}", "destroy"),
        ]
        if not is_api:
            methods.insert(1, ("GET", f"{base_path}/create", "create"))
            methods.insert(-1, ("GET", f"{base_path}/{param}/edit", "edit"))

        for http_method, path, action in methods:
            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, f"{http_method}:{path}"),
                kind=NodeKind.ROUTE,
                name=f"{resource_name}.{action}",
                qualified_name=f"{http_method} {path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="php",
                metadata={
                    "framework": "laravel",
                    "http_method": http_method,
                    "url_pattern": path,
                    "route_name": f"{resource_name}.{action}",
                    "resource": True,
                    "controller_ref": controller_ref,
                },
            )
            nodes.append(route_node)

            if controller_ref:
                target_id = self._resolve_controller(controller_ref, store, action)
                if target_id:
                    edges.append(Edge(
                        source_id=route_node.id,
                        target_id=target_id,
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.80,
                        line_number=line_no,
                        metadata={
                            "framework": "laravel",
                            "http_method": http_method,
                            "resource_action": action,
                        },
                    ))

        return nodes, edges

    def _resolve_controller(
        self, controller_ref: str, store: Any, method: str | None = None,
    ) -> str | None:
        """Resolve a controller reference to a node ID."""
        controller_name = ""
        method_name = method or ""

        if "::class" in controller_ref:
            parts = controller_ref.split(",")
            controller_name = parts[0].replace("::class", "").strip()
            if len(parts) > 1:
                method_name = parts[1].strip().strip("'\"")
        elif "@" in controller_ref:
            parts = controller_ref.split("@")
            controller_name = parts[0].strip()
            if len(parts) > 1:
                method_name = parts[1].strip()
        else:
            controller_name = controller_ref.strip()

        if not controller_name:
            return None

        short_name = controller_name.rsplit("\\", 1)[-1] if "\\" in controller_name else controller_name

        if method_name:
            method_nodes = store.find_nodes(
                kind=NodeKind.METHOD, name_pattern=method_name, limit=20,
            )
            for mn in method_nodes:
                if short_name.lower() in mn.file_path.lower():
                    return mn.id

        class_nodes = store.find_nodes(
            kind=NodeKind.CLASS, name_pattern=short_name, limit=10,
        )
        for cn in class_nodes:
            if cn.name == short_name:
                return cn.id

        return None

    def _extract_event_listener_mappings(
        self, store: Any, project_root: str,
    ) -> FrameworkPattern | None:
        """Parse EventServiceProvider to connect events to listeners."""
        new_edges: list[Edge] = []

        esp_path = None
        for root, _dirs, files in os.walk(project_root):
            for fname in files:
                if fname == "EventServiceProvider.php":
                    esp_path = os.path.join(root, fname)
                    break
            if esp_path:
                break

        if not esp_path or not os.path.isfile(esp_path):
            return None

        try:
            with open(esp_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return None

        listen_re = re.compile(
            r"([A-Za-z_\\]+)::class\s*=>\s*\[([^\]]+)\]",
            re.MULTILINE,
        )

        for match in listen_re.finditer(content):
            event_name = match.group(1).strip().rsplit("\\", 1)[-1]
            listeners_raw = match.group(2)

            event_nodes = store.find_nodes(
                kind=NodeKind.EVENT, name_pattern=event_name, limit=5,
            )
            if not event_nodes:
                event_nodes = store.find_nodes(
                    kind=NodeKind.CLASS, name_pattern=event_name, limit=5,
                )

            event_node = next(
                (n for n in event_nodes if n.name == event_name), None
            )
            if not event_node:
                continue

            listener_refs = re.findall(r"([A-Za-z_\\]+)::class", listeners_raw)
            for listener_ref in listener_refs:
                listener_name = listener_ref.strip().rsplit("\\", 1)[-1]

                listener_nodes = store.find_nodes(
                    kind=NodeKind.LISTENER, name_pattern=listener_name, limit=5,
                )
                if not listener_nodes:
                    listener_nodes = store.find_nodes(
                        kind=NodeKind.CLASS, name_pattern=listener_name, limit=5,
                    )

                listener_node = next(
                    (n for n in listener_nodes if n.name == listener_name), None,
                )
                if not listener_node:
                    continue

                new_edges.append(Edge(
                    source_id=event_node.id,
                    target_id=listener_node.id,
                    kind=EdgeKind.DISPATCHES_EVENT,
                    confidence=0.90,
                    metadata={
                        "framework": "laravel",
                        "event": event_name,
                        "listener": listener_name,
                    },
                ))
                new_edges.append(Edge(
                    source_id=listener_node.id,
                    target_id=event_node.id,
                    kind=EdgeKind.LISTENS_TO,
                    confidence=0.90,
                    metadata={
                        "framework": "laravel",
                        "event": event_name,
                        "listener": listener_name,
                    },
                ))

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="laravel",
            pattern_type="event_listeners",
            nodes=[],
            edges=new_edges,
            metadata={"mapping_count": len(new_edges) // 2},
        )
