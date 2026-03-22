"""Session management CLI commands for CodeRAG.

Provides `coderag session list`, `coderag session show`, and
`coderag session context` commands.
"""

from __future__ import annotations

import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _find_db_path(project_path: str | None = None) -> str | None:
    """Find the graph.db path for the given or current project."""
    if project_path is None:
        project_path = os.getcwd()
    db_path = os.path.join(project_path, ".codegraph", "graph.db")
    if os.path.isfile(db_path):
        return db_path
    return None


def _open_session_store(project_path: str | None = None):
    """Open a SessionStore for the given or current project."""
    from coderag.session.store import SessionStore

    db_path = _find_db_path(project_path)
    if db_path is None:
        console.print("[red]No CodeRAG database found.[/red] Run 'coderag parse' first.")
        raise SystemExit(1)
    return SessionStore(db_path)


@click.group()
def session() -> None:
    """Manage session memory and context."""


@session.command("list")
@click.option("--limit", "-n", default=10, type=int, help="Number of sessions to show.")
@click.option(
    "--project",
    "-p",
    default=None,
    type=click.Path(exists=True),
    help="Project directory (default: current directory).",
)
def session_list(limit: int, project: str | None) -> None:
    """List recent sessions."""
    store = _open_session_store(project)
    try:
        sessions = store.get_recent_sessions(limit=limit)
        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return

        table = Table(title="Recent Sessions", show_lines=False)
        table.add_column("ID", style="cyan", max_width=12)
        table.add_column("Started", style="green")
        table.add_column("Tool", style="yellow")
        table.add_column("Events", justify="right", style="magenta")
        table.add_column("Prompt", max_width=40)

        for s in sessions:
            sid = s["id"][:12]
            started = s["started_at"][:19] if s["started_at"] else "?"
            tool = s["tool"] or "-"
            events = str(s["event_count"] or 0)
            prompt = (s["prompt"] or "-")[:40]
            table.add_row(sid, started, tool, events, prompt)

        console.print(table)
    finally:
        store.close()


@session.command("show")
@click.argument("session_id")
@click.option(
    "--project",
    "-p",
    default=None,
    type=click.Path(exists=True),
    help="Project directory (default: current directory).",
)
def session_show(session_id: str, project: str | None) -> None:
    """Show details for a specific session."""
    store = _open_session_store(project)
    try:
        # Find matching session (support partial IDs)
        sessions = store.get_recent_sessions(limit=100)
        match = None
        for s in sessions:
            if s["id"].startswith(session_id):
                match = s
                break

        if match is None:
            console.print(f"[red]Session not found:[/red] {session_id}")
            return

        # Session info panel
        info_lines = [
            f"ID: {match['id']}",
            f"Started: {match['started_at']}",
            f"Ended: {match['ended_at'] or 'active'}",
            f"Tool: {match['tool'] or '-'}",
            f"Prompt: {match['prompt'] or '-'}",
            f"Events: {match['event_count']}",
        ]
        console.print(Panel("\n".join(info_lines), title="Session Details", border_style="cyan"))

        # Events table
        events = store.get_events(session_id=match["id"], limit=50)
        if events:
            table = Table(title="Events", show_lines=False)
            table.add_column("Time", style="green", max_width=19)
            table.add_column("Type", style="yellow")
            table.add_column("Target", style="cyan")

            for ev in events:
                ts = ev.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                table.add_row(ts, ev.event_type, ev.target[:60])

            console.print(table)
    finally:
        store.close()


@session.command("context")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["decision", "task", "fact"]),
    help="Filter by category.",
)
@click.option(
    "--project",
    "-p",
    default=None,
    type=click.Path(exists=True),
    help="Project directory (default: current directory).",
)
def session_context(category: str | None, project: str | None) -> None:
    """Show persisted context (decisions, tasks, facts)."""
    store = _open_session_store(project)
    try:
        items = store.get_context(category=category, active_only=True)
        if not items:
            filter_msg = f" for '{category}'" if category else ""
            console.print(f"[dim]No active context items{filter_msg}.[/dim]")
            return

        table = Table(title="Persisted Context", show_lines=False)
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Category", style="yellow")
        table.add_column("Content", style="white")
        table.add_column("Created", style="green", max_width=10)

        for item in items:
            table.add_row(
                str(item["id"]),
                item["category"],
                item["content"][:80],
                item["created_at"][:10],
            )

        console.print(table)

        # Also show hot files
        hot_files = store.get_hot_files(limit=10)
        if hot_files:
            console.print()
            hot_table = Table(title="Hot Files", show_lines=False)
            hot_table.add_column("#", style="dim", justify="right")
            hot_table.add_column("File", style="cyan")
            hot_table.add_column("Accesses", style="magenta", justify="right")

            for i, (path, count) in enumerate(hot_files, 1):
                hot_table.add_row(str(i), path, str(count))

            console.print(hot_table)
    finally:
        store.close()
