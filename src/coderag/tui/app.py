"""CodeRAG Monitor — main Textual application."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
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
from coderag.tui.events import FileProcessed, LogMessage, PipelineFinished
from coderag.tui.screens.dashboard import DashboardScreen
from coderag.tui.screens.details import DetailsScreen
from coderag.tui.screens.graph import GraphScreen
from coderag.tui.screens.help import HelpScreen
from coderag.tui.screens.logs import LogsScreen
from coderag.tui.widgets import (
    FilterableLog,
    MetricCard,
    PipelineProgress,
    ResourceMonitor,
    ThroughputChart,
)


# ── Header & Footer Widgets ──────────────────────────────────


class CodeRAGHeader(Widget):
    """Top bar: logo, pipeline state, phase, elapsed time, screen tabs."""

    DEFAULT_CSS = """
    CodeRAGHeader {
        dock: top;
        height: 1;
        background: #1e293b;
        color: #00d4aa;
        layout: horizontal;
    }
    CodeRAGHeader .header-section {
        height: 1;
        padding: 0 1;
    }
    CodeRAGHeader #header-logo {
        width: auto;
        min-width: 18;
        text-style: bold;
        color: #00d4aa;
    }
    CodeRAGHeader #header-state {
        width: auto;
        min-width: 14;
    }
    CodeRAGHeader #header-phase {
        width: auto;
        min-width: 22;
    }
    CodeRAGHeader #header-elapsed {
        width: auto;
        min-width: 12;
    }
    CodeRAGHeader #header-tabs {
        width: 1fr;
        text-align: right;
        color: #94a3b8;
    }
    """

    state_text: reactive[str] = reactive("⏸ Idle")
    phase_text: reactive[str] = reactive("—")
    elapsed_text: reactive[str] = reactive("00:00:00")
    active_screen: reactive[str] = reactive("dashboard")

    def compose(self) -> ComposeResult:
        yield Static("▓ CodeRAG Monitor", id="header-logo", classes="header-section")
        yield Static("", id="header-state", classes="header-section")
        yield Static("", id="header-phase", classes="header-section")
        yield Static("", id="header-elapsed", classes="header-section")
        yield Static("", id="header-tabs", classes="header-section")

    def on_mount(self) -> None:
        self._refresh_all()

    def watch_state_text(self, value: str) -> None:
        try:
            self.query_one("#header-state", Static).update(value)
        except Exception:
            pass

    def watch_phase_text(self, value: str) -> None:
        try:
            self.query_one("#header-phase", Static).update(f"Phase: {value}")
        except Exception:
            pass

    def watch_elapsed_text(self, value: str) -> None:
        try:
            self.query_one("#header-elapsed", Static).update(value)
        except Exception:
            pass

    def watch_active_screen(self, value: str) -> None:
        self._refresh_tabs()

    def _refresh_all(self) -> None:
        self.watch_state_text(self.state_text)
        self.watch_phase_text(self.phase_text)
        self.watch_elapsed_text(self.elapsed_text)
        self._refresh_tabs()

    def _refresh_tabs(self) -> None:
        tabs = [
            ("1:Dashboard", "dashboard"),
            ("2:Logs", "logs"),
            ("3:Details", "details"),
            ("4:Graph", "graph"),
        ]
        parts = []
        for label, name in tabs:
            if name == self.active_screen:
                parts.append(f"[bold reverse] {label} [/bold reverse]")
            else:
                parts.append(f"[dim] {label} [/dim]")
        parts.append("[dim] ?:Help [/dim]")
        try:
            self.query_one("#header-tabs", Static).update(" ".join(parts))
        except Exception:
            pass


class CodeRAGFooter(Widget):
    """Bottom bar: context-sensitive keybinding hints."""

    DEFAULT_CSS = """
    CodeRAGFooter {
        dock: bottom;
        height: 1;
        background: #1e293b;
        color: #94a3b8;
        padding: 0 1;
    }
    """

    active_screen: reactive[str] = reactive("dashboard")

    _HINTS: dict[str, str] = {
        "dashboard": "j/k:Scroll  f:Follow  d/i/w/e:Filter  a:All  1-4:Screens  ?:Help  q:Quit",
        "logs": "j/k:Scroll  /:Search  n/N:Next/Prev  f:Follow  d/i/w/e:Filter  s:Save  y:Yank  q:Quit",
        "details": "j/k:Scroll  h/l:Tab  Tab:Next  g/G:Top/Bottom  1-4:Screens  q:Quit",
        "graph": "j/k:Scroll  h/l:Tab  r:Refresh  g/G:Top/Bottom  1-4:Screens  q:Quit",
    }

    def render(self) -> str:
        return self._HINTS.get(self.active_screen, self._HINTS["dashboard"])


# ── Main Application ─────────────────────────────────────────


class CodeRAGApp(App):
    """The CodeRAG monitoring TUI application."""

    TITLE = "CodeRAG Monitor"
    CSS_PATH = [
        "styles/common.tcss",
        "styles/dashboard.tcss",
        "styles/logs.tcss",
        "styles/details.tcss",
        "styles/graph.tcss",
        "styles/help.tcss",
    ]

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("question_mark", "toggle_help", "Help", show=True, priority=True),
        Binding("1", "screen_dashboard", "Dashboard", show=False, priority=True),
        Binding("2", "screen_logs", "Logs", show=False, priority=True),
        Binding("3", "screen_details", "Details", show=False, priority=True),
        Binding("4", "screen_graph", "Graph", show=False, priority=True),
        # Vim scrolling (delegated to active screen)
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
        Binding("ctrl+d", "half_page_down", "Half Page Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Page Up", show=False),
        Binding("ctrl+f", "full_page_down", "Full Page Down", show=False),
        Binding("ctrl+b", "full_page_up", "Full Page Up", show=False),
    ]

    # Named screens for install_screen


    def __init__(
        self,
        project_root: str,
        config_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        # Accept both project_root and project_dir for compatibility
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

        # Shared data for cross-screen access
        self._shared_log_buffer: list[tuple[str, str]] = []  # (text, level)
        self._shared_file_details: dict[str, dict] = {}

        # Current screen name
        self._active_screen_name: str = "dashboard"

    # Accept project_dir as alias
    @property
    def project_dir(self) -> str:
        return self.project_root

    def compose(self) -> ComposeResult:
        yield CodeRAGHeader()
        yield CodeRAGFooter()

    def on_mount(self) -> None:
        """Called when the app is mounted — push dashboard and start pipeline."""
        self.install_screen(DashboardScreen(), name="dashboard")
        self.install_screen(LogsScreen(), name="logs")
        self.install_screen(DetailsScreen(), name="details")
        self.install_screen(GraphScreen(), name="graph")
        self.push_screen("dashboard")
        # Start periodic timers
        self.set_interval(1.0, self._update_elapsed)
        self.set_interval(2.0, self._update_resources)
        self.set_interval(1.0, self._update_throughput)
        # Start the pipeline worker
        self._start_time = time.time()
        self._running = True
        self.run_worker(self._run_pipeline, thread=True, name="pipeline")

    # ── Screen Navigation ─────────────────────────────────────

    def _switch_screen(self, name: str) -> None:
        """Switch to a named screen."""
        if self._active_screen_name == name:
            return
        # If help modal is showing, pop it first
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        self.switch_screen(name)
        self._active_screen_name = name
        try:
            self.query_one(CodeRAGHeader).active_screen = name
            self.query_one(CodeRAGFooter).active_screen = name
        except Exception:
            pass

    def action_screen_dashboard(self) -> None:
        self._switch_screen("dashboard")

    def action_screen_logs(self) -> None:
        self._switch_screen("logs")

    def action_screen_details(self) -> None:
        self._switch_screen("details")

    def action_screen_graph(self) -> None:
        self._switch_screen("graph")

    def action_toggle_help(self) -> None:
        """Toggle the help modal overlay."""
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
        else:
            self.push_screen(HelpScreen())


    # ── Pipeline Worker ───────────────────────────────────────

    def _run_pipeline(self) -> None:
        """Run the pipeline in a background thread."""
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
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: Any) -> None:
        """Process a pipeline event on the main thread."""
        if isinstance(event, PipelineStarted):
            self._post_log(
                f"Pipeline started: {event.project_root}", "INFO"
            )
            self._update_header_state("▶ Running")

        elif isinstance(event, PhaseStarted):
            self._current_phase = event.phase
            phase_label = event.phase.value.replace("_", " ").title()
            self._post_log(f"Phase started: {phase_label}", "INFO")
            try:
                pp = self.screen.query_one(PipelineProgress)
                pp.mark_phase_started(event.phase, event.total_items)
                if event.total_items > 0:
                    self._total_files = event.total_items
            except Exception:
                pass
            self._update_header_state("▶ Running")

        elif isinstance(event, PhaseProgress):
            self._files_processed = event.current
            try:
                pp = self.screen.query_one(PipelineProgress)
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
                pp = self.screen.query_one(PipelineProgress)
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
            # Update shared file details
            self._shared_file_details[event.file_path] = {
                "language": getattr(event, "language", "?"),
                "nodes_count": event.nodes_count,
                "edges_count": event.edges_count,
                "parse_time_ms": getattr(event, "parse_time_ms", 0.0),
                "node_kinds": getattr(event, "node_kinds", {}),
                "edge_kinds": getattr(event, "edge_kinds", {}),
                "error": "",
            }
            self._update_metrics()
            # Refresh details screen if active
            self._refresh_details_screen()

        elif isinstance(event, FileError):
            self._total_errors += 1
            self._post_log(
                f"{event.file_path}: {event.error}", "ERROR"
            )
            # Update shared file details with error
            self._shared_file_details[event.file_path] = {
                "language": "?",
                "nodes_count": 0,
                "edges_count": 0,
                "parse_time_ms": 0.0,
                "node_kinds": {},
                "edge_kinds": {},
                "error": str(event.error),
            }
            self._update_metrics()
            self._refresh_details_screen()

        elif isinstance(event, PipelineCompletedEvent):
            self._running = False
            self._post_log(
                f"Done: {event.total_files} files, {event.total_nodes} nodes, "
                f"{event.total_edges} edges, {event.total_errors} errors "
                f"in {event.duration_s:.1f}s",
                "SUCCESS",
            )
            self._update_header_state("✓ Complete")
            self._update_metrics()

    # ── Shared Log Buffer ─────────────────────────────────────

    def _post_log(self, text: str, level: str = "INFO") -> None:
        """Write a message to the filterable log and shared buffer."""
        # Add to shared buffer (capped at 10000 entries)
        self._shared_log_buffer.append((text, level))
        if len(self._shared_log_buffer) > 10000:
            self._shared_log_buffer = self._shared_log_buffer[-5000:]

        # Write to dashboard FilterableLog if visible
        try:
            log_widget = self.screen.query_one(FilterableLog)
            log_widget.write_log(text, level)
        except Exception:
            pass

        # Write to LogsScreen if it exists and is active
        if isinstance(self.screen, LogsScreen):
            try:
                self.screen.append_log(text, level)
            except Exception:
                pass

    def _on_finished(self, success: bool, error: str) -> None:
        """Handle pipeline completion."""
        self._running = False
        if success:
            self._update_header_state("✓ Complete")
        else:
            self._update_header_state("✗ Failed")

    # ── Header Updates ────────────────────────────────────────

    def _update_header_state(self, status: str) -> None:
        """Update the header state indicator."""
        try:
            self.query_one(CodeRAGHeader).state_text = status
        except Exception:
            pass

    def _update_header(self) -> None:
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
            header = self.query_one(CodeRAGHeader)
            header.elapsed_text = time_str
            header.phase_text = phase_str
        except Exception:
            pass

        # Also update old-style header bar on dashboard if present
        try:
            if self._running:
                status = "▶ Running"
            else:
                status = "✓ Complete" if self._total_errors == 0 else "✗ Errors"
            header_bar = self.screen.query_one("#header-bar", Static)
            header_bar.update(
                f"CodeRAG Monitor │ {status} │ Phase: {phase_str} │ {time_str}"
            )
        except Exception:
            pass

    def _update_metrics(self) -> None:
        """Update all metric cards."""
        try:
            self.screen.query_one("#metric-nodes", MetricCard).value = f"{self._total_nodes:,}"
            self.screen.query_one("#metric-edges", MetricCard).value = f"{self._total_edges:,}"
            self.screen.query_one("#metric-errors", MetricCard).value = str(self._total_errors)
            self.screen.query_one("#metric-processed", MetricCard).value = str(self._files_processed)
        except Exception:
            pass

    def _update_elapsed(self) -> None:
        """Timer callback to update elapsed time in header."""
        if self._running:
            status = "▶ Running"
        else:
            status = "✓ Complete" if self._total_errors == 0 else "✗ Errors"
        self._update_header_state(status)
        self._update_header()

    def _update_resources(self) -> None:
        """Timer callback to update resource monitor."""
        try:
            rm = self.screen.query_one(ResourceMonitor)
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
                    chart = self.screen.query_one(ThroughputChart)
                    chart.add_value(fps)
                    self.screen.query_one("#metric-fps", MetricCard).value = f"{fps:.1f}"
                except Exception:
                    pass
        self._last_throughput_time = now
        self._last_throughput_count = self._files_processed

    def _refresh_details_screen(self) -> None:
        """Refresh the details screen if it is active."""
        if isinstance(self.screen, DetailsScreen):
            try:
                self.screen.refresh_details()
            except Exception:
                pass

    # ── Key Bindings (delegated to active screen) ─────────────

    def action_scroll_down(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_down()
        except Exception:
            pass

    def action_scroll_up(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_up()
        except Exception:
            pass

    def action_scroll_home(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_home()
        except Exception:
            pass

    def action_scroll_end(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_end()
        except Exception:
            pass

    def action_half_page_down(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_relative(y=20)
        except Exception:
            pass

    def action_half_page_up(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_relative(y=-20)
        except Exception:
            pass

    def action_full_page_down(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_relative(y=40)
        except Exception:
            pass

    def action_full_page_up(self) -> None:
        try:
            self.screen.query_one(FilterableLog).scroll_relative(y=-40)
        except Exception:
            pass

    def action_toggle_follow(self) -> None:
        try:
            self.screen.query_one(FilterableLog).toggle_follow()
        except Exception:
            pass

    def action_filter_debug(self) -> None:
        try:
            self.screen.query_one(FilterableLog).toggle_level("DEBUG")
        except Exception:
            pass

    def action_filter_info(self) -> None:
        try:
            self.screen.query_one(FilterableLog).toggle_level("INFO")
        except Exception:
            pass

    def action_filter_warn(self) -> None:
        try:
            self.screen.query_one(FilterableLog).toggle_level("WARN")
        except Exception:
            pass

    def action_filter_error(self) -> None:
        try:
            self.screen.query_one(FilterableLog).toggle_level("ERROR")
        except Exception:
            pass

    def action_filter_all(self) -> None:
        try:
            self.screen.query_one(FilterableLog).show_all_levels()
        except Exception:
            pass
