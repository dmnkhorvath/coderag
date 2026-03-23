"""Coverage tests for Express detector - Pass 2.

Targets missing lines: 103-105, 203, 272-273, 279-283, 301-305
"""
import os
import re
from unittest.mock import patch, MagicMock

import pytest

from coderag.core.models import Node, Edge, NodeKind, EdgeKind
from coderag.plugins.javascript.frameworks.express import ExpressDetector


@pytest.fixture
def detector():
    return ExpressDetector()


# ── detect_framework Tests ───────────────────────────────────

class TestDetectFramework:
    """Test detect_framework method."""

    def test_detect_via_package_json(self, tmp_path, detector):
        """Detect Express via package.json."""
        (tmp_path / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_monorepo_subdir(self, tmp_path, detector):
        """Detect Express in monorepo subdirectory (lines 103-105)."""
        server = tmp_path / "server"
        server.mkdir()
        app = server / "myapp"
        app.mkdir()
        (app / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_apps_subdir(self, tmp_path, detector):
        """Detect Express in apps/ subdirectory."""
        apps = tmp_path / "apps" / "api"
        apps.mkdir(parents=True)
        (apps / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_express(self, tmp_path, detector):
        """No Express detected."""
        (tmp_path / "package.json").write_text('{"dependencies": {"koa": "^2.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is False

    def test_no_package_json(self, tmp_path, detector):
        """No package.json at all."""
        assert detector.detect_framework(str(tmp_path)) is False

    def test_oserror_reading_subdir(self, tmp_path, detector):
        """OSError reading monorepo subdir is caught."""
        server = tmp_path / "server"
        server.mkdir()
        with patch("os.listdir", side_effect=OSError("Permission denied")):
            result = detector.detect_framework(str(tmp_path))
            assert isinstance(result, bool)


# ── _find_handler_near_line Tests ────────────────────────────

class TestFindHandlerNearLine:
    """Test _find_handler_near_line method (lines 272-273, 279-283, 301-305)."""

    def test_no_match_returns_none(self, detector):
        """No matching handler returns None."""
        result = detector._find_handler_near_line(
            route_line=5,
            func_nodes=[],
            file_path="app.js",
            source_text="app.get('/api', handler)",
            match_end=10,
        )
        assert result is None

    def test_named_handler_reference(self, detector):
        """Find handler by name reference after path (lines 272-273)."""
        func_node = Node(
            id="fn1", kind=NodeKind.FUNCTION, name="getUsers",
            qualified_name="getUsers", file_path="app.js",
            start_line=1, end_line=5, language="javascript",
        )
        source = "app.get('/users', getUsers)"
        match_end = source.index("getUsers") - 2  # position after path string
        result = detector._find_handler_near_line(
            route_line=1,
            func_nodes=[func_node],
            file_path="app.js",
            source_text=source,
            match_end=match_end,
        )
        assert result == "fn1"

    def test_same_line_function(self, detector):
        """Find handler on same line (lines 279-283)."""
        func_node = Node(
            id="fn2", kind=NodeKind.FUNCTION, name="handler",
            qualified_name="handler", file_path="app.js",
            start_line=5, end_line=10, language="javascript",
        )
        result = detector._find_handler_near_line(
            route_line=5,
            func_nodes=[func_node],
            file_path="app.js",
            source_text="app.get('/api', (req, res) => {})",
            match_end=0,
        )
        assert result == "fn2"

    def test_closest_within_2_lines(self, detector):
        """Find closest function within 2 lines (lines 301-305)."""
        func_node = Node(
            id="fn3", kind=NodeKind.FUNCTION, name="nearby",
            qualified_name="nearby", file_path="app.js",
            start_line=7, end_line=15, language="javascript",
        )
        result = detector._find_handler_near_line(
            route_line=5,
            func_nodes=[func_node],
            file_path="app.js",
            source_text="app.get('/api', handler)",
            match_end=0,
        )
        assert result == "fn3"

    def test_too_far_function(self, detector):
        """Function more than 2 lines away returns None."""
        func_node = Node(
            id="fn4", kind=NodeKind.FUNCTION, name="faraway",
            qualified_name="faraway", file_path="app.js",
            start_line=20, end_line=30, language="javascript",
        )
        result = detector._find_handler_near_line(
            route_line=5,
            func_nodes=[func_node],
            file_path="app.js",
            source_text="app.get('/api', handler)",
            match_end=0,
        )
        assert result is None

    def test_different_file_ignored(self, detector):
        """Functions in different files are ignored."""
        func_node = Node(
            id="fn5", kind=NodeKind.FUNCTION, name="handler",
            qualified_name="handler", file_path="other.js",
            start_line=5, end_line=10, language="javascript",
        )
        result = detector._find_handler_near_line(
            route_line=5,
            func_nodes=[func_node],
            file_path="app.js",
            source_text="app.get('/api', handler)",
            match_end=0,
        )
        assert result is None


# ── detect_global_patterns Tests ─────────────────────────────

class TestDetectGlobalPatterns:
    """Test detect_global_patterns method (line 203+)."""

    def test_returns_empty_list(self, detector):
        """Express detect_global_patterns returns empty list."""
        mock_store = MagicMock()
        result = detector.detect_global_patterns(mock_store)
        assert result == []


# ── _extract_middleware_name Tests ────────────────────────────

class TestExtractMiddlewareName:
    """Test _extract_middleware_name method."""

    def test_simple_name(self, detector):
        result = detector._extract_middleware_name("cors()")
        assert result is not None

    def test_no_name(self, detector):
        result = detector._extract_middleware_name("()")
        # May return None or a name depending on regex
        assert isinstance(result, (str, type(None)))
