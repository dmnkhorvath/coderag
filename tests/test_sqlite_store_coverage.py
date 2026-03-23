"""Targeted tests for SQLite store coverage.

Covers missing lines: 206-207, 212-216, 256-257, 473, 531-533, 556,
792-816, 828-850, 863-901, 984, 988, 992, 1004-1010, 1132, 1149,
1158, 1161-1162, 1165
"""

from __future__ import annotations

import sqlite3

import pytest

from coderag.core.models import Edge, EdgeKind, Node, NodeKind
from coderag.storage.sqlite_store import SQLiteStore


def _make_node(id, kind, name, qname, fpath, start, end, lang, **kw):
    """Helper to create Node with all required fields."""
    return Node(
        id=id,
        kind=kind,
        name=name,
        qualified_name=qname,
        file_path=fpath,
        start_line=start,
        end_line=end,
        language=lang,
        **kw,
    )


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SQLiteStore(db_path)
    s.initialize()
    return s


@pytest.fixture
def populated_store(store):
    """Store with some nodes and edges for testing."""
    nodes = [
        _make_node("file1.py:1:file:file1.py", NodeKind.FILE, "file1.py", "file1.py", "file1.py", 1, 100, "python"),
        _make_node(
            "file1.py:3:class:Foo", NodeKind.CLASS, "Foo", "Foo", "file1.py", 3, 20, "python", docblock="A Foo class."
        ),
        _make_node("file1.py:5:method:bar", NodeKind.METHOD, "bar", "Foo.bar", "file1.py", 5, 10, "python"),
        _make_node("file2.py:1:file:file2.py", NodeKind.FILE, "file2.py", "file2.py", "file2.py", 1, 50, "python"),
        _make_node("file2.py:3:function:helper", NodeKind.FUNCTION, "helper", "helper", "file2.py", 3, 8, "python"),
    ]
    edges = [
        Edge(
            source_id="file1.py:1:file:file1.py",
            target_id="file1.py:3:class:Foo",
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=3,
        ),
        Edge(
            source_id="file1.py:3:class:Foo",
            target_id="file1.py:5:method:bar",
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=5,
        ),
        Edge(
            source_id="file1.py:5:method:bar",
            target_id="file2.py:3:function:helper",
            kind=EdgeKind.CALLS,
            confidence=0.9,
            line_number=7,
        ),
    ]
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)
    return store


# ---------------------------------------------------------------------------
# execute_write / _execute_with_retry  (lines 206-216, 256-257)
# ---------------------------------------------------------------------------


class TestExecuteWrite:
    def test_execute_write_basic(self, store):
        """Line 206-207: basic execute_write path."""
        cursor = store.execute_write(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("test_key", "test_value"),
        )
        assert cursor is not None
        row = store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("test_key",)).fetchone()
        assert row[0] == "test_value"

    def test_execute_with_retry_database_locked(self, store):
        """Lines 212-216: retry on database locked error."""
        call_count = 0
        real_conn = store._conn

        class WrappedConn:
            """Wrapper that fails first 2 execute calls with locked."""

            def __init__(self, real):
                self._real = real
                self._call_count = 0

            def execute(self, sql, params=()):
                self._call_count += 1
                if self._call_count <= 2:
                    raise sqlite3.OperationalError("database is locked")
                return self._real.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._real, name)

        store._conn = WrappedConn(real_conn)
        try:
            result = store._execute_with_retry("SELECT 1", (), max_retries=5, base_delay=0.001)
            assert result is not None
        finally:
            store._conn = real_conn

    def test_execute_with_retry_max_retries_exceeded(self, store):
        """Lines 256-257: max retries exceeded raises."""
        real_conn = store._conn

        class AlwaysLockedConn:
            def execute(self, sql, params=()):
                raise sqlite3.OperationalError("database is locked")

            def __getattr__(self, name):
                return getattr(real_conn, name)

        store._conn = AlwaysLockedConn()
        try:
            with pytest.raises(sqlite3.OperationalError):
                store._execute_with_retry("SELECT 1", (), max_retries=2, base_delay=0.001)
        finally:
            store._conn = real_conn

    def test_execute_with_retry_non_locked_error(self, store):
        """Non-locked errors should raise immediately."""
        real_conn = store._conn

        class OtherErrorConn:
            def execute(self, sql, params=()):
                raise sqlite3.OperationalError("no such table: foobar")

            def __getattr__(self, name):
                return getattr(real_conn, name)

        store._conn = OtherErrorConn()
        try:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                store._execute_with_retry("SELECT 1", (), max_retries=5, base_delay=0.001)
        finally:
            store._conn = real_conn


# ---------------------------------------------------------------------------
# delete_nodes_for_file  (lines 473, 531-533, 556)
# ---------------------------------------------------------------------------


