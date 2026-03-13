"""Comprehensive tests for the CodeRAG TUI monitoring dashboard."""

from __future__ import annotations

import time

import pytest

from coderag.pipeline.events import (
    EventEmitter,
    FileCompleted,
    FileError,
    PhaseCompleted,
    PhaseProgress,
    PhaseStarted,
    PipelineCompleted,
    PipelinePhase,
    PipelineStarted,
)

# Shorthand for common phases
DISC = PipelinePhase.DISCOVERY
HASH = PipelinePhase.HASHING
EXTR = PipelinePhase.EXTRACTION
RESOL = PipelinePhase.RESOLUTION
FRAME = PipelinePhase.FRAMEWORK_DETECTION
CROSS = PipelinePhase.CROSS_LANGUAGE
PERSIST = PipelinePhase.PERSISTENCE


def _make_app_no_worker(project_root="/tmp/test-project"):
    """Create a CodeRAGApp with the pipeline worker disabled.

    This prevents the background thread from emitting events that
    interfere with manual event-handling tests.
    """
    app = CodeRAGApp(project_root=project_root)
    # Monkey-patch run_worker to be a no-op so on_mount doesn't start pipeline
    app.run_worker = lambda *a, **kw: None
    return app


# ── EventEmitter Tests ────────────────────────────────────────────


class TestEventEmitter:
    """Tests for the pipeline EventEmitter."""

    def test_create_emitter(self):
        emitter = EventEmitter()
        assert emitter is not None

    def test_on_any_receives_all_events(self):
        emitter = EventEmitter()
        received = []
        emitter.on_any(lambda e: received.append(e))
        e1 = PipelineStarted(project_root="/tmp/test")
        e2 = PhaseStarted(phase=DISC, total_items=10)
        emitter.emit(e1)
        emitter.emit(e2)
        assert len(received) == 2
        assert received[0] is e1
        assert received[1] is e2

    def test_on_typed_receives_only_matching(self):
        emitter = EventEmitter()
        received = []
        emitter.on(FileCompleted, lambda e: received.append(e))
        emitter.emit(PipelineStarted(project_root="/tmp"))
        emitter.emit(FileCompleted(phase=EXTR, file_path="test.php", nodes_count=5, edges_count=3))
        assert len(received) == 1
        assert received[0].file_path == "test.php"
        assert received[0].nodes_count == 5

    def test_on_typed_and_global_both_fire(self):
        emitter = EventEmitter()
        global_received = []
        typed_received = []
        emitter.on_any(lambda e: global_received.append(e))
        emitter.on(FileError, lambda e: typed_received.append(e))
        event = FileError(phase=EXTR, file_path="bad.php", error="parse error")
        emitter.emit(event)
        assert len(global_received) == 1
        assert len(typed_received) == 1

    def test_listener_exception_does_not_crash(self):
        emitter = EventEmitter()
        emitter.on_any(lambda e: 1 / 0)  # Will raise ZeroDivisionError
        # Should not raise
        emitter.emit(PipelineStarted(project_root="/tmp"))

    def test_remove_all_clears_listeners(self):
        emitter = EventEmitter()
        received = []
        emitter.on_any(lambda e: received.append(e))
        emitter.emit(PipelineStarted(project_root="/tmp"))
        assert len(received) == 1
        emitter.remove_all()
        emitter.emit(PipelineStarted(project_root="/tmp"))
        assert len(received) == 1  # No new events

    def test_multiple_listeners_same_type(self):
        emitter = EventEmitter()
        r1, r2 = [], []
        emitter.on(PhaseStarted, lambda e: r1.append(e))
        emitter.on(PhaseStarted, lambda e: r2.append(e))
        emitter.emit(PhaseStarted(phase=EXTR, total_items=5))
        assert len(r1) == 1
        assert len(r2) == 1


# ── Pipeline Event Dataclass Tests ────────────────────────────────


