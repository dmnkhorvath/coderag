"""DetailsScreen — file detail view with nodes and edges DataTables."""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Static

if TYPE_CHECKING:
    from coderag.tui.app import CodeRAGApp


class DetailsScreen(Screen):
    """File detail view showing parsed metadata, nodes, and edges."""

    BINDINGS = [
        Binding("h", "prev_tab", "Prev Tab", show=False),
        Binding("l", "next_tab", "Next Tab", show=False),
        Binding("tab", "next_tab", "Next Tab", show=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("ctrl+d", "half_page_down", "Half Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Up", show=False),
    ]

    active_tab: reactive[str] = reactive("files")

    def compose(self) -> ComposeResult:
        with Vertical(id="details-container"):
            yield Static("", id="details-tab-bar")
            yield Static("", id="details-summary")
            yield DataTable(id="details-files-table")
            yield DataTable(id="details-nodes-table", classes="hidden")
            yield DataTable(id="details-edges-table", classes="hidden")

    def on_mount(self) -> None:
        """Set up tables and populate data."""
        # Files table
        ft = self.query_one("#details-files-table", DataTable)
        ft.add_columns("File", "Language", "Nodes", "Edges", "Time (ms)", "Status")
        ft.cursor_type = "row"
        ft.zebra_stripes = True

        # Nodes table
        nt = self.query_one("#details-nodes-table", DataTable)
        nt.add_columns("File", "Kind", "Name", "Line", "Language")
        nt.cursor_type = "row"
        nt.zebra_stripes = True

        # Edges table
        et = self.query_one("#details-edges-table", DataTable)
        et.add_columns("Source", "Kind", "Target", "Confidence", "Line")
        et.cursor_type = "row"
        et.zebra_stripes = True

        self._refresh_data()
        self._update_tab_bar()

    @property
    def _file_details(self) -> dict:
        """Access the shared file details from the app."""
        app: CodeRAGApp = self.app  # type: ignore[assignment]
        if not hasattr(app, "_shared_file_details"):
            app._shared_file_details = {}
        return app._shared_file_details

    def _refresh_data(self) -> None:
        """Populate all tables from shared file details."""
        details = self._file_details

        # Summary
        total_files = len(details)
        total_nodes = sum(d.get("nodes_count", 0) for d in details.values())
        total_edges = sum(d.get("edges_count", 0) for d in details.values())
        total_errors = sum(1 for d in details.values() if d.get("error"))
        try:
            self.query_one("#details-summary", Static).update(
                f"  Files: [bold]{total_files}[/bold]  "
                f"Nodes: [bold cyan]{total_nodes:,}[/bold cyan]  "
                f"Edges: [bold green]{total_edges:,}[/bold green]  "
                f"Errors: [bold red]{total_errors}[/bold red]"
            )
        except Exception:
            pass

        # Files table
        try:
            ft = self.query_one("#details-files-table", DataTable)
            ft.clear()
            for fp, info in sorted(details.items()):
                short = fp if len(fp) <= 50 else "..." + fp[-47:]
                status = "[red]✗[/red]" if info.get("error") else "[green]✓[/green]"
                ft.add_row(
                    short,
                    info.get("language", "?"),
                    str(info.get("nodes_count", 0)),
                    str(info.get("edges_count", 0)),
                    f"{info.get("parse_time_ms", 0):.1f}",
                    status,
                )
        except Exception:
            pass

        # Nodes table — aggregate node_kinds across files
        try:
            nt = self.query_one("#details-nodes-table", DataTable)
            nt.clear()
            for fp, info in sorted(details.items()):
                short = fp if len(fp) <= 40 else "..." + fp[-37:]
                for kind, count in sorted(info.get("node_kinds", {}).items()):
                    nt.add_row(
                        short,
                        kind,
                        str(count),
                        "-",
                        info.get("language", "?"),
                    )
        except Exception:
            pass

        # Edges table — aggregate edge_kinds across files
        try:
            et = self.query_one("#details-edges-table", DataTable)
            et.clear()
            for fp, info in sorted(details.items()):
                short = fp if len(fp) <= 40 else "..." + fp[-37:]
                for kind, count in sorted(info.get("edge_kinds", {}).items()):
                    et.add_row(
                        short,
                        kind,
                        str(count),
                        "-",
                        "-",
                    )
        except Exception:
            pass

    def _update_tab_bar(self) -> None:
        """Update the tab bar to show active tab."""
        tabs = ["files", "nodes", "edges"]
        parts = []
        for tab in tabs:
            if tab == self.active_tab:
                parts.append(f"[bold reverse] {tab.upper()} [/bold reverse]")
            else:
                parts.append(f"[dim] {tab.upper()} [/dim]")
        try:
            self.query_one("#details-tab-bar", Static).update(
                "  ".join(parts) + "    [dim]h/l or Tab to switch[/dim]"
            )
        except Exception:
            pass

    def _show_active_table(self) -> None:
        """Show only the active table."""
        table_map = {
            "files": "#details-files-table",
            "nodes": "#details-nodes-table",
            "edges": "#details-edges-table",
        }
        for tab, selector in table_map.items():
            try:
                widget = self.query_one(selector, DataTable)
                if tab == self.active_tab:
                    widget.remove_class("hidden")
                    widget.focus()
                else:
                    widget.add_class("hidden")
            except Exception:
                pass

    def watch_active_tab(self, _old: str, _new: str) -> None:
        self._update_tab_bar()
        self._show_active_table()

    def action_next_tab(self) -> None:
        tabs = ["files", "nodes", "edges"]
        idx = tabs.index(self.active_tab)
        self.active_tab = tabs[(idx + 1) % len(tabs)]

    def action_prev_tab(self) -> None:
        tabs = ["files", "nodes", "edges"]
        idx = tabs.index(self.active_tab)
        self.active_tab = tabs[(idx - 1) % len(tabs)]

    # ── Scrolling ─────────────────────────────────────────────

    def _get_active_table(self) -> DataTable | None:
        table_map = {
            "files": "#details-files-table",
            "nodes": "#details-nodes-table",
            "edges": "#details-edges-table",
        }
        try:
            return self.query_one(table_map[self.active_tab], DataTable)
        except Exception:
            return None

    def action_cursor_down(self) -> None:
        t = self._get_active_table()
        if t:
            t.action_cursor_down()

    def action_cursor_up(self) -> None:
        t = self._get_active_table()
        if t:
            t.action_cursor_up()

    def action_scroll_home(self) -> None:
        t = self._get_active_table()
        if t:
            t.action_scroll_top()

    def action_scroll_end(self) -> None:
        t = self._get_active_table()
        if t:
            t.action_scroll_bottom()

    def action_half_page_down(self) -> None:
        t = self._get_active_table()
        if t:
            t.scroll_relative(y=t.size.height // 2)

    def action_half_page_up(self) -> None:
        t = self._get_active_table()
        if t:
            t.scroll_relative(y=-(t.size.height // 2))

    def refresh_details(self) -> None:
        """Public method to refresh data when new files are processed."""
        self._refresh_data()