class TestDeleteNodesForFile:
    def test_delete_nodes_for_existing_file(self, populated_store):
        """Lines 531-533: delete nodes and edges for a file."""
        count = populated_store.delete_nodes_for_file("file1.py")
        assert count == 3  # file, class, method
        remaining = populated_store.connection.execute(
            "SELECT COUNT(*) FROM nodes WHERE file_path = ?", ("file1.py",)
        ).fetchone()[0]
        assert remaining == 0

    def test_delete_nodes_for_nonexistent_file(self, populated_store):
        """Line 473: no nodes found returns 0."""
        count = populated_store.delete_nodes_for_file("nonexistent.py")
        assert count == 0

    def test_delete_nodes_removes_edges(self, populated_store):
        """Verify edges referencing deleted nodes are also removed."""
        populated_store.delete_nodes_for_file("file1.py")
        edges = populated_store.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id LIKE ?", ("file1.py%",)
        ).fetchone()[0]
        assert edges == 0


# ---------------------------------------------------------------------------
# get_summary / get_communities  (lines 792-816, 828-850, 863-901)
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_get_summary_empty_store(self, store):
        """Lines 792-816: summary of empty store."""
        summary = store.get_summary()
        assert summary.total_nodes == 0
        assert summary.total_edges == 0

    def test_get_summary_populated(self, populated_store):
        """Lines 792-816: summary with data."""
        summary = populated_store.get_summary()
        assert summary.total_nodes == 5
        assert summary.total_edges == 3
        assert "file" in summary.nodes_by_kind
        assert "class" in summary.nodes_by_kind

    def test_get_summary_nodes_by_kind(self, populated_store):
        """Verify nodes_by_kind breakdown."""
        summary = populated_store.get_summary()
        assert summary.nodes_by_kind.get("file") == 2
        assert summary.nodes_by_kind.get("class") == 1
        assert summary.nodes_by_kind.get("method") == 1
        assert summary.nodes_by_kind.get("function") == 1

    def test_get_summary_edges_by_kind(self, populated_store):
        """Verify edges_by_kind breakdown."""
        summary = populated_store.get_summary()
        assert summary.edges_by_kind.get("contains") == 2
        assert summary.edges_by_kind.get("calls") == 1

    def test_get_summary_with_communities(self, populated_store):
        """Lines 863-901: communities count in summary."""
        populated_store.connection.execute("UPDATE nodes SET community_id = 1 WHERE file_path = ?", ("file1.py",))
        populated_store.connection.execute("UPDATE nodes SET community_id = 2 WHERE file_path = ?", ("file2.py",))
        populated_store.connection.commit()
        summary = populated_store.get_summary()
        assert summary.communities >= 2


# ---------------------------------------------------------------------------
# Metadata operations  (lines 984, 988, 992)
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_set_and_get_metadata(self, store):
        """Lines 984, 988: basic set/get."""
        store.set_metadata("test_key", "test_value")
        assert store.get_metadata("test_key") == "test_value"

    def test_get_metadata_nonexistent(self, store):
        """Line 992: nonexistent key returns None."""
        assert store.get_metadata("nonexistent") is None

    def test_set_metadata_overwrite(self, store):
        """Overwriting existing metadata."""
        store.set_metadata("key", "value1")
        store.set_metadata("key", "value2")
        assert store.get_metadata("key") == "value2"


# ---------------------------------------------------------------------------
# Transaction context manager  (lines 1004-1010)
# ---------------------------------------------------------------------------


class TestTransaction:
    def test_transaction_commit(self, store):
        """Lines 1004-1010: successful transaction commits."""
        with store.transaction():
            store.connection.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("tx_key", "tx_value"),
            )
        row = store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("tx_key",)).fetchone()
        assert row[0] == "tx_value"

    def test_transaction_rollback(self, store):
        """Lines 1004-1010: failed transaction rolls back."""
        with pytest.raises(ValueError):
            with store.transaction():
                store.connection.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    ("tx_fail", "should_not_exist"),
                )
                raise ValueError("simulated error")
        row = store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("tx_fail",)).fetchone()
        assert row is None

    def test_begin_commit_transaction(self, store):
        """Test begin/commit transaction methods directly."""
        store.begin_transaction()
        store.connection.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("manual_tx", "manual_value"),
        )
        store.commit_transaction()
        row = store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("manual_tx",)).fetchone()
        assert row[0] == "manual_value"

    def test_begin_rollback_transaction(self, store):
        """Test begin/rollback transaction methods directly."""
        store.begin_transaction()
        store.connection.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            ("rollback_tx", "should_not_exist"),
        )
        store.rollback_transaction()
        row = store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("rollback_tx",)).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# Search / FTS  (lines 1132, 1149, 1158, 1161-1165)
# ---------------------------------------------------------------------------