class TestPipelineEvents:
    """Tests for pipeline event dataclasses."""

    def test_pipeline_phase_enum(self):
        assert PipelinePhase.DISCOVERY.value == "discovery"
        assert PipelinePhase.HASHING.value == "hashing"
        assert PipelinePhase.EXTRACTION.value == "extraction"
        assert PipelinePhase.RESOLUTION.value == "resolution"
        assert PipelinePhase.FRAMEWORK_DETECTION.value == "framework_detection"
        assert PipelinePhase.CROSS_LANGUAGE.value == "cross_language"
        assert PipelinePhase.PERSISTENCE.value == "persistence"

    def test_pipeline_started_defaults(self):
        e = PipelineStarted()
        assert e.project_root == ""
        assert e.phase == DISC  # default
        assert e.timestamp > 0

    def test_pipeline_completed_fields(self):
        e = PipelineCompleted(
            total_files=10,
            total_nodes=100,
            total_edges=50,
            total_errors=2,
            duration_s=3.5,
        )
        assert e.total_files == 10
        assert e.total_nodes == 100
        assert e.total_edges == 50
        assert e.total_errors == 2
        assert e.duration_s == 3.5
        assert e.phase == PERSIST  # default

    def test_file_completed_fields(self):
        e = FileCompleted(
            phase=EXTR,
            file_path="src/User.php",
            language="php",
            nodes_count=15,
            edges_count=8,
            duration_ms=42.5,
        )
        assert e.file_path == "src/User.php"
        assert e.language == "php"
        assert e.nodes_count == 15
        assert e.edges_count == 8
        assert e.duration_ms == 42.5
        assert e.phase == EXTR

    def test_file_error_fields(self):
        e = FileError(phase=EXTR, file_path="bad.js", error="SyntaxError")
        assert e.file_path == "bad.js"
        assert e.error == "SyntaxError"

    def test_phase_started_fields(self):
        e = PhaseStarted(phase=EXTR, total_items=42)
        assert e.phase == EXTR
        assert e.total_items == 42

    def test_phase_progress_fields(self):
        e = PhaseProgress(phase=EXTR, current=5, total=42, message="parsing")
        assert e.current == 5
        assert e.total == 42
        assert e.message == "parsing"

    def test_phase_completed_fields(self):
        e = PhaseCompleted(
            phase=EXTR,
            duration_ms=1234.5,
            summary={"files": 10},
        )
        assert e.phase == EXTR
        assert e.duration_ms == 1234.5
        assert e.summary == {"files": 10}

    def test_all_phases_exist(self):
        phases = list(PipelinePhase)
        assert len(phases) >= 7  # At least 7 phases

    def test_event_timestamp_auto_set(self):
        before = time.time()
        e = PipelineStarted()
        after = time.time()
        assert before <= e.timestamp <= after


# ── Widget Unit Tests ─────────────────────────────────────────────

from coderag.tui.widgets.filterable_log import FilterableLog
from coderag.tui.widgets.metric_card import MetricCard
from coderag.tui.widgets.pipeline_progress import PipelineProgress
from coderag.tui.widgets.resource_monitor import ResourceMonitor
from coderag.tui.widgets.throughput_chart import ThroughputChart


class TestMetricCard:
    """Tests for MetricCard widget."""

    def test_create_with_defaults(self):
        card = MetricCard()
        assert card.value == "—"  # em dash
        assert card.label_text == ""

    def test_create_with_values(self):
        card = MetricCard(label="nodes", value="42", id="test-card")
        assert card.value == "42"
        assert card.label_text == "nodes"

    def test_value_reactive_update(self):
        card = MetricCard(label="test", value="0")
        card.value = "100"
        assert card.value == "100"


