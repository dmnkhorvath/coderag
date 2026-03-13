"""Next.js framework detector for CodeRAG.

Detects Next.js-specific patterns including file-based routing
(App Router and Pages Router), server/client components, and
route handlers from project structure and source directives.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import PurePosixPath
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

# ── App Router special file conventions ───────────────────────
_APP_ROUTER_FILES: dict[str, str] = {
    "page": "page",
    "layout": "layout",
    "loading": "loading",
    "error": "error",
    "not-found": "not_found",
    "template": "template",
    "default": "default",
    "route": "api_route",
    "global-error": "global_error",
}

# Extensions recognised as Next.js route files
_ROUTE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Regex for "use client" / "use server" directives
_USE_CLIENT_RE = re.compile(
    r"""^\s*["\']use\s+client["\']\s*;?""",
    re.MULTILINE,
)
_USE_SERVER_RE = re.compile(
    r"""^\s*["\']use\s+server["\']\s*;?""",
    re.MULTILINE,
)

# Dynamic segment patterns in directory names
_DYNAMIC_SEGMENT_RE = re.compile(r"\[(?P<param>[^\]]+)\]")
_CATCH_ALL_RE = re.compile(r"\[\.\.\.(?P<param>[^\]]+)\]")
_OPTIONAL_CATCH_ALL_RE = re.compile(r"\[\[\.\.\.(?P<param>[^\]]+)\]\]")
_ROUTE_GROUP_RE = re.compile(r"^\((?P<group>[^)]+)\)$")


def _dir_to_url_segment(dirname: str) -> str | None:
    """Convert a directory name to a URL segment.

    Returns None for route groups (parenthesised names) since
    they do not contribute to the URL path.
    """
    # Route groups like (marketing) are layout-only, no URL segment
    if _ROUTE_GROUP_RE.match(dirname):
        return None

    # Optional catch-all [[...slug]]
    m = _OPTIONAL_CATCH_ALL_RE.match(dirname)
    if m:
        return f"[[...{m.group('param')}]]"

    # Catch-all [...slug]
    m = _CATCH_ALL_RE.match(dirname)
    if m:
        return f"[...{m.group('param')}]"

    # Dynamic segment [id]
    m = _DYNAMIC_SEGMENT_RE.match(dirname)
    if m:
        return f"[{m.group('param')}]"

    return dirname


def _build_route_path(rel_parts: tuple[str, ...]) -> str:
    """Build a URL route path from directory parts relative to app/ or pages/."""
    segments: list[str] = []
    for part in rel_parts:
        seg = _dir_to_url_segment(part)
        if seg is not None:
            segments.append(seg)
    route = "/" + "/".join(segments) if segments else "/"
    return route


