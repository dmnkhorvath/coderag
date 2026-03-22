"""Tests for SessionStore — SQLite storage for session memory."""

from __future__ import annotations

import os

import pytest

from coderag.session.store import SessionStore


@pytest.fixture
def store(tmp_path):
    """Create a SessionStore with a temporary database."""
    db_path = str(tmp_path / "test.db")
    s = SessionStore(db_path)
    yield s
    s.close()


@pytest.fixture
def memory_store():
    """Create an in-memory SessionStore."""
    s = SessionStore(":memory:")
    yield s
    s.close()


class TestTableCreation:
    """Test that session tables are created on init."""

    def test_tables_exist(self, store):
        """All session tables should exist after init."""
        cursor = store.connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "sessions" in tables
        assert "session_events" in tables
        assert "context_store" in tables

    def test_indexes_exist(self, store):
        """All session indexes should exist after init."""
        cursor = store.connection.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_events_session" in indexes
        assert "idx_events_type" in indexes
        assert "idx_events_target" in indexes
        assert "idx_context_category" in indexes

    def test_memory_store(self, memory_store):
        """In-memory store should work."""
        sid = memory_store.create_session()
        assert sid
        assert len(sid) == 32  # uuid4().hex


class TestSessionLifecycle:
    """Test session create/end."""

    def test_create_session(self, store):
        """create_session returns a UUID hex string."""
        sid = store.create_session()
        assert isinstance(sid, str)
        assert len(sid) == 32

    def test_create_session_with_metadata(self, store):
        """create_session stores tool and prompt."""
        sid = store.create_session(tool="claude-code", prompt="fix routing")
        sessions = store.get_recent_sessions(limit=1)
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["tool"] == "claude-code"
        assert sessions[0]["prompt"] == "fix routing"

    def test_end_session(self, store):
        """end_session sets ended_at and total_events."""
        sid = store.create_session()
        store.log_event(sid, "read", "file.py")
        store.log_event(sid, "edit", "file.py")
        store.end_session(sid)

        sessions = store.get_recent_sessions(limit=1)
        assert sessions[0]["ended_at"] is not None
        assert sessions[0]["total_events"] == 2

    def test_multiple_sessions(self, store):
        """Multiple sessions can be created."""
        sid1 = store.create_session(tool="tool1")
        sid2 = store.create_session(tool="tool2")
        assert sid1 != sid2

        sessions = store.get_recent_sessions(limit=10)
        assert len(sessions) == 2


class TestEventLogging:
    """Test event logging and querying."""

    def test_log_event(self, store):
        """log_event stores an event."""
        sid = store.create_session()
        store.log_event(sid, "read", "src/main.py")

        events = store.get_events(session_id=sid)
        assert len(events) == 1
        assert events[0].event_type == "read"
        assert events[0].target == "src/main.py"
        assert events[0].session_id == sid

    def test_log_event_with_metadata(self, store):
        """log_event stores metadata as JSON."""
        sid = store.create_session()
        store.log_event(sid, "read", "file.py", metadata={"line_start": 10, "line_end": 20})

        events = store.get_events(session_id=sid)
        assert events[0].metadata == {"line_start": 10, "line_end": 20}

    def test_log_event_no_metadata(self, store):
        """log_event works without metadata."""
        sid = store.create_session()
        store.log_event(sid, "read", "file.py")

        events = store.get_events(session_id=sid)
        assert events[0].metadata == {}

    def test_get_events_filter_by_session(self, store):
        """get_events filters by session_id."""
        sid1 = store.create_session()
        sid2 = store.create_session()
        store.log_event(sid1, "read", "a.py")
        store.log_event(sid2, "read", "b.py")

        events = store.get_events(session_id=sid1)
        assert len(events) == 1
        assert events[0].target == "a.py"

    def test_get_events_filter_by_type(self, store):
        """get_events filters by event_type."""
        sid = store.create_session()
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "edit", "b.py")
        store.log_event(sid, "read", "c.py")

        events = store.get_events(event_type="read")
        assert len(events) == 2
        assert all(e.event_type == "read" for e in events)

    def test_get_events_filter_by_target(self, store):
        """get_events filters by target."""
        sid = store.create_session()
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "edit", "a.py")
        store.log_event(sid, "read", "b.py")

        events = store.get_events(target="a.py")
        assert len(events) == 2

    def test_get_events_limit(self, store):
        """get_events respects limit."""
        sid = store.create_session()
        for i in range(10):
            store.log_event(sid, "read", f"file{i}.py")

        events = store.get_events(limit=3)
        assert len(events) == 3

    def test_get_events_combined_filters(self, store):
        """get_events supports combined filters."""
        sid = store.create_session()
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "edit", "a.py")
        store.log_event(sid, "read", "b.py")

        events = store.get_events(session_id=sid, event_type="read", target="a.py")
        assert len(events) == 1


