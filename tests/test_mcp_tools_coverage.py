from unittest.mock import MagicMock, patch

import pytest

from coderag.core.models import Edge, EdgeKind, Node, NodeKind
from coderag.mcp.tools import (
    DependencyDirection,
    _normalize_file_path,
    _resolve_symbol,
    _truncate_to_budget,
    register_tools,
)


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    mcp.tools = {}

    def tool_decorator(name=None, description=None):
        def decorator(func):
            tool_name = name or func.__name__
            mcp.tools[tool_name] = func
            return func

        return decorator

    mcp.tool = tool_decorator
    return mcp


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def mock_analyzer():
    return MagicMock()


# 1. _truncate_to_budget
def test_truncate_to_budget_truncates():
    text = "a" * 1000
    budget = 100
    result = _truncate_to_budget(text, budget)
    assert len(result) < 1000
    assert "... (truncated" in result


def test_truncate_to_budget_exact_chars():
    text = "a" * 350
    budget = 100
    result = _truncate_to_budget(text, budget)
    assert result == text


def test_truncate_to_budget_line_98():
    with patch("coderag.mcp.tools.estimate_tokens", return_value=100):
        text = "a" * 100
        budget = 50
        result = _truncate_to_budget(text, budget)
        assert result == text


# 2. _resolve_symbol
def test_resolve_symbol(mock_store):
    mock_store.get_node_by_qualified_name.return_value = Node(
        id="1",
        kind=NodeKind.CLASS,
        name="exact",
        qualified_name="exact",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    node, candidates = _resolve_symbol("exact", mock_store)
    assert node.name == "exact"
    assert candidates == []

    mock_store.get_node_by_qualified_name.return_value = None
    mock_store.search_nodes.return_value = [
        Node(
            id="2",
            kind=NodeKind.CLASS,
            name="search_exact",
            qualified_name="search_exact",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        )
    ]
    node, candidates = _resolve_symbol("search_exact", mock_store)
    assert node.name == "search_exact"
    assert candidates == []

    mock_store.search_nodes.return_value = [
        Node(
            id="3",
            kind=NodeKind.CLASS,
            name="other1",
            qualified_name="other1",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Node(
            id="4",
            kind=NodeKind.CLASS,
            name="other2",
            qualified_name="other2",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
    ]
    node, candidates = _resolve_symbol("search_best", mock_store)
    assert node.name == "other1"
    assert len(candidates) == 1
    assert candidates[0].name == "other2"

    mock_store.search_nodes.return_value = []
    node, candidates = _resolve_symbol("none", mock_store)
    assert node is None
    assert candidates == []


# 3. _normalize_file_path
def test_normalize_file_path_exact(mock_store):
    mock_store.find_nodes.return_value = [
        Node(
            id="1",
            kind=NodeKind.FILE,
            name="exact.py",
            qualified_name="exact.py",
            file_path="exact.py",
            start_line=1,
            end_line=2,
            language="python",
        )
    ]
    assert _normalize_file_path("exact.py", mock_store) == "exact.py"


def test_normalize_file_path_stripped(mock_store):
    mock_store.find_nodes.side_effect = [
        [],
        [
            Node(
                id="1",
                kind=NodeKind.FILE,
                name="stripped.py",
                qualified_name="stripped.py",
                file_path="stripped.py",
                start_line=1,
                end_line=2,
                language="python",
            )
        ],
    ]
    assert _normalize_file_path("/stripped.py", mock_store) == "stripped.py"


def test_normalize_file_path_none(mock_store):
    mock_store.find_nodes.return_value = []
    mock_store.connection.execute.return_value.fetchone.return_value = None
    assert _normalize_file_path("none.py", mock_store) is None


# 4. coderag_lookup_symbol
def test_lookup_symbol(mock_mcp, mock_store, mock_analyzer):
    with patch("coderag.output.context.ContextAssembler") as mock_assembler:
        mock_assembler_instance = MagicMock()
        mock_assembler.return_value = mock_assembler_instance
        mock_assembler_instance.assemble_for_symbol.return_value = MagicMock(text="result")

        register_tools(mock_mcp, mock_store, mock_analyzer)
        lookup = mock_mcp.tools["coderag_lookup_symbol"]

        assert lookup("symbol") == "result"

        mock_assembler_instance.assemble_for_symbol.side_effect = Exception("test error")
        assert "Error looking up symbol" in lookup("symbol")


# 5. coderag_find_usages
def test_find_usages_exception(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    find_usages = mock_mcp.tools["coderag_find_usages"]

    with patch("coderag.mcp.tools._resolve_symbol", side_effect=Exception("test error")):
        assert "Error finding usages" in find_usages("symbol")


def test_find_usages_candidates(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    find_usages = mock_mcp.tools["coderag_find_usages"]

    with patch("coderag.mcp.tools._resolve_symbol") as mock_resolve:
        mock_resolve.return_value = (
            None,
            [
                Node(
                    id="1",
                    kind=NodeKind.CLASS,
                    name="A",
                    qualified_name="A",
                    file_path="a.py",
                    start_line=1,
                    end_line=2,
                    language="python",
                )
            ],
        )
        result = find_usages("ambiguous")
        assert "Did you mean one of these?" in result


# 6. coderag_impact_analysis
def test_impact_analysis(mock_mcp, mock_store, mock_analyzer):
    with patch("coderag.output.context.ContextAssembler") as mock_assembler:
        mock_assembler_instance = MagicMock()
        mock_assembler.return_value = mock_assembler_instance
        mock_assembler_instance.assemble_impact_analysis.return_value = MagicMock(text="impact result")

        register_tools(mock_mcp, mock_store, mock_analyzer)
        impact = mock_mcp.tools["coderag_impact_analysis"]

        assert impact("symbol") == "impact result"

        mock_assembler_instance.assemble_impact_analysis.side_effect = Exception("test error")
        assert "Error analyzing impact" in impact("symbol")


# 7. coderag_file_context
def test_file_context(mock_mcp, mock_store, mock_analyzer):
    with (
        patch("coderag.mcp.tools._normalize_file_path", return_value="file.py"),
        patch("coderag.output.context.ContextAssembler") as mock_assembler,
    ):
        mock_assembler_instance = MagicMock()
        mock_assembler.return_value = mock_assembler_instance
        mock_assembler_instance.assemble_for_file.return_value = MagicMock(text="file result")

        register_tools(mock_mcp, mock_store, mock_analyzer)
        file_context = mock_mcp.tools["coderag_file_context"]

        assert file_context("file.py") == "file result"

        mock_assembler_instance.assemble_for_file.side_effect = Exception("test error")
        assert "Error getting context" in file_context("file.py")


def test_file_context_similar_files(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    file_context = mock_mcp.tools["coderag_file_context"]

    with patch("coderag.mcp.tools._normalize_file_path", return_value=None):
        mock_store.connection.execute.return_value.fetchall.return_value = [("file1.py",), ("file2.py",)]
        result = file_context("file.py")
        assert "Similar files:" in result
        assert "- `file1.py`" in result


# 8. coderag_find_routes
def test_find_routes_coverage(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    find_routes = mock_mcp.tools["coderag_find_routes"]

    mock_store.find_nodes.return_value = []
    assert "No routes found in the knowledge graph" in find_routes("/api")

    mock_store.find_nodes.side_effect = Exception("test error")
    assert "Error finding routes" in find_routes("/api")


def test_find_routes_controller_action(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    find_routes = mock_mcp.tools["coderag_find_routes"]

    node = Node(
        id="1",
        kind=NodeKind.ROUTE,
        name="/api",
        qualified_name="/api",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
        metadata={"http_method": "GET", "path": "/api", "controller": "MyController", "action": "myAction"},
    )
    mock_store.find_nodes.return_value = [node]
    mock_store.get_edges.return_value = []

    result = find_routes("/api")
    assert "- **Controller**: `MyController`" in result
    assert "- **Action**: `myAction`" in result


# 9. coderag_search
def test_search_coverage(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    search = mock_mcp.tools["coderag_search"]

    with patch.dict("sys.modules", {"coderag.search": None}):
        mock_store.search_nodes.return_value = []
        assert "No results found" in search("query", mode="semantic")

    import coderag.search

    coderag.search.SEMANTIC_AVAILABLE = True
    with (
        patch("coderag.search.vector_store.VectorStore") as mock_vs,
        patch("coderag.search.embedder.CodeEmbedder"),
        patch("coderag.search.hybrid.HybridSearcher") as mock_hybrid,
    ):
        mock_vs.exists.return_value = True
        mock_hybrid_instance = MagicMock()
        mock_hybrid.return_value = mock_hybrid_instance

        class MockResult:
            def __init__(self, lang):
                self.qualified_name = "name"
                self.name = "name"
                self.kind = "class"
                self.language = lang
                self.file_path = "file"
                self.score = 0.9
                self.match_type = "hybrid"
                self.vector_similarity = 0.9

        mock_hybrid_instance.search.return_value = [MockResult("python"), MockResult("javascript")]

        result = search("query", mode="hybrid", language="python")
        assert "python" in result
        assert "javascript" not in result

        result = search("query", mode="hybrid", language="ruby")
        assert "No results found" in result

    mock_store.search_nodes.return_value = [
        Node(
            id="1",
            kind=NodeKind.CLASS,
            name="A",
            qualified_name="A",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        )
    ]
    result = search("query", mode="fts", language="python")
    assert "A" in result

    result = search("query", mode="fts", language="ruby")
    assert "No results found" in result

    mock_store.search_nodes.side_effect = Exception("test error")
    assert "Error searching" in search("query", mode="fts")


# 10. coderag_architecture
def test_architecture_coverage(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    architecture = mock_mcp.tools["coderag_architecture"]

    mock_store.get_communities.side_effect = Exception("test error")
    assert "Error generating architecture" in architecture()


def test_architecture_none_nodes(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    architecture = mock_mcp.tools["coderag_architecture"]

    mock_store.get_communities.return_value = []
    mock_store.get_top_nodes_by_pagerank.return_value = []
    mock_store.get_entry_points.return_value = []
    result = architecture()
    assert "## Architecture Overview" in result


# 11. coderag_dependency_graph
def test_dependency_graph_coverage(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    dependency_graph = mock_mcp.tools["coderag_dependency_graph"]

    # Candidates formatting
    candidates = [
        Node(
            id="1",
            kind=NodeKind.CLASS,
            name="A",
            qualified_name="A",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Node(
            id="2",
            kind=NodeKind.CLASS,
            name="B",
            qualified_name="B",
            file_path="b.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
    ]
    with patch("coderag.mcp.tools._resolve_symbol", return_value=(None, candidates)):
        with patch("coderag.mcp.tools._normalize_file_path", return_value=None):
            assert "Did you mean one of these?" in dependency_graph("ambiguous")

    # Dependencies and dependents logic
    node1 = Node(
        id="1",
        kind=NodeKind.CLASS,
        name="A",
        qualified_name="A",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    node2 = Node(
        id="2",
        kind=NodeKind.CLASS,
        name="B",
        qualified_name="B",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )

    mock_store.get_node_by_qualified_name.return_value = node1
    mock_store.get_neighbors.side_effect = lambda *args, **kwargs: (
        [(node2, Edge(source_id="1", target_id="2", kind=EdgeKind.CALLS), 1)]
        if kwargs.get("direction") == "outgoing"
        else [(node2, Edge(source_id="2", target_id="1", kind=EdgeKind.CALLS), 1)]
    )

    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "What `A` depends on:" in result
    assert "What depends on `A`:" in result

    # Empty dependencies
    mock_store.get_neighbors.side_effect = None
    mock_store.get_neighbors.return_value = []
    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "No dependencies found." in result
    assert "No dependents found." in result

    # Exception handling
    mock_store.get_neighbors.side_effect = Exception("DB Error")
    result = dependency_graph("A")
    assert "Error building dependency graph" in result

    # Candidates formatting
    candidates = [
        Node(
            id="1",
            kind=NodeKind.CLASS,
            name="A",
            qualified_name="A",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Node(
            id="2",
            kind=NodeKind.CLASS,
            name="B",
            qualified_name="B",
            file_path="b.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
    ]
    with patch("coderag.mcp.tools._resolve_symbol", return_value=(None, candidates)):
        with patch("coderag.mcp.tools._normalize_file_path", return_value=None):
            assert "Did you mean one of these?" in dependency_graph("ambiguous")

    # Dependencies and dependents logic
    node1 = Node(
        id="1",
        kind=NodeKind.CLASS,
        name="A",
        qualified_name="A",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    node2 = Node(
        id="2",
        kind=NodeKind.CLASS,
        name="B",
        qualified_name="B",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )

    mock_store.get_node_by_qualified_name.return_value = node1
    mock_store.get_neighbors.side_effect = lambda *args, **kwargs: (
        [(node2, Edge(source_id="1", target_id="2", kind=EdgeKind.CALLS), 1)]
        if kwargs.get("direction") == "outgoing"
        else [(node2, Edge(source_id="2", target_id="1", kind=EdgeKind.CALLS), 1)]
    )

    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "What `A` depends on:" in result
    assert "What depends on `A`:" in result

    # Empty dependencies
    mock_store.get_neighbors.side_effect = None
    mock_store.get_neighbors.return_value = []
    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "No dependencies found." in result
    assert "No dependents found." in result

    # Exception handling
    mock_store.get_neighbors.side_effect = Exception("DB Error")
    result = dependency_graph("A")
    assert "Error building dependency graph" in result

    # Candidates formatting
    mock_store.get_neighbors.side_effect = None
    mock_store.get_neighbors.return_value = []
    candidates_list = [
        Node(
            id="1",
            kind=NodeKind.CLASS,
            name="A",
            qualified_name="A",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Node(
            id="2",
            kind=NodeKind.CLASS,
            name="B",
            qualified_name="B",
            file_path="b.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
    ]
    with (
        patch("coderag.mcp.tools._resolve_symbol", return_value=(None, candidates_list)),
        patch("coderag.mcp.tools._normalize_file_path", return_value=None),
    ):
        assert "Did you mean one of these?" in dependency_graph("ambiguous")

    # Dependencies and dependents logic
    node1 = Node(
        id="1",
        kind=NodeKind.CLASS,
        name="A",
        qualified_name="A",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    node2 = Node(
        id="2",
        kind=NodeKind.CLASS,
        name="B",
        qualified_name="B",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )

    mock_store.get_node_by_qualified_name.return_value = node1
    mock_store.get_neighbors.side_effect = lambda *args, **kwargs: (
        [(node2, Edge(source_id="1", target_id="2", kind=EdgeKind.CALLS), 1)]
        if kwargs.get("direction") == "outgoing"
        else [(node2, Edge(source_id="2", target_id="1", kind=EdgeKind.CALLS), 1)]
    )

    result = dependency_graph("A", direction=DependencyDirection.dependencies)
    assert "What `A` depends on:" in result

    result = dependency_graph("A", direction=DependencyDirection.dependents)
    assert "What depends on `A`:" in result

    # Exception
    mock_store.get_node_by_qualified_name.side_effect = Exception("test error")
    assert "Error building dependency graph" in dependency_graph("A")


def test_dependency_graph_not_found_no_candidates(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    dependency_graph = mock_mcp.tools["coderag_dependency_graph"]

    mock_store.get_node_by_qualified_name.return_value = None
    mock_store.search_nodes.return_value = []

    with patch("coderag.mcp.tools._normalize_file_path", return_value=None):
        result = dependency_graph("missing")
        assert "Target `missing` not found" in result


def test_dependency_graph_coverage_extended(mock_mcp, mock_store, mock_analyzer):
    register_tools(mock_mcp, mock_store, mock_analyzer)
    dependency_graph = mock_mcp.tools["coderag_dependency_graph"]

    # Candidates formatting
    candidates = [
        Node(
            id="1",
            kind=NodeKind.CLASS,
            name="A",
            qualified_name="A",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Node(
            id="2",
            kind=NodeKind.CLASS,
            name="B",
            qualified_name="B",
            file_path="b.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
    ]
    with patch("coderag.mcp.tools._resolve_symbol", return_value=(None, candidates)):
        with patch("coderag.mcp.tools._normalize_file_path", return_value=None):
            assert "Did you mean one of these?" in dependency_graph("ambiguous")

    # Dependencies and dependents logic
    node1 = Node(
        id="1",
        kind=NodeKind.CLASS,
        name="A",
        qualified_name="A",
        file_path="a.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    node2 = Node(
        id="2",
        kind=NodeKind.CLASS,
        name="B",
        qualified_name="B",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )

    mock_store.get_node_by_qualified_name.return_value = node1
    mock_store.get_neighbors.side_effect = lambda *args, **kwargs: (
        [(node2, Edge(source_id="1", target_id="2", kind=EdgeKind.CALLS), 1)]
        if kwargs.get("direction") == "outgoing"
        else [(node2, Edge(source_id="2", target_id="1", kind=EdgeKind.CALLS), 1)]
    )

    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "What `A` depends on:" in result
    assert "What depends on `A`:" in result

    # Empty dependencies
    mock_store.get_neighbors.side_effect = [[], []]
    result = dependency_graph("A", direction=DependencyDirection.both)
    assert "No dependencies found." in result
    assert "No dependents found." in result

    # Exception handling
    mock_store.get_neighbors.side_effect = Exception("DB Error")
    result = dependency_graph("A")
    assert "Error building dependency graph" in result
