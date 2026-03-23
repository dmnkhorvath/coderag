"""Tests for token_tools.py — targeting uncovered lines 32, 58-109, 124-184."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field

import pytest


# ---------------------------------------------------------------------------
# Helpers to capture tools registered via @mcp.tool()
# ---------------------------------------------------------------------------

class FakeMCP:
    """Captures functions registered via @mcp.tool()."""

    def __init__(self):
        self.tools: dict[str, callable] = {}

    def tool(self, name: str | None = None, **kwargs):
        def decorator(fn):
            tool_name = name or fn.__name__
            self.tools[tool_name] = fn
            return fn
        return decorator


@dataclass
class FakeSessionStats:
    model: str = "claude-sonnet-4"
    total_events: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost: float = 0.0
    avg_input_per_event: float = 0.0
    avg_output_per_event: float = 0.0
    tokens_saved_by_cache: int = 0
    estimated_savings_pct: float = 0.0
    cost_by_type: dict = field(default_factory=dict)


@dataclass
class FakeTokenTracker:
    model: str = "claude-sonnet-4"
    _stats: FakeSessionStats = field(default_factory=FakeSessionStats)

    def log_tool_call(self, tool: str, input_text: str, output_text: str):
        pass

    def get_session_stats(self):
        return self._stats

    def reset(self):
        self._stats = FakeSessionStats()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_mcp():
    return FakeMCP()


@pytest.fixture
def fake_tracker():
    return FakeTokenTracker()


def _register_tools(fake_mcp, fake_tracker):
    """Register token tools with our fakes, patching the module globals."""
    import coderag.mcp.token_tools as mod

    # Patch the module-level _get_tracker to return our fake
    with patch.object(mod, "_get_tracker", return_value=fake_tracker):
        mod.register_token_tools(fake_mcp)

    return fake_mcp.tools


# ---------------------------------------------------------------------------
# Tests for token_count_text
# ---------------------------------------------------------------------------

class TestTokenCountText:
    """Cover lines 58-109: token_count_text tool."""

    def test_count_text_no_model(self, fake_mcp, fake_tracker):
        """When no model specified, shows cost table for all models."""
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_count_text"]
        # Call with _get_tracker patched
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn(text="Hello world, this is a test string.")

        assert "Token Count Analysis" in result
        assert "Characters" in result
        assert "Estimated tokens" in result
        assert "Cost Estimates" in result
        assert "Model" in result

    def test_count_text_with_valid_model(self, fake_mcp, fake_tracker):
        """When a valid model is specified, shows cost for that model."""
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_count_text"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn(text="Hello world", model="claude-sonnet-4")

        assert "Token Count Analysis" in result
        assert "Cost for" in result
        assert "As input" in result
        assert "As output" in result
        assert "As cached input" in result

    def test_count_text_with_invalid_model(self, fake_mcp, fake_tracker):
        """When an invalid model is specified, shows available models."""
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_count_text"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn(text="Hello world", model="nonexistent-model-xyz")

        assert "Unknown model" in result
        assert "Available" in result


# ---------------------------------------------------------------------------
# Tests for token_session_stats
# ---------------------------------------------------------------------------

class TestTokenSessionStats:
    """Cover lines 124-184: token_session_stats tool."""

    def test_session_stats_basic(self, fake_mcp, fake_tracker):
        """Basic session stats with zero events."""
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_session_stats"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn()

        assert "Session Token Statistics" in result
        assert "Token Usage" in result
        assert "Input tokens" in result

    def test_session_stats_with_events(self, fake_mcp, fake_tracker):
        """Session stats with events shows averages section."""
        fake_tracker._stats = FakeSessionStats(
            total_events=5,
            total_input_tokens=1000,
            total_output_tokens=500,
            avg_input_per_event=200.0,
            avg_output_per_event=100.0,
        )
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_session_stats"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn()

        assert "Averages" in result
        assert "Avg input/event" in result

    def test_session_stats_with_cache_savings(self, fake_mcp, fake_tracker):
        """Session stats with cache savings shows savings section."""
        fake_tracker._stats = FakeSessionStats(
            total_events=3,
            tokens_saved_by_cache=500,
            estimated_savings_pct=25.0,
        )
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_session_stats"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn()

        assert "Cache Savings" in result
        assert "Tokens served from cache" in result

    def test_session_stats_with_cost_by_type(self, fake_mcp, fake_tracker):
        """Session stats with cost_by_type shows cost breakdown."""
        fake_tracker._stats = FakeSessionStats(
            total_events=2,
            cost_by_type={"tool_call": 0.001, "context": 0.002},
        )
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_session_stats"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn()

        assert "Cost by Event Type" in result
        assert "tool_call" in result
        assert "context" in result

    def test_session_stats_with_model_switch(self, fake_mcp, fake_tracker):
        """Passing a valid model switches the tracker model."""
        import coderag.mcp.token_tools as mod
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            mod.register_token_tools(fake_mcp)
            tools = fake_mcp.tools

        fn = tools["token_session_stats"]
        with patch.object(mod, "_get_tracker", return_value=fake_tracker):
            result = fn(model="claude-sonnet-4")

        assert "Session Token Statistics" in result


# ---------------------------------------------------------------------------
# Tests for _get_tracker / _reset_tracker
# ---------------------------------------------------------------------------

class TestTrackerHelpers:
    """Cover line 32: _get_tracker auto-creates tracker."""

    def test_get_tracker_creates_default(self):
        """_get_tracker creates a tracker if none exists."""
        import coderag.mcp.token_tools as mod
        # Reset the global
        original = mod._session_tracker
        try:
            mod._session_tracker = None
            tracker = mod._get_tracker()
            assert tracker is not None
            assert tracker.model == "claude-sonnet-4"
        finally:
            mod._session_tracker = original

    def test_get_tracker_returns_existing(self):
        """_get_tracker returns existing tracker."""
        import coderag.mcp.token_tools as mod
        original = mod._session_tracker
        try:
            mod._session_tracker = FakeTokenTracker(model="test-model")
            tracker = mod._get_tracker()
            assert tracker.model == "test-model"
        finally:
            mod._session_tracker = original

    def test_reset_tracker(self):
        """_reset_tracker creates a new tracker with specified model."""
        import coderag.mcp.token_tools as mod
        original = mod._session_tracker
        try:
            tracker = mod.reset_tracker(model="gpt-4o")
            assert tracker.model == "gpt-4o"
            assert mod._session_tracker is tracker
        finally:
            mod._session_tracker = original
