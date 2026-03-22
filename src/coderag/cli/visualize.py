"""CLI command for interactive graph visualization.

Generates a self-contained HTML file with an interactive D3.js
force-directed graph of the knowledge graph.
"""

from __future__ import annotations

import json
import os
import webbrowser
from pathlib import Path

import click
from rich.console import Console

from coderag.core.config import CodeGraphConfig
from coderag.storage.sqlite_store import SQLiteStore

console = Console()


def _load_config(config_path: str | None, project_root: str | None = None) -> CodeGraphConfig:
    """Load configuration, searching common locations."""
    if config_path and os.path.exists(config_path):
        return CodeGraphConfig.from_yaml(config_path)
    candidates = []
    if project_root:
        candidates.append(os.path.join(project_root, "codegraph.yaml"))
        candidates.append(os.path.join(project_root, "codegraph.yml"))
    candidates.extend(["codegraph.yaml", "codegraph.yml"])
    for c in candidates:
        if os.path.exists(c):
            return CodeGraphConfig.from_yaml(c)
    return CodeGraphConfig.default()


def _open_store(config: CodeGraphConfig) -> SQLiteStore:
    """Open the SQLite store from config."""
    db_path = config.db_path_absolute
    if not os.path.exists(db_path):
        console.print(f"[red]Database not found:[/red] {db_path}")
        console.print("Run [bold]coderag parse <path>[/bold] first.")
        raise SystemExit(1)
    store = SQLiteStore(db_path)
    store.initialize()
    return store


@click.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output file path (default: .codegraph/graph.html or .codegraph/graph.json).",
)
@click.option(
    "--symbol",
    "-s",
    default=None,
    help="Center visualization on a specific symbol.",
)
@click.option(
    "--depth",
    "-d",
    default=2,
    type=int,
    help="Neighborhood depth when using --symbol (default: 2).",
)
@click.option(
    "--language",
    "-l",
    multiple=True,
    help="Filter by language (can repeat: -l php -l javascript).",
)
@click.option(
    "--kind",
    "-k",
    multiple=True,
    help="Filter by node kind (can repeat: -k class -k function).",
)
@click.option(
    "--max-nodes",
    default=500,
    type=int,
    help="Maximum nodes to include (default: 500).",
)
@click.option(
    "--open",
    "auto_open",
    is_flag=True,
    default=False,
    help="Auto-open in browser after generation.",
)
@click.option(
    "--title",
    default="CodeRAG Visualization",
    help="Custom title for the visualization.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["html", "json"]),
    default="html",
    help="Output format: html (default) or json (raw data only).",
)
@click.pass_context
def visualize(
    ctx: click.Context,
    path: str,
    output: str | None,
    symbol: str | None,
    depth: int,
    language: tuple[str, ...],
    kind: tuple[str, ...],
    max_nodes: int,
    auto_open: bool,
    title: str,
    fmt: str,
) -> None:
    """Generate an interactive graph visualization.

    Creates a self-contained HTML file with a D3.js force-directed
    graph of the knowledge graph. Supports filtering by language,
    node kind, and neighborhood exploration.

    PATH is the project root directory (default: current directory).

    Examples:

        coderag visualize /path/to/project

        coderag visualize . -s UserService -d 3

        coderag visualize . -l php -l javascript --max-nodes 200

        coderag visualize . --format json -o graph-data.json
    """
    from coderag.visualization.exporter import GraphExporter
    from coderag.visualization.renderer import GraphRenderer

    # Resolve config and store
    config_path = ctx.obj.get("config_path") if ctx.obj else None
    config = _load_config(config_path, project_root=path)
    db_override = ctx.obj.get("db_override") if ctx.obj else None
    if db_override:
        config.db_path = db_override

    store = _open_store(config)

    # Determine output path
    ext = ".json" if fmt == "json" else ".html"
    if output is None:
        output = os.path.join(os.path.dirname(config.db_path_absolute), f"graph{ext}")

    try:
        # Export graph data
        if symbol:
            console.print(
                f"[bold cyan]Exporting neighbourhood of[/bold cyan] [green]{symbol}[/green] (depth={depth})..."
            )
            data = GraphExporter.export_neighborhood(
                store,
                output if fmt == "json" else "/dev/null",
                symbol,
                depth=depth,
                max_nodes=max_nodes,
            )
        elif language or kind:
            langs = list(language) if language else None
            kinds = list(kind) if kind else None
            console.print("[bold cyan]Exporting filtered graph...[/bold cyan]")
            data = GraphExporter.export_filtered(
                store,
                output if fmt == "json" else "/dev/null",
                languages=langs,
                kinds=kinds,
                max_nodes=max_nodes,
            )
        else:
            console.print(f"[bold cyan]Exporting graph[/bold cyan] (max {max_nodes} nodes)...")
            data = GraphExporter.export_full(
                store,
                output if fmt == "json" else "/dev/null",
                max_nodes=max_nodes,
            )

        if fmt == "json":
            # Write JSON directly
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            console.print(
                f"[green]✓[/green] Exported [bold]{data['metadata']['total_nodes']}[/bold] nodes, "
                f"[bold]{data['metadata']['total_edges']}[/bold] edges"
            )
            console.print(f"[green]✓[/green] JSON saved to [bold]{output}[/bold]")
        else:
            # Render HTML
            out_path = GraphRenderer.render(data, output, title=title)
            size_kb = out_path.stat().st_size / 1024
            console.print(
                f"[green]✓[/green] Rendered [bold]{data['metadata']['total_nodes']}[/bold] nodes, "
                f"[bold]{data['metadata']['total_edges']}[/bold] edges"
            )
            console.print(f"[green]✓[/green] HTML saved to [bold]{out_path}[/bold] ({size_kb:.1f} KB)")

            if auto_open:
                webbrowser.open(f"file://{out_path}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)
    finally:
        store.close()