class TestPipelineProgress:
    """Tests for PipelineProgress widget."""

    def test_create(self):
        pp = PipelineProgress()
        assert pp.current_phase is None
        assert pp.completed_phases == frozenset()
        assert pp.progress_current == 0
        assert pp.progress_total == 0

    def test_mark_phase_started(self):
        pp = PipelineProgress()
        pp.mark_phase_started(DISC, total_items=10)
        assert pp.current_phase == DISC
        assert pp.progress_total == 10
        assert pp.progress_current == 0

    def test_mark_phase_completed(self):
        pp = PipelineProgress()
        pp.mark_phase_started(DISC, total_items=10)
        pp.mark_phase_completed(DISC)
        assert DISC in pp.completed_phases
        assert pp.current_phase is None

    def test_update_progress(self):
        pp = PipelineProgress()
        pp.mark_phase_started(EXTR, total_items=50)
        pp.update_progress(25, 50)
        assert pp.progress_current == 25
        assert pp.progress_total == 50

    def test_multiple_phases(self):
        pp = PipelineProgress()
        pp.mark_phase_started(DISC)
        pp.mark_phase_completed(DISC)
        pp.mark_phase_started(HASH)
        pp.mark_phase_completed(HASH)
        assert DISC in pp.completed_phases
        assert HASH in pp.completed_phases
        assert pp.current_phase is None


class TestFilterableLog:
    """Tests for FilterableLog widget."""

    def test_create(self):
        log = FilterableLog()
        assert log.auto_follow is True
        assert "DEBUG" in log.active_levels
        assert "INFO" in log.active_levels
        assert "ERROR" in log.active_levels

    def test_toggle_follow(self):
        log = FilterableLog()
        assert log.auto_follow is True
        log.toggle_follow()
        assert log.auto_follow is False
        log.toggle_follow()
        assert log.auto_follow is True

    def test_toggle_level(self):
        log = FilterableLog()
        assert "DEBUG" in log.active_levels
        log.toggle_level("DEBUG")
        assert "DEBUG" not in log.active_levels
        log.toggle_level("DEBUG")
        assert "DEBUG" in log.active_levels

    def test_show_all_levels(self):
        log = FilterableLog()
        log.toggle_level("DEBUG")
        log.toggle_level("INFO")
        log.show_all_levels()
        assert "DEBUG" in log.active_levels
        assert "INFO" in log.active_levels
        assert "ERROR" in log.active_levels

    def test_set_level_only(self):
        log = FilterableLog()
        log.set_level_only("ERROR")
        assert log.active_levels == frozenset({"ERROR"})


class TestThroughputChart:
    """Tests for ThroughputChart widget."""

    def test_create(self):
        chart = ThroughputChart(label="Throughput", unit="f/s")
        assert chart.peak_value == 0.0
        assert chart.current_value == 0.0

    def test_add_value(self):
        chart = ThroughputChart(label="Test", unit="ops")
        chart.add_value(5.0)
        assert chart.current_value == 5.0
        assert chart.peak_value == 5.0

    def test_peak_tracking(self):
        chart = ThroughputChart(label="Test", unit="ops")
        chart.add_value(5.0)
        chart.add_value(10.0)
        chart.add_value(3.0)
        assert chart.peak_value == 10.0
        assert chart.current_value == 3.0


class TestResourceMonitor:
    """Tests for ResourceMonitor widget."""

    def test_create(self):
        rm = ResourceMonitor()
        assert rm is not None


# ── Screen Import Tests ───────────────────────────────────────────


