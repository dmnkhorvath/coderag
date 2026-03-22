import json
from unittest.mock import MagicMock

import pytest

from coderag.core.models import (
    EdgeKind,
    Node,
    NodeKind,
)
from coderag.plugins.css.frameworks.tailwind import (
    TailwindDetector,
    _detect_token_namespace,
)


@pytest.fixture
def detector():
    return TailwindDetector()


# ── _detect_token_namespace ───────────────────────────────────


class TestDetectTokenNamespace:
    def test_color_prefix(self):
        assert _detect_token_namespace("color-primary") == "color"

    def test_spacing_prefix(self):
        assert _detect_token_namespace("spacing-128") == "spacing"

    def test_font_prefix(self):
        assert _detect_token_namespace("font-display") == "font"

    def test_unknown_prefix(self):
        assert _detect_token_namespace("custom-thing") == "other"


# ── detect_framework ──────────────────────────────────────────


class TestDetectFramework:
    def test_v3_config_js(self, detector, tmp_path):
        (tmp_path / "tailwind.config.js").write_text("module.exports = {}")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_v3_config_ts(self, detector, tmp_path):
        (tmp_path / "tailwind.config.ts").write_text("export default {}")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_v3_config_cjs(self, detector, tmp_path):
        (tmp_path / "tailwind.config.cjs").write_text("module.exports = {}")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_v3_config_mjs(self, detector, tmp_path):
        (tmp_path / "tailwind.config.mjs").write_text("export default {}")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_package_json_deps(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "^3.4.0"}}))
        assert detector.detect_framework(str(tmp_path)) is True

    def test_package_json_devdeps(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"tailwindcss": "^4.0.0"}}))
        assert detector.detect_framework(str(tmp_path)) is True

    def test_package_json_no_tailwind(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
        assert detector.detect_framework(str(tmp_path)) is False

    def test_package_json_malformed(self, detector, tmp_path):
        (tmp_path / "package.json").write_text("not json")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_v4_import_directive(self, detector, tmp_path):
        css_dir = tmp_path / "src"
        css_dir.mkdir()
        (css_dir / "app.css").write_text('@import "tailwindcss";\n')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_v3_tailwind_directive(self, detector, tmp_path):
        css_dir = tmp_path / "src"
        css_dir.mkdir()
        (css_dir / "app.css").write_text("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_skips_node_modules(self, detector, tmp_path):
        nm = tmp_path / "node_modules" / "tailwindcss"
        nm.mkdir(parents=True)
        (nm / "base.css").write_text("@tailwind base;")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_skips_deep_directories(self, detector, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "app.css").write_text('@import "tailwindcss";')
        assert detector.detect_framework(str(tmp_path)) is False

    def test_no_indicators(self, detector, tmp_path):
        (tmp_path / "style.css").write_text("body { color: red; }")
        assert detector.detect_framework(str(tmp_path)) is False


# ── _detect_versions ──────────────────────────────────────────


class TestDetectVersions:
    def test_v3_from_package_json(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "^3.4.0"}}))
        versions = detector._detect_versions(str(tmp_path))
        assert "v3" in versions

    def test_v4_from_package_json(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"tailwindcss": "^4.0.0"}}))
        versions = detector._detect_versions(str(tmp_path))
        assert "v4" in versions

    def test_v3_from_config_file(self, detector, tmp_path):
        (tmp_path / "tailwind.config.js").write_text("module.exports = {}")
        versions = detector._detect_versions(str(tmp_path))
        assert "v3" in versions

    def test_both_versions(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "^4.0.0"}}))
        (tmp_path / "tailwind.config.js").write_text("module.exports = {}")
        versions = detector._detect_versions(str(tmp_path))
        assert "v3" in versions
        assert "v4" in versions

    def test_no_package_json(self, detector, tmp_path):
        versions = detector._detect_versions(str(tmp_path))
        assert len(versions) == 0

    def test_malformed_package_json(self, detector, tmp_path):
        (tmp_path / "package.json").write_text("not json")
        versions = detector._detect_versions(str(tmp_path))
        assert len(versions) == 0

    def test_tilde_v3(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "~3.2.0"}}))
        versions = detector._detect_versions(str(tmp_path))
        assert "v3" in versions

    def test_exact_v4(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "4.1.0"}}))
        versions = detector._detect_versions(str(tmp_path))
        assert "v4" in versions

    def test_unknown_version(self, detector, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"tailwindcss": "latest"}}))
        versions = detector._detect_versions(str(tmp_path))
        # "latest" doesn't start with 3 or 4
        assert "v3" not in versions
        assert "v4" not in versions


