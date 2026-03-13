"""SummaryScreen — post-parse summary overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class SummaryScreen(ModalScreen):
    """Modal overlay showing pipeline completion summary."""

    BINDINGS = [
        Binding("enter", "browse", "Browse Results", show=True, priority=True),
        Binding("q", "quit_app", "Quit", show=True, priority=True),
        Binding("escape", "dismiss_summary", "Dismiss", show=True, priority=True),
    ]

    DEFAULT_CSS = """
    SummaryScreen {
        align: center middle;
    }
    SummaryScreen #summary-container {
        width: 70;
        height: auto;
        max-height: 30;
        background: #1e293b;
        border: heavy #00d4aa;
        padding: 1 2;
    }
    SummaryScreen #summary-title {
        text-align: center;
        text-style: bold;
        color: #00d4aa;
        padding: 0 0 1 0;
    }
    SummaryScreen .summary-row {
        height: 1;
        padding: 0 1;
    }
    SummaryScreen .summary-divider {
        height: 1;
        color: #334155;
        padding: 0 1;
    }
    SummaryScreen #summary-prompt {
        text-align: center;
        color: #64748b;
        padding: 1 0 0 0;
    }
    """

    def __init__(
        self,
        success: bool = True,
        duration_s: float = 0.0,
        files_parsed: int = 0,
        errors: int = 0,
        node_count: int = 0,
        edge_count: int = 0,
        languages: list[str] | None = None,
        frameworks: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._success = success
        self._duration_s = duration_s
        self._files_parsed = files_parsed
        self._errors = errors
        self._node_count = node_count
        self._edge_count = edge_count
        self._languages = languages or []
        self._frameworks = frameworks or []

    def compose(self) -> ComposeResult:
        status = "✓ Pipeline Complete" if self._success else "✗ Pipeline Failed"

        # Format duration
        m, s = divmod(self._duration_s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            dur_str = f"{int(h)}h {int(m)}m {s:.1f}s"
        elif m > 0:
            dur_str = f"{int(m)}m {s:.1f}s"
        else:
            dur_str = f"{s:.1f}s"

        langs_str = ", ".join(self._languages) if self._languages else "—"
        fw_str = ", ".join(self._frameworks) if self._frameworks else "—"
        err_color = "red" if self._errors else "green"

        with Vertical(id="summary-container"):
            yield Static(
                f"[bold]{status}[/bold]",
                id="summary-title",
            )
            yield Static("─" * 66, classes="summary-divider")
            yield Static(
                f"  Parse Time:         [bold]{dur_str}[/bold]",
                classes="summary-row",
            )
            yield Static(
                f"  Files Parsed:       [bold]{self._files_parsed:,}[/bold]",
                classes="summary-row",
            )
            yield Static(
                f"  Errors:             [bold {err_color}]{self._errors:,}[/bold {err_color}]",
                classes="summary-row",
            )
            yield Static(
                f"  Nodes Created:      [bold]{self._node_count:,}[/bold]",
                classes="summary-row",
            )
            yield Static(
                f"  Edges Created:      [bold]{self._edge_count:,}[/bold]",
                classes="summary-row",
            )
            yield Static("─" * 66, classes="summary-divider")
            yield Static(
                f"  Languages:          [bold]{langs_str}[/bold]",
                classes="summary-row",
            )
            yield Static(
                f"  Frameworks:         [bold]{fw_str}[/bold]",
                classes="summary-row",
            )
            yield Static("─" * 66, classes="summary-divider")
            yield Static(
                "[dim]Enter: Browse Results  │  q: Quit  │  Esc: Dismiss[/dim]",
                id="summary-prompt",
            )

    def action_browse(self) -> None:
        """Dismiss summary and switch to graph screen."""
        self.dismiss("browse")

    def action_quit_app(self) -> None:
        """Quit the application."""
        self.dismiss("quit")

    def action_dismiss_summary(self) -> None:
        """Dismiss the summary overlay."""
        self.dismiss("dismiss")