class TestScreenImports:
    """Tests that all screens can be imported and instantiated."""

    def test_import_dashboard_screen(self):
        from coderag.tui.screens.dashboard import DashboardScreen

        screen = DashboardScreen()
        assert screen is not None

    def test_import_logs_screen(self):
        from coderag.tui.screens.logs import LogsScreen

        screen = LogsScreen()
        assert screen is not None

    def test_import_details_screen(self):
        from coderag.tui.screens.details import DetailsScreen

        screen = DetailsScreen()
        assert screen is not None

    def test_import_graph_screen(self):
        from coderag.tui.screens.graph import GraphScreen

        screen = GraphScreen()
        assert screen is not None

    def test_import_help_screen(self):
        from coderag.tui.screens.help import HelpScreen

        screen = HelpScreen()
        assert screen is not None

    def test_screens_init_exports(self):
        from coderag.tui.screens import (
            DashboardScreen,
            DetailsScreen,
            GraphScreen,
            HelpScreen,
            LogsScreen,
        )

        assert all(
            [
                DashboardScreen,
                LogsScreen,
                DetailsScreen,
                GraphScreen,
                HelpScreen,
            ]
        )

    def test_widgets_init_exports(self):
        from coderag.tui.widgets import (
            FilterableLog,
            MetricCard,
            PipelineProgress,
            ResourceMonitor,
            ThroughputChart,
        )

        assert all(
            [
                MetricCard,
                PipelineProgress,
                FilterableLog,
                ThroughputChart,
                ResourceMonitor,
            ]
        )


# ── TUI App Tests (Headless via Textual Test Pilot) ───────────────

from coderag.tui.app import CodeRAGApp, CodeRAGFooter, CodeRAGHeader


class TestCodeRAGApp:
    """Tests for the main CodeRAG TUI application."""

    def test_app_creation(self):
        app = _make_app_no_worker()
        assert app.project_root == "/tmp/test-project"
        assert app.project_dir == "/tmp/test-project"
        assert app._files_processed == 0
        assert app._total_nodes == 0
        assert app._total_edges == 0
        assert app._total_errors == 0
        assert app._running is False

    def test_app_with_config(self):
        app = CodeRAGApp(project_root="/tmp/test", config_path="/tmp/config.yaml")
        assert app.config_path == "/tmp/config.yaml"

    def test_shared_data_structures(self):
        app = CodeRAGApp(project_root="/tmp/test")
        assert isinstance(app._shared_log_buffer, list)
        assert isinstance(app._shared_file_details, dict)
        assert len(app._shared_log_buffer) == 0
        assert len(app._shared_file_details) == 0


