"""PipelineProgress widget — shows all pipeline phases with status indicators."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ProgressBar, Static

from coderag.pipeline.events import PipelinePhase


# Ordered list of phases for display
PHASE_ORDER: list[PipelinePhase] = [
    PipelinePhase.DISCOVERY,
    PipelinePhase.HASHING,
    PipelinePhase.EXTRACTION,
    PipelinePhase.RESOLUTION,
    PipelinePhase.FRAMEWORK_DETECTION,
    PipelinePhase.CROSS_LANGUAGE,
    PipelinePhase.STYLE_MATCHING,
    PipelinePhase.GIT_ENRICHMENT,
    PipelinePhase.PERSISTENCE,
]

PHASE_LABELS: dict[PipelinePhase, str] = {
    PipelinePhase.DISCOVERY: "Discovery",
    PipelinePhase.HASHING: "Hashing",
    PipelinePhase.EXTRACTION: "Extraction",
    PipelinePhase.RESOLUTION: "Resolution",
    PipelinePhase.FRAMEWORK_DETECTION: "Frameworks",
    PipelinePhase.CROSS_LANGUAGE: "Cross-Lang",
    PipelinePhase.STYLE_MATCHING: "Styles",
    PipelinePhase.GIT_ENRICHMENT: "Git",
    PipelinePhase.PERSISTENCE: "Persist",
}


class PipelineProgress(Widget):
    """Displays pipeline phases with checkmarks and a progress bar for the active phase."""

    DEFAULT_CSS = """
    PipelineProgress {
        height: auto;
        min-height: 4;
        padding: 0 1;
    }
    PipelineProgress .phase-row {
        width: 100%;
        height: 1;
    }
    PipelineProgress .progress-row {
        width: 100%;
        height: 1;
        margin-top: 1;
    }
    PipelineProgress ProgressBar {
        width: 100%;
    }
    """

    current_phase: reactive[PipelinePhase | None] = reactive(None)
    completed_phases: reactive[frozenset] = reactive(frozenset())
    progress_current: reactive[int] = reactive(0)
    progress_total: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static("", id="phase-indicators", classes="phase-row")
        yield Static("", id="progress-detail", classes="progress-row")
        yield ProgressBar(total=100, show_eta=False, id="phase-bar")

    def _render_phases(self) -> str:
        parts = []
        for phase in PHASE_ORDER:
            label = PHASE_LABELS[phase]
            if phase in self.completed_phases:
                parts.append(f"[green]✓[/green] {label}")
            elif phase == self.current_phase:
                parts.append(f"[bold cyan]▶[/bold cyan] [bold]{label}[/bold]")
            else:
                parts.append(f"[dim]○ {label}[/dim]")
        return "  ".join(parts)

    def watch_current_phase(self, phase: PipelinePhase | None) -> None:
        try:
            self.query_one("#phase-indicators", Static).update(self._render_phases())
        except Exception:
            pass

    def watch_completed_phases(self, _: frozenset) -> None:
        try:
            self.query_one("#phase-indicators", Static).update(self._render_phases())
        except Exception:
            pass

    def watch_progress_current(self, current: int) -> None:
        self._update_progress()

    def watch_progress_total(self, total: int) -> None:
        self._update_progress()

    def _update_progress(self) -> None:
        total = self.progress_total
        current = self.progress_current
        try:
            bar = self.query_one("#phase-bar", ProgressBar)
            if total > 0:
                bar.update(total=total, progress=current)
                pct = int(current / total * 100)
                detail = f"{pct}%  {current}/{total} files"
            else:
                bar.update(total=100, progress=0)
                detail = ""
            self.query_one("#progress-detail", Static).update(detail)
        except Exception:
            pass

    def mark_phase_started(self, phase: PipelinePhase, total_items: int = 0) -> None:
        self.current_phase = phase
        self.progress_current = 0
        self.progress_total = total_items

    def mark_phase_completed(self, phase: PipelinePhase) -> None:
        self.completed_phases = self.completed_phases | frozenset([phase])
        if self.current_phase == phase:
            self.current_phase = None

    def update_progress(self, current: int, total: int) -> None:
        self.progress_current = current
        self.progress_total = total
