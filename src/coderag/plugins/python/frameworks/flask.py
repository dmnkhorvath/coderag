"""Flask framework detector for CodeRAG.

Detects Flask-specific patterns including routes, blueprints,
error handlers, before/after request hooks, extensions,
and template rendering from already-parsed AST nodes and source code.
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

# Flask route decorator: @app.route('/path', methods=['GET', 'POST'])
# Also matches @blueprint.route, @bp.route, etc.
_ROUTE_RE = re.compile(
    r"@(?P<obj>\w+)\.route\s*\(\s*[\'\"](?P<path>[^\'\"]+)[\'\"]\s*"
    r"(?:,\s*methods\s*=\s*\[(?P<methods>[^\]]+)\])?",
    re.MULTILINE,
)

# Blueprint creation: Blueprint('name', __name__)
_BLUEPRINT_RE = re.compile(
    r"(?P<var>\w+)\s*=\s*Blueprint\s*\(\s*[\'\"](?P<name>[^\'\"]+)[\'\"]\s*"
    r"(?:,\s*[\w\.]+)?\s*"
    r"(?:,\s*url_prefix\s*=\s*[\'\"](?P<prefix>[^\'\"]*)[\'\"])?",
    re.MULTILINE,
)

# Error handler: @app.errorhandler(404)
_ERROR_HANDLER_RE = re.compile(
    r"@(?P<obj>\w+)\.errorhandler\s*\(\s*(?P<code>[\w\.]+)\s*\)",
    re.MULTILINE,
)

# Before/after request hooks
_HOOK_RE = re.compile(
    r"@(?P<obj>\w+)\.(?P<hook>before_request|after_request|before_first_request|"
    r"teardown_request|teardown_appcontext|after_request)\b",
    re.MULTILINE,
)

# Flask extension initialization: ext = Extension(app) or ext.init_app(app)
_EXTENSION_INIT_RE = re.compile(
    r"(?P<var>\w+)\s*=\s*(?P<ext>SQLAlchemy|LoginManager|Migrate|Mail|"
    r"Cors|CORS|Marshmallow|Bcrypt|SocketIO|Celery|Cache|Limiter|"
    r"JWT|JWTManager|Admin|Babel|DebugToolbar|WTF|CSRFProtect|"
    r"Talisman|Compress|Session|RESTful|Api)\s*\(",
    re.MULTILINE,
)

# render_template calls
_RENDER_TEMPLATE_RE = re.compile(
    r"render_template\s*\(\s*[\'\"](?P<template>[^\'\"]+)[\'\"]",
    re.MULTILINE,
)

# app.register_blueprint()
_REGISTER_BLUEPRINT_RE = re.compile(
    r"(?P<app>\w+)\.register_blueprint\s*\(\s*(?P<bp>\w+)"
    r"(?:\s*,\s*url_prefix\s*=\s*[\'\"](?P<prefix>[^\'\"]*)[\'\"])?",
    re.MULTILINE,
)

# Flask app creation: Flask(__name__)
_FLASK_APP_RE = re.compile(
    r"(?P<var>\w+)\s*=\s*Flask\s*\(",
    re.MULTILINE,
)


class FlaskDetector(FrameworkDetector):
    """Detect Flask framework patterns in Python projects."""

    @property
    def framework_name(self) -> str:
        return "flask"

    def detect_framework(self, project_root: str) -> bool:
        """Check for flask in dependency files or source imports."""
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
                    if "flask" in content:
                        return True
                except OSError:
                    continue

        # Check common entry points for Flask import
        for entry in ["app.py", "wsgi.py", "main.py", "__init__.py"]:
            fpath = os.path.join(project_root, entry)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                    if "from flask import" in content or "import flask" in content:
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
        """Detect per-file Flask patterns from source code."""
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        func_nodes = [n for n in nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]

        # ── Route detection ───────────────────────────────────
        route_nodes: list[Node] = []
        route_edges: list[Edge] = []

        for match in _ROUTE_RE.finditer(source_text):
            obj_name = match.group("obj")
            path = match.group("path")
            methods_str = match.group("methods")
            line_no = source_text[: match.start()].count("\n") + 1

            # Parse HTTP methods
            if methods_str:
                http_methods = [m.strip().strip("'\"") for m in methods_str.split(",")]
            else:
                http_methods = ["GET"]

            for method in http_methods:
                method = method.upper()
                route_node = Node(
                    id=generate_node_id(file_path, line_no, NodeKind.ROUTE, f"{method}:{path}"),
                    kind=NodeKind.ROUTE,
                    name=f"{method} {path}",
                    qualified_name=f"{method} {path}",
                    file_path=file_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="python",
                    metadata={
                        "framework": "flask",
                        "http_method": method,
                        "url_pattern": path,
                        "bound_to": obj_name,
                    },
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
                                "framework": "flask",
                                "http_method": method,
                                "url_pattern": path,
                            },
                        )
                    )

        if route_nodes:
            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="routes",
                    nodes=route_nodes,
                    edges=route_edges,
                    metadata={"route_count": len(route_nodes)},
                )
            )

        # ── Blueprint detection ───────────────────────────────
        for match in _BLUEPRINT_RE.finditer(source_text):
            var_name = match.group("var")
            bp_name = match.group("name")
            prefix = match.group("prefix") or ""
            line_no = source_text[: match.start()].count("\n") + 1

            bp_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MODULE, f"blueprint:{bp_name}"),
                kind=NodeKind.MODULE,
                name=bp_name,
                qualified_name=f"flask.blueprint:{bp_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="python",
                metadata={
                    "framework": "flask",
                    "component_type": "blueprint",
                    "variable_name": var_name,
                    "url_prefix": prefix,
                },
            )
            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="blueprint",
                    nodes=[bp_node],
                    edges=[],
                    metadata={"blueprint_name": bp_name, "prefix": prefix},
                )
            )

        # ── Error handler detection ───────────────────────────
        for match in _ERROR_HANDLER_RE.finditer(source_text):
            error_code = match.group("code")
            line_no = source_text[: match.start()].count("\n") + 1

            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            handler_name = handler.name if handler else f"error_handler_{error_code}"

            eh_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.FUNCTION, f"errorhandler:{error_code}"),
                kind=NodeKind.FUNCTION,
                name=handler_name,
                qualified_name=f"flask.errorhandler:{error_code}",
                file_path=file_path,
                start_line=line_no,
                end_line=handler.end_line if handler else line_no,
                language="python",
                metadata={
                    "framework": "flask",
                    "component_type": "error_handler",
                    "error_code": error_code,
                },
            )
            eh_edges: list[Edge] = []
            if handler:
                eh_edges.append(
                    Edge(
                        source_id=eh_node.id,
                        target_id=handler.id,
                        kind=EdgeKind.DEPENDS_ON,
                        confidence=0.90,
                        line_number=line_no,
                        metadata={"framework": "flask", "error_code": error_code},
                    )
                )

            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="error_handler",
                    nodes=[eh_node],
                    edges=eh_edges,
                    metadata={"error_code": error_code},
                )
            )

        # ── Before/after request hooks ────────────────────────
        mw_nodes: list[Node] = []
        for match in _HOOK_RE.finditer(source_text):
            hook_type = match.group("hook")
            line_no = source_text[: match.start()].count("\n") + 1

            handler = self._find_func_near_line(line_no, func_nodes, file_path)
            handler_name = handler.name if handler else f"{hook_type}@L{line_no}"

            mw_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MIDDLEWARE, handler_name),
                kind=NodeKind.MIDDLEWARE,
                name=handler_name,
                qualified_name=f"flask.{hook_type}:{handler_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=handler.end_line if handler else line_no,
                language="python",
                metadata={
                    "framework": "flask",
                    "hook_type": hook_type,
                },
            )
            mw_nodes.append(mw_node)

        if mw_nodes:
            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="middleware",
                    nodes=mw_nodes,
                    edges=[],
                    metadata={"middleware_count": len(mw_nodes)},
                )
            )

        # ── Extension detection ───────────────────────────────
        for match in _EXTENSION_INIT_RE.finditer(source_text):
            var_name = match.group("var")
            ext_name = match.group("ext")
            line_no = source_text[: match.start()].count("\n") + 1

            # Add extension metadata to file-level patterns
            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="extension",
                    nodes=[],
                    edges=[],
                    metadata={
                        "extension_name": ext_name,
                        "variable_name": var_name,
                        "line": line_no,
                    },
                )
            )

        # ── Template rendering ────────────────────────────────
        templates: list[str] = []
        for match in _RENDER_TEMPLATE_RE.finditer(source_text):
            templates.append(match.group("template"))

        if templates:
            patterns.append(
                FrameworkPattern(
                    framework_name="flask",
                    pattern_type="templates",
                    nodes=[],
                    edges=[],
                    metadata={"templates": templates, "template_count": len(templates)},
                )
            )

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Flask patterns.

        - Blueprint registration chain (app.register_blueprint())
        - Extension initialization patterns
        """
        patterns: list[FrameworkPattern] = []

        project_root = self._infer_project_root(store)
        if not project_root:
            return patterns

        bp_pattern = self._extract_blueprint_registrations(store, project_root)
        if bp_pattern:
            patterns.append(bp_pattern)

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
                # Flask projects typically have app.py or a package with __init__.py
                for entry in ["app.py", "wsgi.py", "requirements.txt"]:
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

    def _extract_blueprint_registrations(
        self,
        store: Any,
        project_root: str,
    ) -> FrameworkPattern | None:
        """Extract blueprint registration chain from source files."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Scan Python files for register_blueprint calls
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

                if "register_blueprint" not in content:
                    continue

                rel_path = os.path.relpath(fpath, project_root)

                for match in _REGISTER_BLUEPRINT_RE.finditer(content):
                    app_var = match.group("app")
                    bp_var = match.group("bp")
                    prefix = match.group("prefix") or ""
                    line_no = content[: match.start()].count("\n") + 1

                    reg_node = Node(
                        id=generate_node_id(rel_path, line_no, NodeKind.MODULE, f"bp_reg:{bp_var}"),
                        kind=NodeKind.MODULE,
                        name=f"register({bp_var})",
                        qualified_name=f"flask.register_blueprint:{bp_var}",
                        file_path=rel_path,
                        start_line=line_no,
                        end_line=line_no,
                        language="python",
                        metadata={
                            "framework": "flask",
                            "component_type": "blueprint_registration",
                            "app_variable": app_var,
                            "blueprint_variable": bp_var,
                            "url_prefix": prefix,
                        },
                    )
                    new_nodes.append(reg_node)

                    # Try to find the blueprint module node in store
                    bp_nodes = store.find_nodes(
                        kind=NodeKind.MODULE,
                        name_pattern=bp_var,
                        limit=10,
                    )
                    for bn in bp_nodes:
                        if "blueprint" in bn.metadata.get("component_type", ""):
                            new_edges.append(
                                Edge(
                                    source_id=reg_node.id,
                                    target_id=bn.id,
                                    kind=EdgeKind.DEPENDS_ON,
                                    confidence=0.80,
                                    line_number=line_no,
                                    metadata={
                                        "framework": "flask",
                                        "relationship": "registers_blueprint",
                                    },
                                )
                            )
                            break

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="flask",
            pattern_type="blueprint_registrations",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"registration_count": len(new_nodes)},
        )