@pytest.mark.asyncio
class TestCodeRAGAppHeadless:
    """Headless TUI tests using Textual's test pilot."""

    async def test_app_starts_and_shows_dashboard(self):
        """Test that the app starts and shows the dashboard screen."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)

    async def test_dashboard_has_metric_cards(self):
        """Test that dashboard contains all 5 metric cards."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            cards = app.screen.query(MetricCard)
            assert len(cards) == 5
            assert app.screen.query_one("#metric-fps", MetricCard) is not None
            assert app.screen.query_one("#metric-nodes", MetricCard) is not None
            assert app.screen.query_one("#metric-edges", MetricCard) is not None
            assert app.screen.query_one("#metric-errors", MetricCard) is not None
            assert app.screen.query_one("#metric-processed", MetricCard) is not None

    async def test_dashboard_has_pipeline_progress(self):
        """Test that dashboard contains PipelineProgress widget."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            pp = app.screen.query_one(PipelineProgress)
            assert pp is not None

    async def test_dashboard_has_filterable_log(self):
        """Test that dashboard contains FilterableLog widget."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            log = app.screen.query_one(FilterableLog)
            assert log is not None

    async def test_dashboard_has_throughput_chart(self):
        """Test that dashboard contains ThroughputChart widget."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            chart = app.screen.query_one(ThroughputChart)
            assert chart is not None

    async def test_dashboard_has_resource_monitor(self):
        """Test that dashboard contains ResourceMonitor widget."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            rm = app.screen.query_one(ResourceMonitor)
            assert rm is not None

    async def test_header_and_footer_present(self):
        """Test that CodeRAGHeader and CodeRAGFooter are present."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            header = app.query_one(CodeRAGHeader)
            assert header is not None
            footer = app.query_one(CodeRAGFooter)
            assert footer is not None

    async def test_screen_navigation_to_logs(self):
        """Test switching to logs screen via key press."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("2")
            await pilot.pause()
            from coderag.tui.screens.logs import LogsScreen

            assert isinstance(app.screen, LogsScreen)

    async def test_screen_navigation_to_details(self):
        """Test switching to details screen via key press."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("3")
            await pilot.pause()
            from coderag.tui.screens.details import DetailsScreen

            assert isinstance(app.screen, DetailsScreen)

    async def test_screen_navigation_to_graph(self):
        """Test switching to graph screen via key press."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("4")
            await pilot.pause()
            from coderag.tui.screens.graph import GraphScreen

            assert isinstance(app.screen, GraphScreen)

    async def test_screen_navigation_back_to_dashboard(self):
        """Test switching back to dashboard from another screen."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("2")  # Go to logs
            await pilot.pause()
            await pilot.press("1")  # Back to dashboard
            await pilot.pause()
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)

    async def test_help_screen_toggle(self):
        """Test opening and closing help screen."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            from coderag.tui.screens.help import HelpScreen

            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    async def test_post_log_updates_shared_buffer(self):
        """Test that _post_log adds to shared buffer."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            app._post_log("Test message", "INFO")
            found = any(text == "Test message" and level == "INFO" for text, level in app._shared_log_buffer)
            assert found

    async def test_metric_card_updates(self):
        """Test that metric cards can be updated."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            app._total_nodes = 42
            app._total_edges = 21
            app._total_errors = 3
            app._files_processed = 10
            app._update_metrics()
            await pilot.pause()
            nodes_card = app.screen.query_one("#metric-nodes", MetricCard)
            assert nodes_card.value == "42"
            edges_card = app.screen.query_one("#metric-edges", MetricCard)
            assert edges_card.value == "21"
            errors_card = app.screen.query_one("#metric-errors", MetricCard)
            assert errors_card.value == "3"
            processed_card = app.screen.query_one("#metric-processed", MetricCard)
            assert processed_card.value == "10"

    async def test_handle_pipeline_started_event(self):
        """Test handling PipelineStarted event."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            event = PipelineStarted(project_root="/tmp/test-project")
            app._handle_event(event)
            await pilot.pause()
            found = any("Pipeline started" in text for text, level in app._shared_log_buffer)
            assert found

    async def test_handle_phase_started_event(self):
        """Test handling PhaseStarted event."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            event = PhaseStarted(phase=EXTR, total_items=10)
            app._handle_event(event)
            await pilot.pause()
            assert app._current_phase == EXTR

    async def test_handle_file_completed_event(self):
        """Test handling FileCompleted event."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            initial_nodes = app._total_nodes
            initial_edges = app._total_edges
            event = FileCompleted(
                phase=EXTR,
                file_path="src/User.php",
                language="php",
                nodes_count=15,
                edges_count=8,
            )
            app._handle_event(event)
            await pilot.pause()
            assert app._total_nodes == initial_nodes + 15
            assert app._total_edges == initial_edges + 8
            assert "src/User.php" in app._shared_file_details

    async def test_handle_file_error_event(self):
        """Test handling FileError event."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            initial_errors = app._total_errors
            event = FileError(phase=EXTR, file_path="bad.php", error="parse error")
            app._handle_event(event)
            await pilot.pause()
            assert app._total_errors == initial_errors + 1
            assert "bad.php" in app._shared_file_details
            assert app._shared_file_details["bad.php"]["error"] == "parse error"

    async def test_handle_pipeline_completed_event(self):
        """Test handling PipelineCompleted event."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            app._running = True
            event = PipelineCompleted(
                total_files=10,
                total_nodes=100,
                total_edges=50,
                total_errors=0,
                duration_s=5.0,
            )
            app._handle_event(event)
            await pilot.pause()
            assert app._running is False

    async def test_log_buffer_cap(self):
        """Test that log buffer is capped."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)):
            for i in range(10500):
                app._shared_log_buffer.append((f"msg {i}", "INFO"))
            # Trigger the cap logic
            app._post_log("final", "INFO")
            assert len(app._shared_log_buffer) <= 10001

    async def test_multiple_screen_switches(self):
        """Test rapid screen switching doesn't crash."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            for key in ["2", "3", "4", "1", "2", "1", "4", "3", "1"]:
                await pilot.press(key)
                await pilot.pause()
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)

    async def test_small_terminal_size(self):
        """Test that app works at minimum terminal size."""
        app = _make_app_no_worker()
        async with app.run_test(size=(80, 24)):
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)
            # Should not crash at small size
            cards = app.screen.query(MetricCard)
            assert len(cards) == 5

    async def test_large_terminal_size(self):
        """Test that app works at large terminal size."""
        app = _make_app_no_worker()
        async with app.run_test(size=(200, 60)):
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)


# ── CLI Integration Test ──────────────────────────────────────────


class TestCLIMonitorCommand:
    """Tests for the CLI monitor command."""

    def test_monitor_command_exists(self):
        from coderag.cli.main import cli

        assert "monitor" in cli.commands

    def test_monitor_command_params(self):
        from coderag.cli.main import monitor

        param_names = [p.name for p in monitor.params]
        assert "path" in param_names


# ── Header/Footer Widget Tests ────────────────────────────────────


class TestCodeRAGHeader:
    """Tests for CodeRAGHeader widget."""

    def test_create(self):
        header = CodeRAGHeader()
        assert header.state_text == "⏸ Idle"
        assert header.phase_text == "—"
        assert header.active_screen == "dashboard"

    def test_reactive_state(self):
        header = CodeRAGHeader()
        header.state_text = "▶ Running"
        assert header.state_text == "▶ Running"

    def test_reactive_phase(self):
        header = CodeRAGHeader()
        header.phase_text = "Extraction"
        assert header.phase_text == "Extraction"

    def test_reactive_active_screen(self):
        header = CodeRAGHeader()
        header.active_screen = "logs"
        assert header.active_screen == "logs"


class TestCodeRAGFooter:
    """Tests for CodeRAGFooter widget."""

    def test_create(self):
        footer = CodeRAGFooter()
        assert footer.active_screen == "dashboard"

    def test_render_dashboard_hints(self):
        footer = CodeRAGFooter()
        footer.active_screen = "dashboard"
        rendered = footer.render()
        assert "Scroll" in rendered
        assert "Quit" in rendered

    def test_render_logs_hints(self):
        footer = CodeRAGFooter()
        footer.active_screen = "logs"
        rendered = footer.render()
        assert "Search" in rendered
        assert "::Cmd" in rendered

    def test_render_details_hints(self):
        footer = CodeRAGFooter()
        footer.active_screen = "details"
        rendered = footer.render()
        assert "Scroll" in rendered

    def test_render_graph_hints(self):
        footer = CodeRAGFooter()
        footer.active_screen = "graph"
        rendered = footer.render()
        assert "Refresh" in rendered

    def test_render_unknown_screen_falls_back(self):
        footer = CodeRAGFooter()
        footer.active_screen = "nonexistent"
        rendered = footer.render()
        # Should fall back to dashboard hints
        assert "Quit" in rendered


# ── TUI Events (Textual Messages) Tests ───────────────────────────


class TestTUIEvents:
    """Tests for TUI-specific Textual message events."""

    def test_import_tui_events(self):
        from coderag.tui.events import FileProcessed, LogMessage, PipelineFinished

        assert FileProcessed is not None
        assert LogMessage is not None
        assert PipelineFinished is not None

    def test_log_message_creation(self):
        from coderag.tui.events import LogMessage

        msg = LogMessage(text="test", level="ERROR", file_path="a.php")
        assert msg.text == "test"
        assert msg.level == "ERROR"
        assert msg.file_path == "a.php"

    def test_file_processed_creation(self):
        from coderag.tui.events import FileProcessed

        msg = FileProcessed(
            file_path="a.php",
            language="php",
            nodes_count=10,
            edges_count=5,
        )
        assert msg.file_path == "a.php"
        assert msg.language == "php"
        assert msg.nodes_count == 10
        assert msg.edges_count == 5

    def test_pipeline_finished_creation(self):
        from coderag.tui.events import PipelineFinished

        msg = PipelineFinished(success=True, error="")
        assert msg.success is True
        assert msg.error == ""

    def test_pipeline_event_message_wraps_event(self):
        from coderag.tui.events import PipelineEventMessage

        event = PipelineStarted(project_root="/tmp")
        msg = PipelineEventMessage(event)
        assert msg.event is event

    def test_metric_update_creation(self):
        from coderag.tui.events import MetricUpdate

        msg = MetricUpdate(key="nodes", value=42)
        assert msg.key == "nodes"
        assert msg.value == 42


# ── Integration: Event Flow Test ──────────────────────────────────


class TestEventFlow:
    """Tests for the full event flow from emitter to app."""

    def test_emitter_to_app_handler(self):
        """Test that events emitted by EventEmitter reach the app handler."""
        emitter = EventEmitter()
        received_events = []

        def capture(event):
            received_events.append(event)

        emitter.on_any(capture)

        # Emit a sequence of events
        emitter.emit(PipelineStarted(project_root="/tmp/test"))
        emitter.emit(PhaseStarted(phase=DISC, total_items=5))
        emitter.emit(FileCompleted(phase=EXTR, file_path="a.php", nodes_count=3, edges_count=1))
        emitter.emit(PhaseCompleted(phase=DISC, duration_ms=100))
        emitter.emit(PipelineCompleted(total_files=1, total_nodes=3, total_edges=1))

        assert len(received_events) == 5
        assert isinstance(received_events[0], PipelineStarted)
        assert isinstance(received_events[1], PhaseStarted)
        assert isinstance(received_events[2], FileCompleted)
        assert isinstance(received_events[3], PhaseCompleted)
        assert isinstance(received_events[4], PipelineCompleted)

    def test_emitter_thread_safety(self):
        """Test that emitter works from multiple threads."""
        import threading

        emitter = EventEmitter()
        received = []
        lock = threading.Lock()

        def capture(event):
            with lock:
                received.append(event)

        emitter.on_any(capture)

        def emit_events():
            for i in range(100):
                emitter.emit(PhaseProgress(phase=EXTR, current=i, total=100))

        threads = [threading.Thread(target=emit_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 500


# ── Part 3: SummaryScreen, gg keybinding, command mode ────────


class TestSummaryScreen:
    """Tests for the post-parse SummaryScreen modal."""

    def test_import(self):
        from coderag.tui.screens.summary import SummaryScreen

        assert SummaryScreen is not None

    def test_create_success(self):
        from coderag.tui.screens.summary import SummaryScreen

        s = SummaryScreen(
            success=True,
            duration_s=12.5,
            files_parsed=42,
            errors=0,
            node_count=150,
            edge_count=200,
            languages=["PHP", "JavaScript"],
        )
        assert s._success is True
        assert s._duration_s == 12.5
        assert s._files_parsed == 42
        assert s._errors == 0
        assert s._node_count == 150
        assert s._edge_count == 200
        assert s._languages == ["PHP", "JavaScript"]

    def test_create_failure(self):
        from coderag.tui.screens.summary import SummaryScreen

        s = SummaryScreen(
            success=False,
            duration_s=5.0,
            files_parsed=10,
            errors=3,
            node_count=20,
            edge_count=15,
        )
        assert s._success is False
        assert s._errors == 3
        assert s._languages == []
        assert s._frameworks == []

    def test_default_values(self):
        from coderag.tui.screens.summary import SummaryScreen

        s = SummaryScreen()
        assert s._success is True
        assert s._duration_s == 0.0
        assert s._files_parsed == 0
        assert s._errors == 0
        assert s._node_count == 0
        assert s._edge_count == 0
        assert s._languages == []
        assert s._frameworks == []

    def test_screens_init_exports_summary(self):
        from coderag.tui import screens

        assert hasattr(screens, "SummaryScreen")
        assert "SummaryScreen" in screens.__all__


class TestGGKeybinding:
    """Tests for the gg two-key sequence."""

    def test_g_pending_initial_state(self):
        app = _make_app_no_worker()
        assert app._g_pending is False
        assert app._g_timer is None

    def test_command_mode_initial_state(self):
        app = _make_app_no_worker()
        assert app._command_mode is False

    def test_detected_languages_initial_state(self):
        app = _make_app_no_worker()
        assert isinstance(app._detected_languages, set)
        assert len(app._detected_languages) == 0


class TestGGKeybindingHeadless:
    """Headless tests for gg two-key sequence."""

    @pytest.mark.asyncio
    async def test_g_pending_after_first_g(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert app._g_pending is True

    @pytest.mark.asyncio
    async def test_gg_resets_pending(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert app._g_pending is False

    @pytest.mark.asyncio
    async def test_g_timeout_resets_pending(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert app._g_pending is True
            # Wait for timeout (500ms + buffer)
            import asyncio

            await asyncio.sleep(0.7)
            await pilot.pause()
            assert app._g_pending is False

    @pytest.mark.asyncio
    async def test_other_key_cancels_g(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert app._g_pending is True
            await pilot.press("j")
            await pilot.pause()
            assert app._g_pending is False


class TestCommandMode:
    """Tests for : command mode."""

    @pytest.mark.asyncio
    async def test_execute_command_quit(self):
        """Test that :q command triggers exit."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Verify command mode is off initially
            assert app._command_mode is False

    @pytest.mark.asyncio
    async def test_execute_command_unknown(self):
        """Test that unknown command logs a warning."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._execute_command("nonexistent")
            await pilot.pause()
            # Check that warning was logged
            found = any("Unknown command" in text for text, level in app._shared_log_buffer)
            assert found

    @pytest.mark.asyncio
    async def test_execute_command_filter(self):
        """Test that :filter INFO command works."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._execute_command("filter INFO")
            await pilot.pause()
            found = any("Filter set to" in text for text, level in app._shared_log_buffer)
            assert found

    @pytest.mark.asyncio
    async def test_execute_command_save(self):
        """Test that :w command saves logs."""
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._post_log("test log entry", "INFO")
            app._execute_command("w")
            await pilot.pause()
            import os

            log_path = os.path.join(app.project_root, ".codegraph", "monitor.log")
            assert os.path.exists(log_path)
            with open(log_path) as f:
                content = f.read()
            assert "test log entry" in content


