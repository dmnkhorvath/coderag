"""CodeRAG CLI — Build knowledge graphs from your codebase.

Provides commands for parsing codebases, querying the knowledge graph,
and managing CodeRAG projects.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

from coderag.core.config import CodeGraphConfig
from coderag.core.models import DetailLevel, NodeKind
from coderag.core.registry import PluginRegistry
from coderag.output.markdown import MarkdownFormatter
from coderag.storage.sqlite_store import SQLiteStore

console = Console()
formatter = MarkdownFormatter()


# ── Helpers ───────────────────────────────────────────────────

def _load_config(config_path: str | None, project_root: str | None = None) -> CodeGraphConfig:
    """Load config from YAML or create defaults."""
    if config_path and os.path.isfile(config_path):
        cfg = CodeGraphConfig.from_yaml(config_path)
        if project_root:
            cfg.project_root = str(Path(project_root).resolve())
        return cfg

    # Try common locations
    search_dirs = []
    if project_root:
        search_dirs.append(project_root)
    search_dirs.append(os.getcwd())

    for d in search_dirs:
        for name in ("codegraph.yaml", "codegraph.yml", ".codegraph.yaml"):
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                cfg = CodeGraphConfig.from_yaml(candidate)
                if project_root:
                    cfg.project_root = str(Path(project_root).resolve())
                return cfg

    # Fall back to defaults
    cfg = CodeGraphConfig.default()
    if project_root:
        cfg.project_root = str(Path(project_root).resolve())
        cfg.project_name = Path(project_root).name
    return cfg


def _open_store(config: CodeGraphConfig) -> SQLiteStore:
    """Open an existing SQLite store, or error if it doesn't exist."""
    db_path = config.db_path_absolute
    if not os.path.isfile(db_path):
        console.print(
            f"[red]Error:[/red] Database not found at [bold]{db_path}[/bold]\n"
            f"Run [cyan]coderag parse <path>[/cyan] first to build the graph."
        )
        raise SystemExit(1)
    store = SQLiteStore(db_path)
    store.initialize()
    return store


def _setup_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    if verbosity >= 3:
        level = logging.DEBUG
    elif verbosity >= 2:
        level = logging.INFO
    elif verbosity >= 1:
        level = logging.WARNING
    else:
        level = logging.ERROR

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


# ── Main CLI Group ────────────────────────────────────────────

