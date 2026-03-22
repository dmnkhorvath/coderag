"""Data models for session memory and context persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionEvent:
    """A single event within a coding session."""

    timestamp: datetime
    event_type: str  # "read", "edit", "query", "decision", "task", "fact"
    target: str  # file path, symbol name, or query text
    metadata: dict = field(default_factory=dict)
    session_id: str = ""


@dataclass
class SessionMemory:
    """Aggregated session memory for a project."""

    project_root: str
    sessions: list[SessionEvent] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    hot_files: dict[str, int] = field(default_factory=dict)
