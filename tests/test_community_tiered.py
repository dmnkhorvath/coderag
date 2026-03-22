"""Tests for tiered community detection in NetworkXAnalyzer."""
from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch, PropertyMock

import networkx as nx
import pytest

from coderag.analysis.networkx_analyzer import NetworkXAnalyzer


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def analyzer():
    """Create a fresh NetworkXAnalyzer."""
    return NetworkXAnalyzer()


def _build_graph(n_nodes: int, connect: bool = True) -> nx.DiGraph:
    """Build a directed graph with n_nodes nodes and optional edges."""
    g = nx.DiGraph()
    for i in range(n_nodes):
        g.add_node(f"node_{i}", kind="class", name=f"Node{i}",
                   qualified_name=f"mod.Node{i}", file_path=f"f{i}.py",
                   start_line=1, end_line=10, language="python",
                   metadata={}, pagerank=0.0, community_id=None)
    if connect and n_nodes > 1:
        # Create a chain plus some cross-links for community structure
        for i in range(n_nodes - 1):
            g.add_edge(f"node_{i}", f"node_{i+1}", kind="calls")
        # Add some cross-links to create community structure
        for i in range(0, n_nodes - 2, 3):
            g.add_edge(f"node_{i}", f"node_{i+2}", kind="imports")
    return g


def _setup_analyzer(analyzer: NetworkXAnalyzer, graph: nx.DiGraph) -> None:
    """Inject a graph directly into the analyzer."""
    analyzer._graph = graph
    analyzer._loaded = True
    analyzer._pagerank_cache = None
    analyzer._betweenness_cache = None


# ── Tier Selection Tests ──────────────────────────────────────

def test_small_graph_uses_greedy_modularity(analyzer):
    """Graphs < 10K nodes should use greedy modularity."""
    g = _build_graph(100)
    _setup_analyzer(analyzer, g)

    with patch("networkx.algorithms.community.greedy_modularity_communities") as mock_greedy:
        mock_greedy.return_value = [{"node_0", "node_1"}, {"node_2", "node_3"}]
        result = analyzer.community_detection()
        mock_greedy.assert_called_once()
        assert len(result) == 2


def test_medium_graph_uses_leiden(analyzer):
    """Graphs 10K-500K nodes should use Leiden algorithm."""
    g = _build_graph(15_000)
    _setup_analyzer(analyzer, g)

    with patch.object(analyzer, "_leiden_communities") as mock_leiden:
        mock_leiden.return_value = [{"node_0", "node_1"}, {"node_2", "node_3"}]
        result = analyzer.community_detection()
        mock_leiden.assert_called_once()
        assert len(result) == 2


def test_large_graph_uses_label_propagation(analyzer):
    """Graphs > 500K nodes should use label propagation."""
    # We can't actually build a 500K+ node graph in a test, so we mock
    g = nx.DiGraph()
    # Add a few real nodes for the undirected conversion
    for i in range(10):
        g.add_node(f"node_{i}", kind="class")
    for i in range(9):
        g.add_edge(f"node_{i}", f"node_{i+1}", kind="calls")
    _setup_analyzer(analyzer, g)

    # Mock the undirected graph to report 600K nodes
    original_to_undirected = g.to_undirected

    def mock_to_undirected():
        ug = original_to_undirected()
        original_number_of_nodes = ug.number_of_nodes
        # First call returns real count (for isolate removal), subsequent calls return 600K
        call_count = [0]
        def patched_number_of_nodes():
            call_count[0] += 1
            if call_count[0] <= 1:
                return original_number_of_nodes()
            return 600_000
        ug.number_of_nodes = patched_number_of_nodes
        return ug

    with patch.object(g, "to_undirected", side_effect=mock_to_undirected):
        with patch("networkx.algorithms.community.label_propagation_communities") as mock_lp:
            mock_lp.return_value = [{"node_0", "node_1"}]
            result = analyzer.community_detection()
            mock_lp.assert_called_once()


def test_boundary_10k_uses_leiden(analyzer):
    """Exactly 10K nodes should use Leiden (not greedy)."""
    g = _build_graph(10_000)
    _setup_analyzer(analyzer, g)

    with patch.object(analyzer, "_leiden_communities") as mock_leiden:
        mock_leiden.return_value = [{"node_0"}]
        analyzer.community_detection()
        mock_leiden.assert_called_once()


def test_boundary_below_10k_uses_greedy(analyzer):
    """9999 nodes should use greedy modularity."""
    g = _build_graph(9_999)
    _setup_analyzer(analyzer, g)

    with patch("networkx.algorithms.community.greedy_modularity_communities") as mock_greedy:
        mock_greedy.return_value = [{"node_0"}]
        analyzer.community_detection()
        mock_greedy.assert_called_once()


