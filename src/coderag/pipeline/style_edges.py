"""Cross-language style edge matcher for CodeRAG.

Creates edges connecting JavaScript/TypeScript components to CSS/SCSS
stylesheets, enabling the knowledge graph to represent styling
relationships across language boundaries.

Edge types created:
- imports_stylesheet: JS/TS file imports a CSS/SCSS file
- css_module_import: JS/TS file imports a CSS Module
- uses_css_class: JSX className references a CSS class definition
- js_sets_css_variable: JS code calls setProperty with a CSS variable
- js_reads_css_variable: JS code calls getPropertyValue with a CSS variable
- tailwind_class_uses_token: Tailwind utility class maps to a theme token
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for scanning JS/TS/JSX/TSX source files
# ---------------------------------------------------------------------------

# className="foo bar" or className={'foo bar'} or class="foo bar"
_CLASSNAME_RE = re.compile(
    r"""(?:className|class)\s*=\s*["'](?P<classes>[^"']+)["']""",
)

# className={`foo ${bar} baz`} — template literal
_CLASSNAME_TEMPLATE_RE = re.compile(
    r"""className\s*=\s*\{\s*`(?P<classes>[^`]+)`\s*\}""",
)

# className={styles.container} or className={styles['header-main']}
_CSS_MODULE_USAGE_RE = re.compile(
    r"""(?P<binding>\w+)\.(?P<class_name>[\w-]+)""",
)

# element.style.setProperty('--color-primary', value)
_SET_PROPERTY_RE = re.compile(
    r"""setProperty\s*\(\s*["'](?P<var>--[\w-]+)["']""",
)

# getComputedStyle(el).getPropertyValue('--color-primary')
_GET_PROPERTY_RE = re.compile(
    r"""getPropertyValue\s*\(\s*["'](?P<var>--[\w-]+)["']""",
)

# document.documentElement.style.setProperty('--var', val)
_STYLE_SET_RE = re.compile(
    r"""style\.setProperty\s*\(\s*["'](?P<var>--[\w-]+)["']""",
)

# Tailwind utility class prefix → theme namespace mapping
TAILWIND_PREFIX_MAP: dict[str, str] = {
    # Colors
    "bg": "color", "text": "color", "border": "color",
    "ring": "color", "divide": "color", "outline": "color",
    "shadow": "color", "accent": "color", "caret": "color",
    "fill": "color", "stroke": "color", "decoration": "color",
    "placeholder": "color", "from": "color", "via": "color", "to": "color",
    # Spacing
    "p": "spacing", "px": "spacing", "py": "spacing",
    "pt": "spacing", "pr": "spacing", "pb": "spacing", "pl": "spacing",
    "m": "spacing", "mx": "spacing", "my": "spacing",
    "mt": "spacing", "mr": "spacing", "mb": "spacing", "ml": "spacing",
    "gap": "spacing", "space-x": "spacing", "space-y": "spacing",
    "w": "spacing", "h": "spacing", "size": "spacing",
    "inset": "spacing", "top": "spacing", "right": "spacing",
    "bottom": "spacing", "left": "spacing",
    # Fonts
    "font": "font", "leading": "font", "tracking": "font",
}

# File extensions for JS/TS/JSX/TSX
_JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
_CSS_EXTENSIONS = frozenset({".css", ".scss", ".less", ".sass"})


class StyleEdgeMatcher:
    """Create edges connecting JS/TS components to CSS/SCSS stylesheets.

    Runs after framework detection and cross-language matching to add
    style-specific edges to the knowledge graph.
    """

    def __init__(self, store: Any, project_root: str) -> None:
        self._store = store
        self._project_root = project_root

    def match(self) -> int:
        """Run all style edge matchers and return total edges created."""
        total = 0

        total += self._match_stylesheet_imports()
        total += self._match_css_module_imports()
        total += self._match_css_class_usage()
        total += self._match_css_variable_bridges()
        total += self._match_tailwind_class_tokens()

        return total

    # ── 1. imports_stylesheet ─────────────────────────────────

    def _match_stylesheet_imports(self) -> int:
        """Reclassify import edges where the target is a CSS/SCSS file.

        Creates IMPORTS_STYLESHEET edges for JS/TS → CSS/SCSS imports.
        """
        new_edges: list[Edge] = []

        # Get all IMPORTS edges
        import_edges = self._store.get_edges(kind=EdgeKind.IMPORTS)

        for edge in import_edges:
            # Check if target is a CSS/SCSS file by looking at the target node
            target_nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                name_pattern="%.css",
                limit=1000,
            )
            css_file_ids = {n.id for n in target_nodes}

            # Also get SCSS files
            scss_nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                name_pattern="%.scss",
                limit=1000,
            )
            css_file_ids.update(n.id for n in scss_nodes)
            break  # Only need to build the set once

        if not import_edges:
            return 0

        # Build CSS file ID set
        css_file_ids: set[str] = set()
        for ext_pattern in ("%.css", "%.scss", "%.less", "%.sass"):
            nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                name_pattern=ext_pattern,
                limit=5000,
            )
            css_file_ids.update(n.id for n in nodes)

        if not css_file_ids:
            return 0

        # Build JS file ID set for source filtering
        js_file_ids: set[str] = set()
        for lang in ("javascript", "typescript"):
            nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                language=lang,
                limit=10000,
            )
            js_file_ids.update(n.id for n in nodes)

        for edge in import_edges:
            if edge.target_id in css_file_ids:
                # Determine if it's a CSS module import
                is_module = ".module." in edge.target_id
                edge_kind = (
                    EdgeKind.CSS_MODULE_IMPORT
                    if is_module
                    else EdgeKind.IMPORTS_STYLESHEET
                )

                new_edges.append(Edge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    kind=edge_kind,
                    confidence=1.0,
                    line_number=edge.line_number,
                    metadata={
                        "original_edge_kind": "imports",
                        "is_css_module": is_module,
                    },
                ))

        if new_edges:
            self._store.upsert_edges(new_edges)
            logger.info(
                "Style edges: %d stylesheet import edges created",
                len(new_edges),
            )

        return len(new_edges)

    # ── 2. css_module_import ──────────────────────────────────

    def _match_css_module_imports(self) -> int:
        """Detect CSS Module imports (already handled in _match_stylesheet_imports).

        This method handles any additional CSS module patterns not caught
        by the import edge reclassification.
        """
        # CSS module imports are already handled in _match_stylesheet_imports
        # This method exists for future extension (e.g., scanning for
        # `import styles from './X.module.css'` patterns in source)
        return 0

    # ── 3. uses_css_class ─────────────────────────────────────

    def _match_css_class_usage(self) -> int:
        """Match className/class attribute values in JSX/HTML to CSS class definitions."""
        new_edges: list[Edge] = []

        # Get all CSS class nodes
        css_class_nodes = self._store.find_nodes(
            kind=NodeKind.CSS_CLASS,
            limit=50000,
        )
        if not css_class_nodes:
            return 0

        # Build lookup: class_name → [css_class_nodes]
        class_lookup: dict[str, list[Node]] = {}
        for node in css_class_nodes:
            # CSS class names are stored with leading dot, strip it
            name = node.name.lstrip(".")
            if name:
                class_lookup.setdefault(name, []).append(node)

        if not class_lookup:
            return 0

        logger.info(
            "Style edges: scanning for className usage (%d CSS classes indexed)",
            len(class_lookup),
        )

        # Scan JS/TS/JSX/TSX files for className usage
        for lang in ("javascript", "typescript"):
            file_nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                language=lang,
                limit=10000,
            )
            for file_node in file_nodes:
                file_path = file_node.file_path
                if not file_path:
                    continue

                # Only scan JSX/TSX files or files that might contain JSX
                abs_path = (
                    file_path
                    if os.path.isabs(file_path)
                    else os.path.join(self._project_root, file_path)
                )

                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                except OSError:
                    continue

                # Skip files without className or class= usage
                if "className" not in source and 'class=' not in source:
                    continue

                file_edges = self._scan_classname_usage(
                    file_node, source, class_lookup,
                )
                new_edges.extend(file_edges)

        if new_edges:
            self._store.upsert_edges(new_edges)
            logger.info(
                "Style edges: %d uses_css_class edges created",
                len(new_edges),
            )

        return len(new_edges)

    def _scan_classname_usage(
        self,
        file_node: Node,
        source: str,
        class_lookup: dict[str, list[Node]],
    ) -> list[Edge]:
        """Scan a single JS/TS file for className usage."""
        edges: list[Edge] = []
        seen: set[tuple[str, str]] = set()  # (source_id, target_id)

        for pattern in (_CLASSNAME_RE, _CLASSNAME_TEMPLATE_RE):
            for match in pattern.finditer(source):
                classes_str = match.group("classes")
                line_no = source[:match.start()].count("\n") + 1

                # Split by whitespace and filter template expressions
                for class_name in classes_str.split():
                    # Skip template expressions like ${var}
                    if "$" in class_name or "{" in class_name:
                        continue
                    # Strip any remaining non-alphanumeric prefix/suffix
                    clean = class_name.strip(".-_")
                    if not clean:
                        continue

                    if clean in class_lookup:
                        for css_node in class_lookup[clean]:
                            key = (file_node.id, css_node.id)
                            if key not in seen:
                                seen.add(key)
                                edges.append(Edge(
                                    source_id=file_node.id,
                                    target_id=css_node.id,
                                    kind=EdgeKind.USES_CSS_CLASS,
                                    confidence=0.7,
                                    line_number=line_no,
                                    metadata={
                                        "class_name": clean,
                                    },
                                ))

        return edges

    # ── 4. js_sets/reads_css_variable ─────────────────────────

    def _match_css_variable_bridges(self) -> int:
        """Detect JS code that manipulates CSS custom properties."""
        new_edges: list[Edge] = []

        # Get all CSS variable nodes
        css_var_nodes = self._store.find_nodes(
            kind=NodeKind.CSS_VARIABLE,
            limit=10000,
        )
        if not css_var_nodes:
            return 0

        # Build lookup: variable_name → [css_variable_nodes]
        var_lookup: dict[str, list[Node]] = {}
        for node in css_var_nodes:
            var_lookup.setdefault(node.name, []).append(node)

        # Also include Tailwind theme tokens as CSS variables
        tw_token_nodes = self._store.find_nodes(
            kind=NodeKind.TAILWIND_THEME_TOKEN,
            limit=10000,
        )
        for node in tw_token_nodes:
            var_lookup.setdefault(node.name, []).append(node)

        if not var_lookup:
            return 0

        # Scan JS/TS files
        for lang in ("javascript", "typescript"):
            file_nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                language=lang,
                limit=10000,
            )
            for file_node in file_nodes:
                file_path = file_node.file_path
                if not file_path:
                    continue

                abs_path = (
                    file_path
                    if os.path.isabs(file_path)
                    else os.path.join(self._project_root, file_path)
                )

                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                except OSError:
                    continue

                # Quick check
                if "setProperty" not in source and "getPropertyValue" not in source:
                    continue

                # Scan for setProperty calls
                for pattern, edge_kind in (
                    (_SET_PROPERTY_RE, EdgeKind.JS_SETS_CSS_VARIABLE),
                    (_STYLE_SET_RE, EdgeKind.JS_SETS_CSS_VARIABLE),
                    (_GET_PROPERTY_RE, EdgeKind.JS_READS_CSS_VARIABLE),
                ):
                    for match in pattern.finditer(source):
                        var_name = match.group("var")
                        line_no = source[:match.start()].count("\n") + 1

                        if var_name in var_lookup:
                            for css_node in var_lookup[var_name]:
                                new_edges.append(Edge(
                                    source_id=file_node.id,
                                    target_id=css_node.id,
                                    kind=edge_kind,
                                    confidence=0.85,
                                    line_number=line_no,
                                    metadata={
                                        "variable_name": var_name,
                                    },
                                ))

        if new_edges:
            self._store.upsert_edges(new_edges)
            logger.info(
                "Style edges: %d CSS variable bridge edges created",
                len(new_edges),
            )

        return len(new_edges)

    # ── 5. tailwind_class_uses_token ──────────────────────────

    def _match_tailwind_class_tokens(self) -> int:
        """Match Tailwind utility classes in templates to theme tokens."""
        new_edges: list[Edge] = []

        # Get all Tailwind theme token nodes
        token_nodes = self._store.find_nodes(
            kind=NodeKind.TAILWIND_THEME_TOKEN,
            limit=10000,
        )
        if not token_nodes:
            return 0

        # Build lookup: (namespace, value_name) → [token_nodes]
        # e.g., ("color", "primary") → [token_node for --color-primary]
        token_lookup: dict[tuple[str, str], list[Node]] = {}
        for node in token_nodes:
            # Parse --color-primary → namespace="color", value="primary"
            name = node.name.lstrip("-")  # Remove leading --
            parts = name.split("-", 1)
            if len(parts) == 2:
                namespace = node.metadata.get("namespace", parts[0]) if node.metadata else parts[0]
                value_name = parts[1]
                token_lookup.setdefault((namespace, value_name), []).append(node)
            # Also store by full name for direct matching
            token_lookup.setdefault(("any", name), []).append(node)

        if not token_lookup:
            return 0

        logger.info(
            "Style edges: scanning for Tailwind class→token matches (%d tokens indexed)",
            len(token_nodes),
        )

        # Scan JS/TS/JSX/TSX files for className with Tailwind classes
        for lang in ("javascript", "typescript"):
            file_nodes = self._store.find_nodes(
                kind=NodeKind.FILE,
                language=lang,
                limit=10000,
            )
            for file_node in file_nodes:
                file_path = file_node.file_path
                if not file_path:
                    continue

                abs_path = (
                    file_path
                    if os.path.isabs(file_path)
                    else os.path.join(self._project_root, file_path)
                )

                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                except OSError:
                    continue

                if "className" not in source and 'class=' not in source:
                    continue

                file_edges = self._scan_tailwind_classes(
                    file_node, source, token_lookup,
                )
                new_edges.extend(file_edges)

        # Also scan CSS files for @apply directives
        css_file_nodes = self._store.find_nodes(
            kind=NodeKind.FILE,
            language="css",
            limit=5000,
        )
        for file_node in css_file_nodes:
            file_path = file_node.file_path
            if not file_path:
                continue

            abs_path = (
                file_path
                if os.path.isabs(file_path)
                else os.path.join(self._project_root, file_path)
            )

            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except OSError:
                continue

            if "@apply" not in source:
                continue

            # Scan @apply directives for Tailwind classes
            apply_re = re.compile(r"@apply\s+([^;]+);")
            for match in apply_re.finditer(source):
                classes_str = match.group(1).strip()
                line_no = source[:match.start()].count("\n") + 1
                for cls in classes_str.split():
                    edges = self._match_single_tw_class(
                        cls, file_node.id, line_no, token_lookup,
                    )
                    new_edges.extend(edges)

        if new_edges:
            self._store.upsert_edges(new_edges)
            logger.info(
                "Style edges: %d tailwind_class_uses_token edges created",
                len(new_edges),
            )

        return len(new_edges)

    def _scan_tailwind_classes(
        self,
        file_node: Node,
        source: str,
        token_lookup: dict[tuple[str, str], list[Node]],
    ) -> list[Edge]:
        """Scan a single file for Tailwind utility class usage."""
        edges: list[Edge] = []
        seen: set[tuple[str, str]] = set()

        for pattern in (_CLASSNAME_RE, _CLASSNAME_TEMPLATE_RE):
            for match in pattern.finditer(source):
                classes_str = match.group("classes")
                line_no = source[:match.start()].count("\n") + 1

                for cls in classes_str.split():
                    if "$" in cls or "{" in cls:
                        continue

                    # Strip responsive/state prefixes: sm:, hover:, dark:, etc.
                    clean = cls.split(":")[-1] if ":" in cls else cls
                    # Strip negative prefix
                    if clean.startswith("-"):
                        clean = clean[1:]

                    matched = self._match_single_tw_class(
                        clean, file_node.id, line_no, token_lookup,
                    )
                    for edge in matched:
                        key = (edge.source_id, edge.target_id)
                        if key not in seen:
                            seen.add(key)
                            edges.append(edge)

        return edges

    @staticmethod
    def _match_single_tw_class(
        class_name: str,
        source_id: str,
        line_no: int,
        token_lookup: dict[tuple[str, str], list[Node]],
    ) -> list[Edge]:
        """Try to match a single Tailwind utility class to a theme token."""
        edges: list[Edge] = []

        # Parse class: "bg-primary" → prefix="bg", value="primary"
        # Handle multi-segment prefixes: "space-x-4" → prefix="space-x", value="4"
        parts = class_name.split("-")
        if len(parts) < 2:
            return edges

        # Try progressively longer prefixes
        for i in range(1, min(len(parts), 3)):
            prefix = "-".join(parts[:i])
            value = "-".join(parts[i:])

            if prefix in TAILWIND_PREFIX_MAP and value:
                namespace = TAILWIND_PREFIX_MAP[prefix]

                # Look up token by (namespace, value)
                tokens = token_lookup.get((namespace, value), [])
                if not tokens:
                    # Try with "any" namespace
                    tokens = token_lookup.get(("any", f"{namespace}-{value}"), [])

                for token_node in tokens:
                    edges.append(Edge(
                        source_id=source_id,
                        target_id=token_node.id,
                        kind=EdgeKind.TAILWIND_CLASS_USES_TOKEN,
                        confidence=0.8,
                        line_number=line_no,
                        metadata={
                            "utility_class": class_name,
                            "prefix": prefix,
                            "namespace": namespace,
                            "token_value": value,
                        },
                    ))
                if tokens:
                    break  # Found a match, stop trying longer prefixes

        return edges
