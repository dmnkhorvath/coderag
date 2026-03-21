"""Tests for coderag.launcher.preloader module."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

from coderag.launcher.preloader import (
    _build_entry_points_section,
    _build_key_files_section,
    _build_project_overview,
    _build_search_results_section,
    _estimate_tokens,
    build_preload_context,
)

# ── Mock helpers ──────────────────────────────────────────────


@dataclass
class MockGraphSummary:
    project_name: str = "TestProject"
    project_root: str = "/tmp/test"
    db_path: str = "/tmp/test/.codegraph/graph.db"
    db_size_bytes: int = 1024
    last_parsed: str = "2024-01-01"
    total_nodes: int = 100
    total_edges: int = 200
    nodes_by_kind: dict = field(default_factory=lambda: {"class": 10, "function": 50, "method": 40})
    edges_by_kind: dict = field(default_factory=lambda: {"calls": 100, "imports": 100})
    files_by_language: dict = field(default_factory=lambda: {"php": 30, "javascript": 20})
    frameworks: list = field(default_factory=lambda: ["laravel", "react"])
    communities: int = 5
    avg_confidence: float = 0.95
    top_nodes_by_pagerank: list = field(default_factory=list)


@dataclass
class MockNode:
    id: str = "node-1"
    kind: MagicMock = field(default_factory=lambda: MagicMock(value="class"))
    name: str = "UserService"
    qualified_name: str = "App\\Services\\UserService"
    file_path: str = "src/Services/UserService.php"
    start_line: int = 10
    end_line: int = 100
    language: str = "php"
    docblock: str | None = "Handles user operations"
    source_text: str | None = None
    content_hash: str | None = None
    metadata: dict = field(default_factory=dict)
    pagerank: float = 0.05
    community_id: int | None = None


def _make_mock_store(summary=None, nodes=None, search_results=None):
    store = MagicMock()
    store.get_summary.return_value = summary or MockGraphSummary()
    if nodes:
        store.get_node.side_effect = lambda nid: nodes.get(nid)
    else:
        store.get_node.return_value = MockNode()
    store.search_nodes.return_value = search_results or []
    return store


def _make_mock_config(name="TestProject", root="/tmp/test"):
    config = MagicMock()
    config.project_name = name
    config.project_root = root
    return config


def _make_mock_analyzer(top_nodes=None, entry_points=None):
    analyzer = MagicMock()
    analyzer.pagerank.return_value = {}
    analyzer.get_top_nodes.return_value = top_nodes or []
    analyzer.get_entry_points.return_value = entry_points or []
    return analyzer


# ── Tests ─────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_basic(self):
        assert _estimate_tokens("abcd") == 1

    def test_empty(self):
        assert _estimate_tokens("") == 0

    def test_longer_text(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100


class TestBuildProjectOverview:
    def test_basic_overview(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = _build_project_overview(store, config)
        assert "# Project Overview" in result
        assert "TestProject" in result
        assert "100" in result  # total nodes
        assert "200" in result  # total edges

    def test_with_languages(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = _build_project_overview(store, config)
        assert "php" in result.lower() or "PHP" in result

    def test_with_frameworks(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = _build_project_overview(store, config)
        assert "laravel" in result.lower() or "react" in result.lower()

    def test_fallback_name(self):
        store = _make_mock_store()
        config = _make_mock_config(name="")
        result = _build_project_overview(store, config)
        assert "Unknown Project" in result

    def test_summary_error(self):
        store = MagicMock()
        store.get_summary.side_effect = RuntimeError("DB error")
        config = _make_mock_config()
        result = _build_project_overview(store, config)
        assert "# Project Overview" in result


class TestBuildKeyFilesSection:
    def test_with_nodes(self):
        nodes = {
            "n1": MockNode(id="n1", name="Foo", qualified_name="App\\Foo"),
            "n2": MockNode(id="n2", name="Bar", qualified_name="App\\Bar"),
        }
        store = _make_mock_store(nodes=nodes)
        analyzer = _make_mock_analyzer(top_nodes=[("n1", 0.05), ("n2", 0.03)])
        result = _build_key_files_section(store, analyzer)
        assert "Key Files" in result
        assert "App\\Foo" in result
        assert "App\\Bar" in result

    def test_empty_graph(self):
        store = _make_mock_store()
        analyzer = _make_mock_analyzer(top_nodes=[])
        result = _build_key_files_section(store, analyzer)
        assert "No nodes found" in result

    def test_pagerank_error(self):
        store = _make_mock_store()
        analyzer = MagicMock()
        analyzer.pagerank.side_effect = RuntimeError("Graph error")
        result = _build_key_files_section(store, analyzer)
        assert "Could not compute" in result

    def test_missing_node(self):
        store = _make_mock_store()
        store.get_node.return_value = None
        analyzer = _make_mock_analyzer(top_nodes=[("missing", 0.1)])
        result = _build_key_files_section(store, analyzer)
        # Should not crash, just skip missing nodes
        assert "Key Files" in result


class TestBuildSearchResultsSection:
    def test_with_results(self):
        results = [
            MockNode(name="UserController", qualified_name="App\\UserController"),
            MockNode(name="UserService", qualified_name="App\\UserService"),
        ]
        store = _make_mock_store(search_results=results)
        result = _build_search_results_section(store, "user")
        assert "Relevant Symbols" in result
        assert "UserController" in result
        assert "UserService" in result

    def test_no_results(self):
        store = _make_mock_store(search_results=[])
        result = _build_search_results_section(store, "nonexistent")
        assert "No matching symbols" in result

    def test_with_docblock(self):
        node = MockNode(docblock="This is a user service that handles authentication")
        store = _make_mock_store(search_results=[node])
        result = _build_search_results_section(store, "user")
        assert "user service" in result.lower() or "authentication" in result.lower()

    def test_search_error(self):
        store = MagicMock()
        store.search_nodes.side_effect = RuntimeError("FTS error")
        result = _build_search_results_section(store, "test")
        assert "unavailable" in result.lower()


class TestBuildEntryPointsSection:
    def test_with_entries(self):
        nodes = {
            "e1": MockNode(id="e1", name="main", qualified_name="main"),
            "e2": MockNode(id="e2", name="index", qualified_name="index"),
        }
        store = _make_mock_store(nodes=nodes)
        analyzer = _make_mock_analyzer(entry_points=["e1", "e2"])
        result = _build_entry_points_section(store, analyzer)
        assert "Entry Points" in result
        assert "main" in result

    def test_no_entries(self):
        store = _make_mock_store()
        analyzer = _make_mock_analyzer(entry_points=[])
        result = _build_entry_points_section(store, analyzer)
        assert "No entry points" in result

    def test_entry_error(self):
        store = _make_mock_store()
        analyzer = MagicMock()
        analyzer.get_entry_points.side_effect = RuntimeError("Error")
        result = _build_entry_points_section(store, analyzer)
        assert "Could not detect" in result


class TestBuildPreloadContext:
    @patch("coderag.launcher.preloader._load_analyzer")
    def test_basic_context(self, mock_load):
        nodes = {"n1": MockNode()}
        store = _make_mock_store(nodes=nodes)
        config = _make_mock_config()
        analyzer = _make_mock_analyzer(top_nodes=[("n1", 0.05)], entry_points=["n1"])
        mock_load.return_value = analyzer

        result = build_preload_context(store, config)
        assert "Project Overview" in result
        assert isinstance(result, str)

    @patch("coderag.launcher.preloader._load_analyzer")
    def test_with_query(self, mock_load):
        results = [MockNode(name="Router", qualified_name="App\\Router")]
        store = _make_mock_store(search_results=results)
        config = _make_mock_config()
        analyzer = _make_mock_analyzer(top_nodes=[], entry_points=[])
        mock_load.return_value = analyzer

        result = build_preload_context(store, config, query="routing")
        assert "routing" in result.lower() or "Router" in result

    @patch("coderag.launcher.preloader._load_analyzer")
    def test_token_budget_respected(self, mock_load):
        store = _make_mock_store()
        config = _make_mock_config()
        analyzer = _make_mock_analyzer()
        mock_load.return_value = analyzer

        result = build_preload_context(store, config, token_budget=100)
        # With a tiny budget, output should be limited
        assert len(result) < 100 * 4 + 200  # Some overhead allowed

    @patch("coderag.launcher.preloader._load_analyzer")
    def test_analyzer_failure(self, mock_load):
        mock_load.side_effect = RuntimeError("Cannot load")
        store = _make_mock_store()
        config = _make_mock_config()

        result = build_preload_context(store, config)
        assert "unavailable" in result.lower()

    @patch("coderag.launcher.preloader._load_analyzer")
    def test_empty_graph(self, mock_load):
        summary = MockGraphSummary(total_nodes=0, total_edges=0)
        store = _make_mock_store(summary=summary)
        config = _make_mock_config()
        analyzer = _make_mock_analyzer()
        mock_load.return_value = analyzer

        result = build_preload_context(store, config)
        assert "Project Overview" in result
