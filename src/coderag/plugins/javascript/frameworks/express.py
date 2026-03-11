"""Express.js framework detector for CodeRAG.

Detects Express-specific patterns including routes, middleware,
and route handlers from already-parsed AST nodes.
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

# HTTP methods used by Express
_HTTP_METHODS = frozenset({
    "get", "post", "put", "patch", "delete", "options", "head", "all",
})

# Regex for Express route patterns in source code
# Matches: app.get('/path', handler), router.post('/path', handler), etc.
_ROUTE_RE = re.compile(
    r"""(?:app|router|server)\s*\.\s*"""
    r"""(?P<method>get|post|put|patch|delete|options|head|all)"""
    r"""\s*\(\s*['"](?P<path>[^'"]+)['"]""" ,
    re.MULTILINE,
)

# Regex for middleware: app.use('/path', handler) or app.use(handler)
_MIDDLEWARE_RE = re.compile(
    r"""(?:app|router|server)\s*\.\s*use\s*\("""
    r"""(?:\s*['"](?P<path>[^'"]+)['"]\s*,)?""",
    re.MULTILINE,
)

# Regex for Router creation: express.Router()
_ROUTER_RE = re.compile(
    r"(?:express\.Router|Router)\s*\(",
)


class ExpressDetector(FrameworkDetector):
    """Detect Express.js framework patterns in JavaScript/TypeScript projects."""

    @property
    def framework_name(self) -> str:
        return "express"

    def detect_framework(self, project_root: str) -> bool:
        """Check package.json for express dependency."""
        pkg_json = os.path.join(project_root, "package.json")
        if not os.path.isfile(pkg_json):
            return False

        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            return "express" in deps or "express" in dev_deps
        except (json.JSONDecodeError, OSError):
            return False

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Express patterns from source code.

        Scans for:
        - Route definitions: app.get('/path', handler)
        - Middleware: app.use(handler)
        - Router instances: express.Router()
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Build a map of function nodes by line range for handler resolution
        func_nodes = [
            n for n in nodes
            if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.VARIABLE)
        ]

        # ── Route extraction ──────────────────────────────────
        route_nodes: list[Node] = []
        route_edges: list[Edge] = []

        for match in _ROUTE_RE.finditer(source_text):
            http_method = match.group("method").upper()
            path = match.group("path")
            line_no = source_text[:match.start()].count("\n") + 1

            route_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.ROUTE, f"{http_method}:{path}"),
                kind=NodeKind.ROUTE,
                name=f"{http_method} {path}",
                qualified_name=f"{http_method} {path}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "express",
                    "http_method": http_method,
                    "url_pattern": path,
                },
            )
            route_nodes.append(route_node)

            # Try to find the handler function
            handler_id = self._find_handler_near_line(
                line_no, func_nodes, file_path, source_text, match.end(),
            )
            if handler_id:
                route_edges.append(Edge(
                    source_id=route_node.id,
                    target_id=handler_id,
                    kind=EdgeKind.ROUTES_TO,
                    confidence=0.80,
                    line_number=line_no,
                    metadata={
                        "framework": "express",
                        "http_method": http_method,
                        "url_pattern": path,
                    },
                ))

        if route_nodes:
            patterns.append(FrameworkPattern(
                framework_name="express",
                pattern_type="routes",
                nodes=route_nodes,
                edges=route_edges,
                metadata={"route_count": len(route_nodes)},
            ))

        # ── Middleware extraction ──────────────────────────────
        mw_nodes: list[Node] = []
        mw_edges: list[Edge] = []

        for match in _MIDDLEWARE_RE.finditer(source_text):
            path = match.group("path") or "/"
            line_no = source_text[:match.start()].count("\n") + 1

            # Extract middleware name from the rest of the line
            rest = source_text[match.end():match.end() + 200]
            mw_name = self._extract_middleware_name(rest)
            if not mw_name:
                mw_name = f"middleware@L{line_no}"

            mw_node = Node(
                id=generate_node_id(file_path, line_no, NodeKind.MIDDLEWARE, mw_name),
                kind=NodeKind.MIDDLEWARE,
                name=mw_name,
                qualified_name=f"middleware:{mw_name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no,
                language="javascript",
                metadata={
                    "framework": "express",
                    "mount_path": path,
                },
            )
            mw_nodes.append(mw_node)

        if mw_nodes:
            patterns.append(FrameworkPattern(
                framework_name="express",
                pattern_type="middleware",
                nodes=mw_nodes,
                edges=mw_edges,
                metadata={"middleware_count": len(mw_nodes)},
            ))

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Express patterns.

        Currently returns empty — Express patterns are primarily per-file.
        Future: could detect router mounting (app.use('/api', apiRouter)).
        """
        return []

    # ── Private helpers ───────────────────────────────────────

    def _find_handler_near_line(
        self,
        route_line: int,
        func_nodes: list[Node],
        file_path: str,
        source_text: str,
        match_end: int,
    ) -> str | None:
        """Find the handler function/variable referenced in a route call.

        Looks for:
        1. Named function reference after the path argument
        2. Function node defined on the same line
        3. Closest function node within a few lines
        """
        # Try to extract handler name from the source after the path
        rest = source_text[match_end:match_end + 200]
        # Look for a named reference: , handlerName) or , handlerName,
        handler_match = re.match(r"\s*,\s*([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[,)]", rest)
        if handler_match:
            handler_name = handler_match.group(1)
            # Find matching function node
            for fn in func_nodes:
                if fn.name == handler_name and fn.file_path == file_path:
                    return fn.id

        # Fall back to finding function on same line
        for fn in func_nodes:
            if fn.file_path == file_path and fn.start_line == route_line:
                return fn.id

        # Fall back to closest function within 2 lines
        closest = None
        closest_dist = float("inf")
        for fn in func_nodes:
            if fn.file_path == file_path:
                dist = abs(fn.start_line - route_line)
                if dist <= 2 and dist < closest_dist:
                    closest = fn
                    closest_dist = dist

        return closest.id if closest else None

    def _extract_middleware_name(self, rest: str) -> str | None:
        """Extract middleware name from the code after app.use(.

        Handles:
        - app.use(cors())  → 'cors'
        - app.use(express.json())  → 'express.json'
        - app.use(authMiddleware)  → 'authMiddleware'
        """
        # Match function call: name() or name.method()
        m = re.match(r"\s*([a-zA-Z_$][a-zA-Z0-9_$.]*?)\s*[()]", rest)
        if m:
            return m.group(1)

        # Match variable reference: name) or name,
        m = re.match(r"\s*([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[,)]", rest)
        if m:
            return m.group(1)

        return None
