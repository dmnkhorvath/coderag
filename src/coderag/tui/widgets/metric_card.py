"""MetricCard widget — displays a single KPI with big number + label."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class MetricCard(Widget):
    """A card showing a large metric value and a label beneath it."""

    DEFAULT_CSS = """
    MetricCard {
        width: 1fr;
        height: auto;
        min-height: 5;
        padding: 0 1;
        content-align: center middle;
        text-align: center;
    }
    MetricCard .metric-value {
        text-style: bold;
        width: 100%;
        text-align: center;
    }
    MetricCard .metric-label {
        color: $text-muted;
        width: 100%;
        text-align: center;
    }
    """

    value: reactive[str] = reactive("—")
    label_text: reactive[str] = reactive("")

    def __init__(
        self,
        label: str = "",
        value: str = "—",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.label_text = label
        self.value = value

    def compose(self) -> ComposeResult:
        yield Static(self.value, classes="metric-value")
        yield Static(self.label_text, classes="metric-label")

    def watch_value(self, new_value: str) -> None:
        try:
            self.query_one(".metric-value", Static).update(new_value)
        except Exception:
            pass

    def watch_label_text(self, new_label: str) -> None:
        try:
            self.query_one(".metric-label", Static).update(new_label)
        except Exception:
            pass
