"""Targeted tests to cover remaining uncovered lines in tailwind.py.

Focuses on:
- Lines 194-195: OSError during CSS file scan in detect_framework
- Line 323: parent == d (root reached) in detect_global_patterns project root inference
- Line 662: spacing namespace branch in _parse_v3_config KV pairs
- Line 720: non-font namespace in _parse_v3_config array values
"""

import json
import os
from unittest.mock import MagicMock, patch, mock_open

import pytest

from coderag.core.models import Edge, EdgeKind, FrameworkPattern, Node, NodeKind
from coderag.plugins.css.frameworks.tailwind import TailwindDetector


@pytest.fixture
def detector():
    return TailwindDetector()


class TestDetectFrameworkOSError:
    """Cover lines 194-195: OSError when reading a CSS file during walk."""

    def test_css_file_oserror_during_scan(self, detector, tmp_path):
        """When a CSS file raises OSError on read, detect_framework should
        continue scanning and return False if no other indicators exist."""
        css_dir = tmp_path / "src"
        css_dir.mkdir()
        css_file = css_dir / "app.css"
        css_file.write_text("body { color: red; }")

        real_open = open

        def patched_open(path, *args, **kwargs):
            if str(path).endswith("app.css") and "src" in str(path):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=patched_open):
            result = detector.detect_framework(str(tmp_path))
        assert result is False

    def test_css_file_oserror_with_fallback_to_other_file(self, detector, tmp_path):
        """One CSS file errors but another valid one has tailwind import."""
        css_dir = tmp_path / "src"
        css_dir.mkdir()
        (css_dir / "broken.css").write_text("placeholder")
        (css_dir / "valid.css").write_text('@import "tailwindcss";\n')

        real_open = open
        call_count = {"broken": 0}

        def patched_open(path, *args, **kwargs):
            path_str = str(path)
            if path_str.endswith("broken.css"):
                call_count["broken"] += 1
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=patched_open):
            result = detector.detect_framework(str(tmp_path))
        # valid.css should still be found
        assert result is True


class TestDetectGlobalPatternsRootInference:
    """Cover line 323: parent == d when walking up to filesystem root."""

    def test_infer_root_reaches_filesystem_root(self, detector):
        """When file_path is absolute but no package.json exists anywhere
        up the tree, the loop should hit the filesystem root and stop."""
        store = MagicMock()
        # Use a path deep in the filesystem where no package.json exists
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.css",
            qualified_name="app.css",
            file_path="/nonexistent/deep/path/to/src/app.css",
            start_line=1,
            end_line=1,
            language="css",
        )
        store.find_nodes.return_value = [file_node]
        store.get_metadata.side_effect = Exception("no metadata")

        patterns = detector.detect_global_patterns(store)
        assert patterns == []


