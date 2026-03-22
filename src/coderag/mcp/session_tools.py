"""MCP Tools for session memory and context persistence.

Registers 8 session tools on a FastMCP server instance that expose
session tracking and context management to AI coding assistants.

Each tool has a public `_impl` function for testability.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from coderag.session.injector import ContextInjector
from coderag.session.store import SessionStore
from coderag.session.tracker import SessionTracker

logger = logging.getLogger(__name__)

# Module-level tracker, initialized when tools are registered
_tracker: SessionTracker | None = None
_store: SessionStore | None = None
_injector: ContextInjector | None = None


def _get_tracker() -> SessionTracker:
    """Get the module-level tracker, auto-starting a session if needed."""
    if _tracker is None:
        raise RuntimeError("Session tools not initialized. Call register_session_tools first.")
    if _tracker.current_session_id is None:
        _tracker.start_session(tool="mcp")
    return _tracker


def _get_store() -> SessionStore:
    if _store is None:
        raise RuntimeError("Session tools not initialized. Call register_session_tools first.")
    return _store


def _get_injector() -> ContextInjector:
    if _injector is None:
        raise RuntimeError("Session tools not initialized. Call register_session_tools first.")
    return _injector


# ── Implementation functions (testable without MCP) ───────────


def session_log_read_impl(
    store: SessionStore,
    tracker: SessionTracker,
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Log a file read event. Returns status string."""
    try:
        if tracker.current_session_id is None:
            return "\u274c Error: No active session. Start a session first."
        metadata: dict[str, Any] = {}
        if line_start is not None:
            metadata["line_start"] = line_start
        if line_end is not None:
            metadata["line_end"] = line_end
        tracker.log_read(file_path, metadata=metadata or None)
        return f"\u2705 Logged read: {file_path}"
    except Exception as e:
        logger.exception("Error logging read")
        return f"\u274c Error logging read: {e}"


def session_log_edit_impl(
    store: SessionStore,
    tracker: SessionTracker,
    file_path: str,
    description: str = "",
) -> str:
    """Log a file edit event. Returns status string."""
    try:
        if tracker.current_session_id is None:
            return "\u274c Error: No active session. Start a session first."
        metadata: dict[str, Any] = {}
        if description:
            metadata["description"] = description
        tracker.log_edit(file_path, metadata=metadata or None)
        return f"\u2705 Logged edit: {file_path}"
    except Exception as e:
        logger.exception("Error logging edit")
        return f"\u274c Error logging edit: {e}"


def session_log_decision_impl(
    store: SessionStore,
    tracker: SessionTracker,
    decision: str,
    rationale: str = "",
) -> str:
    """Log an architectural decision. Returns status string."""
    try:
        if tracker.current_session_id is None:
            return "\u274c Error: No active session. Start a session first."
        metadata: dict[str, Any] = {}
        if rationale:
            metadata["rationale"] = rationale
        tracker.log_decision(decision, metadata=metadata or None)
        return f"\u2705 Logged decision: {decision}"
    except Exception as e:
        logger.exception("Error logging decision")
        return f"\u274c Error logging decision: {e}"


def session_log_task_impl(
    store: SessionStore,
    tracker: SessionTracker,
    task: str,
    status: str = "open",
) -> str:
    """Log a task. Returns status string."""
    try:
        if tracker.current_session_id is None:
            return "\u274c Error: No active session. Start a session first."
        tracker.log_task(task, status=status)
        return f"\u2705 Logged task [{status}]: {task}"
    except Exception as e:
        logger.exception("Error logging task")
        return f"\u274c Error logging task: {e}"


def session_log_fact_impl(
    store: SessionStore,
    tracker: SessionTracker,
    fact: str,
    source: str = "",
) -> str:
    """Log a codebase fact. Returns status string."""
    try:
        if tracker.current_session_id is None:
            return "\u274c Error: No active session. Start a session first."
        metadata: dict[str, Any] = {}
        if source:
            metadata["source"] = source
        tracker.log_fact(fact, metadata=metadata or None)
        return f"\u2705 Logged fact: {fact}"
    except Exception as e:
        logger.exception("Error logging fact")
        return f"\u274c Error logging fact: {e}"


