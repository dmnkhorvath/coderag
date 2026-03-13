"""Tests for SQLite concurrent access improvements (Feature 3)."""

import os
import tempfile
import threading
import time

import pytest

from coderag.core.models import Node, NodeKind
from coderag.storage.sqlite_store import SQLiteStore


@pytest.fixture
def file_store():
    """Create a file-based SQLite store for concurrent access testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = SQLiteStore(db_path)
        store.initialize()
        yield store
        store.close()


@pytest.fixture
def memory_store():
    """Create an in-memory SQLite store."""
    store = SQLiteStore(":memory:")
    store.initialize()
    yield store
    store.close()


class TestSQLiteStoreEnhancements:
    """Tests for SQLite store concurrent access enhancements."""

    def test_write_lock_attribute(self, memory_store):
        """Store should have a threading lock for writes."""
        assert hasattr(memory_store, "_write_lock")

    def test_execute_write_method(self, memory_store):
        """execute_write should execute SQL with locking."""
        memory_store.execute_write(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("test", "value"),
        )
        memory_store.connection.commit()
        row = memory_store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("test",)).fetchone()
        assert row is not None
        assert row[0] == "value"

    def test_execute_with_retry(self, memory_store):
        """_execute_with_retry should handle normal operations."""
        cursor = memory_store._execute_with_retry(
            "SELECT 1",
        )
        assert cursor is not None

    def test_busy_timeout_pragma(self, file_store):
        """File store should have busy_timeout set."""
        row = file_store.connection.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] >= 30000

    def test_wal_mode_enabled(self, file_store):
        """File store should use WAL journal mode."""
        row = file_store.connection.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"

    def test_create_thread_connection(self, file_store):
        """Thread connection should be created with correct pragmas."""
        conn = file_store.create_thread_connection()
        try:
            # Should be read-only
            row = conn.execute("PRAGMA query_only").fetchone()
            assert row[0] == 1

            # Should have WAL mode
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0].lower() == "wal"

            # Should have busy_timeout
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] >= 30000

            # Should be able to read
            rows = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            assert rows[0] == 0
        finally:
            conn.close()

    def test_concurrent_read_write(self, file_store):
        """Concurrent reads and writes should not deadlock."""
        errors = []

        def writer():
            try:
                for i in range(20):
                    node = Node(
                        id=f"writer-{i}",
                        kind=NodeKind.FUNCTION,
                        name=f"func_{i}",
                        qualified_name=f"mod.func_{i}",
                        file_path=f"/tmp/f{i}.py",
                        start_line=1,
                        end_line=5,
                        language="python",
                    )
                    file_store.upsert_nodes([node])
                    time.sleep(0.01)
            except Exception as exc:
                errors.append(("writer", str(exc)))

        def reader():
            try:
                conn = file_store.create_thread_connection()
                try:
                    for _ in range(20):
                        conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
                        time.sleep(0.01)
                finally:
                    conn.close()
            except Exception as exc:
                errors.append(("reader", str(exc)))

        threads = []
        threads.append(threading.Thread(target=writer))
        for _ in range(3):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Concurrent access errors: {errors}"

    def test_multiple_writers_serialized(self, file_store):
        """Multiple writers using execute_write should be serialized."""
        errors = []
        written_keys = []

        def writer(thread_id):
            try:
                for i in range(5):
                    key = f"t{thread_id}_k{i}"
                    file_store.execute_write(
                        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                        (key, f"value_{thread_id}_{i}"),
                    )
                    file_store.connection.commit()
                    written_keys.append(key)
            except Exception as exc:
                errors.append((thread_id, str(exc)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Writer errors: {errors}"
        # All keys should be written
        for key in written_keys:
            row = file_store.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            assert row is not None, f"Missing key: {key}"

    def test_delete_nodes_for_file_with_concurrent_read(self, file_store):
        """delete_nodes_for_file should work while readers are active."""
        # Insert nodes
        nodes = [
            Node(
                id=f"del-{i}",
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                qualified_name=f"mod.func_{i}",
                file_path="/tmp/target.py",
                start_line=i,
                end_line=i + 5,
                language="python",
            )
            for i in range(10)
        ]
        file_store.upsert_nodes(nodes)

        errors = []

        def reader():
            try:
                conn = file_store.create_thread_connection()
                try:
                    for _ in range(10):
                        conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
                        time.sleep(0.01)
                finally:
                    conn.close()
            except Exception as exc:
                errors.append(str(exc))

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()

        # Delete while reader is active
        count = file_store.delete_nodes_for_file("/tmp/target.py")
        assert count == 10

        reader_thread.join(timeout=5)
        assert len(errors) == 0