class TestOnFinished:
    """Tests for the _on_finished method and summary screen integration."""

    @pytest.mark.asyncio
    async def test_on_finished_success_updates_header(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._start_time = 1000000.0
            app._files_processed = 5
            app._total_nodes = 50
            app._total_edges = 30
            app._total_errors = 0
            app._detected_languages = {"PHP", "JavaScript"}
            # _on_finished should push SummaryScreen
            app._on_finished(True, "")
            await pilot.pause()
            from coderag.tui.screens.summary import SummaryScreen

            assert isinstance(app.screen, SummaryScreen)

    @pytest.mark.asyncio
    async def test_on_finished_failure_shows_summary(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._start_time = 1000000.0
            app._on_finished(False, "some error")
            await pilot.pause()
            from coderag.tui.screens.summary import SummaryScreen

            assert isinstance(app.screen, SummaryScreen)

    @pytest.mark.asyncio
    async def test_summary_dismiss_returns_to_dashboard(self):
        app = _make_app_no_worker()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._start_time = 1000000.0
            app._on_finished(True, "")
            await pilot.pause()
            from coderag.tui.screens.summary import SummaryScreen

            assert isinstance(app.screen, SummaryScreen)
            # Dismiss via escape
            await pilot.press("escape")
            await pilot.pause()
            # Should be back on dashboard
            from coderag.tui.screens.dashboard import DashboardScreen

            assert isinstance(app.screen, DashboardScreen)