class NextJSDetector(FrameworkDetector):
    """Detect Next.js framework patterns in JavaScript/TypeScript projects."""

    @property
    def framework_name(self) -> str:
        return "nextjs"

    def detect_framework(self, project_root: str) -> bool:
        """Check package.json for next dependency."""
        pkg_json = os.path.join(project_root, "package.json")
        if not os.path.isfile(pkg_json):
            return False

        try:
            with open(pkg_json, encoding="utf-8") as f:
                data = json.load(f)
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            return "next" in deps or "next" in dev_deps
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
        """Detect per-file Next.js patterns from source code.

        Identifies:
        - App Router route files (page.tsx, layout.tsx, route.ts, etc.)
        - Pages Router route files (pages/**/*.tsx)
        - "use client" / "use server" directives
        - Server and client component classification
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Normalise path separators
        norm_path = file_path.replace(os.sep, "/")

        # ── Directive detection ────────────────────────────────
        directive_pattern = self._detect_directives(
            file_path,
            nodes,
            source_text,
        )
        if directive_pattern:
            patterns.append(directive_pattern)

        # ── App Router detection ──────────────────────────────
        app_pattern = self._detect_app_router(
            file_path,
            norm_path,
            nodes,
            source_text,
        )
        if app_pattern:
            patterns.append(app_pattern)

        # ── Pages Router detection ────────────────────────────
        pages_pattern = self._detect_pages_router(
            file_path,
            norm_path,
            nodes,
            source_text,
        )
        if pages_pattern:
            patterns.append(pages_pattern)

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Next.js patterns.

        Currently returns empty — Next.js patterns are primarily per-file.
        Future: could detect layout nesting, parallel routes, intercepting routes.
        """
        return []

    # ── Private helpers ───────────────────────────────────────

    def _detect_directives(
        self,
        file_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect \"use client\" and \"use server\" directives.

        Classifies components/functions in the file as server or client.
        """
        is_client = bool(_USE_CLIENT_RE.search(source_text))
        is_server = bool(_USE_SERVER_RE.search(source_text))

        if not is_client and not is_server:
            return None

        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Find exported functions/components in this file
        component_nodes = [
            n
            for n in nodes
            if n.kind in (NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.VARIABLE) and n.name and n.name[0].isupper()
        ]

        directive = "use client" if is_client else "use server"
        component_type = "client" if is_client else "server"

        for comp in component_nodes:
            comp_node = Node(
                id=generate_node_id(
                    file_path,
                    comp.start_line,
                    NodeKind.COMPONENT,
                    f"{component_type}:{comp.name}",
                ),
                kind=NodeKind.COMPONENT,
                name=comp.name,
                qualified_name=comp.qualified_name or comp.name,
                file_path=file_path,
                start_line=comp.start_line,
                end_line=comp.end_line,
                language=comp.language,
                metadata={
                    "framework": "nextjs",
                    "directive": directive,
                    "component_type": component_type,
                    "original_node_id": comp.id,
                },
            )
            new_nodes.append(comp_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="nextjs",
            pattern_type="directives",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "directive": directive,
                "component_count": len(new_nodes),
            },
        )

    def _detect_app_router(
        self,
        file_path: str,
        norm_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect App Router route files under app/ directory.

        Recognises page.tsx, layout.tsx, loading.tsx, error.tsx,
        route.ts, template.tsx, not-found.tsx, default.tsx, global-error.tsx.
        """
        # Check if file is under an app/ directory
        app_idx = self._find_router_root(norm_path, "app")
        if app_idx is None:
            return None

        parts = PurePosixPath(norm_path).parts
        # Get the filename without extension
        filename = PurePosixPath(parts[-1])
        stem = filename.stem
        ext = filename.suffix

        if ext not in _ROUTE_EXTENSIONS:
            return None

        if stem not in _APP_ROUTER_FILES:
            return None

        file_type = _APP_ROUTER_FILES[stem]

        # Build route path from directory structure between app/ and the file
        route_dir_parts = parts[app_idx + 1 : -1]  # directories between app/ and file
        route_path = _build_route_path(route_dir_parts)

        # Determine component type from directives
        is_client = bool(_USE_CLIENT_RE.search(source_text))
        component_type = "client" if is_client else "server"

        # Determine HTTP method for route handlers
        http_methods = []
        if file_type == "api_route":
            http_methods = self._detect_http_methods(source_text)

        route_nodes: list[Node] = []
        route_edges: list[Edge] = []

        if file_type == "api_route" and http_methods:
            # Create a ROUTE node for each HTTP method handler
            for method in http_methods:
                line_no = self._find_export_line(source_text, method)
                route_node = Node(
                    id=generate_node_id(
                        file_path,
                        line_no,
                        NodeKind.ROUTE,
                        f"{method}:{route_path}",
                    ),
                    kind=NodeKind.ROUTE,
                    name=f"{method} {route_path}",
                    qualified_name=f"{method} {route_path}",
                    file_path=file_path,
                    start_line=line_no,
                    end_line=line_no,
                    language="typescript",
                    metadata={
                        "framework": "nextjs",
                        "router": "app",
                        "file_type": file_type,
                        "http_method": method,
                        "url_pattern": route_path,
                        "component_type": component_type,
                    },
                )
                route_nodes.append(route_node)

                # Link to handler function
                handler = self._find_handler(nodes, method)
                if handler:
                    route_edges.append(
                        Edge(
                            source_id=route_node.id,
                            target_id=handler.id,
                            kind=EdgeKind.ROUTES_TO,
                            confidence=0.90,
                            line_number=line_no,
                            metadata={
                                "framework": "nextjs",
                                "http_method": method,
                            },
                        )
                    )
        else:
            # Create a single ROUTE node for page/layout/etc.
            route_node = Node(
                id=generate_node_id(
                    file_path,
                    1,
                    NodeKind.ROUTE,
                    f"{file_type}:{route_path}",
                ),
                kind=NodeKind.ROUTE,
                name=f"{file_type} {route_path}",
                qualified_name=f"{file_type} {route_path}",
                file_path=file_path,
                start_line=1,
                end_line=1,
                language="typescript",
                metadata={
                    "framework": "nextjs",
                    "router": "app",
                    "file_type": file_type,
                    "url_pattern": route_path,
                    "component_type": component_type,
                },
            )
            route_nodes.append(route_node)

            # Link to default export component
            default_export = self._find_default_export(nodes, source_text)
            if default_export:
                route_edges.append(
                    Edge(
                        source_id=route_node.id,
                        target_id=default_export.id,
                        kind=EdgeKind.ROUTES_TO,
                        confidence=0.90,
                        line_number=1,
                        metadata={
                            "framework": "nextjs",
                            "file_type": file_type,
                        },
                    )
                )

        if not route_nodes:
            return None

        return FrameworkPattern(
            framework_name="nextjs",
            pattern_type="app_router",
            nodes=route_nodes,
            edges=route_edges,
            metadata={
                "router": "app",
                "route_path": route_path,
                "file_type": file_type,
                "route_count": len(route_nodes),
            },
        )

    def _detect_pages_router(
        self,
        file_path: str,
        norm_path: str,
        nodes: list[Node],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect Pages Router route files under pages/ directory.

        Handles standard pages, dynamic routes [param], catch-all [...param],
        and API routes under pages/api/.
        """
        pages_idx = self._find_router_root(norm_path, "pages")
        if pages_idx is None:
            return None

        parts = PurePosixPath(norm_path).parts
        filename = PurePosixPath(parts[-1])
        stem = filename.stem
        ext = filename.suffix

        if ext not in _ROUTE_EXTENSIONS:
            return None

        # Skip _app, _document, _error special files
        if stem.startswith("_"):
            return None

        # Build route path
        route_dir_parts = parts[pages_idx + 1 : -1]
        if stem == "index":
            route_path = _build_route_path(route_dir_parts)
        else:
            route_path = _build_route_path((*route_dir_parts, stem))

        # Determine if this is an API route
        is_api = len(parts) > pages_idx + 1 and parts[pages_idx + 1] == "api"

        route_nodes: list[Node] = []
        route_edges: list[Edge] = []

        file_type = "api_route" if is_api else "page"

        route_node = Node(
            id=generate_node_id(
                file_path,
                1,
                NodeKind.ROUTE,
                f"pages:{route_path}",
            ),
            kind=NodeKind.ROUTE,
            name=f"{file_type} {route_path}",
            qualified_name=f"pages:{file_type} {route_path}",
            file_path=file_path,
            start_line=1,
            end_line=1,
            language="typescript",
            metadata={
                "framework": "nextjs",
                "router": "pages",
                "file_type": file_type,
                "url_pattern": route_path,
                "is_api": is_api,
            },
        )
        route_nodes.append(route_node)

        # Link to default export
        default_export = self._find_default_export(nodes, source_text)
        if default_export:
            route_edges.append(
                Edge(
                    source_id=route_node.id,
                    target_id=default_export.id,
                    kind=EdgeKind.ROUTES_TO,
                    confidence=0.90,
                    line_number=1,
                    metadata={
                        "framework": "nextjs",
                        "file_type": file_type,
                    },
                )
            )

        return FrameworkPattern(
            framework_name="nextjs",
            pattern_type="pages_router",
            nodes=route_nodes,
            edges=route_edges,
            metadata={
                "router": "pages",
                "route_path": route_path,
                "file_type": file_type,
                "route_count": len(route_nodes),
            },
        )

    # ── Utility helpers ───────────────────────────────────────

    @staticmethod
    def _find_router_root(norm_path: str, router_dir: str) -> int | None:
        """Find the index of the router root directory (app/ or pages/) in path parts."""
        parts = PurePosixPath(norm_path).parts
        for i, part in enumerate(parts):
            if part == router_dir:
                return i
        return None

    @staticmethod
    def _detect_http_methods(source_text: str) -> list[str]:
        """Detect exported HTTP method handlers in a route.ts file.

        Next.js App Router route handlers export named functions:
        export async function GET(request) { ... }
        export async function POST(request) { ... }
        """
        methods = []
        http_method_re = re.compile(
            r"export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(",
        )
        for match in http_method_re.finditer(source_text):
            methods.append(match.group("method"))
        return methods

    @staticmethod
    def _find_export_line(source_text: str, method: str) -> int:
        """Find the line number of an exported HTTP method handler."""
        pattern = re.compile(
            rf"export\s+(?:async\s+)?function\s+{method}\s*\(",
        )
        match = pattern.search(source_text)
        if match:
            return source_text[: match.start()].count("\n") + 1
        return 1

    @staticmethod
    def _find_handler(nodes: list[Node], method: str) -> Node | None:
        """Find a function node matching an HTTP method name."""
        for n in nodes:
            if n.kind == NodeKind.FUNCTION and n.name == method:
                return n
        return None

    @staticmethod
    def _find_default_export(
        nodes: list[Node],
        source_text: str,
    ) -> Node | None:
        """Find the default-exported component/function.

        Looks for:
        - export default function Name
        - export default Name
        - A function whose name matches a default export reference
        """
        # Try to find a direct "export default function Name" pattern
        default_fn_re = re.compile(
            r"export\s+default\s+(?:async\s+)?function\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
        )
        match = default_fn_re.search(source_text)
        if match:
            name = match.group("name")
            for n in nodes:
                if n.name == name and n.kind in (
                    NodeKind.FUNCTION,
                    NodeKind.CLASS,
                    NodeKind.VARIABLE,
                ):
                    return n

        # Try "export default Name" referencing a previously defined symbol
        default_ref_re = re.compile(
            r"export\s+default\s+(?P<name>[A-Z][A-Za-z0-9_$]*)\s*;?",
        )
        match = default_ref_re.search(source_text)
        if match:
            name = match.group("name")
            for n in nodes:
                if n.name == name and n.kind in (
                    NodeKind.FUNCTION,
                    NodeKind.CLASS,
                    NodeKind.VARIABLE,
                ):
                    return n

        # Fallback: return first uppercase-named function
        for n in nodes:
            if n.kind in (NodeKind.FUNCTION, NodeKind.CLASS) and n.name and n.name[0].isupper():
                return n

        return None