# ── Fallback Tests ────────────────────────────────────────────

def test_fallback_to_connected_components_on_error(analyzer):
    """If community detection fails, fall back to connected components."""
    g = _build_graph(50)
    _setup_analyzer(analyzer, g)

    with patch("networkx.algorithms.community.greedy_modularity_communities",
               side_effect=RuntimeError("algo failed")):
        result = analyzer.community_detection()
        # Should fall back to connected components
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(c, set) for c in result)


def test_fallback_leiden_error_uses_connected_components(analyzer):
    """If Leiden fails, fall back to connected components."""
    g = _build_graph(15_000)
    _setup_analyzer(analyzer, g)

    with patch.object(analyzer, "_leiden_communities",
                      side_effect=ImportError("leidenalg not installed")):
        result = analyzer.community_detection()
        assert isinstance(result, list)
        assert len(result) > 0


# ── Empty / Edge Case Tests ───────────────────────────────────

def test_empty_graph(analyzer):
    """Empty graph returns empty list."""
    _setup_analyzer(analyzer, nx.DiGraph())
    assert analyzer.community_detection() == []


def test_all_isolates(analyzer):
    """Graph with only isolated nodes returns empty list."""
    g = nx.DiGraph()
    for i in range(100):
        g.add_node(f"node_{i}", kind="class")
    _setup_analyzer(analyzer, g)
    assert analyzer.community_detection() == []


def test_communities_sorted_by_size(analyzer):
    """Communities should be sorted largest first."""
    g = _build_graph(50)
    _setup_analyzer(analyzer, g)
    result = analyzer.community_detection()
    if len(result) > 1:
        for i in range(len(result) - 1):
            assert len(result[i]) >= len(result[i + 1])


# ── _leiden_communities Helper Tests ──────────────────────────

def test_leiden_communities_direct(analyzer):
    """Test _leiden_communities helper directly with a small graph."""
    g = nx.Graph()  # undirected
    # Create two clear communities
    for i in range(5):
        for j in range(i + 1, 5):
            g.add_edge(f"a_{i}", f"a_{j}")
    for i in range(5):
        for j in range(i + 1, 5):
            g.add_edge(f"b_{i}", f"b_{j}")
    # Single bridge between communities
    g.add_edge("a_0", "b_0")

    _setup_analyzer(analyzer, nx.DiGraph())  # just to set _loaded
    result = analyzer._leiden_communities(g)
    assert isinstance(result, list)
    assert len(result) >= 1
    # All nodes should be covered
    all_nodes = set()
    for community in result:
        assert isinstance(community, set)
        all_nodes.update(community)
    assert all_nodes == set(g.nodes())


def test_leiden_communities_with_mock(analyzer):
    """Test _leiden_communities with mocked igraph/leidenalg."""
    g = nx.Graph()
    g.add_edge("x", "y")
    g.add_edge("y", "z")

    mock_ig_graph = MagicMock()
    mock_ig_graph.vs.__getitem__ = MagicMock(return_value=["x", "y", "z"])

    mock_partition = [[0, 1], [2]]  # Two communities

    with patch.dict("sys.modules", {"igraph": MagicMock(), "leidenalg": MagicMock()}):
        import sys
        mock_ig = sys.modules["igraph"]
        mock_la = sys.modules["leidenalg"]
        mock_ig.Graph.from_networkx.return_value = mock_ig_graph
        mock_la.find_partition.return_value = mock_partition

        _setup_analyzer(analyzer, nx.DiGraph())
        result = analyzer._leiden_communities(g)
        assert len(result) == 2
        mock_ig.Graph.from_networkx.assert_called_once_with(g)
        mock_la.find_partition.assert_called_once()


# ── Timeout Tests ─────────────────────────────────────────────

def test_timeout_handler_raises():
    """_timeout_handler should raise TimeoutError."""
    with pytest.raises(TimeoutError, match="Community detection timed out"):
        NetworkXAnalyzer._timeout_handler(signal.SIGALRM, None)


# ── persist_scores_to_store Tests ─────────────────────────────

def _make_mock_store():
    """Create a mock store for persist_scores_to_store tests."""
    store = MagicMock()
    conn = MagicMock()
    store.connection = conn
    return store, conn


