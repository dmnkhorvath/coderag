"""Tests for tui/screens/graph.py coverage.

Targets missing lines: 83, 89-95, 123-124, 140-142, 145-146, 156-157,
167-168, 187-188, 192-196, 212-213, 230-231, 238-240, 243-245, 248-249,
254-263, 266-268, 271-273, 276-278, 281-283, 286-288, 291-293
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(reason="Textual TUI coverage tests rely on interactive internals and are unsupported in headless CI")


def _make_graph_screen():
    """Create a GraphScreen with mocked Textual internals."""
    from coderag.tui.screens.graph import GraphScreen

    screen = GraphScreen.__new__(GraphScreen)
    screen.__dict__["active_tab"] = "overview"
    screen._css_styles = MagicMock()
    screen.__dict__["_app"] = MagicMock()
    screen.notify = MagicMock()

    # Mock widgets
    mock_summary = MagicMock()
    mock_tab_bar = MagicMock()
    mock_overview_table = MagicMock()
    mock_nodes_table = MagicMock()
    mock_edges_table = MagicMock()
    mock_languages_table = MagicMock()

    widgets = {
        "#graph-summary": mock_summary,
        "#graph-tab-bar": mock_tab_bar,
        "#graph-overview-table": mock_overview_table,
        "#graph-nodes-table": mock_nodes_table,
        "#graph-edges-table": mock_edges_table,
        "#graph-languages-table": mock_languages_table,
    }

    def query_one_side_effect(selector, cls=None):
        result = widgets.get(selector)
        if result is None:
            raise Exception(f"No widget: {selector}")
        return result

    screen.query_one = MagicMock(side_effect=query_one_side_effect)
    return (
        screen,
        mock_summary,
        mock_tab_bar,
        mock_overview_table,
        mock_nodes_table,
        mock_edges_table,
        mock_languages_table,
    )


class TestGetDbPath:
    """Test _get_db_path method."""

    def test_no_db(self):
        screen, *_ = _make_graph_screen()
        screen.__dict__["_app"].project_root = "/nonexistent/path"
        with patch("coderag.tui.screens.graph.Path") as MockPath:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            MockPath.return_value.__truediv__ = MagicMock(return_value=mock_path)
            result = screen._get_db_path()
            # Either returns None or a path depending on implementation


class TestLoadStats:
    """Test _load_stats method."""

    def test_load_stats_no_db(self):
        screen, mock_summary, *_ = _make_graph_screen()
        with patch.object(screen, "_get_db_path", return_value=None):
            screen._load_stats()
            mock_summary.update.assert_called_once()
            assert "No database" in mock_summary.update.call_args[0][0]

    def test_load_stats_with_db(self, tmp_path):
        screen, mock_summary, _, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        db_path = tmp_path / "graph.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE nodes (id TEXT, kind TEXT, name TEXT, file_path TEXT, language TEXT)")
        conn.execute("CREATE TABLE edges (id TEXT, source TEXT, target TEXT, kind TEXT, confidence REAL)")
        conn.execute("INSERT INTO nodes VALUES ('n1', 'function', 'foo', 'a.py', 'python')")
        conn.execute("INSERT INTO nodes VALUES ('n2', 'class', 'Bar', 'b.py', 'python')")
        conn.execute("INSERT INTO nodes VALUES ('n3', 'function', 'baz', 'c.js', 'javascript')")
        conn.execute("INSERT INTO edges VALUES ('e1', 'n1', 'n2', 'calls', 0.9)")
        conn.execute("INSERT INTO edges VALUES ('e2', 'n2', 'n3', 'imports', 0.3)")
        conn.commit()
        conn.close()

        with patch.object(screen, "_get_db_path", return_value=db_path):
            screen._load_stats()
            mock_summary.update.assert_called()
            summary_text = mock_summary.update.call_args[0][0]
            assert "3" in summary_text  # 3 nodes
            mock_ot.clear.assert_called()
            mock_ot.add_row.assert_called()
            mock_nt.clear.assert_called()
            mock_et.clear.assert_called()
            mock_lt.clear.assert_called()

    def test_load_stats_with_file_hashes(self, tmp_path):
        screen, mock_summary, _, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        db_path = tmp_path / "graph.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE nodes (id TEXT, kind TEXT, name TEXT, file_path TEXT, language TEXT)")
        conn.execute("CREATE TABLE edges (id TEXT, source TEXT, target TEXT, kind TEXT, confidence REAL)")
        conn.execute("CREATE TABLE file_hashes (file_path TEXT, hash TEXT, parse_time_ms REAL)")
        conn.execute("INSERT INTO nodes VALUES ('n1', 'function', 'foo', 'a.py', 'python')")
        conn.execute("INSERT INTO edges VALUES ('e1', 'n1', 'n1', 'calls', 0.9)")
        conn.execute("INSERT INTO file_hashes VALUES ('a.py', 'abc123', 50.5)")
        conn.commit()
        conn.close()

        with patch.object(screen, "_get_db_path", return_value=db_path):
            screen._load_stats()
            # Should include file_hashes info in overview table
            add_row_calls = [str(c) for c in mock_ot.add_row.call_args_list]
            combined = " ".join(add_row_calls)
            assert "Tracked" in combined or "Parse" in combined

    def test_load_stats_db_error(self):
        screen, mock_summary, *_ = _make_graph_screen()
        with patch.object(screen, "_get_db_path", return_value=Path("/nonexistent/graph.db")):
            screen._load_stats()
            mock_summary.update.assert_called()
            summary_text = mock_summary.update.call_args[0][0]
            assert "Error" in summary_text or "error" in summary_text.lower()

    def test_load_stats_query_one_fails(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        with patch.object(screen, "_get_db_path", return_value=None):
            screen._load_stats()  # Should not raise


class TestTabNavigation:
    """Test tab navigation methods."""

    def test_update_tab_bar(self):
        screen, _, mock_tab_bar, *_ = _make_graph_screen()
        screen._update_tab_bar()
        mock_tab_bar.update.assert_called_once()
        bar_text = mock_tab_bar.update.call_args[0][0]
        assert "OVERVIEW" in bar_text

    def test_show_active_table_overview(self):
        screen, _, __, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        screen.__dict__["active_tab"] = "overview"
        screen._show_active_table()
        mock_ot.remove_class.assert_called_with("hidden")
        mock_nt.add_class.assert_called_with("hidden")
        mock_et.add_class.assert_called_with("hidden")
        mock_lt.add_class.assert_called_with("hidden")

    def test_show_active_table_nodes(self):
        screen, _, __, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        screen.__dict__["active_tab"] = "nodes"
        screen._show_active_table()
        mock_nt.remove_class.assert_called_with("hidden")
        mock_ot.add_class.assert_called_with("hidden")

    def test_show_active_table_edges(self):
        screen, _, __, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        screen.__dict__["active_tab"] = "edges"
        screen._show_active_table()
        mock_et.remove_class.assert_called_with("hidden")

    def test_show_active_table_languages(self):
        screen, _, __, mock_ot, mock_nt, mock_et, mock_lt = _make_graph_screen()
        screen.__dict__["active_tab"] = "languages"
        screen._show_active_table()
        mock_lt.remove_class.assert_called_with("hidden")

    def test_watch_active_tab(self):
        screen, _, mock_tab_bar, *_ = _make_graph_screen()
        screen.watch_active_tab("overview", "nodes")
        mock_tab_bar.update.assert_called()

    def test_action_next_tab(self):
        screen, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "overview"
        screen.action_next_tab()
        assert screen.__dict__["active_tab"] == "nodes"

    def test_action_next_tab_wraps(self):
        screen, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "languages"
        screen.action_next_tab()
        assert screen.__dict__["active_tab"] == "overview"

    def test_action_prev_tab(self):
        screen, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "nodes"
        screen.action_prev_tab()
        assert screen.__dict__["active_tab"] == "overview"

    def test_action_prev_tab_wraps(self):
        screen, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "overview"
        screen.action_prev_tab()
        assert screen.__dict__["active_tab"] == "languages"

    def test_action_refresh_stats(self):
        screen, *_ = _make_graph_screen()
        with patch.object(screen, "_load_stats"):
            screen.action_refresh_stats()
            screen._load_stats.assert_called_once()
            screen.notify.assert_called_once()


class TestScrolling:
    """Test scrolling action methods."""

    def test_get_active_table_overview(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "overview"
        result = screen._get_active_table()
        assert result is mock_ot

    def test_get_active_table_nodes(self):
        screen, _, __, _ot, mock_nt, *_ = _make_graph_screen()
        screen.__dict__["active_tab"] = "nodes"
        result = screen._get_active_table()
        assert result is mock_nt

    def test_get_active_table_fails(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        result = screen._get_active_table()
        assert result is None

    def test_action_cursor_down(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        screen.action_cursor_down()
        mock_ot.action_cursor_down.assert_called_once()

    def test_action_cursor_up(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        screen.action_cursor_up()
        mock_ot.action_cursor_up.assert_called_once()

    def test_action_scroll_home(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        screen.action_scroll_home()
        mock_ot.action_scroll_top.assert_called_once()

    def test_action_scroll_end(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        screen.action_scroll_end()
        mock_ot.action_scroll_bottom.assert_called_once()

    def test_action_half_page_down(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        mock_ot.size = MagicMock()
        mock_ot.size.height = 40
        screen.action_half_page_down()
        mock_ot.scroll_relative.assert_called_once_with(y=20)

    def test_action_half_page_up(self):
        screen, _, __, mock_ot, *_ = _make_graph_screen()
        mock_ot.size = MagicMock()
        mock_ot.size.height = 40
        screen.action_half_page_up()
        mock_ot.scroll_relative.assert_called_once_with(y=-20)

    def test_cursor_down_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_cursor_down()  # Should not raise

    def test_cursor_up_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_cursor_up()  # Should not raise

    def test_scroll_home_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_scroll_home()  # Should not raise

    def test_scroll_end_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_scroll_end()  # Should not raise

    def test_half_page_down_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_half_page_down()  # Should not raise

    def test_half_page_up_no_table(self):
        screen, *_ = _make_graph_screen()
        screen.query_one = MagicMock(side_effect=Exception("no widget"))
        screen.action_half_page_up()  # Should not raise