# ── detect (per-file) ─────────────────────────────────────────


class TestDetectPerFile:
    def _make_tree_mock(self):
        tree = MagicMock()
        return tree

    def test_v4_theme_block(self, detector):
        source = b"""@import "tailwindcss";

@theme {
  --color-primary: oklch(0.84 0.18 117.33);
  --color-secondary: #6c757d;
  --spacing-128: 32rem;
  --font-display: "Satoshi", sans-serif;
}
"""
        tree = self._make_tree_mock()
        patterns = detector.detect("app.css", tree, source, [], [])
        theme_patterns = [p for p in patterns if p.pattern_type == "theme_tokens"]
        assert len(theme_patterns) == 1
        assert theme_patterns[0].metadata["token_count"] == 4

    def test_v4_utility_block(self, detector):
        source = b"""@utility tab-4 {
  tab-size: 4;
}

@utility content-auto {
  content-visibility: auto;
}
"""
        tree = self._make_tree_mock()
        patterns = detector.detect("app.css", tree, source, [], [])
        utility_patterns = [p for p in patterns if p.pattern_type == "utilities"]
        assert len(utility_patterns) == 1
        assert utility_patterns[0].metadata["utility_count"] == 2

    def test_apply_directives(self, detector):
        source = b""".btn {
  @apply px-4 py-2 bg-blue-500 text-white rounded;
}
.card {
  @apply shadow-lg p-6;
}
"""
        tree = self._make_tree_mock()
        patterns = detector.detect("components.css", tree, source, [], [])
        apply_patterns = [p for p in patterns if p.pattern_type == "apply_directives"]
        assert len(apply_patterns) == 1
        # 5 classes in first @apply + 2 in second = 7
        assert apply_patterns[0].metadata["apply_count"] == 7

    def test_source_directives(self, detector):
        source = b"""@import "tailwindcss";
@source "../node_modules/@my-company/ui-lib";
@source "../shared/components";
"""
        tree = self._make_tree_mock()
        patterns = detector.detect("app.css", tree, source, [], [])
        source_patterns = [p for p in patterns if p.pattern_type == "source_directives"]
        assert len(source_patterns) == 1
        assert source_patterns[0].metadata["source_count"] == 2

    def test_no_patterns(self, detector):
        source = b"""body {
  color: red;
  font-size: 16px;
}
"""
        tree = self._make_tree_mock()
        patterns = detector.detect("plain.css", tree, source, [], [])
        assert len(patterns) == 0

    def test_apply_with_class_nodes(self, detector):
        """Test that @apply edges link to enclosing CSS class nodes."""
        source = b""".btn-primary {
  @apply bg-blue-500 text-white;
}
"""
        btn_node = Node(
            id="btn-id",
            kind=NodeKind.CSS_CLASS,
            name=".btn-primary",
            qualified_name=".btn-primary",
            file_path="components.css",
            start_line=1,
            end_line=3,
            language="css",
        )
        tree = self._make_tree_mock()
        patterns = detector.detect("components.css", tree, source, [btn_node], [])
        apply_patterns = [p for p in patterns if p.pattern_type == "apply_directives"]
        assert len(apply_patterns) == 1
        # Edges should reference the btn_node as source
        for edge in apply_patterns[0].edges:
            assert edge.source_id == "btn-id"


