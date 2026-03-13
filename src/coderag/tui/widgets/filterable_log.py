"""FilterableLog widget — RichLog with level filtering and auto-follow."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog, Static

LEVEL_ICONS = {
    "DEBUG": "[dim]🔍[/dim]",
    "INFO": "[blue]ℹ️[/blue]",
    "WARN": "[yellow]⚠️[/yellow]",
    "WARNING": "[yellow]⚠️[/yellow]",
    "ERROR": "[red]❌[/red]",
    "SUCCESS": "[green]✓[/green]",
}


class FilterableLog(Widget):
    """A log viewer with level filtering and auto-follow."""

    DEFAULT_CSS = """
    FilterableLog {
        height: 1fr;
    }
    FilterableLog RichLog {
        height: 1fr;
    }
    FilterableLog .log-status {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    auto_follow: reactive[bool] = reactive(True)
    active_levels: reactive[frozenset] = reactive(frozenset({"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "SUCCESS"}))

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._all_entries: list[tuple[str, str]] = []  # (level, markup)
        self._entry_count = 0

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, id="log-output")
        yield Static("", classes="log-status")

    def _format_entry(self, text: str, level: str) -> str:
        icon = LEVEL_ICONS.get(level.upper(), "")
        return f"{icon} {text}"

    def write_log(
        self,
        text: str,
        level: str = "INFO",
    ) -> None:
        """Add a log entry, respecting current filter."""
        markup = self._format_entry(text, level)
        self._all_entries.append((level.upper(), markup))
        self._entry_count += 1

        if level.upper() in self.active_levels:
            try:
                log = self.query_one("#log-output", RichLog)
                log.write(markup)
                if self.auto_follow:
                    log.scroll_end(animate=False)
            except Exception:
                pass

        self._update_status()

    def _update_status(self) -> None:
        visible = sum(1 for lvl, _ in self._all_entries if lvl in self.active_levels)
        follow_indicator = "[bold green]FOLLOW[/bold green]" if self.auto_follow else "[dim]follow off[/dim]"
        levels_str = " ".join(
            f"[bold]{level[0]}[/bold]" if level in self.active_levels else f"[dim]{level[0]}[/dim]"
            for level in ["DEBUG", "INFO", "WARN", "ERROR"]
        )
        try:
            self.query_one(".log-status", Static).update(
                f" {follow_indicator}  │  Levels: {levels_str}  │  {visible}/{self._entry_count} entries"
            )
        except Exception:
            pass

    def toggle_follow(self) -> None:
        self.auto_follow = not self.auto_follow
        self._update_status()

    def toggle_level(self, level: str) -> None:
        """Toggle a log level on/off."""
        level = level.upper()
        if level in self.active_levels:
            self.active_levels = self.active_levels - frozenset([level])
        else:
            self.active_levels = self.active_levels | frozenset([level])
        self._refilter()

    def set_level_only(self, level: str) -> None:
        """Show only the specified level."""
        self.active_levels = frozenset([level.upper()])
        self._refilter()

    def show_all_levels(self) -> None:
        self.active_levels = frozenset({"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "SUCCESS"})
        self._refilter()

    def _refilter(self) -> None:
        """Re-render the log with current filter."""
        try:
            log = self.query_one("#log-output", RichLog)
            log.clear()
            for level, markup in self._all_entries:
                if level in self.active_levels:
                    log.write(markup)
            if self.auto_follow:
                log.scroll_end(animate=False)
        except Exception:
            pass
        self._update_status()

    def scroll_up(self) -> None:
        try:
            self.query_one("#log-output", RichLog).scroll_up()
        except Exception:
            pass

    def scroll_down(self) -> None:
        try:
            self.query_one("#log-output", RichLog).scroll_down()
        except Exception:
            pass

    def scroll_home(self) -> None:
        try:
            self.query_one("#log-output", RichLog).scroll_home()
        except Exception:
            pass

    def scroll_end(self) -> None:
        try:
            self.query_one("#log-output", RichLog).scroll_end()
        except Exception:
            pass
