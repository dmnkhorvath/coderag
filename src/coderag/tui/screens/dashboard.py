"""DashboardScreen — main monitoring view composing all widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Static

from coderag.tui.widgets import (
    FilterableLog,
    MetricCard,
    PipelineProgress,
    ResourceMonitor,
    ThroughputChart,
)


class DashboardScreen(Screen):
    """The main dashboard screen with all monitoring widgets."""

    def compose(self) -> ComposeResult:
        yield Static(
            "CodeRAG Monitor │ ⏳ Initializing │ Phase: — │ 00:00:00",
            id="header-bar",
        )

        with Horizontal(id="metrics-row"):
            yield MetricCard(label="files/sec", value="—", id="metric-fps")
            yield MetricCard(label="nodes", value="0", id="metric-nodes")
            yield MetricCard(label="edges", value="0", id="metric-edges")
            yield MetricCard(label="errors", value="0", id="metric-errors")
            yield MetricCard(label="processed", value="0", id="metric-processed")

        yield PipelineProgress(id="pipeline-section")
        yield ThroughputChart(label="Throughput", unit="f/s", id="throughput-section")
        yield FilterableLog(id="log-section")
        yield ResourceMonitor(id="resource-section")

        yield Static(
            "j/k:Scroll  f:Follow  d/i/w/e:Filter  q:Quit  ?:Help",
            id="footer-bar",
        )