@click.group()
@click.option(
    "--config", "-c",
    default=None,
    type=click.Path(),
    help="Config file path (default: codegraph.yaml in project root).",
)
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="Override database path.",
)
@click.option(
    "--verbose", "-v",
    count=True,
    help="Increase verbosity (-v=info, -vv=debug).",
)
@click.version_option(version="0.1.0", prog_name="coderag")
@click.pass_context
def cli(ctx: click.Context, config: str | None, db: str | None, verbose: int) -> None:
    """CodeRAG \u2014 Build knowledge graphs from your codebase."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["db_override"] = db
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose + 1)  # +1 so default shows warnings


# ── parse ─────────────────────────────────────────────────────

@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--incremental/--full",
    default=True,
    help="Incremental (default) or full re-parse.",
)
@click.pass_context
def parse(ctx: click.Context, path: str, incremental: bool) -> None:
    """Parse a codebase and build the knowledge graph."""
    from coderag.pipeline.orchestrator import PipelineOrchestrator
    from coderag.plugins import BUILTIN_PLUGINS

    project_root = str(Path(path).resolve())
    config = _load_config(ctx.obj["config_path"], project_root)

    # Override DB path if specified
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    # Ensure DB directory exists
    db_path = config.db_path_absolute
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    console.print(Panel(
        Text.assemble(
            ("CodeRAG", "bold cyan"),
            (" \u2014 Parsing ", "dim"),
            (project_root, "bold white"),
        ),
        expand=False,
    ))
    console.print(f"  Database: [dim]{db_path}[/dim]")
    mode_str = "incremental" if incremental else "full"
    console.print(f"  Mode:     [dim]{mode_str}[/dim]")
    console.print()

    # Initialize plugin registry
    registry = PluginRegistry()
    for plugin_cls in BUILTIN_PLUGINS:
        registry.register_plugin(plugin_cls())

    # Initialize store
    store = SQLiteStore(db_path)
    store.initialize()

    # Initialize plugins
    registry.initialize_all({}, project_root)

    # Run pipeline
    orchestrator = PipelineOrchestrator(config, registry, store)

    start_time = time.monotonic()
    summary = orchestrator.run(project_root, incremental=incremental)
    elapsed = time.monotonic() - start_time

    # Display results
    formatter.render_parse_results(summary, console)
    console.print()
    console.print(f"[green]\u2713[/green] Parse completed in [bold]{elapsed:.2f}s[/bold]")


# ── info ──────────────────────────────────────────────────────

@cli.command()
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def info(ctx: click.Context, as_json: bool) -> None:
    """Show graph statistics and project information."""
    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        summary = store.get_summary()

        if as_json:
            data = {
                "project_name": summary.project_name,
                "project_root": summary.project_root,
                "db_path": summary.db_path,
                "db_size_bytes": summary.db_size_bytes,
                "last_parsed": summary.last_parsed,
                "total_nodes": summary.total_nodes,
                "total_edges": summary.total_edges,
                "nodes_by_kind": summary.nodes_by_kind,
                "edges_by_kind": summary.edges_by_kind,
                "files_by_language": summary.files_by_language,
                "frameworks": summary.frameworks,
                "communities": summary.communities,
                "avg_confidence": summary.avg_confidence,
                "top_nodes_by_pagerank": [
                    {"name": n, "qualified_name": q, "pagerank": p}
                    for n, q, p in summary.top_nodes_by_pagerank
                ],
            }
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            formatter.render_summary_table(summary, console)
    finally:
        store.close()


# ── query ─────────────────────────────────────────────────────

@cli.command()
@click.argument("search")
@click.option(
    "--kind", "-k",
    default=None,
    help="Filter by node kind (class, function, method, etc.).",
)
@click.option(
    "--depth", "-d",
    default=1,
    type=int,
    help="Neighbor traversal depth (default: 1).",
)
@click.option(
    "--format", "-f", "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--limit", "-l",
    default=20,
    type=int,
    help="Maximum number of results.",
)
@click.pass_context
def query(ctx: click.Context, search: str, kind: str | None, depth: int, fmt: str, limit: int) -> None:
    """Query the knowledge graph by searching for symbols."""
    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        # Search nodes (kind filter applied at SQL level for efficiency)
        results = store.search_nodes(search, limit=limit, kind=kind.lower() if kind else None)

        if fmt == "json":
            data = []
            for node in results:
                node_data = {
                    "id": node.id,
                    "kind": node.kind.value if isinstance(node.kind, NodeKind) else node.kind,
                    "name": node.name,
                    "qualified_name": node.qualified_name,
                    "file_path": node.file_path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "language": node.language,
                    "pagerank": node.pagerank,
                }

                if depth > 0:
                    neighbors = store.get_neighbors(node.id, max_depth=depth)
                    node_data["relationships"] = [
                        {
                            "node": {
                                "id": n.id,
                                "kind": n.kind.value if isinstance(n.kind, NodeKind) else n.kind,
                                "name": n.qualified_name,
                            },
                            "edge_kind": e.kind.value if hasattr(e.kind, "value") else e.kind,
                            "direction": "outgoing" if e.source_id == node.id else "incoming",
                            "confidence": e.confidence,
                            "depth": d,
                        }
                        for n, e, d in neighbors
                    ]

                data.append(node_data)

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            # Markdown output with rich
            if not results:
                console.print(f"[yellow]No results found for:[/yellow] [bold]{search}[/bold]")
                return

            # Show search results table
            formatter.render_search_results(results, search, console)

            # Show details for each result with neighbors
            if depth > 0:
                console.print()
                for node in results:
                    neighbors = store.get_neighbors(node.id, max_depth=depth)
                    md = formatter.format_node_with_edges(node, neighbors, DetailLevel.SUMMARY)
                    formatter.render_to_console(md, console)
                    console.print("---")
    finally:
        store.close()


# ── init ──────────────────────────────────────────────────────

@cli.command("init")
@click.option(
    "--languages", "-l",
    default="php,javascript,typescript",
    help="Comma-separated list of languages to enable.",
)
@click.option(
    "--name", "-n",
    default=None,
    help="Project name (default: directory name).",
)
@click.pass_context
def init_cmd(ctx: click.Context, languages: str, name: str | None) -> None:
    """Initialize a codegraph.yaml config file in the current directory."""
    output_path = os.path.join(os.getcwd(), "codegraph.yaml")

    if os.path.exists(output_path):
        if not click.confirm(f"Config file already exists at {output_path}. Overwrite?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    project_name = name or Path(os.getcwd()).name
    lang_list = [lang.strip() for lang in languages.split(",")]

    # Build YAML content
    lang_section = ""
    for lang in lang_list:
        ext_map = {
            "php": '[".php"]',
            "javascript": '[".js", ".jsx", ".mjs", ".cjs"]',
            "typescript": '[".ts", ".tsx"]',
        }
        extensions = ext_map.get(lang, '[]')
        lang_section += f"""  {lang}:
    enabled: true
    extensions: {extensions}
"""

    yaml_content = f"""# CodeRAG Configuration
# Generated by: coderag init

project:
  name: "{project_name}"
  root: "."

storage:
  db_path: ".codegraph/graph.db"

languages:
{lang_section}
performance:
  max_workers: 4
  batch_size: 500
  max_file_size_bytes: 1048576  # 1MB

output:
  default_format: markdown
  default_detail_level: summary
  default_token_budget: 8000

ignore_patterns:
  - "node_modules/**"
  - "vendor/**"
  - ".git/**"
  - "*.min.js"
  - "*.min.css"
  - "dist/**"
  - "build/**"
  - "__pycache__/**"
  - ".codegraph/**"
  - "*.lock"
"""

    with open(output_path, "w") as f:
        f.write(yaml_content)

    console.print(f"[green]\u2713[/green] Created [bold]{output_path}[/bold]")
    console.print(f"  Project: [cyan]{project_name}[/cyan]")
    console.print(f"  Languages: [cyan]{', '.join(lang_list)}[/cyan]")
    console.print()
    console.print("Next steps:")
    console.print("  1. Edit [bold]codegraph.yaml[/bold] to customize settings")
    console.print("  2. Run [cyan]coderag parse .[/cyan] to build the knowledge graph")
    console.print("  3. Run [cyan]coderag info[/cyan] to view graph statistics")
    console.print("  4. Run [cyan]coderag query <search>[/cyan] to search the graph")


# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    cli()
