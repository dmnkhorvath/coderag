"""GraphScreen — graph statistics from SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Static

if TYPE_CHECKING:
    from coderag.tui.app import CodeRAGApp


class GraphScreen(Screen):
    """Graph statistics view — queries SQLite for node/edge breakdowns."""

    BINDINGS = [
        Binding("h", "prev_tab", "Prev Tab", show=False),
        Binding("l", "next_tab", "Next Tab", show=False),
        Binding("tab", "next_tab", "Next Tab", show=True),
        Binding("r", "refresh_stats", "Refresh", show=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("ctrl+d", "half_page_down", "Half Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Up", show=False),
    ]

    active_tab: reactive[str] = reactive("overview")

    def compose(self) -> ComposeResult:
        with Vertical(id="graph-container"):
            yield Static("", id="graph-tab-bar")
            yield Static("", id="graph-summary")
            yield DataTable(id="graph-overview-table")
            yield DataTable(id="graph-nodes-table", classes="hidden")
            yield DataTable(id="graph-edges-table", classes="hidden")
            yield DataTable(id="graph-languages-table", classes="hidden")

    def on_mount(self) -> None:
        """Set up tables and load data."""
        # Overview table
        ot = self.query_one("#graph-overview-table", DataTable)
        ot.add_columns("Metric", "Value")
        ot.cursor_type = "row"
        ot.zebra_stripes = True

        # Nodes by kind
        nt = self.query_one("#graph-nodes-table", DataTable)
        nt.add_columns("Node Kind", "Count", "Percentage")
        nt.cursor_type = "row"
        nt.zebra_stripes = True

        # Edges by kind
        et = self.query_one("#graph-edges-table", DataTable)
        et.add_columns("Edge Kind", "Count", "Percentage")
        et.cursor_type = "row"
        et.zebra_stripes = True

        # Languages
        lt = self.query_one("#graph-languages-table", DataTable)
        lt.add_columns("Language", "Files", "Nodes", "Edges")
        lt.cursor_type = "row"
        lt.zebra_stripes = True

        self._update_tab_bar()
        self._load_stats()

    def _get_db_path(self) -> Path | None:
        """Find the SQLite database path."""
        app: CodeRAGApp = self.app  # type: ignore[assignment]
        project_root = Path(app.project_root).resolve()
        db_path = project_root / ".codegraph" / "graph.db"
        if db_path.exists():
            return db_path
        return None

    def _load_stats(self) -> None:
        """Load graph statistics from SQLite."""
        db_path = self._get_db_path()
        if not db_path:
            try:
                self.query_one("#graph-summary", Static).update(
                    "  [dim]No database found yet. Run the pipeline first.[/dim]"
                )
            except Exception:
                pass
            return

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Overview stats
            total_nodes = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            total_edges = cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            total_files = cur.execute(
                "SELECT COUNT(DISTINCT file_path) FROM nodes"
            ).fetchone()[0]
            total_languages = cur.execute(
                "SELECT COUNT(DISTINCT language) FROM nodes"
            ).fetchone()[0]

            avg_confidence = 0.0
            row = cur.execute("SELECT AVG(confidence) FROM edges").fetchone()
            if row and row[0]:
                avg_confidence = row[0]

            low_conf = cur.execute(
                "SELECT COUNT(*) FROM edges WHERE confidence < 0.5"
            ).fetchone()[0]

            try:
                self.query_one("#graph-summary", Static).update(
                    f"  Nodes: [bold cyan]{total_nodes:,}[/bold cyan]  "
                    f"Edges: [bold green]{total_edges:,}[/bold green]  "
                    f"Files: [bold]{total_files:,}[/bold]  "
                    f"Languages: [bold]{total_languages}[/bold]  "
                    f"Avg Confidence: [bold]{avg_confidence:.2f}[/bold]"
                )
            except Exception:
                pass

            # Overview table
            try:
                ot = self.query_one("#graph-overview-table", DataTable)
                ot.clear()
                ot.add_row("Total Nodes", f"{total_nodes:,}")
                ot.add_row("Total Edges", f"{total_edges:,}")
                ot.add_row("Total Files", f"{total_files:,}")
                ot.add_row("Languages", str(total_languages))
                ot.add_row("Avg Edge Confidence", f"{avg_confidence:.3f}")
                ot.add_row("Low Confidence Edges (<0.5)", f"{low_conf:,}")

                # File hashes info if available
                try:
                    fh_count = cur.execute(
                        "SELECT COUNT(*) FROM file_hashes"
                    ).fetchone()[0]
                    total_parse_time = cur.execute(
                        "SELECT SUM(parse_time_ms) FROM file_hashes"
                    ).fetchone()[0] or 0
                    ot.add_row("Tracked Files", f"{fh_count:,}")
                    ot.add_row("Total Parse Time", f"{total_parse_time:,.0f} ms")
                except Exception:
                    pass
            except Exception:
                pass

            # Nodes by kind
            try:
                nt = self.query_one("#graph-nodes-table", DataTable)
                nt.clear()
                rows = cur.execute(
                    "SELECT kind, COUNT(*) as cnt FROM nodes "
                    "GROUP BY kind ORDER BY cnt DESC"
                ).fetchall()
                for row in rows:
                    pct = (row[1] / total_nodes * 100) if total_nodes else 0
                    nt.add_row(row[0], f"{row[1]:,}", f"{pct:.1f}%")
            except Exception:
                pass

            # Edges by kind
            try:
                et = self.query_one("#graph-edges-table", DataTable)
                et.clear()
                rows = cur.execute(
                    "SELECT kind, COUNT(*) as cnt FROM edges "
                    "GROUP BY kind ORDER BY cnt DESC"
                ).fetchall()
                for row in rows:
                    pct = (row[1] / total_edges * 100) if total_edges else 0
                    et.add_row(row[0], f"{row[1]:,}", f"{pct:.1f}%")
            except Exception:
                pass

            # Languages breakdown
            try:
                lt = self.query_one("#graph-languages-table", DataTable)
                lt.clear()
                rows = cur.execute(
                    "SELECT language, "
                    "COUNT(DISTINCT file_path) as files, "
                    "COUNT(*) as nodes "
                    "FROM nodes GROUP BY language ORDER BY nodes DESC"
                ).fetchall()
                for row in rows:
                    # Count edges for this language
                    edge_count = cur.execute(
                        "SELECT COUNT(*) FROM edges e "
                        "JOIN nodes n ON e.source_id = n.id "
                        "WHERE n.language = ?",
                        (row[0],),
                    ).fetchone()[0]
                    lt.add_row(
                        row[0], f"{row[1]:,}", f"{row[2]:,}", f"{edge_count:,}"
                    )
            except Exception:
                pass

            conn.close()

        except Exception as exc:
            try:
                self.query_one("#graph-summary", Static).update(
                    f"  [red]Error loading stats: {exc}[/red]"
                )
            except Exception:
                pass

    # ── Tab Navigation ────────────────────────────────────────

    def _update_tab_bar(self) -> None:
        tabs = ["overview", "nodes", "edges", "languages"]
        parts = []
        for tab in tabs:
            if tab == self.active_tab:
                parts.append(f"[bold reverse] {tab.upper()} [/bold reverse]")
            else:
                parts.append(f"[dim] {tab.upper()} [/dim]")
        try:
            self.query_one("#graph-tab-bar", Static).update(
                "  ".join(parts) + "    [dim]h/l or Tab to switch  r:Refresh[/dim]"
            )
        except Exception:
            pass

    def _show_active_table(self) -> None:
        table_map = {
            "overview": "#graph-overview-table",
            "nodes": "#graph-nodes-table",
            "edges": "#graph-edges-table",
            "languages": "#graph-languages-table",
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
        tabs = ["overview", "nodes", "edges", "languages"]
        idx = tabs.index(self.active_tab)
        self.active_tab = tabs[(idx + 1) % len(tabs)]

    def action_prev_tab(self) -> None:
        tabs = ["overview", "nodes", "edges", "languages"]
        idx = tabs.index(self.active_tab)
        self.active_tab = tabs[(idx - 1) % len(tabs)]

    def action_refresh_stats(self) -> None:
        self._load_stats()
        self.notify("Stats refreshed")

    # ── Scrolling ─────────────────────────────────────────────

    def _get_active_table(self) -> DataTable | None:
        table_map = {
            "overview": "#graph-overview-table",
            "nodes": "#graph-nodes-table",
            "edges": "#graph-edges-table",
            "languages": "#graph-languages-table",
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