class TestSearchNodes:
    def test_search_by_name(self, populated_store):
        results = populated_store.search_nodes("Foo")
        assert len(results) >= 1
        assert any(n.name == "Foo" for n in results)

    def test_search_by_qualified_name(self, populated_store):
        results = populated_store.search_nodes("Foo.bar")
        assert len(results) >= 1

    def test_search_with_kind_filter(self, populated_store):
        results = populated_store.search_nodes("Foo", kind="class")
        assert len(results) >= 1
        assert all(n.kind == NodeKind.CLASS for n in results)

    def test_search_no_results(self, populated_store):
        results = populated_store.search_nodes("NonexistentSymbol12345")
        assert len(results) == 0

    def test_search_camel_case_splitting(self, populated_store):
        """Lines 1149, 1158: camelCase/PascalCase splitting in FTS query."""
        node = _make_node(
            "test:1:class:HttpKernel", NodeKind.CLASS, "HttpKernel", "App.HttpKernel", "test.py", 1, 10, "python"
        )
        populated_store.upsert_nodes([node])
        results = populated_store.search_nodes("HttpKernel")
        assert len(results) >= 1

    def test_search_special_characters(self, populated_store):
        """Lines 1132, 1161-1162: special characters stripped from FTS query."""
        results = populated_store.search_nodes("foo(bar)")
        assert isinstance(results, list)
        results = populated_store.search_nodes("foo[bar]")
        assert isinstance(results, list)
        results = populated_store.search_nodes("foo{bar}")
        assert isinstance(results, list)

    def test_search_empty_query_after_cleaning(self, populated_store):
        """Line 1165: empty query after cleaning returns empty list."""
        results = populated_store.search_nodes("()[]{}")
        assert isinstance(results, list)

    def test_search_underscore_splitting(self, populated_store):
        """Lines 1149: underscore splitting in FTS query."""
        node = _make_node("test:1:class:WP_Query", NodeKind.CLASS, "WP_Query", "WP_Query", "test.php", 1, 10, "php")
        populated_store.upsert_nodes([node])
        results = populated_store.search_nodes("WP_Query")
        assert len(results) >= 1

    def test_search_with_limit(self, populated_store):
        results = populated_store.search_nodes("file", limit=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------


class TestEdgeOperations:
    def test_get_edges_for_node(self, populated_store):
        edges = populated_store.get_edges(source_id="file1.py:3:class:Foo")
        assert len(edges) >= 1

    def test_get_edges_for_nonexistent_node(self, populated_store):
        edges = populated_store.get_edges(source_id="nonexistent")
        assert len(edges) == 0

    def test_upsert_single_edge(self, populated_store):
        edge = Edge(
            source_id="file2.py:1:file:file2.py",
            target_id="file2.py:3:function:helper",
            kind=EdgeKind.CONTAINS,
            confidence=1.0,
            line_number=3,
        )
        populated_store.upsert_edge(edge)
        edges = populated_store.get_edges(source_id="file2.py:1:file:file2.py")
        assert any(e.kind == EdgeKind.CONTAINS for e in edges)


# ---------------------------------------------------------------------------
# Context manager / dunder  (lines __enter__, __exit__)
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager(self, tmp_path):
        db_path = str(tmp_path / "ctx.db")
        with SQLiteStore(db_path) as s:
            s.set_metadata("key", "value")
            assert s.get_metadata("key") == "value"

    def test_repr(self, store):
        r = repr(store)
        assert "SQLiteStore" in r

    def test_connection_not_initialized(self, tmp_path):
        """connection property raises if not initialized."""
        s = SQLiteStore(str(tmp_path / "uninit.db"))
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = s.connection

    def test_close_twice(self, tmp_path):
        """Closing twice should not error."""
        db_path = str(tmp_path / "close.db")
        s = SQLiteStore(db_path)
        s.initialize()
        s.close()
        s.close()  # second close should be safe


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_get_stats_empty(self, store):
        stats = store.get_stats()
        assert isinstance(stats, dict)
        assert stats["total_nodes"] == 0

    def test_get_stats_populated(self, populated_store):
        stats = populated_store.get_stats()
        assert isinstance(stats, dict)
        assert stats["total_nodes"] == 5
        assert stats["total_edges"] == 3


# ---------------------------------------------------------------------------
# Node operations
# ---------------------------------------------------------------------------


class TestNodeOperations:
    def test_upsert_single_node(self, store):
        node = _make_node("test:1:class:X", NodeKind.CLASS, "X", "X", "test.py", 1, 10, "python")
        store.upsert_node(node)
        results = store.search_nodes("X")
        assert len(results) >= 1

    def test_upsert_nodes_empty(self, store):
        count = store.upsert_nodes([])
        assert count == 0

    def test_upsert_edges_empty(self, store):
        count = store.upsert_edges([])
        assert count == 0

    def test_get_node_by_id(self, populated_store):
        node = populated_store.get_node("file1.py:3:class:Foo")
        assert node is not None
        assert node.name == "Foo"

    def test_get_node_by_id_nonexistent(self, populated_store):
        node = populated_store.get_node("nonexistent")
        assert node is None

    def test_get_nodes_by_file(self, populated_store):
        nodes = populated_store.find_nodes(file_path="file1.py")
        assert len(nodes) == 3

    def test_get_nodes_by_file_empty(self, populated_store):
        nodes = populated_store.find_nodes(file_path="nonexistent.py")
        assert len(nodes) == 0


# ---------------------------------------------------------------------------
# create_thread_connection
# ---------------------------------------------------------------------------


class TestThreadConnection:
    def test_create_thread_connection(self, populated_store):
        """Test creating a read-only thread connection."""
        conn = populated_store.create_thread_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            assert row[0] == 5
        finally:
            conn.close()