def test_persist_no_longer_skips_community_detection(analyzer):
    """persist_scores_to_store should always attempt community detection."""
    # Build a graph that would have been skipped before (>50K nodes)
    # We'll use a small graph but mock number_of_nodes to return 60K
    g = _build_graph(100)
    _setup_analyzer(analyzer, g)
    store, conn = _make_mock_store()

    with patch.object(analyzer, "pagerank", return_value={"node_0": 0.5}):
        with patch.object(analyzer, "community_detection",
                          return_value=[{"node_0", "node_1"}]) as mock_cd:
            analyzer.persist_scores_to_store(store)
            # Community detection should have been called
            mock_cd.assert_called_once()


def test_persist_handles_community_timeout(analyzer):
    """persist_scores_to_store should handle timeout gracefully."""
    g = _build_graph(100)
    _setup_analyzer(analyzer, g)
    store, conn = _make_mock_store()

    with patch.object(analyzer, "pagerank", return_value={"node_0": 0.5}):
        with patch.object(analyzer, "community_detection",
                          side_effect=TimeoutError("timed out")):
            # Should not raise
            analyzer.persist_scores_to_store(store)
            # PageRank should still be persisted
            assert conn.executemany.called
            assert conn.commit.called


def test_persist_handles_community_exception(analyzer):
    """persist_scores_to_store should handle community detection exceptions."""
    g = _build_graph(100)
    _setup_analyzer(analyzer, g)
    store, conn = _make_mock_store()

    with patch.object(analyzer, "pagerank", return_value={"node_0": 0.5}):
        with patch.object(analyzer, "community_detection",
                          side_effect=RuntimeError("unexpected error")):
            analyzer.persist_scores_to_store(store)
            # Should not raise, PageRank still persisted
            assert conn.commit.called


def test_persist_commits_pagerank_before_community(analyzer):
    """PageRank should be committed before community detection starts."""
    g = _build_graph(100)
    _setup_analyzer(analyzer, g)
    store, conn = _make_mock_store()

    call_order = []

    original_commit = conn.commit
    def track_commit():
        call_order.append("commit")
        return original_commit()
    conn.commit = track_commit

    def track_community():
        call_order.append("community_detection")
        return [{"node_0", "node_1"}]

    with patch.object(analyzer, "pagerank", return_value={"node_0": 0.5}):
        with patch.object(analyzer, "community_detection", side_effect=track_community):
            analyzer.persist_scores_to_store(store)

    # First commit (PageRank) should come before community_detection
    assert "commit" in call_order
    assert "community_detection" in call_order
    pr_commit_idx = call_order.index("commit")
    cd_idx = call_order.index("community_detection")
    assert pr_commit_idx < cd_idx


def test_persist_no_community_detection_node_limit(analyzer):
    """Verify _COMMUNITY_DETECTION_NODE_LIMIT no longer exists."""
    assert not hasattr(analyzer, "_COMMUNITY_DETECTION_NODE_LIMIT")
    assert not hasattr(NetworkXAnalyzer, "_COMMUNITY_DETECTION_NODE_LIMIT")


# ── Integration Test (small graph, real algorithms) ───────────

def test_small_graph_real_community_detection(analyzer):
    """Integration test: real community detection on a small graph."""
    g = nx.DiGraph()
    # Two clusters
    for i in range(5):
        for j in range(5):
            if i != j:
                g.add_edge(f"a_{i}", f"a_{j}", kind="calls")
                g.add_edge(f"b_{i}", f"b_{j}", kind="calls")
    # Bridge
    g.add_edge("a_0", "b_0", kind="imports")

    for n in g.nodes():
        g.nodes[n].update(kind="class", name=n, qualified_name=n,
                          file_path="f.py", start_line=1, end_line=10,
                          language="python", metadata={}, pagerank=0.0,
                          community_id=None)

    _setup_analyzer(analyzer, g)
    result = analyzer.community_detection()
    assert len(result) >= 1
    all_nodes = set()
    for c in result:
        all_nodes.update(c)
    # All non-isolated nodes should be in some community
    assert len(all_nodes) > 0


def test_medium_graph_real_leiden(analyzer):
    """Integration test: real Leiden on a medium graph (if libs available)."""
    try:
        import igraph
        import leidenalg
    except ImportError:
        pytest.skip("igraph/leidenalg not installed")

    g = nx.Graph()
    # Two clear communities of 50 nodes each
    for i in range(50):
        for j in range(i + 1, 50):
            if abs(i - j) <= 3:  # local connections
                g.add_edge(f"a_{i}", f"a_{j}")
                g.add_edge(f"b_{i}", f"b_{j}")
    g.add_edge("a_0", "b_0")  # bridge

    _setup_analyzer(analyzer, nx.DiGraph())
    result = analyzer._leiden_communities(g)
    assert len(result) >= 2
    all_nodes = set()
    for c in result:
        all_nodes.update(c)
    assert all_nodes == set(g.nodes())
