"""HelpScreen — modal overlay with organized keybinding reference."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_TEXT = """[bold cyan]CodeRAG Monitor — Keybinding Reference[/bold cyan]

[bold]━━━ Navigation ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]1[/bold yellow]         Dashboard screen
  [bold yellow]2[/bold yellow]         Logs screen (full-screen log viewer)
  [bold yellow]3[/bold yellow]         Details screen (file metadata & tables)
  [bold yellow]4[/bold yellow]         Graph screen (database statistics)
  [bold yellow]?[/bold yellow]         Toggle this help overlay
  [bold yellow]Escape[/bold yellow]    Close overlay / go back
  [bold yellow]q[/bold yellow]         Quit application

[bold]━━━ Scrolling (Vim-style) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]j[/bold yellow]         Scroll down / cursor down
  [bold yellow]k[/bold yellow]         Scroll up / cursor up
  [bold yellow]g[/bold yellow]         Jump to top
  [bold yellow]G[/bold yellow]         Jump to bottom
  [bold yellow]Ctrl+d[/bold yellow]    Half page down
  [bold yellow]Ctrl+u[/bold yellow]    Half page up
  [bold yellow]Ctrl+f[/bold yellow]    Full page down
  [bold yellow]Ctrl+b[/bold yellow]    Full page up

[bold]━━━ Logs Screen ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]/[/bold yellow]         Toggle regex search
  [bold yellow]n[/bold yellow]         Next search match
  [bold yellow]N[/bold yellow]         Previous search match
  [bold yellow]f[/bold yellow]         Toggle auto-follow
  [bold yellow]s[/bold yellow]         Save visible logs to file
  [bold yellow]y[/bold yellow]         Yank (copy) last log entry

[bold]━━━ Log Level Filtering ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]d[/bold yellow]         Toggle DEBUG level
  [bold yellow]i[/bold yellow]         Toggle INFO level
  [bold yellow]w[/bold yellow]         Toggle WARN level
  [bold yellow]e[/bold yellow]         Toggle ERROR level
  [bold yellow]a[/bold yellow]         Show all levels

[bold]━━━ Details & Graph Screens ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]h[/bold yellow]         Previous tab
  [bold yellow]l[/bold yellow]         Next tab
  [bold yellow]Tab[/bold yellow]       Next tab
  [bold yellow]r[/bold yellow]         Refresh data (Graph screen)

[bold]━━━ Dashboard ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]
  [bold yellow]f[/bold yellow]         Toggle log auto-follow
  [bold yellow]d/i/w/e[/bold yellow]   Toggle log level filters
  [bold yellow]a[/bold yellow]         Show all log levels

[dim]Press Escape or ? to close this help overlay.[/dim]
"""


class HelpScreen(ModalScreen):
    """Modal help overlay showing all keybindings."""

    BINDINGS = [
        Binding("escape", "close_help", "Close", show=True, priority=True),
        Binding("question_mark", "close_help", "Close", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen #help-container {
        width: 70;
        max-height: 85%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    HelpScreen #help-content {
        height: auto;
        max-height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-container"):
            yield Static(HELP_TEXT, id="help-content")

    def action_close_help(self) -> None:
        """Close the help overlay."""
        self.dismiss()
