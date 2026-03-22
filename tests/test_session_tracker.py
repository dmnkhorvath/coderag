"""Tests for SessionTracker — high-level event tracking."""

from __future__ import annotations

import pytest

from coderag.session.store import SessionStore
from coderag.session.tracker import SessionTracker


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SessionStore(db_path)
    yield s
    s.close()


@pytest.fixture
def tracker(store):
    return SessionTracker(store)


class TestSessionLifecycle:
    """Test start/end session."""

    def test_start_session(self, tracker):
        sid = tracker.start_session(tool="claude-code", prompt="fix routing")
        assert isinstance(sid, str)
        assert len(sid) == 32
        assert tracker.current_session_id == sid

    def test_end_session(self, tracker):
        tracker.start_session()
        tracker.end_session()
        assert tracker.current_session_id is None

    def test_end_session_no_active(self, tracker):
        """end_session with no active session should not raise."""
        tracker.end_session()  # Should not raise

    def test_multiple_sessions(self, tracker):
        sid1 = tracker.start_session(tool="tool1")
        tracker.end_session()
        sid2 = tracker.start_session(tool="tool2")
        assert sid1 != sid2
        assert tracker.current_session_id == sid2


class TestLogMethods:
    """Test each log method."""

    def test_log_read(self, tracker, store):
        tracker.start_session()
        tracker.log_read("src/main.py")

        events = store.get_events(event_type="read")
        assert len(events) == 1
        assert events[0].target == "src/main.py"

    def test_log_read_with_metadata(self, tracker, store):
        tracker.start_session()
        tracker.log_read("src/main.py", metadata={"line_start": 10})

        events = store.get_events(event_type="read")
        assert events[0].metadata == {"line_start": 10}

    def test_log_edit(self, tracker, store):
        tracker.start_session()
        tracker.log_edit("src/main.py", metadata={"description": "Fixed bug"})

        events = store.get_events(event_type="edit")
        assert len(events) == 1
        assert events[0].target == "src/main.py"

    def test_log_query(self, tracker, store):
        tracker.start_session()
        tracker.log_query("authentication flow", results_count=5)

        events = store.get_events(event_type="query")
        assert len(events) == 1
        assert events[0].target == "authentication flow"
        assert events[0].metadata["results_count"] == 5

    def test_log_query_with_metadata(self, tracker, store):
        tracker.start_session()
        tracker.log_query("auth", results_count=3, metadata={"source": "fts5"})

        events = store.get_events(event_type="query")
        assert events[0].metadata["results_count"] == 3
        assert events[0].metadata["source"] == "fts5"

    def test_log_decision(self, tracker, store):
        tracker.start_session()
        tracker.log_decision("Use JWT tokens instead of session cookies")

        # Check event
        events = store.get_events(event_type="decision")
        assert len(events) == 1
        assert events[0].target == "Use JWT tokens instead of session cookies"

        # Check context store
        ctx = store.get_context(category="decision")
        assert len(ctx) == 1
        assert ctx[0]["content"] == "Use JWT tokens instead of session cookies"

    def test_log_task(self, tracker, store):
        tracker.start_session()
        tracker.log_task("Add rate limiting to login endpoint", status="open")

        events = store.get_events(event_type="task")
        assert len(events) == 1
        assert events[0].metadata["status"] == "open"

        ctx = store.get_context(category="task")
        assert len(ctx) == 1
        assert ctx[0]["content"] == "Add rate limiting to login endpoint"

    def test_log_fact(self, tracker, store):
        tracker.start_session()
        tracker.log_fact("The project uses PostgreSQL 15 in production")

        events = store.get_events(event_type="fact")
        assert len(events) == 1

        ctx = store.get_context(category="fact")
        assert len(ctx) == 1
        assert ctx[0]["content"] == "The project uses PostgreSQL 15 in production"

    def test_log_without_session_raises(self, tracker):
        """Logging without an active session should raise."""
        with pytest.raises(RuntimeError, match="No active session"):
            tracker.log_read("file.py")


class TestHotFiles:
    """Test hot files computation."""

    def test_hot_files(self, tracker):
        tracker.start_session()
        tracker.log_read("a.py")
        tracker.log_read("a.py")
        tracker.log_edit("a.py")
        tracker.log_read("b.py")

        hot = tracker.get_hot_files(limit=10)
        assert len(hot) == 2
        assert hot[0] == ("a.py", 3)
        assert hot[1] == ("b.py", 1)

    def test_hot_files_across_sessions(self, tracker):
        tracker.start_session()
        tracker.log_read("a.py")
        tracker.end_session()

        tracker.start_session()
        tracker.log_read("a.py")
        tracker.log_read("b.py")
        tracker.end_session()

        hot = tracker.get_hot_files(limit=10)
        assert hot[0] == ("a.py", 2)


class TestSessionSummary:
    """Test session summary."""

    def test_session_summary(self, tracker):
        tracker.start_session()
        tracker.log_read("a.py")
        tracker.log_read("b.py")
        tracker.log_edit("a.py")
        tracker.log_query("test query")

        summary = tracker.get_session_summary()
        assert summary["total_events"] == 4
        assert summary["event_types"]["read"] == 2
        assert summary["event_types"]["edit"] == 1
        assert summary["event_types"]["query"] == 1
        assert summary["unique_files"] == 2
        assert set(summary["files_touched"]) == {"a.py", "b.py"}

    def test_session_summary_no_session_raises(self, tracker):
        with pytest.raises(RuntimeError, match="No active session"):
            tracker.get_session_summary()

    def test_session_summary_empty(self, tracker):
        tracker.start_session()
        summary = tracker.get_session_summary()
        assert summary["total_events"] == 0
        assert summary["unique_files"] == 0
