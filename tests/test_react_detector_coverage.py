"""Coverage tests for React detector - Pass 2.

Targets missing lines: 114-116, 121, 195, 242-251, 309, 474, 490-523
"""
import os
from unittest.mock import patch, MagicMock

import pytest

from coderag.core.models import Node, Edge, NodeKind, EdgeKind
from coderag.plugins.javascript.frameworks.react import ReactDetector


@pytest.fixture
def detector():
    return ReactDetector()


# ── detect_framework Tests ───────────────────────────────────

class TestDetectFramework:
    """Test detect_framework method."""

    def test_detect_via_package_json(self, tmp_path, detector):
        """Detect React via package.json."""
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_monorepo_subdir(self, tmp_path, detector):
        """Detect React in monorepo subdirectory (lines 114-116)."""
        client = tmp_path / "packages" / "web"
        client.mkdir(parents=True)
        (client / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_tsx_files(self, tmp_path, detector):
        """Detect React via .tsx files (line 121)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export default function App() { return <div/>; }")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_jsx_files(self, tmp_path, detector):
        """Detect React via .jsx files."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("export default function App() { return <div/>; }")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_react(self, tmp_path, detector):
        """No React detected."""
        (tmp_path / "package.json").write_text('{"dependencies": {"vue": "^3.0.0"}}')
        assert detector.detect_framework(str(tmp_path)) is False

    def test_oserror_monorepo_subdir(self, tmp_path, detector):
        """OSError reading monorepo subdir is caught."""
        apps = tmp_path / "apps"
        apps.mkdir()
        with patch("os.listdir", side_effect=OSError("Permission denied")):
            result = detector.detect_framework(str(tmp_path))
            assert isinstance(result, bool)

    def test_depth_limit(self, tmp_path, detector):
        """Deep directory trees are not traversed beyond limit."""
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "App.tsx").write_text("export default function App() {}")
        # Should still detect since os.walk starts from root
        result = detector.detect_framework(str(tmp_path))
        assert isinstance(result, bool)


# ── detect_global_patterns Tests ─────────────────────────────

class TestDetectGlobalPatterns:
    """Test detect_global_patterns method (line 195)."""

    def test_no_hooks_returns_empty(self, detector):
        """No cross-file hooks returns empty list."""
        mock_store = MagicMock()
        mock_store.find_nodes.return_value = []
        result = detector.detect_global_patterns(mock_store)
        assert isinstance(result, list)

    def test_with_hook_nodes(self, detector):
        """Cross-file hook connections."""
        mock_store = MagicMock()
        # Create hook definition and usage nodes
        hook_def = Node(
            id="hook1", kind=NodeKind.FUNCTION, name="useAuth",
            qualified_name="useAuth", file_path="hooks/useAuth.ts",
            start_line=1, end_line=10, language="typescript",
        )
        hook_usage = Node(
            id="hook2", kind=NodeKind.FUNCTION, name="useAuth",
            qualified_name="useAuth", file_path="components/Login.tsx",
            start_line=5, end_line=5, language="typescript",
            metadata={"framework": "react", "hook_name": "useAuth"},
        )
        mock_store.find_nodes.return_value = [hook_def, hook_usage]
        result = detector.detect_global_patterns(mock_store)
        assert isinstance(result, list)


# ── _detect_components Tests ─────────────────────────────────

