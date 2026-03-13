"""ResourceMonitor widget — CPU and memory bars using psutil."""

from __future__ import annotations

import psutil
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


def _bar(pct: float, width: int = 20) -> str:
    """Render a text-based progress bar."""
    filled = int(pct / 100 * width)
    empty = width - filled
    if pct > 80:
        color = "red"
    elif pct > 60:
        color = "yellow"
    else:
        color = "green"
    filled_str = "█" * filled
    empty_str = "░" * empty
    return f"[{color}]{filled_str}[/{color}][dim]{empty_str}[/dim]"


class ResourceMonitor(Widget):
    """Displays CPU and memory usage bars."""

    DEFAULT_CSS = """
    ResourceMonitor {
        height: 3;
        padding: 0 1;
        layout: horizontal;
    }
    ResourceMonitor .resource-bar {
        width: 1fr;
        height: 1;
    }
    """

    cpu_percent: reactive[float] = reactive(0.0)
    mem_percent: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Static("CPU ░░░░░░░░░░░░░░░░░░░░  0.0%", id="cpu-bar", classes="resource-bar")
        yield Static("MEM ░░░░░░░░░░░░░░░░░░░░  0.0%", id="mem-bar", classes="resource-bar")

    def refresh_stats(self) -> None:
        """Read current CPU and memory usage."""
        self.cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        self.mem_percent = mem.percent

    def watch_cpu_percent(self, pct: float) -> None:
        try:
            bar = _bar(pct)
            self.query_one("#cpu-bar", Static).update(f"CPU {bar} {pct:5.1f}%")
        except Exception:
            pass

    def watch_mem_percent(self, pct: float) -> None:
        try:
            bar = _bar(pct)
            self.query_one("#mem-bar", Static).update(f"MEM {bar} {pct:5.1f}%")
        except Exception:
            pass