class TestContextStore:
    """Test context save/get/deactivate."""

    def test_save_context(self, store):
        """save_context stores a context item."""
        cid = store.save_context("decision", "Use JWT tokens")
        assert isinstance(cid, int)
        assert cid > 0

    def test_get_context(self, store):
        """get_context retrieves stored items."""
        store.save_context("decision", "Use JWT tokens")
        store.save_context("task", "Add rate limiting")

        items = store.get_context()
        assert len(items) == 2

    def test_get_context_by_category(self, store):
        """get_context filters by category."""
        store.save_context("decision", "Use JWT tokens")
        store.save_context("task", "Add rate limiting")
        store.save_context("fact", "Uses PostgreSQL")

        decisions = store.get_context(category="decision")
        assert len(decisions) == 1
        assert decisions[0]["content"] == "Use JWT tokens"

    def test_deactivate_context(self, store):
        """deactivate_context marks item as inactive."""
        cid = store.save_context("task", "Add rate limiting")
        store.deactivate_context(cid)

        active = store.get_context(active_only=True)
        assert len(active) == 0

        all_items = store.get_context(active_only=False)
        assert len(all_items) == 1
        assert all_items[0]["active"] is False

    def test_save_context_with_session(self, store):
        """save_context stores session_id."""
        sid = store.create_session()
        store.save_context("fact", "Uses PostgreSQL", session_id=sid)

        items = store.get_context(category="fact")
        assert items[0]["session_id"] == sid

    def test_get_context_limit(self, store):
        """get_context respects limit."""
        for i in range(10):
            store.save_context("fact", f"Fact {i}")

        items = store.get_context(limit=3)
        assert len(items) == 3


class TestAggregation:
    """Test aggregation queries."""

    def test_hot_files(self, store):
        """get_hot_files aggregates file access counts."""
        sid = store.create_session()
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "edit", "a.py")
        store.log_event(sid, "read", "b.py")

        hot = store.get_hot_files(limit=10)
        assert len(hot) == 2
        assert hot[0] == ("a.py", 3)  # 2 reads + 1 edit
        assert hot[1] == ("b.py", 1)

    def test_hot_files_excludes_non_file_events(self, store):
        """get_hot_files only counts read/edit events."""
        sid = store.create_session()
        store.log_event(sid, "read", "a.py")
        store.log_event(sid, "query", "search term")
        store.log_event(sid, "decision", "Use JWT")

        hot = store.get_hot_files(limit=10)
        assert len(hot) == 1
        assert hot[0] == ("a.py", 1)

    def test_hot_files_limit(self, store):
        """get_hot_files respects limit."""
        sid = store.create_session()
        for i in range(10):
            store.log_event(sid, "read", f"file{i}.py")

        hot = store.get_hot_files(limit=3)
        assert len(hot) == 3

    def test_hot_files_empty(self, store):
        """get_hot_files returns empty list for empty db."""
        hot = store.get_hot_files()
        assert hot == []

    def test_recent_sessions(self, store):
        """get_recent_sessions returns session summaries."""
        sid1 = store.create_session(tool="tool1")
        store.log_event(sid1, "read", "a.py")
        store.end_session(sid1)

        sid2 = store.create_session(tool="tool2")
        store.log_event(sid2, "read", "b.py")
        store.log_event(sid2, "edit", "b.py")
        store.end_session(sid2)

        sessions = store.get_recent_sessions(limit=5)
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0]["tool"] == "tool2"
        assert sessions[0]["event_count"] == 2

    def test_recent_sessions_empty(self, store):
        """get_recent_sessions returns empty list for empty db."""
        sessions = store.get_recent_sessions()
        assert sessions == []


class TestEmptyDatabase:
    """Test behavior with empty database."""

    def test_get_events_empty(self, store):
        events = store.get_events()
        assert events == []

    def test_get_context_empty(self, store):
        items = store.get_context()
        assert items == []

    def test_get_hot_files_empty(self, store):
        hot = store.get_hot_files()
        assert hot == []

    def test_get_recent_sessions_empty(self, store):
        sessions = store.get_recent_sessions()
        assert sessions == []


class TestStoreLifecycle:
    """Test store open/close."""

    def test_close(self, tmp_path):
        """close() closes the connection."""
        db_path = str(tmp_path / "test.db")
        store = SessionStore(db_path)
        store.close()
        with pytest.raises(RuntimeError):
            _ = store.connection

    def test_double_close(self, tmp_path):
        """Double close should not raise."""
        db_path = str(tmp_path / "test.db")
        store = SessionStore(db_path)
        store.close()
        store.close()  # Should not raise

    def test_creates_parent_dirs(self, tmp_path):
        """Store creates parent directories if needed."""
        db_path = str(tmp_path / "deep" / "nested" / "test.db")
        store = SessionStore(db_path)
        assert os.path.isfile(db_path)
        store.close()