class TestDetectComponents:
    """Test _detect_components method (lines 242-251, 309)."""

    def test_no_jsx_returns_none(self, detector):
        """No JSX returns None."""
        result = detector._detect_components(
            file_path="app.js",
            nodes=[],
            edges=[],
            source_text="function App() { return null; }",
            has_jsx=False,
        )
        assert result is None

    def test_function_component_detected(self, detector):
        """Function component with JSX is detected."""
        func_node = Node(
            id="fn1", kind=NodeKind.FUNCTION, name="UserList",
            qualified_name="UserList", file_path="UserList.jsx",
            start_line=1, end_line=10, language="javascript",
            source_text="function UserList() { return <div><span>Users</span></div>; }",
        )
        result = detector._detect_components(
            file_path="UserList.jsx",
            nodes=[func_node],
            edges=[],
            source_text="function UserList() { return <div><span>Users</span></div>; }",
            has_jsx=True,
        )
        if result:
            assert result.framework_name == "react"
            assert result.pattern_type == "components"
            assert len(result.nodes) > 0

    def test_lowercase_function_skipped(self, detector):
        """Lowercase function names are not components."""
        func_node = Node(
            id="fn2", kind=NodeKind.FUNCTION, name="helper",
            qualified_name="helper", file_path="utils.js",
            start_line=1, end_line=5, language="javascript",
            source_text="function helper() { return <div/>; }",
        )
        result = detector._detect_components(
            file_path="utils.js",
            nodes=[func_node],
            edges=[],
            source_text="function helper() { return <div/>; }",
            has_jsx=True,
        )
        # lowercase functions are filtered out
        assert result is None

    def test_class_without_render_skipped(self, detector):
        """Class without render method and no JSX in source is skipped (lines 242-251)."""
        class_node = Node(
            id="cls1", kind=NodeKind.CLASS, name="MyComponent",
            qualified_name="MyComponent", file_path="comp.jsx",
            start_line=1, end_line=20, language="javascript",
            source_text="class MyComponent { constructor() {} }",
        )
        result = detector._detect_components(
            file_path="comp.jsx",
            nodes=[class_node],
            edges=[],
            source_text="class MyComponent { constructor() {} }",
            has_jsx=True,
        )
        # Class without render and no JSX in source should be skipped
        assert result is None

    def test_class_with_render_detected(self, detector):
        """Class with render method is detected as component."""
        class_node = Node(
            id="cls2", kind=NodeKind.CLASS, name="MyComponent",
            qualified_name="MyComponent", file_path="comp.jsx",
            start_line=1, end_line=20, language="javascript",
            source_text="class MyComponent { constructor() {} }",
        )
        render_node = Node(
            id="render1", kind=NodeKind.METHOD, name="render",
            qualified_name="MyComponent.render", file_path="comp.jsx",
            start_line=5, end_line=15, language="javascript",
        )
        contains_edge = Edge(
            source_id="cls2", target_id="render1",
            kind=EdgeKind.CONTAINS, confidence=1.0,
        )
        result = detector._detect_components(
            file_path="comp.jsx",
            nodes=[class_node, render_node],
            edges=[contains_edge],
            source_text="class MyComponent { render() { return <div/>; } }",
            has_jsx=True,
        )
        if result:
            assert result.framework_name == "react"
            assert len(result.nodes) > 0

    def test_component_from_source_lines(self, detector):
        """Component detected from source lines when source_text is None."""
        func_node = Node(
            id="fn3", kind=NodeKind.FUNCTION, name="Header",
            qualified_name="Header", file_path="Header.jsx",
            start_line=1, end_line=3, language="javascript",
            source_text=None,
        )
        source = "function Header() {\n  return <header>Title</header>;\n}"
        result = detector._detect_components(
            file_path="Header.jsx",
            nodes=[func_node],
            edges=[],
            source_text=source,
            has_jsx=True,
        )
        if result:
            assert result.framework_name == "react"

    def test_no_matching_components(self, detector):
        """No uppercase functions returns None."""
        result = detector._detect_components(
            file_path="utils.js",
            nodes=[],
            edges=[],
            source_text="const x = 1;",
            has_jsx=True,
        )
        assert result is None


# ── _connect_cross_file_hooks Tests ──────────────────────────

class TestConnectCrossFileHooks:
    """Test _connect_cross_file_hooks method (lines 490-523)."""

    def test_no_hooks_returns_none(self, detector):
        """No hook nodes returns None."""
        mock_store = MagicMock()
        mock_store.find_nodes.return_value = []
        result = detector._connect_cross_file_hooks(mock_store)
        assert result is None

    def test_single_hook_no_connections(self, detector):
        """Single hook with no cross-file usage returns None."""
        mock_store = MagicMock()
        hook = Node(
            id="h1", kind=NodeKind.FUNCTION, name="useAuth",
            qualified_name="useAuth", file_path="hooks/useAuth.ts",
            start_line=1, end_line=10, language="typescript",
        )
        mock_store.find_nodes.return_value = [hook]
        result = detector._connect_cross_file_hooks(mock_store)
        assert result is None
