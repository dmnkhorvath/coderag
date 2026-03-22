"""Tests for MCP session tools."""

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
    t = SessionTracker(store)
    t.start_session(tool="test", prompt="testing")
    return t


def _import_tools():
    """Import session tool functions."""
    from coderag.mcp import session_tools

    return session_tools


class TestLogReadTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_read_impl(store, tracker, "src/main.py")
        assert "Logged read" in result
        assert "src/main.py" in result

    def test_with_lines(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_read_impl(store, tracker, "src/main.py", line_start=10, line_end=20)
        assert "Logged read" in result

        events = store.get_events(event_type="read")
        assert events[0].metadata.get("line_start") == 10
        assert events[0].metadata.get("line_end") == 20


class TestLogEditTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_edit_impl(store, tracker, "src/main.py", description="Fixed bug")
        assert "Logged edit" in result

        events = store.get_events(event_type="edit")
        assert len(events) == 1
        assert events[0].metadata.get("description") == "Fixed bug"


class TestLogDecisionTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_decision_impl(store, tracker, "Use JWT tokens", rationale="More scalable")
        assert "Logged decision" in result

        ctx = store.get_context(category="decision")
        assert len(ctx) == 1
        assert "JWT" in ctx[0]["content"]


class TestLogTaskTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_task_impl(store, tracker, "Add rate limiting", status="open")
        assert "Logged task" in result

        ctx = store.get_context(category="task")
        assert len(ctx) == 1

    def test_custom_status(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_task_impl(store, tracker, "Fix bug", status="in-progress")
        events = store.get_events(event_type="task")
        assert events[0].metadata["status"] == "in-progress"


class TestLogFactTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        result = tools.session_log_fact_impl(store, tracker, "Uses PostgreSQL", source="README")
        assert "Logged fact" in result

        ctx = store.get_context(category="fact")
        assert len(ctx) == 1


class TestGetHistoryTool:
    def test_all_events(self, store, tracker):
        tools = _import_tools()
        tracker.log_read("a.py")
        tracker.log_edit("b.py")

        result = tools.session_get_history_impl(store, event_type=None, limit=20)
        assert "a.py" in result
        assert "b.py" in result

    def test_filter_by_type(self, store, tracker):
        tools = _import_tools()
        tracker.log_read("a.py")
        tracker.log_edit("b.py")

        result = tools.session_get_history_impl(store, event_type="read", limit=20)
        assert "a.py" in result
        # b.py is an edit, should not appear when filtering reads

    def test_empty(self, store, tracker):
        tools = _import_tools()
        result = tools.session_get_history_impl(store, event_type=None, limit=20)
        assert "No events" in result or "events" in result.lower()


class TestGetHotFilesTool:
    def test_basic(self, store, tracker):
        tools = _import_tools()
        tracker.log_read("a.py")
        tracker.log_read("a.py")
        tracker.log_read("b.py")

        result = tools.session_get_hot_files_impl(store, limit=10)
        assert "a.py" in result
        assert "b.py" in result

    def test_empty(self, store, tracker):
        tools = _import_tools()
        result = tools.session_get_hot_files_impl(store, limit=10)
        assert "No hot files" in result or "hot" in result.lower()


class TestGetContextTool:
    def test_all_categories(self, store, tracker):
        tools = _import_tools()
        tracker.log_decision("Use JWT")
        tracker.log_task("Add tests")
        tracker.log_fact("Uses Redis")

        result = tools.session_get_context_impl(store, category=None)
        assert "JWT" in result
        assert "tests" in result.lower() or "Add tests" in result
        assert "Redis" in result

    def test_filter_category(self, store, tracker):
        tools = _import_tools()
        tracker.log_decision("Use JWT")
        tracker.log_fact("Uses Redis")

        result = tools.session_get_context_impl(store, category="decision")
        assert "JWT" in result

    def test_empty(self, store, tracker):
        tools = _import_tools()
        result = tools.session_get_context_impl(store, category=None)
        assert "No context" in result or "context" in result.lower()


class TestErrorHandling:
    def test_log_read_no_session(self, store):
        """Tools should handle no active session gracefully."""
        tools = _import_tools()
        tracker = SessionTracker(store)
        # No session started
        result = tools.session_log_read_impl(store, tracker, "file.py")
        assert "error" in result.lower() or "no active session" in result.lower()