class TestParseV3ConfigNamespaceBranches:
    """Cover lines 662, 720: namespace branches in _parse_v3_config."""

    def test_spacing_kv_namespace(self, detector, tmp_path):
        """Line 662: spacing namespace produces spacing-prefixed prop names."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      spacing: {
        '72': '18rem',
        '84': '21rem',
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        token_nodes = [
            n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN
        ]
        assert len(token_nodes) == 2
        for node in token_nodes:
            assert node.metadata["namespace"] == "spacing"
            assert node.name.startswith("--spacing-")

    def test_font_kv_namespace_simple_value(self, detector, tmp_path):
        """Ensure fontFamily KV pairs hit the font namespace branch.
        Use a simple value without inner quotes to match _KV_PAIR_RE."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      fontFamily: {
        mono: 'monospace',
        heading: 'Georgia',
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        font_nodes = [n for n in nodes if n.metadata["namespace"] == "font"]
        assert len(font_nodes) >= 1
        for fn in font_nodes:
            assert fn.name.startswith("--font-")

    def test_breakpoint_kv_namespace(self, detector, tmp_path):
        """Ensure screens KV pairs hit the breakpoint namespace branch."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      screens: {
        'xxl': '1600px',
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        assert len(nodes) == 1
        assert nodes[0].metadata["namespace"] == "breakpoint"
        assert nodes[0].name == "--breakpoint-xxl"

    def test_non_font_array_values_colors(self, detector, tmp_path):
        """Line 720: array values in a non-font section use section-key naming.
        Colors section with array values should use 'colors-key' naming."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      colors: {
        gradient: ['#ff0000', '#00ff00', '#0000ff'],
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        arr_nodes = [n for n in nodes if "gradient" in n.name]
        assert len(arr_nodes) >= 1
        # Non-font array: uses section-key naming → colors-gradient
        assert arr_nodes[0].name == "--colors-gradient"
        assert arr_nodes[0].metadata["namespace"] == "color"
        assert "#ff0000" in arr_nodes[0].metadata["value"]

    def test_non_font_array_values_spacing(self, detector, tmp_path):
        """Array values in spacing section also hit line 720."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      spacing: {
        steps: ['0.25rem', '0.5rem', '1rem'],
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        arr_nodes = [n for n in nodes if "steps" in n.name]
        assert len(arr_nodes) >= 1
        # Non-font array: uses section-key → spacing-steps
        assert arr_nodes[0].name == "--spacing-steps"

    def test_non_font_array_values_screens(self, detector, tmp_path):
        """Array values in screens section hit line 720."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  theme: {
    extend: {
      screens: {
        tablet: ['640px', '768px'],
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        arr_nodes = [n for n in nodes if "tablet" in n.name]
        assert len(arr_nodes) >= 1
        # Non-font array in screens: uses section-key → screens-tablet
        assert arr_nodes[0].name == "--screens-tablet"


class TestParseV3ConfigEdgeCases:
    """Additional edge cases for _parse_v3_config."""

    def test_config_with_only_content_paths(self, detector, tmp_path):
        """Config with content array but no theme section."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  content: [
    './src/**/*.{html,js}',
    './components/**/*.vue',
    './pages/**/*.tsx',
  ],
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        content_edges = [
            e for e in pattern.edges if e.kind == EdgeKind.TAILWIND_SOURCE_SCANS
        ]
        assert len(content_edges) == 3

    def test_config_with_all_sections(self, detector, tmp_path):
        """Config with all four theme sections and content paths."""
        config = tmp_path / "tailwind.config.js"
        config.write_text(
            """module.exports = {
  content: ['./src/**/*.html'],
  theme: {
    extend: {
      colors: {
        brand: '#ff6600',
      },
      spacing: {
        '128': '32rem',
      },
      fontFamily: {
        heading: ['Poppins', 'sans-serif'],
      },
      screens: {
        tablet: '640px',
      },
    },
  },
}"""
        )
        pattern = detector._parse_v3_config(str(config), str(tmp_path))
        assert pattern is not None
        nodes = [n for n in pattern.nodes if n.kind == NodeKind.TAILWIND_THEME_TOKEN]
        namespaces = {n.metadata["namespace"] for n in nodes}
        assert "color" in namespaces
        assert "spacing" in namespaces
        assert "font" in namespaces
        assert "breakpoint" in namespaces
        content_edges = [
            e for e in pattern.edges if e.kind == EdgeKind.TAILWIND_SOURCE_SCANS
        ]
        assert len(content_edges) == 1


class TestDetectFrameworkDepthLimit:
    """Cover line 184: depth limit > 3 check."""

    def test_depth_5_is_skipped(self, detector, tmp_path):
        """Directories at depth > 3 separators should be skipped.
        a/b/c/d/e has 4 separators, 4 > 3 is True → skipped."""
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "app.css").write_text('@import "tailwindcss";')
        assert detector.detect_framework(str(tmp_path)) is False

    def test_depth_3_is_scanned(self, detector, tmp_path):
        """Directories at depth <= 3 separators should be scanned.
        a/b/c has 2 separators, 2 > 3 is False → scanned."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "app.css").write_text('@import "tailwindcss";')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_depth_4_boundary(self, detector, tmp_path):
        """a/b/c/d has 3 separators, 3 > 3 is False → still scanned."""
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "app.css").write_text('@import "tailwindcss";')
        # 3 separators is NOT > 3, so this should be scanned
        assert detector.detect_framework(str(tmp_path)) is True
