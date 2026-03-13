"""LogsScreen — full-screen log viewer with search and filtering."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Input, RichLog, Static

if TYPE_CHECKING:
    from coderag.tui.app import CodeRAGApp

LEVEL_ICONS = {
    "DEBUG": "[dim]⚙[/dim]",
    "INFO": "[blue]ℹ[/blue]",
    "WARN": "[yellow]⚠[/yellow]",
    "WARNING": "[yellow]⚠[/yellow]",
    "ERROR": "[red]✗[/red]",
    "SUCCESS": "[green]✓[/green]",
}

LEVEL_COLORS = {
    "DEBUG": "dim",
    "INFO": "blue",
    "WARN": "yellow",
    "WARNING": "yellow",
    "ERROR": "red",
    "SUCCESS": "green",
}


class LogsScreen(Screen):
    """Full-screen log viewer with regex search, level filtering, and export."""

    BINDINGS = [
        Binding("slash", "toggle_search", "Search", show=True),
        Binding("n", "next_match", "Next Match", show=False),
        Binding("N", "prev_match", "Prev Match", show=False),
        Binding("d", "filter_debug", "Debug", show=False),
        Binding("i", "filter_info", "Info", show=False),
        Binding("w", "filter_warn", "Warn", show=False),
        Binding("e", "filter_error", "Error", show=False),
        Binding("a", "filter_all", "All", show=False),
        Binding("f", "toggle_follow", "Follow", show=False),
        Binding("s", "save_logs", "Save", show=True),
        Binding("y", "yank_log", "Yank", show=True),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("ctrl+d", "half_page_down", "Half Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Up", show=False),
        Binding("ctrl+f", "full_page_down", "Page Down", show=False),
        Binding("ctrl+b", "full_page_up", "Page Up", show=False),
    ]

    auto_follow: reactive[bool] = reactive(True)
    active_levels: reactive[frozenset] = reactive(frozenset({"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "SUCCESS"}))
    search_pattern: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self._search_visible = False
        self._match_indices: list[int] = []
        self._current_match: int = -1

    def compose(self) -> ComposeResult:
        with Vertical(id="logs-container"):
            yield Static("", id="logs-level-bar")
            yield RichLog(highlight=True, markup=True, wrap=True, id="logs-output")
            yield Input(
                placeholder="Search regex...",
                id="logs-search-input",
                classes="hidden",
            )
            yield Static("", id="logs-status-bar")

    def on_mount(self) -> None:
        """Populate log from shared buffer on mount."""
        self._refilter()
        self._update_level_bar()
        self._update_status()

    @property
    def _log_buffer(self) -> list[tuple[str, str, str]]:
        """Access the shared log buffer from the app."""
        app: CodeRAGApp = self.app  # type: ignore[assignment]
        if not hasattr(app, "_shared_log_buffer"):
            app._shared_log_buffer = []
        return app._shared_log_buffer

    def append_log(self, text: str, level: str, file_path: str = "") -> None:
        """Append a log entry and display if it passes filters."""
        level_up = level.upper()
        self._log_buffer.append((level_up, text, file_path))
        if self._passes_filter(level_up, text):
            self._write_entry(level_up, text, len(self._log_buffer) - 1)
        self._update_level_bar()
        self._update_status()

    def _passes_filter(self, level: str, text: str) -> bool:
        """Check if an entry passes current level and search filters."""
        if level not in self.active_levels:
            return False
        if self.search_pattern:
            try:
                if not re.search(self.search_pattern, text, re.IGNORECASE):
                    return False
            except re.error:
                pass
        return True

    def _write_entry(self, level: str, text: str, index: int) -> None:
        """Write a single formatted entry to the RichLog."""
        icon = LEVEL_ICONS.get(level, "")
        color = LEVEL_COLORS.get(level, "")
        markup = f"{icon} [{color}]{text}[/{color}]"
        try:
            log = self.query_one("#logs-output", RichLog)
            log.write(markup)
            if self.auto_follow:
                log.scroll_end(animate=False)
        except Exception:
            pass

    def _refilter(self) -> None:
        """Re-render the log with current filters."""
        try:
            log = self.query_one("#logs-output", RichLog)
            log.clear()
        except Exception:
            return
        self._match_indices.clear()
        self._current_match = -1
        for idx, (level, text, _fp) in enumerate(self._log_buffer):
            if self._passes_filter(level, text):
                self._write_entry(level, text, idx)
                if self.search_pattern:
                    try:
                        if re.search(self.search_pattern, text, re.IGNORECASE):
                            self._match_indices.append(idx)
                    except re.error:
                        pass
        self._update_status()

    def _update_level_bar(self) -> None:
        """Update the level counter bar."""
        counts: dict[str, int] = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0, "SUCCESS": 0}
        for level, _text, _fp in self._log_buffer:
            key = level if level in counts else "INFO"
            counts[key] = counts.get(key, 0) + 1
        parts = []
        for lvl in ["DEBUG", "INFO", "WARN", "ERROR", "SUCCESS"]:
            color = LEVEL_COLORS.get(lvl, "")
            active = "bold" if lvl in self.active_levels else "dim"
            parts.append(f"[{active} {color}]{lvl}:{counts[lvl]}[/{active} {color}]")
        try:
            self.query_one("#logs-level-bar", Static).update("  ".join(parts))
        except Exception:
            pass

    def _update_status(self) -> None:
        """Update the status bar."""
        total = len(self._log_buffer)
        visible = sum(1 for lvl, txt, _ in self._log_buffer if self._passes_filter(lvl, txt))
        follow = "[bold green]FOLLOW[/bold green]" if self.auto_follow else "[dim]follow off[/dim]"
        search_info = ""
        if self.search_pattern:
            n = len(self._match_indices)
            pos = self._current_match + 1 if self._current_match >= 0 else 0
            search_info = f"  │  Search: /{self.search_pattern}/ ({pos}/{n})"
        try:
            self.query_one("#logs-status-bar", Static).update(f" {follow}  │  {visible}/{total} entries{search_info}")
        except Exception:
            pass

    # ── Search ────────────────────────────────────────────────

    def action_toggle_search(self) -> None:
        """Toggle the search input."""
        try:
            inp = self.query_one("#logs-search-input", Input)
        except Exception:
            return
        self._search_visible = not self._search_visible
        if self._search_visible:
            inp.remove_class("hidden")
            inp.focus()
        else:
            inp.add_class("hidden")
            self.search_pattern = ""
            self._refilter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission."""
        if event.input.id == "logs-search-input":
            self.search_pattern = event.value
            self._refilter()
            event.input.add_class("hidden")
            self._search_visible = False

    def action_next_match(self) -> None:
        if not self._match_indices:
            return
        self._current_match = (self._current_match + 1) % len(self._match_indices)
        self._update_status()

    def action_prev_match(self) -> None:
        if not self._match_indices:
            return
        self._current_match = (self._current_match - 1) % len(self._match_indices)
        self._update_status()

    # ── Level Filtering ───────────────────────────────────────

    def _toggle_level(self, level: str) -> None:
        level = level.upper()
        if level in self.active_levels:
            self.active_levels = self.active_levels - frozenset([level])
        else:
            self.active_levels = self.active_levels | frozenset([level])
        self._refilter()
        self._update_level_bar()

    def action_filter_debug(self) -> None:
        self._toggle_level("DEBUG")

    def action_filter_info(self) -> None:
        self._toggle_level("INFO")

    def action_filter_warn(self) -> None:
        self._toggle_level("WARN")

    def action_filter_error(self) -> None:
        self._toggle_level("ERROR")

    def action_filter_all(self) -> None:
        self.active_levels = frozenset({"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "SUCCESS"})
        self._refilter()
        self._update_level_bar()

    def action_toggle_follow(self) -> None:
        self.auto_follow = not self.auto_follow
        self._update_status()

    # ── Save / Yank ───────────────────────────────────────────

    def action_save_logs(self) -> None:
        """Save visible logs to file."""
        lines = []
        for level, text, _fp in self._log_buffer:
            if self._passes_filter(level, text):
                lines.append(f"[{level}] {text}")
        out = Path.cwd() / "coderag-logs.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        self.notify(f"Saved {len(lines)} lines to {out}")

    def action_yank_log(self) -> None:
        """Copy last visible log entry to clipboard."""
        for level, text, _fp in reversed(self._log_buffer):
            if self._passes_filter(level, text):
                import subprocess

                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode(),
                        check=True,
                    )
                    self.notify("Copied to clipboard")
                except Exception:
                    self.notify(f"Yank: {text[:80]}")
                return

    # ── Scrolling ─────────────────────────────────────────────

    def _get_log(self) -> RichLog | None:
        try:
            return self.query_one("#logs-output", RichLog)
        except Exception:
            return None

    def action_scroll_down(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_down()

    def action_scroll_up(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_up()

    def action_scroll_home(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_home()

    def action_scroll_end(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_end()

    def action_half_page_down(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_relative(y=log.size.height // 2)

    def action_half_page_up(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_relative(y=-(log.size.height // 2))

    def action_full_page_down(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_page_down()

    def action_full_page_up(self) -> None:
        log = self._get_log()
        if log:
            log.scroll_page_up()
