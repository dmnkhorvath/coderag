"""Tests for coderag.cli.session to push coverage from 22% to 90%+.

Covers: _find_db_path, _open_session_store, session_list, session_show, session_context.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderag.cli.session import session, _find_db_path, _open_session_store


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _find_db_path
# ---------------------------------------------------------------------------

class TestFindDbPath:
    def test_finds_db_in_project_path(self, tmp_path):
        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.write_text("")
        result = _find_db_path(str(tmp_path))
        assert result is not None
        assert result.endswith("graph.db")

    def test_returns_none_when_no_db(self, tmp_path):
        result = _find_db_path(str(tmp_path))
        assert result is None

    def test_finds_db_in_cwd(self, tmp_path):
        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.write_text("")
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = _find_db_path(None)
            assert result is not None

    def test_returns_none_cwd_no_db(self, tmp_path):
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = _find_db_path(None)
            assert result is None


# ---------------------------------------------------------------------------
# _open_session_store
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# session list
# ---------------------------------------------------------------------------

class TestSessionList:
    def test_list_no_sessions(self, runner):
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list"])
            assert result.exit_code == 0
            assert "No sessions" in result.output

    def test_list_with_sessions(self, runner):
        sess = {
            "id": "abc123def456789",
            "started_at": "2024-01-01 10:00:00",
            "tool": "claude-code",
            "event_count": 5,
            "prompt": "Fix the bug",
            "ended_at": "2024-01-01 11:00:00",
        }
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list"])
            assert result.exit_code == 0

    def test_list_with_limit(self, runner):
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list", "-n", "5"])
            assert result.exit_code == 0
            mock_store.get_recent_sessions.assert_called_once_with(limit=5)

    def test_list_with_project(self, runner, tmp_path):
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list", "--project", str(tmp_path)])
            assert result.exit_code == 0

    def test_list_session_no_prompt_no_tool(self, runner):
        sess = {
            "id": "abc123def456789",
            "started_at": "2024-01-01 10:00:00",
            "tool": None,
            "event_count": 0,
            "prompt": None,
            "ended_at": None,
        }
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list"])
            assert result.exit_code == 0

    def test_list_session_no_started_at(self, runner):
        sess = {
            "id": "abc123def456789",
            "started_at": None,
            "tool": "cursor",
            "event_count": 3,
            "prompt": "Hello",
            "ended_at": None,
        }
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["list"])
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# session show
# ---------------------------------------------------------------------------

class TestSessionShow:
    def test_show_not_found(self, runner):
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["show", "nonexistent"])
            assert result.exit_code == 0
            assert "not found" in result.output.lower()

    def test_show_found_by_partial_id(self, runner):
        sess = {
            "id": "abc123def456789",
            "started_at": "2024-01-01 10:00:00",
            "ended_at": "2024-01-01 11:00:00",
            "tool": "claude-code",
            "prompt": "Fix auth",
            "event_count": 3,
        }
        mock_event = MagicMock()
        mock_event.timestamp = datetime(2024, 1, 1, 10, 5, 0)
        mock_event.event_type = "file_read"
        mock_event.target = "auth.py"

        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        mock_store.get_events.return_value = [mock_event]
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["show", "abc123"])
            assert result.exit_code == 0

    def test_show_with_project(self, runner, tmp_path):
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["show", "abc", "--project", str(tmp_path)])
            assert result.exit_code == 0

    def test_show_session_no_events(self, runner):
        sess = {
            "id": "abc123",
            "started_at": "2024-01-01 10:00:00",
            "ended_at": None,
            "tool": None,
            "prompt": None,
            "event_count": 0,
        }
        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        mock_store.get_events.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["show", "abc123"])
            assert result.exit_code == 0

    def test_show_multiple_events(self, runner):
        sess = {
            "id": "abc123def456789",
            "started_at": "2024-01-01 10:00:00",
            "ended_at": "2024-01-01 11:00:00",
            "tool": "codex",
            "prompt": "Refactor",
            "event_count": 2,
        }
        events = []
        for i, (etype, target) in enumerate([("file_read", "main.py"), ("file_edit", "utils.py")]):
            ev = MagicMock()
            ev.timestamp = datetime(2024, 1, 1, 10, i, 0)
            ev.event_type = etype
            ev.target = target
            events.append(ev)

        mock_store = MagicMock()
        mock_store.get_recent_sessions.return_value = [sess]
        mock_store.get_events.return_value = events
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["show", "abc123"])
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# session context
# ---------------------------------------------------------------------------

class TestSessionContext:
    def test_context_no_data(self, runner):
        mock_store = MagicMock()
        mock_store.get_context.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context"])
            assert result.exit_code == 0
            assert "No active context" in result.output

    def test_context_with_entries_and_hot_files(self, runner):
        items = [
            {"id": 1, "category": "decision", "content": "Use JWT tokens", "created_at": "2024-01-01 10:00:00"},
            {"id": 2, "category": "task", "content": "Add rate limiting", "created_at": "2024-01-02 10:00:00"},
        ]
        hot_files = [("src/auth.py", 15), ("src/models.py", 10)]

        mock_store = MagicMock()
        mock_store.get_context.return_value = items
        mock_store.get_hot_files.return_value = hot_files
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context"])
            assert result.exit_code == 0

    def test_context_with_category_filter(self, runner):
        mock_store = MagicMock()
        mock_store.get_context.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context", "--category", "decision"])
            assert result.exit_code == 0
            mock_store.get_context.assert_called_once_with(category="decision", active_only=True)

    def test_context_with_project(self, runner, tmp_path):
        mock_store = MagicMock()
        mock_store.get_context.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context", "--project", str(tmp_path)])
            assert result.exit_code == 0

    def test_context_entries_no_hot_files(self, runner):
        items = [
            {"id": 1, "category": "fact", "content": "Uses PostgreSQL", "created_at": "2024-01-01 10:00:00"},
        ]
        mock_store = MagicMock()
        mock_store.get_context.return_value = items
        mock_store.get_hot_files.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context"])
            assert result.exit_code == 0

    def test_context_no_data_with_category(self, runner):
        mock_store = MagicMock()
        mock_store.get_context.return_value = []
        with patch("coderag.cli.session._open_session_store", return_value=mock_store):
            result = runner.invoke(session, ["context", "--category", "task"])
            assert result.exit_code == 0
            assert "task" in result.output.lower() or "No active" in result.output
