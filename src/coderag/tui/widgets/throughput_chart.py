"""ThroughputChart widget — sparkline showing files/sec over time."""
from __future__ import annotations

from collections import deque

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Sparkline, Static


class ThroughputChart(Widget):
    """Displays a sparkline of throughput values with peak annotation."""

    DEFAULT_CSS = """
    ThroughputChart {
        height: 4;
        padding: 0 1;
    }
    ThroughputChart .chart-header {
        height: 1;
        width: 100%;
    }
    ThroughputChart Sparkline {
        height: 2;
        width: 100%;
    }
    """

    peak_value: reactive[float] = reactive(0.0)
    current_value: reactive[float] = reactive(0.0)

    def __init__(
        self,
        label: str = "Throughput",
        unit: str = "f/s",
        max_points: int = 60,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._label = label
        self._unit = unit
        self._data: deque[float] = deque(maxlen=max_points)
        # Initialize with zeros
        for _ in range(max_points):
            self._data.append(0.0)

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self._label}  —  0.0 {self._unit} (peak: 0.0)",
            classes="chart-header",
        )
        yield Sparkline(list(self._data), id="sparkline")

    def add_value(self, value: float) -> None:
        """Add a new throughput data point."""
        self._data.append(value)
        self.current_value = value
        if value > self.peak_value:
            self.peak_value = value

        try:
            self.query_one("#sparkline", Sparkline).data = list(self._data)
            self.query_one(".chart-header", Static).update(
                f"{self._label}  {self.current_value:.1f} {self._unit}  "
                f"(peak: {self.peak_value:.1f})"
            )
        except Exception:
            pass
