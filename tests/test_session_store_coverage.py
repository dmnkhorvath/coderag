"""Coverage tests for session store - Pass 2."""
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from coderag.session.store import SessionStore


class TestPragmaOperationalError:
    """Test PRAGMA OperationalError handling (lines 88-89)."""

    def test_pragma_error_caught(self, tmp_path):
        """OperationalError on PRAGMA is caught gracefully."""
        db_path = str(tmp_path / "session.db")
        # Patch sqlite3.connect to return a mock connection that raises on PRAGMA
        real_conn = sqlite3.connect(db_path)
        real_conn.row_factory = sqlite3.Row

        original_execute = real_conn.execute
        pragma_calls = [0]

        class PragmaFailConnection:
            """Wrapper that fails on PRAGMA but delegates everything else."""
            def __getattr__(self, name):
                return getattr(real_conn, name)

            def execute(self, sql, *args, **kwargs):
                if "PRAGMA" in sql.upper():
                    raise sqlite3.OperationalError("database is locked")
                return original_execute(sql, *args, **kwargs)

        fake_conn = PragmaFailConnection()

        with patch("sqlite3.connect", return_value=fake_conn):
            store = SessionStore(db_path)
            assert store is not None

    def test_normal_initialization(self, tmp_path):
        """Normal initialization works."""
        db_path = str(tmp_path / "session_normal.db")
        store = SessionStore(db_path)
        assert store.connection is not None
        store.close()


class TestConnectionProperty:
    """Test connection property when closed (lines 97-98, 110-112)."""

    def test_connection_when_open(self, tmp_path):
        db_path = str(tmp_path / "session_open.db")
        store = SessionStore(db_path)
        conn = store.connection
        assert isinstance(conn, sqlite3.Connection)
        store.close()

    def test_connection_when_closed(self, tmp_path):
        """Accessing connection after close raises RuntimeError."""
        db_path = str(tmp_path / "session_closed.db")
        store = SessionStore(db_path)
        store.close()
        with pytest.raises(RuntimeError, match="closed"):
            _ = store.connection

    def test_execute_write_many(self, tmp_path):
        """Test _execute_write_many method (lines 110-112)."""
        db_path = str(tmp_path / "session_wm.db")
        store = SessionStore(db_path)
        store._execute_write_many(
            "INSERT OR REPLACE INTO sessions (id, started_at) VALUES (?, datetime('now'))",
            [("s1",), ("s2",), ("s3",)],
        )
        cursor = store.connection.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]
        assert count == 3
        store.close()


class TestClose:
    """Test close method."""

    def test_close_sets_conn_none(self, tmp_path):
        db_path = str(tmp_path / "session_close.db")
        store = SessionStore(db_path)
        store.close()
        assert store._conn is None

    def test_double_close(self, tmp_path):
        db_path = str(tmp_path / "session_dclose.db")
        store = SessionStore(db_path)
        store.close()
        store.close()  # Should not raise
