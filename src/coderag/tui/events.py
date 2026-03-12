"""TUI-specific Textual message types.

These bridge pipeline events (from background thread) to Textual's
message system (main thread).
"""
from __future__ import annotations

from dataclasses import dataclass, field

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


class PipelineFinished(Message):
    """Emitted when the pipeline worker completes."""

    def __init__(self, success: bool = True, error: str = "") -> None:
        super().__init__()
        self.success = success
        self.error = error
