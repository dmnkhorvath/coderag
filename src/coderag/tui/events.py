"""TUI-specific Textual message types.

These bridge pipeline events (from background thread) to Textual's
message system (main thread).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.message import Message

from coderag.pipeline.events import PipelineEvent, PipelinePhase


class PipelineEventMessage(Message):
    """Wraps a PipelineEvent for posting to the Textual message bus."""

    def __init__(self, event: PipelineEvent) -> None:
        super().__init__()
        self.event = event


class MetricUpdate(Message):
    """Request to update a metric card."""

    def __init__(self, key: str, value: float | int | str) -> None:
        super().__init__()
        self.key = key
        self.value = value


class LogMessage(Message):
    """A log entry to display in the filterable log."""

    def __init__(
        self,
        text: str,
        level: str = "INFO",
        file_path: str = "",
    ) -> None:
        super().__init__()
        self.text = text
        self.level = level
        self.file_path = file_path


class FileProcessed(Message):
    """Emitted when a file has been fully processed.

    Carries metadata for the DetailsScreen.
    """

    def __init__(
        self,
        file_path: str,
        language: str = "",
        nodes_count: int = 0,
        edges_count: int = 0,
        parse_time_ms: float = 0.0,
        node_kinds: dict[str, int] | None = None,
        edge_kinds: dict[str, int] | None = None,
        error: str = "",
    ) -> None:
        super().__init__()
        self.file_path = file_path
        self.language = language
        self.nodes_count = nodes_count
        self.edges_count = edges_count
        self.parse_time_ms = parse_time_ms
        self.node_kinds = node_kinds or {}
        self.edge_kinds = edge_kinds or {}
        self.error = error


class PipelineFinished(Message):
    """Emitted when the pipeline worker completes."""

    def __init__(self, success: bool = True, error: str = "") -> None:
        super().__init__()
        self.success = success
        self.error = error
