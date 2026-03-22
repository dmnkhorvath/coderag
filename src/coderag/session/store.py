"""SQLite storage for session memory and context persistence.

Creates session-specific tables in the existing .codegraph/graph.db
or a standalone database file.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from coderag.session.models import SessionEvent

logger = logging.getLogger(__name__)

_SESSION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    tool TEXT,
    prompt TEXT,
    total_events INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    target TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS context_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    session_id TEXT,
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON session_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_target ON session_events(target);
CREATE INDEX IF NOT EXISTS idx_context_category ON context_store(category);
"""


class SessionStore:
    """SQLite-backed session memory storage.

    Works with the existing graph.db or a standalone database.
    Creates session tables on initialization.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        """Create connection and session tables."""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row

        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout = 30000")
        except sqlite3.OperationalError:
            pass

        self._conn.executescript(_SESSION_SCHEMA_SQL)
        logger.info("SessionStore initialized at %s", self._db_path)

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the active connection."""
        if self._conn is None:
            raise RuntimeError("SessionStore is closed")
        return self._conn

    def _execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a write operation with thread-safe locking."""
        with self._write_lock:
            cursor = self.connection.execute(sql, params)
            self.connection.commit()
            return cursor

    def _execute_write_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute multiple write operations."""
        with self._write_lock:
            self.connection.executemany(sql, params_list)
            self.connection.commit()

    # ── Session lifecycle ─────────────────────────────────────

    def create_session(self, tool: str | None = None, prompt: str | None = None) -> str:
        """Create a new session and return its ID."""
        import uuid

        session_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        self._execute_write(
            "INSERT INTO sessions (id, started_at, tool, prompt, total_events) VALUES (?, ?, ?, ?, 0)",
            (session_id, now, tool, prompt),
        )
        logger.debug("Created session %s", session_id)
        return session_id

    def end_session(self, session_id: str) -> None:
        """End a session: set ended_at and update total_events count."""
        now = datetime.now().isoformat()
        # Count events for this session
        row = self.connection.execute(
            "SELECT COUNT(*) as cnt FROM session_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        total = row["cnt"] if row else 0
        self._execute_write(
            "UPDATE sessions SET ended_at = ?, total_events = ? WHERE id = ?",
            (now, total, session_id),
        )
        logger.debug("Ended session %s with %d events", session_id, total)

    # ── Event logging ─────────────────────────────────────────

    def log_event(
        self,
        session_id: str,
        event_type: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a session event."""
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata) if metadata else None
        self._execute_write(
            "INSERT INTO session_events (session_id, timestamp, event_type, target, metadata) VALUES (?, ?, ?, ?, ?)",
            (session_id, now, event_type, target, meta_json),
        )

    def get_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        target: str | None = None,
        limit: int = 100,
    ) -> list[SessionEvent]:
        """Query session events with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if target is not None:
            conditions.append("target = ?")
            params.append(target)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM session_events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.connection.execute(sql, tuple(params)).fetchall()
        events: list[SessionEvent] = []
        for row in rows:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            events.append(
                SessionEvent(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    event_type=row["event_type"],
                    target=row["target"],
                    metadata=meta,
                    session_id=row["session_id"],
                )
            )
        return events

    # ── Context store (decisions, tasks, facts) ───────────────

    def save_context(
        self,
        category: str,
        content: str,
        session_id: str | None = None,
    ) -> int:
        """Save a context item (decision, task, fact). Returns the context ID."""
        now = datetime.now().isoformat()
        cursor = self._execute_write(
            "INSERT INTO context_store (category, content, created_at, session_id, active) VALUES (?, ?, ?, ?, 1)",
            (category, content, now, session_id),
        )
        return cursor.lastrowid or 0

    def get_context(
        self,
        category: str | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[dict]:
        """Get context items, optionally filtered by category."""
        conditions: list[str] = []
        params: list[Any] = []

        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if active_only:
            conditions.append("active = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM context_store {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id": row["id"],
                "category": row["category"],
                "content": row["content"],
                "created_at": row["created_at"],
                "session_id": row["session_id"],
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    def deactivate_context(self, context_id: int) -> None:
        """Deactivate a context item (e.g., mark task as done)."""
        self._execute_write(
            "UPDATE context_store SET active = 0 WHERE id = ?",
            (context_id,),
        )

    # ── Aggregation queries ───────────────────────────────────

    def get_hot_files(self, limit: int = 20) -> list[tuple[str, int]]:
        """Get most accessed files across all sessions."""
        sql = """
            SELECT target, COUNT(*) as access_count
            FROM session_events
            WHERE event_type IN ('read', 'edit')
            GROUP BY target
            ORDER BY access_count DESC
            LIMIT ?
        """
        rows = self.connection.execute(sql, (limit,)).fetchall()
        return [(row["target"], row["access_count"]) for row in rows]

    def get_recent_sessions(self, limit: int = 5) -> list[dict]:
        """Get recent session summaries."""
        sql = """
            SELECT s.id, s.started_at, s.ended_at, s.tool, s.prompt, s.total_events,
                   COUNT(e.id) as event_count
            FROM sessions s
            LEFT JOIN session_events e ON s.id = e.session_id
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT ?
        """
        rows = self.connection.execute(sql, (limit,)).fetchall()
        return [
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "tool": row["tool"],
                "prompt": row["prompt"],
                "total_events": row["total_events"],
                "event_count": row["event_count"],
            }
            for row in rows
        ]

    # ── Lifecycle ─────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("SessionStore closed")
