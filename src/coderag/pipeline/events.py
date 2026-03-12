"""Pipeline event system for real-time progress reporting.

Provides an EventEmitter that the TUI (or any observer) can subscribe to.
The emitter is optional — headless CLI works without it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class PipelinePhase(str, Enum):
    """Phases of the extraction pipeline."""
    DISCOVERY = "discovery"
    HASHING = "hashing"
    EXTRACTION = "extraction"
    RESOLUTION = "resolution"
    FRAMEWORK_DETECTION = "framework_detection"
    CROSS_LANGUAGE = "cross_language"
    STYLE_MATCHING = "style_matching"
    GIT_ENRICHMENT = "git_enrichment"
    PERSISTENCE = "persistence"


# ── Base Event ────────────────────────────────────────────────

@dataclass
class PipelineEvent:
    """Base class for all pipeline events."""
    phase: PipelinePhase
    timestamp: float = field(default_factory=time.time)


# ── Phase-level events ────────────────────────────────────────

@dataclass
class PhaseStarted(PipelineEvent):
    """Emitted when a pipeline phase begins."""
    total_items: int = 0


@dataclass
class PhaseProgress(PipelineEvent):
    """Emitted to report progress within a phase."""
    current: int = 0
    total: int = 0
    message: str = ""
    file_path: str = ""


@dataclass
class PhaseCompleted(PipelineEvent):
    """Emitted when a pipeline phase finishes."""
    summary: dict = field(default_factory=dict)
    duration_ms: float = 0.0


# ── File-level events ─────────────────────────────────────────

@dataclass
class FileStarted(PipelineEvent):
    """Emitted when extraction begins on a file."""
    file_path: str = ""
    language: str = ""


@dataclass
class FileCompleted(PipelineEvent):
    """Emitted when extraction finishes on a file."""
    file_path: str = ""
    language: str = ""
    nodes_count: int = 0
    edges_count: int = 0
    duration_ms: float = 0.0


@dataclass
class FileError(PipelineEvent):
    """Emitted when extraction fails on a file."""
    file_path: str = ""
    error: str = ""


# ── Pipeline-level events ─────────────────────────────────────

@dataclass
class PipelineStarted(PipelineEvent):
    """Emitted once when the entire pipeline begins."""
    project_root: str = ""
    phase: PipelinePhase = PipelinePhase.DISCOVERY


@dataclass
class PipelineCompleted(PipelineEvent):
    """Emitted once when the entire pipeline finishes."""
    total_files: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    total_errors: int = 0
    duration_s: float = 0.0
    phase: PipelinePhase = PipelinePhase.PERSISTENCE


# ── EventEmitter ──────────────────────────────────────────────

class EventEmitter:
    """Thread-safe event emitter for pipeline events.

    Supports both typed listeners (subscribe to a specific event class)
    and global listeners (receive every event).

    Usage::

        emitter = EventEmitter()
        emitter.on(PhaseStarted, lambda e: print(f"Phase {e.phase} started"))
        emitter.on_any(lambda e: log_event(e))
        emitter.emit(PhaseStarted(phase=PipelinePhase.DISCOVERY, total_items=42))
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[type, list[Callable]] = {}
        self._global_listeners: list[Callable] = []

    def on(self, event_type: type, callback: Callable) -> None:
        """Register a listener for a specific event type."""
        with self._lock:
            self._listeners.setdefault(event_type, []).append(callback)

    def on_any(self, callback: Callable) -> None:
        """Register a listener that receives all events."""
        with self._lock:
            self._global_listeners.append(callback)

    def emit(self, event: PipelineEvent) -> None:
        """Emit an event to all matching listeners.

        Exceptions in listeners are silently caught to prevent
        observer errors from crashing the pipeline.
        """
        with self._lock:
            globals_copy = list(self._global_listeners)
            typed_copy = list(self._listeners.get(type(event), []))

        for cb in globals_copy:
            try:
                cb(event)
            except Exception:
                pass
        for cb in typed_copy:
            try:
                cb(event)
            except Exception:
                pass

    def remove_all(self) -> None:
        """Remove all listeners."""
        with self._lock:
            self._listeners.clear()
            self._global_listeners.clear()
