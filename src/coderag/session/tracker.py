"""High-level session event tracking.

Provides a convenient API for logging session events
without dealing with raw SQL or session IDs.
"""

from __future__ import annotations

import logging
from typing import Any

from coderag.session.store import SessionStore

logger = logging.getLogger(__name__)


class SessionTracker:
    """High-level session event tracker.

    Wraps SessionStore with convenient methods for logging
    reads, edits, queries, decisions, tasks, and facts.

    Args:
        store: An initialized SessionStore instance.
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._current_session_id: str | None = None

    @property
    def current_session_id(self) -> str | None:
        """Return the current session ID, or None if no session is active."""
        return self._current_session_id

    def start_session(self, tool: str | None = None, prompt: str | None = None) -> str:
        """Start a new session and return its ID."""
        self._current_session_id = self._store.create_session(tool=tool, prompt=prompt)
        logger.info("Started session %s (tool=%s)", self._current_session_id, tool)
        return self._current_session_id

    def end_session(self) -> None:
        """End the current session."""
        if self._current_session_id is None:
            logger.warning("No active session to end")
            return
        self._store.end_session(self._current_session_id)
        logger.info("Ended session %s", self._current_session_id)
        self._current_session_id = None

    def _require_session(self) -> str:
        """Return current session ID or raise."""
        if self._current_session_id is None:
            raise RuntimeError("No active session. Call start_session() first.")
        return self._current_session_id

    def log_read(self, file_path: str, metadata: dict[str, Any] | None = None) -> None:
        """Log a file read event."""
        sid = self._require_session()
        self._store.log_event(sid, "read", file_path, metadata)

    def log_edit(self, file_path: str, metadata: dict[str, Any] | None = None) -> None:
        """Log a file edit event."""
        sid = self._require_session()
        self._store.log_event(sid, "edit", file_path, metadata)

    def log_query(
        self,
        query_text: str,
        results_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a query event."""
        sid = self._require_session()
        meta = dict(metadata) if metadata else {}
        meta["results_count"] = results_count
        self._store.log_event(sid, "query", query_text, meta)

    def log_decision(self, decision_text: str, metadata: dict[str, Any] | None = None) -> None:
        """Log an architectural decision."""
        sid = self._require_session()
        self._store.log_event(sid, "decision", decision_text, metadata)
        self._store.save_context("decision", decision_text, session_id=sid)

    def log_task(
        self,
        task_text: str,
        status: str = "open",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a task."""
        sid = self._require_session()
        meta = dict(metadata) if metadata else {}
        meta["status"] = status
        self._store.log_event(sid, "task", task_text, meta)
        self._store.save_context("task", task_text, session_id=sid)

    def log_fact(self, fact_text: str, metadata: dict[str, Any] | None = None) -> None:
        """Log a fact about the codebase."""
        sid = self._require_session()
        self._store.log_event(sid, "fact", fact_text, metadata)
        self._store.save_context("fact", fact_text, session_id=sid)

    def get_hot_files(self, limit: int = 20) -> list[tuple[str, int]]:
        """Get most accessed files across all sessions."""
        return self._store.get_hot_files(limit=limit)

    def get_session_summary(self) -> dict:
        """Get summary of the current session."""
        sid = self._require_session()
        events = self._store.get_events(session_id=sid, limit=10000)
        type_counts: dict[str, int] = {}
        for ev in events:
            type_counts[ev.event_type] = type_counts.get(ev.event_type, 0) + 1

        unique_files = set()
        for ev in events:
            if ev.event_type in ("read", "edit"):
                unique_files.add(ev.target)

        return {
            "session_id": sid,
            "total_events": len(events),
            "event_types": type_counts,
            "unique_files": len(unique_files),
            "files_touched": sorted(unique_files),
        }