# ── detect_global_patterns ────────────────────────────────────


class TestDetectGlobalPatterns:
    def test_no_file_nodes(self, detector):
        store = MagicMock()
        store.find_nodes.return_value = []
        patterns = detector.detect_global_patterns(store)
        assert patterns == []

    def test_with_project_root_metadata(self, detector, tmp_path):
        # Create a v3 config
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  content: ["./src/**/*.{html,js}"],
  theme: {
    extend: {
      colors: {
        primary: "#007bff",
        secondary: "#6c757d",
      },
    },
  },
}""")

        store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.css",
            qualified_name="app.css",
            file_path=str(tmp_path / "src" / "app.css"),
            start_line=1,
            end_line=1,
            language="css",
        )
        store.find_nodes.return_value = [file_node]
        store.get_metadata.return_value = str(tmp_path)

        patterns = detector.detect_global_patterns(store)
        v3_patterns = [p for p in patterns if p.pattern_type == "v3_config"]
        assert len(v3_patterns) == 1
        assert v3_patterns[0].metadata["token_count"] >= 2

    def test_infer_project_root_from_package_json(self, detector, tmp_path):
        # Create package.json and config
        (tmp_path / "package.json").write_text("{}")
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  content: ["./src/**/*.html"],
  theme: { extend: { spacing: { "128": "32rem" } } },
}""")

        store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.css",
            qualified_name="app.css",
            file_path=str(tmp_path / "src" / "app.css"),
            start_line=1,
            end_line=1,
            language="css",
        )
        store.find_nodes.return_value = [file_node]
        store.get_metadata.side_effect = Exception("no metadata")

        patterns = detector.detect_global_patterns(store)
        v3_patterns = [p for p in patterns if p.pattern_type == "v3_config"]
        assert len(v3_patterns) == 1

    def test_no_project_root_found(self, detector, tmp_path):
        store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.css",
            qualified_name="app.css",
            file_path="relative/path/app.css",  # not absolute
            start_line=1,
            end_line=1,
            language="css",
        )
        store.find_nodes.return_value = [file_node]
        store.get_metadata.side_effect = Exception("no metadata")

        patterns = detector.detect_global_patterns(store)
        assert patterns == []

    def test_no_config_file(self, detector, tmp_path):
        (tmp_path / "package.json").write_text("{}")

        store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.css",
            qualified_name="app.css",
            file_path=str(tmp_path / "src" / "app.css"),
            start_line=1,
            end_line=1,
            language="css",
        )
        store.find_nodes.return_value = [file_node]
        store.get_metadata.return_value = str(tmp_path)

        patterns = detector.detect_global_patterns(store)
        assert patterns == []


# ── _parse_v3_config ──────────────────────────────────────────


