"""React framework detector for CodeRAG.

Detects React-specific patterns including components, hooks,
and context providers/consumers from already-parsed AST nodes.
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

# React built-in hooks
_BUILTIN_HOOKS = frozenset(
    {
        "useState",
        "useEffect",
        "useContext",
        "useReducer",
        "useCallback",
        "useMemo",
        "useRef",
        "useImperativeHandle",
        "useLayoutEffect",
        "useDebugValue",
        "useDeferredValue",
        "useTransition",
        "useId",
        "useSyncExternalStore",
        "useInsertionEffect",
        "useOptimistic",
        "useFormStatus",
        "useFormState",
        "useActionState",
    }
)

# Regex for createContext calls
_CREATE_CONTEXT_RE = re.compile(
    r"(?:React\.)?createContext\s*[<(]",
)

# Regex for useContext calls
_USE_CONTEXT_RE = re.compile(
    r"useContext\s*\(\s*(?P<context>[a-zA-Z_$][a-zA-Z0-9_$]*)",
)

# Regex for custom hook calls (useXxx pattern)
_HOOK_CALL_RE = re.compile(
    r"\buse[A-Z][a-zA-Z0-9]*\s*\(",
)

# Regex for JSX elements (to detect component usage)
_JSX_COMPONENT_RE = re.compile(
    r"<\s*(?P<name>[A-Z][a-zA-Z0-9_.]*)",
)


class ReactDetector(FrameworkDetector):
    """Detect React framework patterns in JavaScript/TypeScript projects."""

    @property
    def framework_name(self) -> str:
        return "react"

    def detect_framework(self, project_root: str) -> bool:
        """Check package.json for react dependency.

        Scans the root package.json first, then checks monorepo
        subdirectories (packages/*, apps/*, etc.) for react.
        Also detects .tsx/.jsx files as a fallback signal.
        """
        react_indicators = {"react", "react-dom", "react-native"}

        def _check_pkg(pkg_path: str) -> bool:
            if not os.path.isfile(pkg_path):
                return False
            try:
                with open(pkg_path, encoding="utf-8") as f:
                    data = json.load(f)
                deps = set(data.get("dependencies", {}).keys())
                dev_deps = set(data.get("devDependencies", {}).keys())
                all_deps = deps | dev_deps
                return bool(all_deps & react_indicators)
            except (json.JSONDecodeError, OSError):
                return False

        # Check root package.json
        if _check_pkg(os.path.join(project_root, "package.json")):
            return True

        # Check monorepo subdirectories (packages/*, apps/*, src/*)
        for subdir in ("packages", "apps", "src", "frontend", "client"):
            subdir_path = os.path.join(project_root, subdir)
            if os.path.isdir(subdir_path):
                try:
                    for entry in os.listdir(subdir_path):
                        pkg = os.path.join(subdir_path, entry, "package.json")
                        if _check_pkg(pkg):
                            return True
                except OSError:
                    continue

        # Fallback: check for .tsx/.jsx files (strong React signal)
        for dirpath, _dirs, files in os.walk(project_root):
            if any(f.endswith((".tsx", ".jsx")) for f in files):
                return True
            # Don't recurse too deep
            depth = dirpath.replace(project_root, "").count(os.sep)
            if depth >= 3:
                _dirs.clear()

        return False

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file React patterns from already-extracted AST data.

        Identifies:
        - Components (functions/classes returning JSX)
        - Custom hooks (functions starting with 'use')
        - Context creation and consumption
        - Hook usage within components
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Detect if file contains JSX
        has_jsx = bool(_JSX_COMPONENT_RE.search(source_text))

        # ── Component detection ───────────────────────────────
        component_pattern = self._detect_components(
            file_path,
            nodes,
            edges,
            source_text,
            has_jsx,
        )
        if component_pattern:
            patterns.append(component_pattern)

        # ── Hook detection ────────────────────────────────────
        hook_pattern = self._detect_hooks(
            file_path,
            nodes,
            edges,
            source_text,
        )
        if hook_pattern:
            patterns.append(hook_pattern)

        # ── Context detection ─────────────────────────────────
        context_pattern = self._detect_context(
            file_path,
            nodes,
            edges,
            source_text,
        )
        if context_pattern:
            patterns.append(context_pattern)

        return patterns

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file React patterns.

        Connects hook usage across files and resolves context
        provider/consumer relationships.
        """
        patterns: list[FrameworkPattern] = []

        # Connect USES_HOOK edges for custom hooks across files
        hook_pattern = self._connect_cross_file_hooks(store)
        if hook_pattern:
            patterns.append(hook_pattern)

        return patterns

    # ── Private helpers ───────────────────────────────────────

    def _detect_components(
        self,
        file_path: str,
        nodes: list[Node],
        edges: list[Edge],
        source_text: str,
        has_jsx: bool,
    ) -> FrameworkPattern | None:
        """Detect React components from function/class nodes.

        A function is a component if:
        - Its name starts with uppercase AND
        - The file contains JSX OR the function body contains JSX
        """
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        if not has_jsx:
            return None

        func_nodes = [
            n
            for n in nodes
            if n.kind in (NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.VARIABLE) and n.name and n.name[0].isupper()
        ]

        for fn in func_nodes:
            # Check if this function's source contains JSX
            fn_source = ""
            if fn.source_text:
                fn_source = fn.source_text
            elif fn.start_line and fn.end_line:
                lines = source_text.splitlines()
                start = max(0, fn.start_line - 1)
                end = min(len(lines), fn.end_line)
                fn_source = "\n".join(lines[start:end])

            # If we can check the function body, verify it has JSX
            if fn_source and not _JSX_COMPONENT_RE.search(fn_source):
                # For classes, check if they have a render method
                if fn.kind == NodeKind.CLASS:
                    has_render = any(
                        e.kind == EdgeKind.CONTAINS
                        and any(
                            n2.name == "render" and n2.kind == NodeKind.METHOD for n2 in nodes if n2.id == e.target_id
                        )
                        for e in edges
                        if e.source_id == fn.id
                    )
                    if not has_render:
                        continue
                else:
                    continue

            component_node = Node(
                id=generate_node_id(file_path, fn.start_line, NodeKind.COMPONENT, fn.name),
                kind=NodeKind.COMPONENT,
                name=fn.name,
                qualified_name=fn.qualified_name or fn.name,
                file_path=file_path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                language=fn.language,
                metadata={
                    "framework": "react",
                    "original_node_id": fn.id,
                    "component_type": "class" if fn.kind == NodeKind.CLASS else "function",
                },
            )
            new_nodes.append(component_node)

            # Detect hook usage within this component
            if fn_source:
                for hook_match in _HOOK_CALL_RE.finditer(fn_source):
                    hook_name = hook_match.group(0).rstrip("(").strip()
                    new_edges.append(
                        Edge(
                            source_id=component_node.id,
                            target_id=f"__unresolved__:hook:{hook_name}",
                            kind=EdgeKind.USES_HOOK,
                            confidence=0.80,
                            metadata={
                                "framework": "react",
                                "hook_name": hook_name,
                                "builtin": hook_name in _BUILTIN_HOOKS,
                            },
                        )
                    )

            # Detect rendered child components
            if fn_source:
                for jsx_match in _JSX_COMPONENT_RE.finditer(fn_source):
                    child_name = jsx_match.group("name")
                    if child_name != fn.name:  # Don't self-reference
                        new_edges.append(
                            Edge(
                                source_id=component_node.id,
                                target_id=f"__unresolved__:component:{child_name}",
                                kind=EdgeKind.RENDERS,
                                confidence=0.70,
                                metadata={
                                    "framework": "react",
                                    "child_component": child_name,
                                },
                            )
                        )

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="react",
            pattern_type="components",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"component_count": len(new_nodes)},
        )

    def _detect_hooks(
        self,
        file_path: str,
        nodes: list[Node],
        edges: list[Edge],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect custom React hooks (functions starting with 'use')."""
        new_nodes: list[Node] = []

        func_nodes = [
            n
            for n in nodes
            if n.kind == NodeKind.FUNCTION
            and n.name
            and n.name.startswith("use")
            and len(n.name) > 3
            and n.name[3].isupper()
        ]

        for fn in func_nodes:
            hook_node = Node(
                id=generate_node_id(file_path, fn.start_line, NodeKind.HOOK, fn.name),
                kind=NodeKind.HOOK,
                name=fn.name,
                qualified_name=fn.qualified_name or fn.name,
                file_path=file_path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                language=fn.language,
                metadata={
                    "framework": "react",
                    "original_node_id": fn.id,
                    "hook_type": "custom",
                },
            )
            new_nodes.append(hook_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="react",
            pattern_type="hooks",
            nodes=new_nodes,
            edges=[],
            metadata={"hook_count": len(new_nodes)},
        )

    def _detect_context(
        self,
        file_path: str,
        nodes: list[Node],
        edges: list[Edge],
        source_text: str,
    ) -> FrameworkPattern | None:
        """Detect React context creation and consumption."""
        new_edges: list[Edge] = []

        # Find variables assigned createContext()
        var_nodes = [n for n in nodes if n.kind == NodeKind.VARIABLE]

        for var in var_nodes:
            # Check if this variable is assigned a createContext call
            var_source = ""
            if var.source_text:
                var_source = var.source_text
            elif var.start_line:
                lines = source_text.splitlines()
                start = max(0, var.start_line - 1)
                end = min(len(lines), var.start_line + 2)
                var_source = "\n".join(lines[start:end])

            if var_source and _CREATE_CONTEXT_RE.search(var_source):
                # This variable is a context
                # Find all useContext(ContextName) calls in the file
                for match in _USE_CONTEXT_RE.finditer(source_text):
                    context_name = match.group("context")
                    if context_name == var.name:
                        line_no = source_text[: match.start()].count("\n") + 1
                        # Find the function containing this useContext call
                        consumer = self._find_enclosing_function(
                            line_no,
                            nodes,
                        )
                        if consumer:
                            new_edges.append(
                                Edge(
                                    source_id=consumer.id,
                                    target_id=var.id,
                                    kind=EdgeKind.CONSUMES_CONTEXT,
                                    confidence=0.85,
                                    line_number=line_no,
                                    metadata={
                                        "framework": "react",
                                        "context_name": var.name,
                                    },
                                )
                            )

        # Find .Provider usage in JSX
        provider_re = re.compile(
            r"<\s*(?P<context>[a-zA-Z_$][a-zA-Z0-9_$]*)\.Provider",
        )
        for match in provider_re.finditer(source_text):
            context_name = match.group("context")
            line_no = source_text[: match.start()].count("\n") + 1
            provider_fn = self._find_enclosing_function(line_no, nodes)
            if provider_fn:
                # Find the context variable
                ctx_var = next(
                    (n for n in var_nodes if n.name == context_name),
                    None,
                )
                target_id = ctx_var.id if ctx_var else f"__unresolved__:context:{context_name}"
                new_edges.append(
                    Edge(
                        source_id=provider_fn.id,
                        target_id=target_id,
                        kind=EdgeKind.PROVIDES_CONTEXT,
                        confidence=0.85,
                        line_number=line_no,
                        metadata={
                            "framework": "react",
                            "context_name": context_name,
                        },
                    )
                )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="react",
            pattern_type="context",
            nodes=[],
            edges=new_edges,
            metadata={"context_edge_count": len(new_edges)},
        )

    def _find_enclosing_function(
        self,
        line_no: int,
        nodes: list[Node],
    ) -> Node | None:
        """Find the function/component that encloses a given line."""
        candidates = [
            n
            for n in nodes
            if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.VARIABLE)
            and n.start_line is not None
            and n.end_line is not None
            and n.start_line <= line_no <= n.end_line
        ]
        if not candidates:
            return None
        # Return the most specific (smallest range) enclosing function
        return min(
            candidates,
            key=lambda n: (n.end_line or 0) - (n.start_line or 0),
        )

    def _connect_cross_file_hooks(self, store: Any) -> FrameworkPattern | None:
        """Connect USES_HOOK edges to actual hook definitions across files."""
        new_edges: list[Edge] = []

        # Find all HOOK nodes
        hook_nodes = store.find_nodes(kind=NodeKind.HOOK, limit=500)
        if not hook_nodes:
            return None

        hook_map: dict[str, str] = {h.name: h.id for h in hook_nodes}

        # Find all COMPONENT nodes
        component_nodes = store.find_nodes(kind=NodeKind.COMPONENT, limit=500)

        for comp in component_nodes:
            # Get edges from this component
            # Look for unresolved hook references in metadata
            comp_edges = store.get_edges(
                source_id=comp.id,
                kind=EdgeKind.USES_HOOK,
            )
            for edge in comp_edges:
                if edge.target_id.startswith("__unresolved__:hook:"):
                    hook_name = edge.target_id.split(":")[-1]
                    if hook_name in hook_map:
                        new_edges.append(
                            Edge(
                                source_id=comp.id,
                                target_id=hook_map[hook_name],
                                kind=EdgeKind.USES_HOOK,
                                confidence=0.85,
                                metadata={
                                    "framework": "react",
                                    "hook_name": hook_name,
                                    "resolved": True,
                                },
                            )
                        )

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="react",
            pattern_type="cross_file_hooks",
            nodes=[],
            edges=new_edges,
            metadata={"resolved_hook_count": len(new_edges)},
        )
