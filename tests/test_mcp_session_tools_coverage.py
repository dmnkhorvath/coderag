"""Tests for session_tools.py MCP wrapper functions (lines 250-316).

Covers the @mcp.tool decorated wrapper functions that delegate to _impl functions.
"""

from __future__ import annotations

import os

import pytest

from coderag.session.store import SessionStore


@pytest.fixture
def session_store(tmp_path):
    """Create a real SessionStore for testing."""
    db_path = os.path.join(str(tmp_path), "session.db")
    store = SessionStore(db_path)
    return store


class MockMCP:
    """Mock FastMCP server that captures registered tool functions."""

    def __init__(self):
        self.tools = {}

    def tool(self, name: str, description: str = ""):
        """Decorator that captures the function."""

        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


class TestSessionToolWrappers:
    """Test the @mcp.tool wrapper functions registered by register_session_tools."""

    def _register(self, session_store):
        """Register tools and return the mock MCP with captured functions."""
        from coderag.mcp.session_tools import register_session_tools

        mock_mcp = MockMCP()
        register_session_tools(mock_mcp, session_store)
        return mock_mcp

    def test_session_log_read_wrapper(self, session_store):
        """Cover line 250: session_log_read wrapper."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_read"](file_path="src/main.py")
        assert isinstance(result, str)
        assert "main.py" in result or "Logged" in result or "read" in result.lower()

    def test_session_log_read_with_lines(self, session_store):
        """Cover session_log_read with line_start and line_end."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_read"](file_path="src/main.py", line_start=10, line_end=20)
        assert isinstance(result, str)

    def test_session_log_edit_wrapper(self, session_store):
        """Cover line 260: session_log_edit wrapper."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_edit"](file_path="src/main.py", description="Fixed bug")
        assert isinstance(result, str)

    def test_session_log_decision_wrapper(self, session_store):
        """Cover line 270: session_log_decision wrapper."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_decision"](decision="Use JWT for auth", rationale="Better for API")
        assert isinstance(result, str)

    def test_session_log_task_wrapper(self, session_store):
        """Cover line 279: session_log_task wrapper."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_task"](task="Add rate limiting", status="open")
        assert isinstance(result, str)

    def test_session_log_fact_wrapper(self, session_store):
        """Cover line 289: session_log_fact wrapper."""
        mcp = self._register(session_store)
        result = mcp.tools["session_log_fact"](fact="Database uses PostgreSQL", source="config.py")
        assert isinstance(result, str)

    def test_session_get_history_wrapper(self, session_store):
        """Cover line 298: session_get_history wrapper."""
        mcp = self._register(session_store)
        # First log something so there's history
        mcp.tools["session_log_read"](file_path="test.py")
        result = mcp.tools["session_get_history"](event_type=None, limit=20)
        assert isinstance(result, str)

    def test_session_get_history_with_filter(self, session_store):
        """Cover session_get_history with event_type filter."""
        mcp = self._register(session_store)
        mcp.tools["session_log_read"](file_path="test.py")
        result = mcp.tools["session_get_history"](event_type="read", limit=5)
        assert isinstance(result, str)

    def test_session_get_hot_files_wrapper(self, session_store):
        """Cover line 307: session_get_hot_files wrapper."""
        mcp = self._register(session_store)
        # Log some reads first
        mcp.tools["session_log_read"](file_path="hot.py")
        mcp.tools["session_log_read"](file_path="hot.py")
        result = mcp.tools["session_get_hot_files"](limit=10)
        assert isinstance(result, str)

    def test_session_get_context_wrapper(self, session_store):
        """Cover line 316: session_get_context wrapper."""
        mcp = self._register(session_store)
        # Log a decision first
        mcp.tools["session_log_decision"](decision="Use microservices", rationale="Scale")
        result = mcp.tools["session_get_context"](category=None)
        assert isinstance(result, str)

    def test_session_get_context_with_category(self, session_store):
        """Cover session_get_context with category filter."""
        mcp = self._register(session_store)
        mcp.tools["session_log_decision"](decision="Use JWT", rationale="API auth")
        result = mcp.tools["session_get_context"](category="decision")
        assert isinstance(result, str)

    def test_all_eight_tools_registered(self, session_store):
        """Verify all 8 session tools are registered."""
        mcp = self._register(session_store)
        expected_tools = [
            "session_log_read",
            "session_log_edit",
            "session_log_decision",
            "session_log_task",
            "session_log_fact",
            "session_get_history",
            "session_get_hot_files",
            "session_get_context",
        ]
        for tool_name in expected_tools:
            assert tool_name in mcp.tools, f"Missing tool: {tool_name}"