class TestParseV3Config:
    def test_full_config(self, detector, tmp_path):
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  content: [
    "./src/**/*.{html,js,jsx}",
    "./public/index.html",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#007bff",
        secondary: "#6c757d",
        accent: "oklch(0.84 0.18 117.33)",
      },
      spacing: {
        "128": "32rem",
        "144": "36rem",
      },
      fontFamily: {
        display: ["Satoshi", "sans-serif"],
        body: ["Inter", "sans-serif"],
      },
      screens: {
        "3xl": "1920px",
      },
    },
  },
}""")

        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        assert pattern.pattern_type == "v3_config"
        assert pattern.framework_version == "v3"

        # Check content path edges
        content_edges = [e for e in pattern.edges if e.kind == EdgeKind.TAILWIND_SOURCE_SCANS]
        assert len(content_edges) == 2

        # Check theme token nodes
        token_nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        assert len(token_nodes) >= 6  # 3 colors + 2 spacing + 1 screen + 2 fonts (array)

        # Check color tokens
        color_tokens = [n for n in token_nodes if n.metadata.get("namespace") == "color"]
        assert len(color_tokens) == 3

        # Check spacing tokens
        spacing_tokens = [n for n in token_nodes if n.metadata.get("namespace") == "spacing"]
        assert len(spacing_tokens) == 2

        # Check font tokens (array values)
        font_tokens = [n for n in token_nodes if n.metadata.get("namespace") == "font"]
        assert len(font_tokens) == 2
        display_font = next(n for n in font_tokens if "display" in n.name)
        assert "Satoshi" in display_font.metadata["value"]

        # Check breakpoint tokens
        bp_tokens = [n for n in token_nodes if n.metadata.get("namespace") == "breakpoint"]
        assert len(bp_tokens) == 1

    def test_empty_config(self, detector, tmp_path):
        config = tmp_path / "tailwind.config.js"
        config.write_text("module.exports = {}")
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is None

    def test_config_oserror(self, detector, tmp_path):
        pattern = detector._parse_v3_config("/nonexistent/tailwind.config.js", str(tmp_path))
        assert pattern is None

    def test_content_only(self, detector, tmp_path):
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  content: ["./src/**/*.html", "./components/**/*.vue"],
}""")
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        content_edges = [e for e in pattern.edges if e.kind == EdgeKind.TAILWIND_SOURCE_SCANS]
        assert len(content_edges) == 2

    def test_theme_extend_only(self, detector, tmp_path):
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  theme: {
    extend: {
      colors: {
        brand: "#ff6600",
      },
    },
  },
}""")
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        token_nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        assert len(token_nodes) == 1
        assert token_nodes[0].metadata["namespace"] == "color"
        assert token_nodes[0].metadata["value"] == "#ff6600"
        assert token_nodes[0].metadata["source"] == "v3"

    def test_theme_defines_edges(self, detector, tmp_path):
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  theme: {
    extend: {
      colors: {
        primary: "#007bff",
      },
    },
  },
}""")
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        defines_edges = [e for e in pattern.edges if e.kind == EdgeKind.TAILWIND_THEME_DEFINES]
        assert len(defines_edges) == 1
        assert defines_edges[0].metadata["config_version"] == "v3"

    def test_screens_section(self, detector, tmp_path):
        """Test screens section produces breakpoint namespace tokens."""
        config = tmp_path / "tailwind.config.js"
        config.write_text("""module.exports = {
  theme: {
    extend: {
      screens: {
        "3xl": "1920px",
        "4xl": "2560px",
      },
    },
  },
}""")
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        token_nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        assert len(token_nodes) == 2
        assert all(n.metadata["namespace"] == "breakpoint" for n in token_nodes)


# ── Edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_theme_block(self, detector):
        source = b"@theme {\n}\n"
        tree = MagicMock()
        patterns = detector.detect("app.css", tree, source, [], [])
        theme_patterns = [p for p in patterns if p.pattern_type == "theme_tokens"]
        assert len(theme_patterns) == 0

    def test_empty_apply(self, detector):
        source = b".btn {\n  @apply ;\n}\n"
        tree = MagicMock()
        patterns = detector.detect("app.css", tree, source, [], [])
        apply_patterns = [p for p in patterns if p.pattern_type == "apply_directives"]
        # Empty @apply should produce no edges
        assert len(apply_patterns) == 0

    def test_multiple_theme_blocks(self, detector):
        source = b"""@theme {
  --color-primary: #007bff;
}

@theme {
  --spacing-lg: 2rem;
}
"""
        tree = MagicMock()
        patterns = detector.detect("app.css", tree, source, [], [])
        theme_patterns = [p for p in patterns if p.pattern_type == "theme_tokens"]
        # Should find tokens from at least one @theme block
        assert len(theme_patterns) >= 1

    def test_framework_name(self, detector):
        assert detector.framework_name == "tailwind"
