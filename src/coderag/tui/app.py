"""CodeRAG Monitor — main Textual application."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from coderag.pipeline.events import (
    EventEmitter,
    FileCompleted,
    FileError,
    FileStarted,
    PhaseCompleted,
    PhaseProgress,
    PhaseStarted,
    PipelinePhase,
    PipelineStarted,
)
from coderag.pipeline.events import (
    PipelineCompleted as PipelineCompletedEvent,
)
from coderag.tui.screens.dashboard import DashboardScreen
from coderag.tui.screens.details import DetailsScreen
from coderag.tui.screens.graph import GraphScreen
from coderag.tui.screens.help import HelpScreen
from coderag.tui.screens.logs import LogsScreen
from coderag.tui.screens.summary import SummaryScreen
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
        "dashboard": "j/k:Scroll  gg/G:Top/Bot  f:Follow  d/i/w/e:Filter  a:All  ::Cmd  1-4:Screens  ?:Help  q:Quit",
        "logs": "j/k:Scroll  gg/G:Top/Bot  /:Search  n/N:Next/Prev  f:Follow  d/i/w/e:Filter  ::Cmd  q:Quit",
        "details": "j/k:Scroll  h/l:Tab  gg/G:Top/Bot  ::Cmd  1-4:Screens  q:Quit",
        "graph": "j/k:Scroll  h/l:Tab  gg/G:Top/Bot  r:Refresh  ::Cmd  1-4:Screens  q:Quit",
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
        # NOTE: 'g' handled via on_key for gg two-key sequence
        Binding("G", "scroll_end", "Scroll End", show=False),
        Binding("ctrl+d", "half_page_down", "Half Page Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Page Up", show=False),
        Binding("ctrl+f", "full_page_down", "Full Page Down", show=False),
        Binding("ctrl+b", "full_page_up", "Full Page Up", show=False),
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

        # Shared data for cross-screen access
        self._shared_log_buffer: list[tuple[str, str]] = []  # (text, level)
        self._shared_file_details: dict[str, dict] = {}

        # Current screen name
        self._active_screen_name: str = "dashboard"

        # gg two-key sequence state
        self._g_pending: bool = False
        self._g_timer: object | None = None

        # Command mode state
        self._command_mode: bool = False

        # Detected languages (for summary)
        self._detected_languages: set[str] = set()

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

    # ── Key Handling (gg sequence & command mode) ─────────────

    def on_key(self, event: Key) -> None:
        """Handle special key sequences before normal binding dispatch."""
        # If command input is focused, let it handle keys normally
        if self._command_mode:
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._exit_command_mode()
            return

        # ':' enters command mode
        if event.key == "colon":
            event.prevent_default()
            event.stop()
            self._enter_command_mode()
            return

        # gg two-key sequence
        if event.key == "g":
            event.prevent_default()
            event.stop()
            if self._g_pending:
                # Second g — scroll to top
                self._cancel_g_timer()
                self._g_pending = False
                self.action_scroll_home()
            else:
                # First g — start timer
                self._g_pending = True
                self._g_timer = self.set_timer(0.5, self._g_timeout)
            return

        # Any other key cancels pending g
        if self._g_pending:
            self._cancel_g_timer()
            self._g_pending = False

    def _g_timeout(self) -> None:
        """Timer expired without second g press."""
        self._g_pending = False
        self._g_timer = None

    def _cancel_g_timer(self) -> None:
        """Cancel the pending g timer."""
        if self._g_timer is not None:
            try:
                self._g_timer.stop()
            except Exception:
                pass
            self._g_timer = None

    # ── Command Mode ──────────────────────────────────────────

    def _enter_command_mode(self) -> None:
        """Show command input at the bottom of the screen."""
        self._command_mode = True
        try:
            footer = self.query_one(CodeRAGFooter)
            footer.display = False
        except Exception:
            pass
        cmd_input = Input(
            placeholder="Enter command (:q :w :filter <level> :set wrap/nowrap)",
            id="command-input",
        )
        cmd_input.styles.dock = "bottom"
        cmd_input.styles.height = 1
        cmd_input.styles.background = "#0f172a"
        cmd_input.styles.color = "#e2e8f0"
        self.mount(cmd_input)
        cmd_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input submission."""
        if event.input.id != "command-input":
            return
        cmd = event.value.strip()
        self._exit_command_mode()
        self._execute_command(cmd)

    def _exit_command_mode(self) -> None:
        """Remove command input and restore footer."""
        self._command_mode = False
        try:
            cmd_input = self.query_one("#command-input", Input)
            cmd_input.remove()
        except Exception:
            pass
        try:
            footer = self.query_one(CodeRAGFooter)
            footer.display = True
        except Exception:
            pass

    def _execute_command(self, cmd: str) -> None:
        """Parse and execute a vim-style command."""
        if not cmd:
            return

        if cmd in ("q", "quit", "q!"):
            self.exit()
        elif cmd in ("w", "write", "save"):
            self._save_logs()
        elif cmd.startswith("filter "):
            level = cmd[7:].strip().upper()
            if level in ("DEBUG", "INFO", "WARN", "WARNING", "ERROR", "ALL"):
                if level == "ALL":
                    self.action_filter_all()
                elif level == "WARNING":
                    self.action_filter_warn()
                else:
                    getattr(self, f"action_filter_{level.lower()}", lambda: None)()
                self._post_log(f"Filter set to: {level}", "INFO")
            else:
                self._post_log(f"Unknown filter level: {level}", "WARN")
        elif cmd == "set wrap":
            self._post_log("Line wrapping enabled", "INFO")
            try:
                log = self.screen.query_one(FilterableLog)
                log.styles.overflow_x = "auto"
            except Exception:
                pass
        elif cmd == "set nowrap":
            self._post_log("Line wrapping disabled", "INFO")
            try:
                log = self.screen.query_one(FilterableLog)
                log.styles.overflow_x = "scroll"
            except Exception:
                pass
        elif cmd.startswith("screen ") or cmd.startswith("s "):
            parts = cmd.split(None, 1)
            if len(parts) == 2:
                name = parts[1].strip()
                screen_map = {"1": "dashboard", "2": "logs", "3": "details", "4": "graph"}
                target = screen_map.get(name, name)
                if target in ("dashboard", "logs", "details", "graph"):
                    self._switch_screen(target)
        else:
            self._post_log(f"Unknown command: :{cmd}", "WARN")

    def _save_logs(self) -> None:
        """Save current log buffer to file."""
        try:
            log_path = Path(self.project_root) / ".codegraph" / "monitor.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as f:
                for text, level in self._shared_log_buffer:
                    f.write(f"[{level}] {text}\n")
            self._post_log(f"Logs saved to {log_path}", "SUCCESS")
        except Exception as exc:
            self._post_log(f"Failed to save logs: {exc}", "ERROR")

    def key_escape(self) -> None:
        """Handle Escape key."""
        if self._command_mode:
            self._exit_command_mode()
        elif isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
        elif isinstance(self.screen, SummaryScreen):
            self.screen.dismiss()

    # ── Screen Navigation ─────────────────────────────────────

    def _switch_screen(self, name: str) -> None:
        """Switch to a named screen."""
        if self._active_screen_name == name:
            return
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
        from coderag.pipeline.orchestrator import PipelineOrchestrator
        from coderag.storage.sqlite_store import SQLiteStore

        emitter = EventEmitter()
        emitter.on_any(self._on_pipeline_event)

        try:
            if self.config_path:
                config = CodeGraphConfig.from_yaml(self.config_path)
            else:
                config = CodeGraphConfig.default()

            project_root = Path(self.project_root).resolve()
            db_dir = project_root / ".codegraph"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "graph.db"

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
                orchestrator.run(str(project_root))

            self.call_from_thread(self._post_log, "Pipeline completed successfully!", "SUCCESS")
            self.call_from_thread(self._on_finished, True, "")

        except Exception as exc:
            self.call_from_thread(self._post_log, f"Pipeline error: {exc}", "ERROR")
            self.call_from_thread(self._on_finished, False, str(exc))

    def _on_pipeline_event(self, event: Any) -> None:
        """Handle pipeline events from the background thread."""
        self.call_from_thread(self._handle_event, event)

    def _handle_event(self, event: Any) -> None:
        """Process a pipeline event on the main thread."""
        if isinstance(event, PipelineStarted):
            self._post_log(f"Pipeline started: {event.project_root}", "INFO")
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
            summary_str = ", ".join(f"{k}: {v}" for k, v in event.summary.items()) if event.summary else ""
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
            self._post_log(f"Parsing: {event.file_path}", "DEBUG")

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
            lang = getattr(event, "language", "?")
            if lang and lang != "?":
                self._detected_languages.add(lang)
            self._shared_file_details[event.file_path] = {
                "language": lang,
                "nodes_count": event.nodes_count,
                "edges_count": event.edges_count,
                "parse_time_ms": getattr(event, "parse_time_ms", 0.0),
                "node_kinds": getattr(event, "node_kinds", {}),
                "edge_kinds": getattr(event, "edge_kinds", {}),
                "error": "",
            }
            self._update_metrics()
            self._refresh_details_screen()

        elif isinstance(event, FileError):
            self._total_errors += 1
            self._post_log(f"{event.file_path}: {event.error}", "ERROR")
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
        self._shared_log_buffer.append((text, level))
        if len(self._shared_log_buffer) > 10000:
            self._shared_log_buffer = self._shared_log_buffer[-5000:]

        try:
            log_widget = self.screen.query_one(FilterableLog)
            log_widget.write_log(text, level)
        except Exception:
            pass

        if isinstance(self.screen, LogsScreen):
            try:
                self.screen.append_log(text, level)
            except Exception:
                pass

    def _on_finished(self, success: bool, error: str) -> None:
        """Handle pipeline completion — show summary overlay."""
        self._running = False
        if success:
            self._update_header_state("✓ Complete")
        else:
            self._update_header_state("✗ Failed")

        duration_s = time.time() - self._start_time if self._start_time else 0.0

        summary = SummaryScreen(
            success=success,
            duration_s=duration_s,
            files_parsed=self._files_processed,
            errors=self._total_errors,
            node_count=self._total_nodes,
            edge_count=self._total_edges,
            languages=sorted(self._detected_languages),
        )

        def _handle_summary_result(result: str | None) -> None:
            if result == "browse":
                self._switch_screen("graph")
            elif result == "quit":
                self.exit()

        self.push_screen(summary, callback=_handle_summary_result)

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
        phase_str = self._current_phase.value.replace("_", " ").title() if self._current_phase else "—"
        try:
            header = self.query_one(CodeRAGHeader)
            header.elapsed_text = time_str
            header.phase_text = phase_str
        except Exception:
            pass

        try:
            if self._running:
                status = "▶ Running"
            else:
                status = "✓ Complete" if self._total_errors == 0 else "✗ Errors"
            header_bar = self.screen.query_one("#header-bar", Static)
            header_bar.update(f"CodeRAG Monitor │ {status} │ Phase: {phase_str} │ {time_str}")
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
