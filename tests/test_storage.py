"""Tests for coderag.storage.sqlite_store."""

import os
import tempfile

import pytest

from coderag.core.models import Edge, EdgeKind, Node, NodeKind
from coderag.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store():
    """Create a temporary SQLite store."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SQLiteStore(path)
    s.initialize()
    yield s
    s.close()
    os.unlink(path)


@pytest.fixture
def populated_store(store):
    """Store with sample nodes and edges."""
    nodes = [
        Node(
            id="file1",
            kind=NodeKind.FILE,
            name="User.php",
            qualified_name="app/User.php",
            file_path="/tmp/app/User.php",
            start_line=1,
            end_line=20,
            language="php",
        ),
        Node(
            id="class1",
            kind=NodeKind.CLASS,
            name="User",
            qualified_name="App\\User",
            file_path="/tmp/app/User.php",
            start_line=3,
            end_line=18,
            language="php",
        ),
        Node(
            id="method1",
            kind=NodeKind.METHOD,
            name="getName",
            qualified_name="App\\User::getName",
            file_path="/tmp/app/User.php",
            start_line=5,
            end_line=7,
            language="php",
        ),
        Node(
            id="method2",
            kind=NodeKind.METHOD,
            name="getEmail",
            qualified_name="App\\User::getEmail",
            file_path="/tmp/app/User.php",
            start_line=9,
            end_line=11,
            language="php",
        ),
        Node(
            id="file2",
            kind=NodeKind.FILE,
            name="UserService.php",
            qualified_name="app/UserService.php",
            file_path="/tmp/app/UserService.php",
            start_line=1,
            end_line=15,
            language="php",
        ),
        Node(
            id="class2",
            kind=NodeKind.CLASS,
            name="UserService",
            qualified_name="App\\UserService",
            file_path="/tmp/app/UserService.php",
            start_line=3,
            end_line=13,
            language="php",
        ),
        Node(
            id="method3",
            kind=NodeKind.METHOD,
            name="getUser",
            qualified_name="App\\UserService::getUser",
            file_path="/tmp/app/UserService.php",
            start_line=5,
            end_line=7,
            language="php",
        ),
    ]
    edges = [
        Edge(source_id="file1", target_id="class1", kind=EdgeKind.CONTAINS),
        Edge(source_id="class1", target_id="method1", kind=EdgeKind.CONTAINS),
        Edge(source_id="class1", target_id="method2", kind=EdgeKind.CONTAINS),
        Edge(source_id="file2", target_id="class2", kind=EdgeKind.CONTAINS),
        Edge(source_id="class2", target_id="method3", kind=EdgeKind.CONTAINS),
        Edge(source_id="method3", target_id="class1", kind=EdgeKind.CALLS, confidence=0.9),
        Edge(source_id="class2", target_id="class1", kind=EdgeKind.IMPORTS),
    ]
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)
    return store


class TestSQLiteStoreInit:
    def test_initialize_creates_tables(self, store):
        conn = store.connection
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "nodes" in tables
        assert "edges" in tables

    def test_wal_mode_enabled(self, store):
        mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


class TestNodeOperations:
    def test_upsert_and_get_node(self, store):
        node = Node(
            id="n1",
            kind=NodeKind.CLASS,
            name="Foo",
            qualified_name="App\\Foo",
            file_path="/tmp/Foo.php",
            start_line=1,
            end_line=10,
            language="php",
        )
        store.upsert_nodes([node])
        result = store.get_node("n1")
        assert result is not None
        assert result.name == "Foo"
        assert result.kind == NodeKind.CLASS

    def test_get_nonexistent_node(self, store):
        result = store.get_node("nonexistent")
        assert result is None

    def test_upsert_updates_existing(self, store):
        node1 = Node(
            id="n1",
            kind=NodeKind.CLASS,
            name="Foo",
            qualified_name="App\\Foo",
            file_path="/tmp/Foo.php",
            start_line=1,
            end_line=10,
            language="php",
        )
        store.upsert_nodes([node1])
        node2 = Node(
            id="n1",
            kind=NodeKind.CLASS,
            name="FooUpdated",
            qualified_name="App\\FooUpdated",
            file_path="/tmp/Foo.php",
            start_line=1,
            end_line=20,
            language="php",
        )
        store.upsert_nodes([node2])
        result = store.get_node("n1")
        assert result.name == "FooUpdated"
        assert result.end_line == 20

    def test_find_nodes_by_kind(self, populated_store):
        classes = populated_store.find_nodes(kind=NodeKind.CLASS)
        assert len(classes) == 2
        names = {n.name for n in classes}
        assert "User" in names
        assert "UserService" in names

    def test_find_nodes_by_file_path(self, populated_store):
        nodes = populated_store.find_nodes(file_path="/tmp/app/User.php")
        assert len(nodes) >= 1

    def test_search_nodes(self, populated_store):
        results = populated_store.search_nodes("User", limit=10)
        assert len(results) >= 1
        names = [n.name for n in results]
        assert any("User" in name for name in names)

    def test_get_node_by_qualified_name(self, populated_store):
        node = populated_store.get_node_by_qualified_name("App\\User")
        assert node is not None
        assert node.name == "User"


class TestEdgeOperations:
    def test_upsert_and_get_edges(self, populated_store):
        edges = populated_store.get_edges(source_id="file1")
        assert len(edges) >= 1
        assert all(e.source_id == "file1" for e in edges)

    def test_get_edges_by_target(self, populated_store):
        edges = populated_store.get_edges(target_id="class1")
        assert len(edges) >= 1

    def test_get_edges_by_kind(self, populated_store):
        edges = populated_store.get_edges(source_id="method3")
        call_edges = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert len(call_edges) == 1
        assert call_edges[0].target_id == "class1"


class TestNeighborTraversal:
    def test_get_neighbors_outgoing(self, populated_store):
        neighbors = populated_store.get_neighbors("class1", direction="outgoing")
        assert len(neighbors) >= 2

    def test_get_neighbors_incoming(self, populated_store):
        neighbors = populated_store.get_neighbors("class1", direction="incoming")
        assert len(neighbors) >= 1

    def test_get_neighbors_both(self, populated_store):
        neighbors = populated_store.get_neighbors("class1", direction="both")
        assert len(neighbors) >= 3

    def test_get_neighbors_with_depth(self, populated_store):
        neighbors_d1 = populated_store.get_neighbors("file1", max_depth=1)
        neighbors_d2 = populated_store.get_neighbors("file1", max_depth=2)
        assert len(neighbors_d2) >= len(neighbors_d1)

    def test_get_neighbors_with_edge_filter(self, populated_store):
        neighbors = populated_store.get_neighbors("class1", direction="outgoing", edge_kinds=[EdgeKind.CONTAINS])
        assert len(neighbors) >= 2
        assert all(edge.kind == EdgeKind.CONTAINS for _, edge, _ in neighbors)


class TestMetadata:
    def test_set_and_get_metadata(self, store):
        store.set_metadata("test_key", "test_value")
        result = store.get_metadata("test_key")
        assert result == "test_value"

    def test_get_nonexistent_metadata(self, store):
        result = store.get_metadata("nonexistent")
        assert result is None


class TestSummary:
    def test_get_summary(self, populated_store):
        summary = populated_store.get_summary()
        assert summary.total_nodes == 7
        assert summary.total_edges == 7
        # files_by_language comes from the 'files' table (populated by pipeline)
        # In unit tests we only insert nodes, so check nodes_by_kind instead
        assert "file" in summary.nodes_by_kind
        assert summary.nodes_by_kind["file"] == 2


class TestBlastRadius:
    def test_blast_radius(self, populated_store):
        affected = populated_store.blast_radius("class1", max_depth=2)
        assert len(affected) >= 1
