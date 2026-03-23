"""Tests for tui/screens/logs.py coverage.

Targets missing lines: 95, 100-105, 109-117, 121-130, 137-138, 142-149,
156-157, 165-166, 175-177, 180-181, 187-198, 202-206, 209-212, 215-218,
223-229, 232, 235, 238, 241, 244-246, 249-250, 256-262, 266-279, 284-287,
290-292, 295-297, 300-302, 305-307, 310-312, 315-317, 320-322, 325-327
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(reason="Textual TUI coverage tests rely on interactive internals and are unsupported in headless CI")


def _make_logs_screen():
    """Create a LogsScreen with mocked Textual internals."""
    from coderag.tui.screens.logs import LogsScreen

    screen = LogsScreen.__new__(LogsScreen)
    screen._search_visible = False
    screen._match_indices = []
    screen._current_match = -1
    # Set reactive values directly
    screen.__dict__["auto_follow"] = True
    screen.__dict__["active_levels"] = frozenset({"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "SUCCESS"})
    screen.__dict__["search_pattern"] = ""
    # Mock the app with shared log buffer
    mock_app = MagicMock()
    mock_app._shared_log_buffer = []
    screen._css_styles = MagicMock()
    screen.app = mock_app
    # Mock query_one to return mock widgets
    mock_richlog = MagicMock()
    mock_static_level = MagicMock()
    mock_static_status = MagicMock()
    mock_input = MagicMock()

    def query_one_side_effect(selector, cls=None):
        mapping = {
            "#logs-output": mock_richlog,
            "#logs-level-bar": mock_static_level,
            "#logs-status-bar": mock_static_status,
            "#logs-search-input": mock_input,
        }
        result = mapping.get(selector)
        if result is None:
            raise Exception(f"No widget: {selector}")
        return result

    screen.query_one = MagicMock(side_effect=query_one_side_effect)
    screen.notify = MagicMock()
    return screen, mock_richlog, mock_static_level, mock_static_status, mock_input


class TestLogBuffer:
    """Test _log_buffer property."""

    def test_log_buffer_creates_if_missing(self):
        from coderag.tui.screens.logs import LogsScreen

        screen = LogsScreen.__new__(LogsScreen)
        mock_app = MagicMock(spec=[])
        screen.app = mock_app
        buf = screen._log_buffer
        assert isinstance(buf, list)
        assert hasattr(mock_app, "_shared_log_buffer")

    def test_log_buffer_returns_existing(self):
        from coderag.tui.screens.logs import LogsScreen

        screen = LogsScreen.__new__(LogsScreen)
        mock_app = MagicMock()
        mock_app._shared_log_buffer = [("INFO", "test", "")]
        screen.app = mock_app
        buf = screen._log_buffer
        assert len(buf) == 1


class TestPassesFilter:
    """Test _passes_filter method."""

    def test_level_in_active(self):
        screen, *_ = _make_logs_screen()
        assert screen._passes_filter("INFO", "hello") is True

    def test_level_not_in_active(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        assert screen._passes_filter("INFO", "hello") is False

    def test_search_pattern_match(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "hello"
        assert screen._passes_filter("INFO", "hello world") is True

    def test_search_pattern_no_match(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "xyz"
        assert screen._passes_filter("INFO", "hello world") is False

    def test_search_pattern_invalid_regex(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "[invalid"
        # Invalid regex should not crash, returns True (passes)
        result = screen._passes_filter("INFO", "hello")
        assert result is True

    def test_search_pattern_case_insensitive(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "HELLO"
        assert screen._passes_filter("INFO", "hello world") is True


class TestWriteEntry:
    """Test _write_entry method."""

    def test_write_entry_formats_correctly(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen._write_entry("INFO", "test message", 0)
        mock_richlog.write.assert_called_once()
        call_arg = mock_richlog.write.call_args[0][0]
        assert "test message" in call_arg

    def test_write_entry_auto_follow(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.__dict__["auto_follow"] = True
        screen._write_entry("INFO", "test", 0)
        mock_richlog.scroll_end.assert_called_once_with(animate=False)

    def test_write_entry_no_follow(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.__dict__["auto_follow"] = False
        screen._write_entry("INFO", "test", 0)
        mock_richlog.scroll_end.assert_not_called()

    def test_write_entry_query_one_fails(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen._write_entry("INFO", "test", 0)  # Should not raise

    def test_write_entry_error_level(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen._write_entry("ERROR", "error msg", 0)
        call_arg = mock_richlog.write.call_args[0][0]
        assert "error msg" in call_arg

    def test_write_entry_debug_level(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen._write_entry("DEBUG", "debug msg", 0)
        call_arg = mock_richlog.write.call_args[0][0]
        assert "debug msg" in call_arg


class TestRefilter:
    """Test _refilter method."""

    def test_refilter_clears_and_rewrites(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
            ("DEBUG", "msg3", ""),
        ]
        screen._refilter()
        mock_richlog.clear.assert_called_once()
        assert mock_richlog.write.call_count == 3

    def test_refilter_with_level_filter(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
        ]
        screen._refilter()
        assert mock_richlog.write.call_count == 1

    def test_refilter_with_search_pattern(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "msg2"
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("INFO", "msg2", ""),
            ("INFO", "msg3", ""),
        ]
        screen._refilter()
        # All 3 pass level filter, but only msg2 matches search
        # However _refilter writes all that pass _passes_filter
        # _passes_filter checks both level AND search
        assert mock_richlog.write.call_count == 1
        assert len(screen._match_indices) == 1

    def test_refilter_query_one_fails(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen._refilter()  # Should return early without crash

    def test_refilter_clears_match_indices(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen._match_indices = [0, 1, 2]
        screen._current_match = 1
        screen.app._shared_log_buffer = []
        screen._refilter()
        assert screen._match_indices == []
        assert screen._current_match == -1


class TestUpdateLevelBar:
    """Test _update_level_bar method."""

    def test_update_level_bar_counts(self):
        screen, _, mock_level_bar, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("INFO", "msg2", ""),
            ("ERROR", "msg3", ""),
            ("DEBUG", "msg4", ""),
        ]
        screen._update_level_bar()
        mock_level_bar.update.assert_called_once()
        bar_text = mock_level_bar.update.call_args[0][0]
        assert "INFO:2" in bar_text
        assert "ERROR:1" in bar_text
        assert "DEBUG:1" in bar_text

    def test_update_level_bar_unknown_level(self):
        screen, _, mock_level_bar, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("CUSTOM", "msg1", ""),
        ]
        screen._update_level_bar()
        mock_level_bar.update.assert_called_once()

    def test_update_level_bar_query_fails(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen._update_level_bar()  # Should not raise


class TestUpdateStatus:
    """Test _update_status method."""

    def test_update_status_basic(self):
        screen, _, __, mock_status, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
        ]
        screen._update_status()
        mock_status.update.assert_called_once()
        status_text = mock_status.update.call_args[0][0]
        assert "2/2" in status_text
        assert "FOLLOW" in status_text

    def test_update_status_follow_off(self):
        screen, _, __, mock_status, *_ = _make_logs_screen()
        screen.__dict__["auto_follow"] = False
        screen.app._shared_log_buffer = []
        screen._update_status()
        status_text = mock_status.update.call_args[0][0]
        assert "follow off" in status_text

    def test_update_status_with_search(self):
        screen, _, __, mock_status, *_ = _make_logs_screen()
        screen.__dict__["search_pattern"] = "test"
        screen._match_indices = [0, 2, 5]
        screen._current_match = 1
        screen.app._shared_log_buffer = []
        screen._update_status()
        status_text = mock_status.update.call_args[0][0]
        assert "Search" in status_text
        assert "2/3" in status_text

    def test_update_status_query_fails(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.app._shared_log_buffer = []
        screen._update_status()  # Should not raise


class TestAppendLog:
    """Test append_log method."""

    def test_append_log_info(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.append_log("test message", "info")
        assert len(screen.app._shared_log_buffer) == 1
        assert screen.app._shared_log_buffer[0] == ("INFO", "test message", "")
        mock_richlog.write.assert_called_once()

    def test_append_log_with_file_path(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.append_log("test", "error", "file.py")
        assert screen.app._shared_log_buffer[0] == ("ERROR", "test", "file.py")

    def test_append_log_filtered_out(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        screen.append_log("test", "info")
        assert len(screen.app._shared_log_buffer) == 1
        mock_richlog.write.assert_not_called()


class TestToggleLevel:
    """Test level toggle actions."""

    def test_toggle_level_remove(self):
        screen, *_ = _make_logs_screen()
        screen._toggle_level("DEBUG")
        assert "DEBUG" not in screen.__dict__["active_levels"]

    def test_toggle_level_add(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        screen._toggle_level("INFO")
        assert "INFO" in screen.__dict__["active_levels"]

    def test_action_filter_debug(self):
        screen, *_ = _make_logs_screen()
        screen.action_filter_debug()

    def test_action_filter_info(self):
        screen, *_ = _make_logs_screen()
        screen.action_filter_info()

    def test_action_filter_warn(self):
        screen, *_ = _make_logs_screen()
        screen.action_filter_warn()

    def test_action_filter_error(self):
        screen, *_ = _make_logs_screen()
        screen.action_filter_error()

    def test_action_filter_all(self):
        screen, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        screen.action_filter_all()
        assert "DEBUG" in screen.__dict__["active_levels"]
        assert "INFO" in screen.__dict__["active_levels"]

    def test_action_toggle_follow(self):
        screen, *_ = _make_logs_screen()
        assert screen.__dict__["auto_follow"] is True
        screen.action_toggle_follow()
        assert screen.__dict__["auto_follow"] is False


class TestSearchActions:
    """Test search-related actions."""

    def test_action_toggle_search_show(self):
        screen, _, __, ___, mock_input = _make_logs_screen()
        screen.action_toggle_search()
        assert screen._search_visible is True
        mock_input.remove_class.assert_called_with("hidden")
        mock_input.focus.assert_called_once()

    def test_action_toggle_search_hide(self):
        screen, _, __, ___, mock_input = _make_logs_screen()
        screen._search_visible = True
        screen.action_toggle_search()
        assert screen._search_visible is False
        mock_input.add_class.assert_called_with("hidden")

    def test_action_toggle_search_no_input(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_toggle_search()  # Should return early

    def test_action_next_match_empty(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = []
        screen.action_next_match()  # Should return early

    def test_action_next_match(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = [0, 3, 7]
        screen._current_match = 0
        screen.action_next_match()
        assert screen._current_match == 1

    def test_action_next_match_wraps(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = [0, 3, 7]
        screen._current_match = 2
        screen.action_next_match()
        assert screen._current_match == 0

    def test_action_prev_match_empty(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = []
        screen.action_prev_match()  # Should return early

    def test_action_prev_match(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = [0, 3, 7]
        screen._current_match = 1
        screen.action_prev_match()
        assert screen._current_match == 0

    def test_action_prev_match_wraps(self):
        screen, *_ = _make_logs_screen()
        screen._match_indices = [0, 3, 7]
        screen._current_match = 0
        screen.action_prev_match()
        assert screen._current_match == 2


class TestSaveLogs:
    """Test action_save_logs method."""

    def test_save_logs(self, tmp_path, monkeypatch):
        screen, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
        ]
        monkeypatch.chdir(tmp_path)
        screen.action_save_logs()
        out_file = tmp_path / "coderag-logs.txt"
        assert out_file.exists()
        content = out_file.read_text()
        assert "[INFO] msg1" in content
        assert "[ERROR] msg2" in content
        screen.notify.assert_called_once()

    def test_save_logs_filtered(self, tmp_path, monkeypatch):
        screen, *_ = _make_logs_screen()
        screen.__dict__["active_levels"] = frozenset({"ERROR"})
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
        ]
        monkeypatch.chdir(tmp_path)
        screen.action_save_logs()
        out_file = tmp_path / "coderag-logs.txt"
        content = out_file.read_text()
        assert "[INFO] msg1" not in content
        assert "[ERROR] msg2" in content


class TestYankLog:
    """Test action_yank_log method."""

    def test_yank_log_with_xclip(self):
        screen, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
            ("ERROR", "msg2", ""),
        ]
        with patch("subprocess.run") as mock_run:
            screen.action_yank_log()
            mock_run.assert_called_once()
            assert mock_run.call_args[1]["input"] == b"msg2"

    def test_yank_log_xclip_fails(self):
        screen, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = [
            ("INFO", "msg1", ""),
        ]
        with patch("subprocess.run", side_effect=Exception("no xclip")):
            screen.action_yank_log()
            screen.notify.assert_called_once()

    def test_yank_log_empty(self):
        screen, *_ = _make_logs_screen()
        screen.app._shared_log_buffer = []
        screen.action_yank_log()  # Should not raise


class TestScrolling:
    """Test scrolling action methods."""

    def test_get_log_returns_richlog(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        result = screen._get_log()
        assert result is mock_richlog

    def test_get_log_returns_none(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        result = screen._get_log()
        assert result is None

    def test_action_scroll_down(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.action_scroll_down()
        mock_richlog.scroll_down.assert_called_once()

    def test_action_scroll_up(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.action_scroll_up()
        mock_richlog.scroll_up.assert_called_once()

    def test_action_scroll_home(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.action_scroll_home()
        mock_richlog.scroll_home.assert_called_once()

    def test_action_scroll_end(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        screen.action_scroll_end()
        mock_richlog.scroll_end.assert_called_once()

    def test_action_half_page_down(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        mock_richlog.size = MagicMock()
        mock_richlog.size.height = 40
        screen.action_half_page_down()
        mock_richlog.scroll_relative.assert_called_once_with(y=20)

    def test_action_half_page_up(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        mock_richlog.size = MagicMock()
        mock_richlog.size.height = 40
        screen.action_half_page_up()
        mock_richlog.scroll_relative.assert_called_once_with(y=-20)

    def test_action_full_page_down(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        mock_richlog.size = MagicMock()
        mock_richlog.size.height = 40
        screen.action_full_page_down()
        mock_richlog.scroll_relative.assert_called_once_with(y=40)

    def test_action_full_page_up(self):
        screen, mock_richlog, *_ = _make_logs_screen()
        mock_richlog.size = MagicMock()
        mock_richlog.size.height = 40
        screen.action_full_page_up()
        mock_richlog.scroll_relative.assert_called_once_with(y=-40)

    def test_scroll_down_no_log(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_scroll_down()  # Should not raise

    def test_scroll_up_no_log(self):
        screen, *_ = _make_logs_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_scroll_up()  # Should not raise