def session_get_history_impl(
    store: SessionStore,
    event_type: str | None = None,
    limit: int = 20,
) -> str:
    """Get session event history. Returns formatted string."""
    try:
        events = store.get_events(event_type=event_type, limit=limit)
        if not events:
            return "No events found."

        lines = [f"## Session History ({len(events)} events)\n"]
        for ev in events:
            ts = ev.timestamp.strftime("%Y-%m-%d %H:%M")
            meta_str = ""
            if ev.metadata:
                meta_str = f" | {json.dumps(ev.metadata, default=str)}"
            lines.append(f"- [{ts}] **{ev.event_type}**: {ev.target}{meta_str}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("Error getting history")
        return f"\u274c Error getting history: {e}"


def session_get_hot_files_impl(
    store: SessionStore,
    limit: int = 10,
) -> str:
    """Get hot files. Returns formatted string."""
    try:
        hot_files = store.get_hot_files(limit=limit)
        if not hot_files:
            return "No hot files found."

        lines = [f"## Hot Files (top {len(hot_files)})\n"]
        for i, (path, count) in enumerate(hot_files, 1):
            lines.append(f"{i}. `{path}` \u2014 {count} accesses")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("Error getting hot files")
        return f"\u274c Error getting hot files: {e}"


def session_get_context_impl(
    store: SessionStore,
    category: str | None = None,
) -> str:
    """Get persisted context. Returns formatted string."""
    try:
        items = store.get_context(category=category, active_only=True)
        if not items:
            filter_msg = f" for category '{category}'" if category else ""
            return f"No active context items{filter_msg}."

        lines = [f"## Persisted Context ({len(items)} items)\n"]
        for item in items:
            created = item["created_at"][:10]
            cat = item["category"]
            content = item["content"]
            active = "\u2705" if item["active"] else "\u274c"
            lines.append(f"- [{created}] **{cat}** {active}: {content}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("Error getting context")
        return f"\u274c Error getting context: {e}"


# ── MCP Registration ──────────────────────────────────────────


def register_session_tools(mcp: Any, session_store: SessionStore) -> None:
    """Register all 8 session tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance.
        session_store: Initialized SessionStore.
    """
    global _tracker, _store, _injector
    _store = session_store
    _tracker = SessionTracker(session_store)
    _injector = ContextInjector(session_store)

    logger.info("Registering 8 session MCP tools")

    @mcp.tool(
        name="session_log_read",
        description=(
            "Log that a file was read in the current session. "
            "Tracks file access patterns to identify hot files across sessions."
        ),
    )
    def session_log_read(
        file_path: str,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> str:
        return session_log_read_impl(_store, _get_tracker(), file_path, line_start, line_end)

    @mcp.tool(
        name="session_log_edit",
        description=(
            "Log that a file was edited in the current session. "
            "Tracks edit patterns to identify frequently modified files."
        ),
    )
    def session_log_edit(file_path: str, description: str = "") -> str:
        return session_log_edit_impl(_store, _get_tracker(), file_path, description)

    @mcp.tool(
        name="session_log_decision",
        description=(
            "Log an architectural or design decision made during the session. "
            "Decisions persist across sessions and appear in context injection."
        ),
    )
    def session_log_decision(decision: str, rationale: str = "") -> str:
        return session_log_decision_impl(_store, _get_tracker(), decision, rationale)

    @mcp.tool(
        name="session_log_task",
        description=(
            "Log a task identified during the session. Tasks persist across sessions with status tracking (open/done)."
        ),
    )
    def session_log_task(task: str, status: str = "open") -> str:
        return session_log_task_impl(_store, _get_tracker(), task, status)

    @mcp.tool(
        name="session_log_fact",
        description=(
            "Log a fact learned about the codebase during the session. "
            "Facts persist across sessions and appear in context injection."
        ),
    )
    def session_log_fact(fact: str, source: str = "") -> str:
        return session_log_fact_impl(_store, _get_tracker(), fact, source)

    @mcp.tool(
        name="session_get_history",
        description=(
            "Get session event history. Optionally filter by event type. Returns recent events across all sessions."
        ),
    )
    def session_get_history(event_type: str | None = None, limit: int = 20) -> str:
        return session_get_history_impl(_get_store(), event_type, limit)

    @mcp.tool(
        name="session_get_hot_files",
        description=(
            "Get the most frequently accessed files across all sessions. Shows files ranked by total read + edit count."
        ),
    )
    def session_get_hot_files(limit: int = 10) -> str:
        return session_get_hot_files_impl(_get_store(), limit)

    @mcp.tool(
        name="session_get_context",
        description=(
            "Get persisted context items (decisions, tasks, facts) from all sessions. Optionally filter by category."
        ),
    )
    def session_get_context(category: str | None = None) -> str:
        return session_get_context_impl(_get_store(), category)

    logger.info("Registered 8 session MCP tools")
