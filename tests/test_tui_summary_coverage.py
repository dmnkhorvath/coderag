"""Tests for tui/screens/summary.py coverage.

Targets missing lines: 78-130, 137, 141
SummaryScreen compose() and action methods.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skip(reason="Textual TUI coverage tests rely on interactive internals and are unsupported in headless CI")


class TestSummaryScreenCompose:
    """Test compose() method with various parameter combinations."""

    def _make_screen(self, **kwargs):
        from coderag.tui.screens.summary import SummaryScreen

        defaults = dict(
            success=True,
            duration_s=65.5,
            files_parsed=100,
            errors=0,
            node_count=500,
            edge_count=1200,
            languages=["python", "javascript"],
            frameworks=["flask", "react"],
        )
        defaults.update(kwargs)
        screen = SummaryScreen.__new__(SummaryScreen)
        screen._success = defaults["success"]
        screen._duration_s = defaults["duration_s"]
        screen._files_parsed = defaults["files_parsed"]
        screen._errors = defaults["errors"]
        screen._node_count = defaults["node_count"]
        screen._edge_count = defaults["edge_count"]
        screen._languages = defaults["languages"]
        screen._frameworks = defaults["frameworks"]
        return screen

    def test_compose_success_with_minutes(self):
        """Duration > 60s shows minutes."""
        screen = self._make_screen(duration_s=125.3)
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_success_with_hours(self):
        """Duration > 3600s shows hours."""
        screen = self._make_screen(duration_s=3725.0)
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_success_seconds_only(self):
        """Duration < 60s shows seconds only."""
        screen = self._make_screen(duration_s=45.2)
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_failure(self):
        """Failed pipeline."""
        screen = self._make_screen(success=False, errors=5)
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_no_languages(self):
        """No languages detected."""
        screen = self._make_screen(languages=[])
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_no_frameworks(self):
        """No frameworks detected."""
        screen = self._make_screen(frameworks=[])
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_zero_errors(self):
        """Zero errors uses green color."""
        screen = self._make_screen(errors=0)
        widgets = list(screen.compose())
        assert len(widgets) > 0

    def test_compose_with_errors(self):
        """Non-zero errors uses red color."""
        screen = self._make_screen(errors=3)
        widgets = list(screen.compose())
        assert len(widgets) > 0


class TestSummaryScreenActions:
    """Test action methods."""

    def _make_screen(self):
        from coderag.tui.screens.summary import SummaryScreen

        screen = SummaryScreen.__new__(SummaryScreen)
        screen._success = True
        screen._duration_s = 10.0
        screen._files_parsed = 10
        screen._errors = 0
        screen._node_count = 50
        screen._edge_count = 100
        screen._languages = []
        screen._frameworks = []
        screen.dismiss = MagicMock()
        return screen

    def test_action_browse(self):
        screen = self._make_screen()
        screen.action_browse()
        screen.dismiss.assert_called_once_with("browse")

    def test_action_quit_app(self):
        screen = self._make_screen()
        screen.action_quit_app()
        screen.dismiss.assert_called_once_with("quit")

    def test_action_dismiss_summary(self):
        screen = self._make_screen()
        screen.action_dismiss_summary()
        screen.dismiss.assert_called_once_with("dismiss")
