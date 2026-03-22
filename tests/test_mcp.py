"""Tests for MCP tools and resources."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.mcp.resources import register_resources
from coderag.mcp.tools import (
    _format_candidates,
    _normalize_file_path,
    _resolve_symbol,
    _truncate_to_budget,
    register_tools,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_node(
    name: str,
    kind: NodeKind = NodeKind.FUNCTION,
    file_path: str = "src/app.py",
    start_line: int = 1,
    end_line: int = 10,
    language: str = "python",
    qualified_name: str | None = None,
    docblock: str | None = None,
    metadata: dict | None = None,
) -> Node:
    qn = qualified_name or f"mod.{name}"
    nid = generate_node_id(file_path, start_line, kind, name)
    return Node(
        id=nid,
        kind=kind,
        name=name,
        qualified_name=qn,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        language=language,
        docblock=docblock,
        metadata=metadata or {},
    )


def _make_edge(
    source_id: str,
    target_id: str,
    kind: EdgeKind = EdgeKind.CALLS,
    confidence: float = 1.0,
    metadata: dict | None = None,
) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        confidence=confidence,
        metadata=metadata or {},
    )


class FakeMCP:
    """Fake FastMCP server that captures registered tools and resources."""

    def __init__(self):
        self.tools: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}

    def tool(self, name: str = "", description: str = "", **kwargs):
        def decorator(fn):
            self.tools[name] = fn
            return fn

        return decorator

    def resource(self, uri: str, name: str = "", description: str = "", **kwargs):
        def decorator(fn):
            self.resources[uri] = fn
            return fn

        return decorator


# ═══════════════════════════════════════════════════════════════════════
# Helper function tests
# ═══════════════════════════════════════════════════════════════════════


class TestTruncateToBudget:
    def test_short_text_unchanged(self):
        text = "Hello world"
        result = _truncate_to_budget(text, 10000)
        assert result == text

    def test_long_text_truncated(self):
        text = "x " * 50000
        result = _truncate_to_budget(text, 100)
        assert len(result) < len(text)
        assert "truncated" in result.lower() or len(result) < len(text)

    def test_exact_budget_unchanged(self):
        text = "short"
        result = _truncate_to_budget(text, 100000)
        assert result == text


class TestResolveSymbol:
    def test_exact_qualified_name_match(self):
        node = _make_node("UserService", qualified_name="App.Services.UserService")
        store = MagicMock()
        store.get_node_by_qualified_name.return_value = node

        result_node, candidates = _resolve_symbol("App.Services.UserService", store)
        assert result_node is node
        assert candidates == []
        store.get_node_by_qualified_name.assert_called_once_with("App.Services.UserService")

    def test_fallback_to_search_single_result(self):
        node = _make_node("UserService", qualified_name="App.Services.UserService")
        store = MagicMock()
        store.get_node_by_qualified_name.return_value = None
        store.search_nodes.return_value = [node]

        result_node, candidates = _resolve_symbol("UserService", store)
        assert result_node is node
        assert candidates == []

    def test_fallback_to_search_multiple_results(self):
        node1 = _make_node("UserSvc", qualified_name="App.UserSvc")
        node2 = _make_node("UserHelper", qualified_name="App.UserHelper")
        store = MagicMock()
        store.get_node_by_qualified_name.return_value = None
        store.search_nodes.return_value = [node1, node2]

        result_node, candidates = _resolve_symbol("User", store)
        assert result_node is node1
        assert node2 in candidates

    def test_no_match_returns_none(self):
        store = MagicMock()
        store.get_node_by_qualified_name.return_value = None
        store.search_nodes.return_value = []

        result_node, candidates = _resolve_symbol("NonExistent", store)
        assert result_node is None
        assert candidates == []


class TestFormatCandidates:
    def test_formats_candidates_list(self):
        nodes = [
            _make_node("func1", NodeKind.FUNCTION, qualified_name="mod.func1"),
            _make_node("ClassA", NodeKind.CLASS, qualified_name="mod.ClassA"),
        ]
        result = _format_candidates(nodes, "something")
        assert "something" in result
        assert "mod.func1" in result
        assert "mod.ClassA" in result

    def test_empty_candidates(self):
        result = _format_candidates([], "missing")
        assert "missing" in result


class TestNormalizeFilePath:
    def test_exact_match(self):
        store = MagicMock()
        store.find_nodes.return_value = [_make_node("f")]
        result = _normalize_file_path("src/app.py", store)
        assert result == "src/app.py"

    def test_strips_leading_slash(self):
        store = MagicMock()
        store.find_nodes.side_effect = [[], [_make_node("f")]]
        result = _normalize_file_path("/src/app.py", store)
        assert result == "src/app.py"

    def test_not_found_returns_none(self):
        store = MagicMock()
        store.find_nodes.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        store.connection = mock_conn
        result = _normalize_file_path("nonexistent.py", store)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# Tool registration tests
# ═══════════════════════════════════════════════════════════════════════


class TestRegisterTools:
    @patch("coderag.output.context.ContextAssembler")
    @patch("coderag.output.markdown.MarkdownFormatter")
    def test_registers_all_8_tools(self, mock_fmt_cls, mock_asm_cls):
        mcp = FakeMCP()
        store = MagicMock()
        analyzer = MagicMock()
        register_tools(mcp, store, analyzer)
        expected_tools = [
            "coderag_lookup_symbol",
            "coderag_find_usages",
            "coderag_impact_analysis",
            "coderag_file_context",
            "coderag_find_routes",
            "coderag_search",
            "coderag_architecture",
            "coderag_dependency_graph",
        ]
        for tool_name in expected_tools:
            assert tool_name in mcp.tools, f"Tool {tool_name} not registered"


# ═══════════════════════════════════════════════════════════════════════
# Tool function tests - using patched assembler/formatter
# ═══════════════════════════════════════════════════════════════════════


class TestLookupSymbol:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_lookup_symbol"]

    def test_symbol_not_found_returns_assembler_output(self):
        # The tool delegates entirely to assembler.assemble_for_symbol
        mock_result = MagicMock()
        mock_result.text = "Symbol `NonExistent` not found in the knowledge graph."
        self.mock_assembler.assemble_for_symbol.return_value = mock_result
        result = self.tool(symbol="NonExistent")
        assert "not found" in result.lower()
        self.mock_assembler.assemble_for_symbol.assert_called_once()

    def test_symbol_found_returns_context(self):
        node = _make_node("UserService", qualified_name="App.UserService")
        self.store.get_node_by_qualified_name.return_value = node
        mock_result = MagicMock()
        mock_result.text = "## UserService\nA service class"
        self.mock_assembler.assemble_for_symbol.return_value = mock_result
        result = self.tool(symbol="App.UserService")
        assert "UserService" in result

    def test_exception_returns_error(self):
        self.mock_assembler.assemble_for_symbol.side_effect = RuntimeError("DB error")
        result = self.tool(symbol="anything")
        assert "error" in result.lower()
        assert "DB error" in result


class TestFindUsages:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_find_usages"]

    def test_symbol_not_found(self):
        self.store.get_node_by_qualified_name.return_value = None
        self.store.search_nodes.return_value = []
        result = self.tool(symbol="Missing")
        assert "not found" in result.lower() or "no" in result.lower()

    def test_usages_found(self):
        target = _make_node("UserService", NodeKind.CLASS, qualified_name="App.UserService")
        caller = _make_node("main", NodeKind.FUNCTION, qualified_name="mod.main", start_line=20)
        edge = _make_edge(caller.id, target.id, EdgeKind.CALLS)

        self.store.get_node_by_qualified_name.return_value = target
        self.store.get_edges.return_value = [edge]
        self.store.get_node.return_value = caller

        result = self.tool(symbol="App.UserService")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.get_node_by_qualified_name.side_effect = RuntimeError("fail")
        result = self.tool(symbol="x")
        assert "error" in result.lower()


class TestImpactAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_impact_analysis"]

    def test_impact_analysis_success(self):
        mock_result = MagicMock()
        mock_result.text = "## Impact Analysis\n5 affected nodes"
        self.mock_assembler.assemble_impact_analysis.return_value = mock_result
        result = self.tool(symbol="App.UserService")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.mock_assembler.assemble_impact_analysis.side_effect = RuntimeError("fail")
        result = self.tool(symbol="x")
        assert "error" in result.lower()


class TestFileContext:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_file_context"]

    def test_file_not_found(self):
        self.store.find_nodes.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        self.store.connection = mock_conn
        result = self.tool(file_path="nonexistent.py")
        assert "not found" in result.lower() or "no" in result.lower()

    def test_file_found(self):
        self.store.find_nodes.return_value = [_make_node("f")]
        mock_result = MagicMock()
        mock_result.text = "## File Context\nsrc/app.py"
        self.mock_assembler.assemble_for_file.return_value = mock_result
        result = self.tool(file_path="src/app.py")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.find_nodes.side_effect = RuntimeError("fail")
        result = self.tool(file_path="x.py")
        assert "error" in result.lower()


class TestFindRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_find_routes"]

    def test_no_routes_found(self):
        self.store.find_nodes.return_value = []
        result = self.tool(pattern="/api/*")
        assert "no routes" in result.lower() or "not found" in result.lower() or "0" in result

    def test_routes_matched(self):
        route = _make_node(
            "/api/users",
            NodeKind.ROUTE,
            qualified_name="GET /api/users",
            metadata={"http_method": "GET", "url": "/api/users", "controller": "UserCtrl", "action": "index"},
        )
        self.store.find_nodes.return_value = [route]
        self.store.get_edges.return_value = []
        result = self.tool(pattern="/api/*")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.find_nodes.side_effect = RuntimeError("fail")
        result = self.tool(pattern="*")
        assert "error" in result.lower()


class TestSearch:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.store._db_path = "/tmp/test.db"
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_search"]

    def test_no_results(self):
        self.store.search_nodes.return_value = []
        result = self.tool(query="nonexistent")
        assert "no results" in result.lower() or "no " in result.lower()

    def test_fts_search_results(self):
        node = _make_node("UserService", NodeKind.CLASS, qualified_name="App.UserService", language="php")
        self.store.search_nodes.return_value = [node]
        result = self.tool(query="UserService")
        assert "UserService" in result

    def test_search_with_language_filter(self):
        node = _make_node("func", language="php")
        self.store.search_nodes.return_value = [node]
        result = self.tool(query="func", language="php")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.search_nodes.side_effect = RuntimeError("fail")
        result = self.tool(query="x")
        assert "error" in result.lower()


class TestArchitecture:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_architecture"]

    def test_architecture_full(self):
        node = _make_node("UserService", NodeKind.CLASS, qualified_name="App.UserService")
        self.store.get_communities.return_value = [(0, [node])]
        self.store.get_top_nodes_by_pagerank.return_value = [(node, 0.15)]
        self.store.get_entry_points.return_value = [node]
        self.mock_formatter.format_architecture_overview.return_value = "## Architecture\nOverview"
        result = self.tool()
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.get_communities.side_effect = RuntimeError("fail")
        result = self.tool()
        assert "error" in result.lower()


class TestDependencyGraph:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_assembler = MagicMock()
        self.mock_formatter = MagicMock()
        with (
            patch("coderag.output.context.ContextAssembler", return_value=self.mock_assembler),
            patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter),
        ):
            register_tools(self.mcp, self.store, self.analyzer)
        self.tool = self.mcp.tools["coderag_dependency_graph"]

    def test_target_not_found(self):
        self.store.get_node_by_qualified_name.return_value = None
        self.store.search_nodes.return_value = []
        self.store.find_nodes.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        self.store.connection = mock_conn
        result = self.tool(target="NonExistent")
        assert "not found" in result.lower() or "no" in result.lower()

    def test_target_found_with_deps(self):
        node = _make_node("UserService", NodeKind.CLASS, qualified_name="App.UserService")
        dep = _make_node("Database", NodeKind.CLASS, qualified_name="App.Database", start_line=20)
        edge = _make_edge(node.id, dep.id, EdgeKind.CALLS)

        self.store.get_node_by_qualified_name.return_value = node
        self.store.get_neighbors.return_value = [(dep, edge, 1)]

        result = self.tool(target="App.UserService")
        assert isinstance(result, str)

    def test_exception_returns_error(self):
        self.store.get_node_by_qualified_name.side_effect = RuntimeError("fail")
        result = self.tool(target="x")
        assert "error" in result.lower()


# ═══════════════════════════════════════════════════════════════════════
# Resource tests
# ═══════════════════════════════════════════════════════════════════════


class TestRegisterResources:
    @patch("coderag.output.markdown.MarkdownFormatter")
    def test_registers_all_3_resources(self, mock_fmt_cls):
        mcp = FakeMCP()
        store = MagicMock()
        analyzer = MagicMock()
        register_resources(mcp, store, analyzer)
        expected = [
            "coderag://summary",
            "coderag://architecture",
            "coderag://file-map",
        ]
        for uri in expected:
            assert uri in mcp.resources, f"Resource {uri} not registered"


class TestSummaryResource:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_formatter = MagicMock()
        with patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter):
            register_resources(self.mcp, self.store, self.analyzer)
        self.resource = self.mcp.resources["coderag://summary"]

    def test_summary_returns_markdown(self):
        mock_summary = MagicMock()
        mock_summary.project_name = "TestProject"
        mock_summary.project_root = "/tmp/test"
        mock_summary.db_path = "/tmp/test/.coderag/graph.db"
        mock_summary.db_size_bytes = 1048576  # 1 MB - real number!
        mock_summary.last_parsed = "2024-01-01"
        mock_summary.total_nodes = 100
        mock_summary.total_edges = 200
        mock_summary.communities = 5
        mock_summary.avg_confidence = 0.95
        mock_summary.files_by_language = {"python": 20}
        mock_summary.nodes_by_kind = {"class": 10, "function": 50}
        mock_summary.edges_by_kind = {"calls": 100}
        mock_summary.frameworks = ["Django"]
        mock_summary.top_nodes_by_pagerank = [("Main", "mod.Main", 0.15)]
        self.store.get_summary.return_value = mock_summary
        result = self.resource()
        assert "TestProject" in result
        assert "100" in result

    def test_summary_exception(self):
        self.store.get_summary.side_effect = RuntimeError("fail")
        result = self.resource()
        assert "error" in result.lower()

    def test_summary_no_frameworks(self):
        mock_summary = MagicMock()
        mock_summary.project_name = "NoFW"
        mock_summary.project_root = "/tmp/test"
        mock_summary.db_path = "/tmp/test/graph.db"
        mock_summary.db_size_bytes = 512000
        mock_summary.last_parsed = None
        mock_summary.total_nodes = 10
        mock_summary.total_edges = 5
        mock_summary.communities = 1
        mock_summary.avg_confidence = 0.8
        mock_summary.files_by_language = {}
        mock_summary.nodes_by_kind = {}
        mock_summary.edges_by_kind = {}
        mock_summary.frameworks = []
        mock_summary.top_nodes_by_pagerank = []
        self.store.get_summary.return_value = mock_summary
        result = self.resource()
        assert "NoFW" in result


class TestArchitectureResource:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_formatter = MagicMock()
        with patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter):
            register_resources(self.mcp, self.store, self.analyzer)
        self.resource = self.mcp.resources["coderag://architecture"]

    def test_architecture_exception(self):
        self.store.get_communities.side_effect = RuntimeError("fail")
        result = self.resource()
        assert "error" in result.lower()


class TestFileMapResource:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mcp = FakeMCP()
        self.store = MagicMock()
        self.analyzer = MagicMock()
        self.mock_formatter = MagicMock()
        with patch("coderag.output.markdown.MarkdownFormatter", return_value=self.mock_formatter):
            register_resources(self.mcp, self.store, self.analyzer)
        self.resource = self.mcp.resources["coderag://file-map"]

    def test_file_map_returns_markdown(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("src/app.py", "python", 5, "class,function"),
            ("src/utils.py", "python", 3, "function"),
        ]
        self.store.connection = mock_conn
        result = self.resource()
        assert isinstance(result, str)

    def test_file_map_exception(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("fail")
        self.store.connection = mock_conn
        result = self.resource()
        assert "error" in result.lower()
