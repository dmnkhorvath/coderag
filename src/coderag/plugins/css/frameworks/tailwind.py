"""Tailwind CSS framework detector for CodeRAG.

Detects Tailwind CSS projects (v3 and v4) and extracts:
- Theme tokens from tailwind.config.js (v3) or @theme blocks (v4)
- Custom utility definitions (@utility)
- @apply usage connecting CSS to Tailwind utilities
- @source directives for content scanning paths
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
# Regex patterns
# ---------------------------------------------------------------------------

# v4 detection
_IMPORT_TW_RE = re.compile(
    r"""@import\s+["']tailwindcss["']""",
)
_THEME_BLOCK_RE = re.compile(
    r"@theme\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)
_SOURCE_DIRECTIVE_RE = re.compile(
    r"""@source\s+["'](?P<path>[^"']+)["']""",
)
_UTILITY_BLOCK_RE = re.compile(
    r"@utility\s+(?P<name>[\w-]+)\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)
_CUSTOM_VARIANT_RE = re.compile(
    r"@custom-variant\s+(?P<name>[\w-]+)\s*\((?P<selector>[^)]+)\)",
)
_APPLY_RE = re.compile(
    r"@apply\s+(?P<classes>[^;]+);",
)

# v3 detection
_TAILWIND_DIRECTIVE_RE = re.compile(
    r"@tailwind\s+(?:base|components|utilities)",
)

# v3 config parsing
_MODULE_EXPORTS_RE = re.compile(
    r"(?:module\.exports\s*=|export\s+default)\s*\{",
)
_CONTENT_ARRAY_RE = re.compile(
    r"""content\s*:\s*\[(?P<items>[^\]]*)\]""",
    re.DOTALL,
)
_STRING_LITERAL_RE = re.compile(
    r"""["'](?P<value>[^"']+)["']""",
)

# v3 theme.extend parsing
_THEME_EXTEND_RE = re.compile(
    r"theme\s*:\s*\{[^}]*extend\s*:\s*\{(?P<body>.*?)\}\s*\}",
    re.DOTALL,
)
_THEME_SECTION_RE = re.compile(
    r"(?P<section>colors|spacing|fontFamily|screens)\s*:\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)
_KV_PAIR_RE = re.compile(
    r"""["']?(?P<key>[\w-]+)["']?\s*:\s*["'](?P<value>[^"']+)["']""",
)
_KV_ARRAY_RE = re.compile(
    r"""["']?(?P<key>[\w-]+)["']?\s*:\s*\[(?P<value>[^\]]*)\]""",
)

# CSS custom property in @theme block
_CSS_CUSTOM_PROP_RE = re.compile(
    r"--(?P<name>[\w-]+)\s*:\s*(?P<value>[^;]+);",
)

# Namespace detection from CSS custom property names
_TOKEN_NAMESPACE_MAP = {
    "color": "color",
    "spacing": "spacing",
    "font": "font",
    "breakpoint": "breakpoint",
    "radius": "spacing",
    "shadow": "color",
    "ease": "animation",
    "animate": "animation",
    "inset": "spacing",
    "width": "spacing",
    "blur": "effect",
    "opacity": "effect",
    "tracking": "font",
    "leading": "font",
    "text": "font",
}

# v3 section → namespace mapping
_V3_SECTION_NAMESPACE = {
    "colors": "color",
    "spacing": "spacing",
    "fontFamily": "font",
    "screens": "breakpoint",
}

# Config file names for v3
_V3_CONFIG_FILES = (
    "tailwind.config.js",
    "tailwind.config.ts",
    "tailwind.config.cjs",
    "tailwind.config.mjs",
)


def _detect_token_namespace(prop_name: str) -> str:
    """Infer the design-token namespace from a CSS custom property name.

    E.g. ``--color-primary`` → ``"color"``, ``--spacing-128`` → ``"spacing"``.
    """
    for prefix, ns in _TOKEN_NAMESPACE_MAP.items():
        if prop_name.startswith(prefix):
            return ns
    return "other"


class TailwindDetector(FrameworkDetector):
    """Detect Tailwind CSS framework patterns in CSS projects."""

    @property
    def framework_name(self) -> str:
        return "tailwind"

    # ── Project-level detection ────────────────────────────────

    def detect_framework(self, project_root: str) -> bool:
        """Check for Tailwind CSS in the project.

        Fast checks:
        1. tailwind.config.* files (v3)
        2. package.json tailwindcss dependency
        3. CSS files with @import "tailwindcss" (v4) or @tailwind directives (v3)
        """
        # Check v3 config files
        for cfg in _V3_CONFIG_FILES:
            if os.path.isfile(os.path.join(project_root, cfg)):
                return True

        # Check package.json
        pkg_json = os.path.join(project_root, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                if "tailwindcss" in deps or "tailwindcss" in dev_deps:
                    return True
            except (json.JSONDecodeError, OSError):
                pass

        # Quick scan for v4 CSS-first indicators (limit depth)
        for dirpath, _dirnames, filenames in os.walk(project_root):
            # Skip node_modules, .git, vendor
            rel = os.path.relpath(dirpath, project_root)
            if any(
                part in ("node_modules", ".git", "vendor", "dist", "build")
                for part in rel.split(os.sep)
            ):
                continue
            # Limit depth to 4
            if rel.count(os.sep) > 3:
                continue
            for fname in filenames:
                if not fname.endswith(".css"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        head = f.read(4096)
                    if _IMPORT_TW_RE.search(head) or _TAILWIND_DIRECTIVE_RE.search(head):
                        return True
                except OSError:
                    continue

        return False

    # ── Version detection ─────────────────────────────────────

    def _detect_versions(self, project_root: str) -> set[str]:
        """Detect which Tailwind versions are in use (v3, v4, or both)."""
        versions: set[str] = set()

        # Check package.json version
        pkg_json = os.path.join(project_root, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for dep_key in ("dependencies", "devDependencies"):
                    ver = data.get(dep_key, {}).get("tailwindcss", "")
                    ver_clean = ver.lstrip("^~>= ")
                    if ver_clean.startswith("4"):
                        versions.add("v4")
                    elif ver_clean.startswith("3"):
                        versions.add("v3")
            except (json.JSONDecodeError, OSError):
                pass

        # Check config files (v3 indicator)
        for cfg in _V3_CONFIG_FILES:
            if os.path.isfile(os.path.join(project_root, cfg)):
                versions.add("v3")
                break

        return versions

    # ── Per-file detection ────────────────────────────────────

    def detect(
        self,
        file_path: str,
        tree: Any,
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect per-file Tailwind patterns from CSS source code.

        Scans for:
        - @theme blocks (v4) → theme token nodes
        - @utility definitions (v4) → utility nodes
        - @apply directives → applies edges
        - @source directives → source scan edges
        - @import "tailwindcss" → version indicator
        """
        patterns: list[FrameworkPattern] = []
        source_text = source.decode("utf-8", errors="replace")

        # Detect v4 indicators
        is_v4 = bool(_IMPORT_TW_RE.search(source_text))
        is_v3 = bool(_TAILWIND_DIRECTIVE_RE.search(source_text))
        has_theme = bool(_THEME_BLOCK_RE.search(source_text))

        # ── @theme blocks (v4) ────────────────────────────────
        if has_theme:
            theme_pattern = self._extract_theme_tokens(
                file_path, source_text, "v4",
            )
            if theme_pattern:
                patterns.append(theme_pattern)

        # ── @utility definitions (v4) ─────────────────────────
        utility_pattern = self._extract_utilities(file_path, source_text)
        if utility_pattern:
            patterns.append(utility_pattern)

        # ── @apply directives ─────────────────────────────────
        apply_pattern = self._extract_apply_edges(
            file_path, source_text, nodes,
        )
        if apply_pattern:
            patterns.append(apply_pattern)

        # ── @source directives (v4) ───────────────────────────
        source_pattern = self._extract_source_directives(
            file_path, source_text,
        )
        if source_pattern:
            patterns.append(source_pattern)

        return patterns

    # ── Global patterns ───────────────────────────────────────

    def detect_global_patterns(self, store: Any) -> list[FrameworkPattern]:
        """Detect cross-file Tailwind patterns.

        Parses v3 tailwind.config.js/ts files to extract theme tokens.
        """
        patterns: list[FrameworkPattern] = []

        # Find the project root from file nodes
        file_nodes = store.find_nodes(kind=NodeKind.FILE, limit=1)
        if not file_nodes:
            return patterns

        # Determine project root from store metadata
        project_root = None
        try:
            project_root = store.get_metadata("project_root")
        except Exception:
            pass

        if not project_root and file_nodes:
            # Infer from file paths
            fp = file_nodes[0].file_path
            if os.path.isabs(fp):
                # Walk up to find package.json
                d = os.path.dirname(fp)
                for _ in range(10):
                    if os.path.isfile(os.path.join(d, "package.json")):
                        project_root = d
                        break
                    parent = os.path.dirname(d)
                    if parent == d:
                        break
                    d = parent

        if not project_root:
            return patterns

        # Parse v3 config files
        for cfg_name in _V3_CONFIG_FILES:
            cfg_path = os.path.join(project_root, cfg_name)
            if os.path.isfile(cfg_path):
                v3_pattern = self._parse_v3_config(cfg_path, project_root)
                if v3_pattern:
                    patterns.append(v3_pattern)
                break  # Only parse the first config found

        return patterns

    # ── Private helpers ───────────────────────────────────────

    def _extract_theme_tokens(
        self,
        file_path: str,
        source_text: str,
        source_version: str,
    ) -> FrameworkPattern | None:
        """Extract theme tokens from @theme blocks (v4)."""
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        # Find the file node ID for edge creation
        file_node_id = generate_node_id(
            file_path, 1, NodeKind.FILE, os.path.basename(file_path),
        )

        for theme_match in _THEME_BLOCK_RE.finditer(source_text):
            body = theme_match.group("body")
            block_start_line = source_text[:theme_match.start()].count("\n") + 1

            for prop_match in _CSS_CUSTOM_PROP_RE.finditer(body):
                prop_name = prop_match.group("name")
                prop_value = prop_match.group("value").strip()
                prop_line = (
                    block_start_line
                    + body[:prop_match.start()].count("\n")
                )
                namespace = _detect_token_namespace(prop_name)

                token_node = Node(
                    id=generate_node_id(
                        file_path, prop_line,
                        NodeKind.TAILWIND_THEME_TOKEN,
                        f"--{prop_name}",
                    ),
                    kind=NodeKind.TAILWIND_THEME_TOKEN,
                    name=f"--{prop_name}",
                    qualified_name=f"tailwind.theme.--{prop_name}",
                    file_path=file_path,
                    start_line=prop_line,
                    end_line=prop_line,
                    language="css",
                    metadata={
                        "framework": "tailwind",
                        "value": prop_value,
                        "namespace": namespace,
                        "source": source_version,
                    },
                )
                new_nodes.append(token_node)

                # Edge: @theme block defines this token
                new_edges.append(Edge(
                    source_id=file_node_id,
                    target_id=token_node.id,
                    kind=EdgeKind.TAILWIND_THEME_DEFINES,
                    confidence=1.0,
                    line_number=prop_line,
                    metadata={
                        "framework": "tailwind",
                        "namespace": namespace,
                    },
                ))

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="tailwind",
            pattern_type="theme_tokens",
            nodes=new_nodes,
            edges=new_edges,
            metadata={"token_count": len(new_nodes), "version": "v4"},
        )

    def _extract_utilities(
        self,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern | None:
        """Extract custom @utility definitions (v4)."""
        new_nodes: list[Node] = []

        for match in _UTILITY_BLOCK_RE.finditer(source_text):
            name = match.group("name")
            body = match.group("body").strip()
            line_no = source_text[:match.start()].count("\n") + 1

            utility_node = Node(
                id=generate_node_id(
                    file_path, line_no,
                    NodeKind.TAILWIND_UTILITY, name,
                ),
                kind=NodeKind.TAILWIND_UTILITY,
                name=name,
                qualified_name=f"tailwind.utility.{name}",
                file_path=file_path,
                start_line=line_no,
                end_line=line_no + body.count("\n") + 1,
                language="css",
                metadata={
                    "framework": "tailwind",
                    "css_output": body,
                },
            )
            new_nodes.append(utility_node)

        if not new_nodes:
            return None

        return FrameworkPattern(
            framework_name="tailwind",
            pattern_type="utilities",
            nodes=new_nodes,
            edges=[],
            metadata={"utility_count": len(new_nodes)},
        )

    def _extract_apply_edges(
        self,
        file_path: str,
        source_text: str,
        nodes: list[Node],
    ) -> FrameworkPattern | None:
        """Extract @apply directive edges.

        Creates edges from the CSS rule containing @apply to the
        utility classes being applied.
        """
        new_edges: list[Edge] = []

        # Build a map of CSS class nodes in this file for source_id
        class_nodes = [
            n for n in nodes
            if n.kind == NodeKind.CSS_CLASS and n.file_path == file_path
        ]
        class_by_line: dict[int, Node] = {}
        for cn in class_nodes:
            if cn.start_line:
                class_by_line[cn.start_line] = cn

        file_node_id = generate_node_id(
            file_path, 1, NodeKind.FILE, os.path.basename(file_path),
        )

        for match in _APPLY_RE.finditer(source_text):
            classes_str = match.group("classes").strip()
            line_no = source_text[:match.start()].count("\n") + 1
            utility_classes = classes_str.split()

            # Find the enclosing CSS class (nearest class node above this line)
            source_id = file_node_id
            for ln in sorted(class_by_line.keys(), reverse=True):
                if ln <= line_no:
                    source_id = class_by_line[ln].id
                    break

            for util_class in utility_classes:
                new_edges.append(Edge(
                    source_id=source_id,
                    target_id=generate_node_id(
                        file_path, line_no,
                        NodeKind.TAILWIND_UTILITY, util_class,
                    ),
                    kind=EdgeKind.TAILWIND_APPLIES,
                    confidence=0.9,
                    line_number=line_no,
                    metadata={
                        "framework": "tailwind",
                        "utility_class": util_class,
                    },
                ))

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="tailwind",
            pattern_type="apply_directives",
            nodes=[],
            edges=new_edges,
            metadata={"apply_count": len(new_edges)},
        )

    def _extract_source_directives(
        self,
        file_path: str,
        source_text: str,
    ) -> FrameworkPattern | None:
        """Extract @source directives (v4) that point to content paths."""
        new_edges: list[Edge] = []

        file_node_id = generate_node_id(
            file_path, 1, NodeKind.FILE, os.path.basename(file_path),
        )

        for match in _SOURCE_DIRECTIVE_RE.finditer(source_text):
            path = match.group("path")
            line_no = source_text[:match.start()].count("\n") + 1

            # Create a virtual target node ID for the source path
            target_id = generate_node_id(
                file_path, line_no,
                NodeKind.DIRECTORY, path,
            )

            new_edges.append(Edge(
                source_id=file_node_id,
                target_id=target_id,
                kind=EdgeKind.TAILWIND_SOURCE_SCANS,
                confidence=1.0,
                line_number=line_no,
                metadata={
                    "framework": "tailwind",
                    "source_path": path,
                },
            ))

        if not new_edges:
            return None

        return FrameworkPattern(
            framework_name="tailwind",
            pattern_type="source_directives",
            nodes=[],
            edges=new_edges,
            metadata={"source_count": len(new_edges)},
        )

    def _parse_v3_config(
        self,
        config_path: str,
        project_root: str,
    ) -> FrameworkPattern | None:
        """Parse a v3 tailwind.config.js/ts file using regex.

        Extracts theme.extend tokens (colors, spacing, fontFamily, screens)
        and content paths.
        """
        try:
            with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
                config_text = f.read()
        except OSError:
            return None

        rel_config = os.path.relpath(config_path, project_root)
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []

        file_node_id = generate_node_id(
            rel_config, 1, NodeKind.FILE, os.path.basename(rel_config),
        )

        # ── Extract content paths ─────────────────────────────
        content_match = _CONTENT_ARRAY_RE.search(config_text)
        if content_match:
            items_str = content_match.group("items")
            line_no = config_text[:content_match.start()].count("\n") + 1
            for str_match in _STRING_LITERAL_RE.finditer(items_str):
                path = str_match.group("value")
                target_id = generate_node_id(
                    rel_config, line_no,
                    NodeKind.DIRECTORY, path,
                )
                new_edges.append(Edge(
                    source_id=file_node_id,
                    target_id=target_id,
                    kind=EdgeKind.TAILWIND_SOURCE_SCANS,
                    confidence=1.0,
                    line_number=line_no,
                    metadata={
                        "framework": "tailwind",
                        "source_path": path,
                        "config_version": "v3",
                    },
                ))

        # ── Extract theme.extend tokens ───────────────────────
        # Try to find theme.extend block
        # Use a more flexible approach: find each section independently
        for section_match in _THEME_SECTION_RE.finditer(config_text):
            section = section_match.group("section")
            body = section_match.group("body")
            section_line = config_text[:section_match.start()].count("\n") + 1
            namespace = _V3_SECTION_NAMESPACE.get(section, "other")

            # Extract key-value pairs
            for kv_match in _KV_PAIR_RE.finditer(body):
                key = kv_match.group("key")
                value = kv_match.group("value")
                prop_line = section_line + body[:kv_match.start()].count("\n")

                # Map v3 config key to CSS custom property name
                if namespace == "color":
                    prop_name = f"color-{key}"
                elif namespace == "spacing":
                    prop_name = f"spacing-{key}"
                elif namespace == "font":
                    prop_name = f"font-{key}"
                elif namespace == "breakpoint":
                    prop_name = f"breakpoint-{key}"
                else:
                    prop_name = f"{section}-{key}"

                token_node = Node(
                    id=generate_node_id(
                        rel_config, prop_line,
                        NodeKind.TAILWIND_THEME_TOKEN,
                        f"--{prop_name}",
                    ),
                    kind=NodeKind.TAILWIND_THEME_TOKEN,
                    name=f"--{prop_name}",
                    qualified_name=f"tailwind.theme.--{prop_name}",
                    file_path=rel_config,
                    start_line=prop_line,
                    end_line=prop_line,
                    language="javascript",
                    metadata={
                        "framework": "tailwind",
                        "value": value,
                        "namespace": namespace,
                        "source": "v3",
                        "config_key": f"theme.extend.{section}.{key}",
                    },
                )
                new_nodes.append(token_node)

                new_edges.append(Edge(
                    source_id=file_node_id,
                    target_id=token_node.id,
                    kind=EdgeKind.TAILWIND_THEME_DEFINES,
                    confidence=1.0,
                    line_number=prop_line,
                    metadata={
                        "framework": "tailwind",
                        "namespace": namespace,
                        "config_version": "v3",
                    },
                ))

            # Extract array values (e.g., fontFamily: { display: ["Satoshi", "sans-serif"] })
            for arr_match in _KV_ARRAY_RE.finditer(body):
                key = arr_match.group("key")
                arr_value = arr_match.group("value").strip()
                prop_line = section_line + body[:arr_match.start()].count("\n")

                # Collect string values from array
                values = [
                    m.group("value")
                    for m in _STRING_LITERAL_RE.finditer(arr_value)
                ]
                value_str = ", ".join(values) if values else arr_value

                if namespace == "font":
                    prop_name = f"font-{key}"
                else:
                    prop_name = f"{section}-{key}"

                token_node = Node(
                    id=generate_node_id(
                        rel_config, prop_line,
                        NodeKind.TAILWIND_THEME_TOKEN,
                        f"--{prop_name}",
                    ),
                    kind=NodeKind.TAILWIND_THEME_TOKEN,
                    name=f"--{prop_name}",
                    qualified_name=f"tailwind.theme.--{prop_name}",
                    file_path=rel_config,
                    start_line=prop_line,
                    end_line=prop_line,
                    language="javascript",
                    metadata={
                        "framework": "tailwind",
                        "value": value_str,
                        "namespace": namespace,
                        "source": "v3",
                        "config_key": f"theme.extend.{section}.{key}",
                    },
                )
                new_nodes.append(token_node)

                new_edges.append(Edge(
                    source_id=file_node_id,
                    target_id=token_node.id,
                    kind=EdgeKind.TAILWIND_THEME_DEFINES,
                    confidence=1.0,
                    line_number=prop_line,
                    metadata={
                        "framework": "tailwind",
                        "namespace": namespace,
                        "config_version": "v3",
                    },
                ))

        if not new_nodes and not new_edges:
            return None

        return FrameworkPattern(
            framework_name="tailwind",
            framework_version="v3",
            pattern_type="v3_config",
            nodes=new_nodes,
            edges=new_edges,
            metadata={
                "token_count": len(new_nodes),
                "content_path_count": sum(
                    1 for e in new_edges
                    if e.kind == EdgeKind.TAILWIND_SOURCE_SCANS
                ),
                "config_file": rel_config,
            },
        )
