"""CodeRAG Monitor — main Textual application."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from coderag.pipeline.events import (
    EventEmitter,
    FileCompleted,
    FileError,
    FileStarted,
    PhaseCompleted,
    PhaseProgress,
    PhaseStarted,
    PipelineCompleted as PipelineCompletedEvent,
    PipelinePhase,
    PipelineStarted,
)
from coderag.tui.events import LogMessage, PipelineFinished
from coderag.tui.screens.dashboard import DashboardScreen
from coderag.tui.widgets import (
    FilterableLog,
    MetricCard,
    PipelineProgress,
    ResourceMonitor,
    ThroughputChart,
)


class CodeRAGApp(App):
    """The CodeRAG monitoring TUI application."""

    TITLE = "CodeRAG Monitor"
    CSS_PATH = "styles/dashboard.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("f", "toggle_follow", "Toggle Follow", show=False),
        Binding("d", "filter_debug", "Filter Debug", show=False),
        Binding("i", "filter_info", "Filter Info", show=False),
        Binding("w", "filter_warn", "Filter Warn", show=False),
        Binding("e", "filter_error", "Filter Error", show=False),
        Binding("a", "filter_all", "Show All", show=False),
        Binding("g", "scroll_home", "Scroll Home", show=False),
        Binding("G", "scroll_end", "Scroll End", show=False),
    ]

    def __init__(
        self,
        project_root: str,
        config_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.project_root = project_root
        self.config_path = config_path

        # Pipeline state tracking
        self._start_time: float = 0.0
        self._files_processed: int = 0
        self._total_files: int = 0
        self._total_nodes: int = 0
        self._total_edges: int = 0
        self._total_errors: int = 0
        self._current_phase: PipelinePhase | None = None
        self._running: bool = False

        # Throughput tracking
        self._last_throughput_time: float = 0.0
        self._last_throughput_count: int = 0

    def on_mount(self) -> None:
        """Called when the app is mounted — push dashboard and start pipeline."""
        self.push_screen(DashboardScreen())
        # Start periodic timers
        self.set_interval(1.0, self._update_elapsed)
        self.set_interval(2.0, self._update_resources)
        self.set_interval(1.0, self._update_throughput)
        # Start the pipeline worker
        self._start_time = time.time()
        self._running = True
        self.run_worker(self._run_pipeline, thread=True, name="pipeline")

    def _run_pipeline(self) -> None:
        """Run the pipeline in a background thread."""
        import logging
        from coderag.core.config import CodeGraphConfig
        from coderag.core.registry import PluginRegistry
        from coderag.storage.sqlite_store import SQLiteStore
        from coderag.pipeline.orchestrator import PipelineOrchestrator

        # Create event emitter and subscribe
        emitter = EventEmitter()
        emitter.on_any(self._on_pipeline_event)

        try:
            # Load config
            if self.config_path:
                config = CodeGraphConfig.from_yaml(self.config_path)
            else:
                config = CodeGraphConfig.default()

            # Set up project
            project_root = Path(self.project_root).resolve()
            db_dir = project_root / ".codegraph"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "graph.db"

            # Initialize components
            registry = PluginRegistry()
            registry.discover_plugins()
            store = SQLiteStore(str(db_path))

            with store:
                orchestrator = PipelineOrchestrator(
                    config=config,
                    registry=registry,
                    store=store,
                    emitter=emitter,
                )
                summary = orchestrator.run(str(project_root))

            # Signal completion
            self.call_from_thread(
                self._post_log, "Pipeline completed successfully!", "SUCCESS"
            )
            self.call_from_thread(self._on_finished, True, "")

        except Exception as exc:
            self.call_from_thread(
                self._post_log, f"Pipeline error: {exc}", "ERROR"
            )
            self.call_from_thread(self._on_finished, False, str(exc))

    def _on_pipeline_event(self, event: Any) -> None:
        """Handle pipeline events from the background thread."""
        # Bridge to main thread via call_from_thread
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: Any) -> None:
        """Process a pipeline event on the main thread."""
        if isinstance(event, PipelineStarted):
            self._post_log(
                f"Pipeline started: {event.project_root}", "INFO"
            )
            self._update_header("▶ Running")

        elif isinstance(event, PhaseStarted):
            self._current_phase = event.phase
            phase_label = event.phase.value.replace("_", " ").title()
            self._post_log(f"Phase started: {phase_label}", "INFO")
            try:
                pp = self.query_one("PipelineProgress")
                pp.mark_phase_started(event.phase, event.total_items)
                if event.total_items > 0:
                    self._total_files = event.total_items
            except Exception:
                pass
            self._update_header("▶ Running")

        elif isinstance(event, PhaseProgress):
            self._files_processed = event.current
            try:
                pp = self.query_one("PipelineProgress")
                pp.update_progress(event.current, event.total)
            except Exception:
                pass
            if event.message:
                self._post_log(event.message, "DEBUG")

        elif isinstance(event, PhaseCompleted):
            phase_label = event.phase.value.replace("_", " ").title()
            summary_str = ", ".join(
                f"{k}: {v}" for k, v in event.summary.items()
            ) if event.summary else ""
            duration_str = f" ({event.duration_ms:.0f}ms)" if event.duration_ms else ""
            self._post_log(
                f"Phase complete: {phase_label}{duration_str} — {summary_str}",
                "SUCCESS",
            )
            try:
                pp = self.query_one("PipelineProgress")
                pp.mark_phase_completed(event.phase)
            except Exception:
                pass

        elif isinstance(event, FileStarted):
            self._post_log(
                f"Parsing: {event.file_path}", "DEBUG"
            )

        elif isinstance(event, FileCompleted):
            self._files_processed += 1
            self._total_nodes += event.nodes_count
            self._total_edges += event.edges_count
            short_path = event.file_path
            if len(short_path) > 60:
                short_path = "..." + short_path[-57:]
            self._post_log(
                f"{short_path} ({event.nodes_count} nodes, {event.edges_count} edges)",
                "SUCCESS",
            )
            self._update_metrics()

        elif isinstance(event, FileError):
            self._total_errors += 1
            self._post_log(
                f"{event.file_path}: {event.error}", "ERROR"
            )
            self._update_metrics()

        elif isinstance(event, PipelineCompletedEvent):
            self._running = False
            self._post_log(
                f"Done: {event.total_files} files, {event.total_nodes} nodes, "
                f"{event.total_edges} edges, {event.total_errors} errors "
                f"in {event.duration_s:.1f}s",
                "SUCCESS",
            )
            self._update_header("✓ Complete")
            self._update_metrics()

    def _post_log(self, text: str, level: str = "INFO") -> None:
        """Write a message to the filterable log."""
        try:
            log_widget = self.query_one("FilterableLog")
            log_widget.write_log(text, level)
        except Exception:
            pass

    def _on_finished(self, success: bool, error: str) -> None:
        """Handle pipeline completion."""
        self._running = False
        if success:
            self._update_header("✓ Complete")
        else:
            self._update_header("✗ Failed")

    def _update_header(self, status: str) -> None:
        """Update the header bar with current status."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        h, m, s = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
        time_str = f"{h:02d}:{m:02d}:{s:02d}"
        phase_str = (
            self._current_phase.value.replace("_", " ").title()
            if self._current_phase
            else "—"
        )
        try:
            header = self.query_one("#header-bar", Static)
            header.update(
                f"CodeRAG Monitor │ {status} │ Phase: {phase_str} │ {time_str}"
            )
        except Exception:
            pass

    def _update_metrics(self) -> None:
        """Update all metric cards."""
        try:
            self.query_one("#metric-nodes", MetricCard).value = f"{self._total_nodes:,}"
            self.query_one("#metric-edges", MetricCard).value = f"{self._total_edges:,}"
            self.query_one("#metric-errors", MetricCard).value = str(self._total_errors)
            self.query_one("#metric-processed", MetricCard).value = str(self._files_processed)
        except Exception:
            pass

    def _update_elapsed(self) -> None:
        """Timer callback to update elapsed time in header."""
        if self._running:
            status = "▶ Running"
        else:
            status = "✓ Complete" if self._total_errors == 0 else "✗ Errors"
        self._update_header(status)

    def _update_resources(self) -> None:
        """Timer callback to update resource monitor."""
        try:
            rm = self.query_one("ResourceMonitor")
            rm.refresh_stats()
        except Exception:
            pass

    def _update_throughput(self) -> None:
        """Timer callback to compute and display throughput."""
        now = time.time()
        if self._last_throughput_time > 0:
            dt = now - self._last_throughput_time
            if dt > 0:
                files_delta = self._files_processed - self._last_throughput_count
                fps = files_delta / dt
                try:
                    chart = self.query_one("ThroughputChart")
                    chart.add_value(fps)
                    self.query_one("#metric-fps", MetricCard).value = f"{fps:.1f}"
                except Exception:
                    pass
        self._last_throughput_time = now
        self._last_throughput_count = self._files_processed

    # ── Key bindings ──────────────────────────────────────────

    def action_scroll_down(self) -> None:
        try:
            self.query_one("FilterableLog").scroll_down()
        except Exception:
            pass

    def action_scroll_up(self) -> None:
        try:
            self.query_one("FilterableLog").scroll_up()
        except Exception:
            pass

    def action_scroll_home(self) -> None:
        try:
            self.query_one("FilterableLog").scroll_home()
        except Exception:
            pass

    def action_scroll_end(self) -> None:
        try:
            self.query_one("FilterableLog").scroll_end()
        except Exception:
            pass

    def action_toggle_follow(self) -> None:
        try:
            self.query_one("FilterableLog").toggle_follow()
        except Exception:
            pass

    def action_filter_debug(self) -> None:
        try:
            self.query_one("FilterableLog").toggle_level("DEBUG")
        except Exception:
            pass

    def action_filter_info(self) -> None:
        try:
            self.query_one("FilterableLog").toggle_level("INFO")
        except Exception:
            pass

    def action_filter_warn(self) -> None:
        try:
            self.query_one("FilterableLog").toggle_level("WARN")
        except Exception:
            pass

    def action_filter_error(self) -> None:
        try:
            self.query_one("FilterableLog").toggle_level("ERROR")
        except Exception:
            pass

    def action_filter_all(self) -> None:
        try:
            self.query_one("FilterableLog").show_all_levels()
        except Exception:
            pass

    def action_help(self) -> None:
        """Show help overlay."""
        self._post_log(
            "[bold]Keybindings:[/bold] j/k=scroll  f=follow  "
            "d/i/w/e=toggle filter  a=show all  g/G=top/bottom  q=quit",
            "INFO",
        )
