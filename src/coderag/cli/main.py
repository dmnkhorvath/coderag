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



# ── analyze ────────────────────────────────────────────────────

@cli.command()
@click.argument("symbol")
@click.option(
    "--depth", "-d", default=3, show_default=True,
    help="Maximum blast radius depth.",
)
@click.option(
    "--budget", "-b", default=4000, show_default=True,
    help="Token budget for context assembly.",
)
@click.option(
    "--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown",
    help="Output format.",
)
@click.pass_context
def analyze(ctx: click.Context, symbol: str, depth: int, budget: int, fmt: str) -> None:
    """Analyze a symbol's blast radius and impact.

    Shows which nodes are affected if the given symbol changes,
    organized by depth level.
    """
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
    from coderag.output.context import ContextAssembler

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        # Load graph into analyzer
        with console.status("[bold cyan]Loading graph into analyzer..."):
            analyzer = NetworkXAnalyzer()
            analyzer.load_from_store(store)

        console.print(
            f"[green]✓[/green] Graph loaded: "
            f"[bold]{analyzer.node_count:,}[/bold] nodes, "
            f"[bold]{analyzer.edge_count:,}[/bold] edges"
        )
        console.print()

        if fmt == "json":
            # Find node
            node = store.get_node_by_qualified_name(symbol)
            if not node:
                results = store.search_nodes(symbol, limit=1)
                node = results[0] if results else None

            if not node:
                console.print(f"[red]Symbol not found:[/red] {symbol}")
                return

            blast = analyzer.blast_radius(node.id, max_depth=depth)
            data = {
                "symbol": node.qualified_name,
                "kind": node.kind.value if isinstance(node.kind, NodeKind) else node.kind,
                "file": node.file_path,
                "blast_radius": {},
            }
            for d, node_ids in blast.items():
                data["blast_radius"][str(d)] = []
                for nid in node_ids:
                    n = store.get_node(nid)
                    if n:
                        data["blast_radius"][str(d)].append({
                            "id": n.id,
                            "kind": n.kind.value if isinstance(n.kind, NodeKind) else n.kind,
                            "name": n.qualified_name,
                            "file": n.file_path,
                        })

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            # Use ContextAssembler for rich output
            assembler = ContextAssembler()
            result = assembler.assemble_impact_analysis(
                symbol, store, analyzer, token_budget=budget
            )
            formatter.render_to_console(result.text, console)

            console.print()
            console.print(
                f"[dim]Tokens: {result.tokens_used}/{result.token_budget} | "
                f"Nodes: {result.nodes_included}/{result.nodes_available}[/dim]"
            )
    finally:
        store.close()


# ── architecture ──────────────────────────────────────────────

@cli.command()
@click.option(
    "--top", "-t", default=20, show_default=True,
    help="Number of top nodes to show.",
)
@click.option(
    "--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown",
    help="Output format.",
)
@click.pass_context
def architecture(ctx: click.Context, top: int, fmt: str) -> None:
    """Show architecture overview of the codebase.

    Displays communities, important nodes (by PageRank),
    and entry points.
    """
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        # Load graph
        with console.status("[bold cyan]Loading graph into analyzer..."):
            analyzer = NetworkXAnalyzer()
            analyzer.load_from_store(store)

        console.print(
            f"[green]✓[/green] Graph loaded: "
            f"[bold]{analyzer.node_count:,}[/bold] nodes, "
            f"[bold]{analyzer.edge_count:,}[/bold] edges"
        )
        console.print()

        # Compute analyses
        with console.status("[bold cyan]Computing PageRank..."):
            pr_scores = analyzer.pagerank()
            top_nodes_raw = analyzer.get_top_nodes("pagerank", limit=top)

        with console.status("[bold cyan]Detecting communities..."):
            communities_raw = analyzer.community_detection()

        with console.status("[bold cyan]Finding entry points..."):
            entry_point_ids = analyzer.get_entry_points(limit=15)

        with console.status("[bold cyan]Computing statistics..."):
            stats = analyzer.get_statistics()

        if fmt == "json":
            data = {
                "statistics": stats,
                "top_nodes": [
                    {
                        "id": nid,
                        "name": analyzer.get_node_info(nid).get("qualified_name", nid),
                        "kind": analyzer.get_node_info(nid).get("kind", "unknown"),
                        "score": score,
                    }
                    for nid, score in top_nodes_raw
                ],
                "communities": [
                    {"id": i, "size": len(c), "members_sample": list(c)[:10]}
                    for i, c in enumerate(communities_raw[:20])
                ],
                "entry_points": [
                    {
                        "id": nid,
                        "name": analyzer.get_node_info(nid).get("qualified_name", nid),
                        "kind": analyzer.get_node_info(nid).get("kind", "unknown"),
                    }
                    for nid in entry_point_ids
                ],
            }
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            # Resolve nodes for formatting
            important_nodes: list[tuple["Node", float]] = []
            for nid, score in top_nodes_raw:
                node = store.get_node(nid)
                if node:
                    important_nodes.append((node, score))

            entry_points: list["Node"] = []
            for nid in entry_point_ids:
                node = store.get_node(nid)
                if node:
                    entry_points.append(node)

            communities: list[tuple[int, list["Node"]]] = []
            for i, comm_set in enumerate(communities_raw[:10]):
                comm_nodes = []
                for nid in list(comm_set)[:50]:  # Cap per community
                    node = store.get_node(nid)
                    if node:
                        comm_nodes.append(node)
                communities.append((i, comm_nodes))

            # Format and display
            md = MarkdownFormatter.format_architecture_overview(
                communities, important_nodes, entry_points
            )
            formatter.render_to_console(md, console)

            # Stats summary
            console.print()
            console.print("[bold]Graph Statistics[/bold]")
            console.print(f"  Density: {stats.get('density', 0):.6f}")
            console.print(f"  Avg In-Degree: {stats.get('avg_in_degree', 0):.1f}")
            console.print(f"  Avg Out-Degree: {stats.get('avg_out_degree', 0):.1f}")
            console.print(f"  Weakly Connected Components: {stats.get('weakly_connected_components', 0)}")
            console.print(f"  Strongly Connected Components: {stats.get('strongly_connected_components', 0)}")
            console.print(f"  Is DAG: {stats.get('is_dag', False)}")
    finally:
        store.close()



# ── frameworks ────────────────────────────────────────────────

@cli.command()
@click.option(
    "--format", "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.pass_context
def frameworks(ctx: click.Context, fmt: str) -> None:
    """Show detected frameworks and their patterns.

    Displays which frameworks were detected during parsing,
    along with the nodes and edges they contributed.
    """
    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        # Get detected frameworks from metadata
        fw_str = store.get_metadata("detected_frameworks")
        detected = fw_str.split(",") if fw_str else []

        if fmt == "json":
            data: dict[str, Any] = {
                "detected_frameworks": detected,
                "framework_patterns": {},
            }

            for fw_name in detected:
                fw_data: dict[str, Any] = {"nodes": {}, "edges": {}}

                # Count framework-specific nodes
                for kind_name in ("route", "component", "hook", "model",
                                  "event", "listener", "middleware",
                                  "provider", "controller"):
                    try:
                        kind = NodeKind(kind_name)
                        nodes = store.find_nodes(kind=kind, limit=10000)
                        fw_nodes = [
                            n for n in nodes
                            if n.metadata.get("framework") == fw_name
                        ]
                        if fw_nodes:
                            fw_data["nodes"][kind_name] = [
                                {
                                    "name": n.name,
                                    "qualified_name": n.qualified_name,
                                    "file": n.file_path,
                                    "line": n.start_line,
                                }
                                for n in fw_nodes[:50]
                            ]
                    except ValueError:
                        pass

                data["framework_patterns"][fw_name] = fw_data

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            if not detected:
                console.print(
                    "[yellow]No frameworks detected.[/yellow]\n"
                    "Run [cyan]coderag parse <path> --full[/cyan] first."
                )
                return

            console.print(Panel(
                Text.assemble(
                    ("Detected Frameworks", "bold cyan"),
                ),
                expand=False,
            ))

            for fw_name in detected:
                console.print(f"\n[bold green]✓ {fw_name.title()}[/bold green]")

                # Show framework-specific nodes by kind
                for kind_name, label in [
                    ("route", "Routes"),
                    ("component", "Components"),
                    ("hook", "Hooks"),
                    ("model", "Models"),
                    ("event", "Events"),
                    ("listener", "Listeners"),
                    ("middleware", "Middleware"),
                    ("provider", "Providers"),
                    ("controller", "Controllers"),
                ]:
                    try:
                        kind = NodeKind(kind_name)
                        nodes = store.find_nodes(kind=kind, limit=10000)
                        fw_nodes = [
                            n for n in nodes
                            if n.metadata.get("framework") == fw_name
                        ]
                        if fw_nodes:
                            console.print(f"  [bold]{label}[/bold] ({len(fw_nodes)})")
                            for n in fw_nodes[:10]:
                                loc = f"  [dim]{n.file_path}:{n.start_line}[/dim]" if n.start_line else ""
                                console.print(f"    • {n.qualified_name}{loc}")
                            if len(fw_nodes) > 10:
                                console.print(f"    [dim]... and {len(fw_nodes) - 10} more[/dim]")
                    except ValueError:
                        pass

    finally:
        store.close()


# ── cross-language ────────────────────────────────────────────

@cli.command("cross-language")
@click.option(
    "--format", "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--min-confidence", "-c",
    default=0.0,
    type=float,
    help="Minimum confidence threshold for matches.",
)
@click.pass_context
def cross_language(ctx: click.Context, fmt: str, min_confidence: float) -> None:
    """Show cross-language connections.

    Displays API endpoints matched to frontend API calls,
    showing how backend routes connect to frontend code.
    """
    from coderag.core.models import EdgeKind

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    # Infer project root from database path (db is at <root>/.codegraph/graph.db)
    import os as _os
    _project_root = None
    if config.db_path:
        _db_abs = _os.path.abspath(config.db_path)
        _codegraph_dir = _os.path.dirname(_db_abs)
        if _os.path.basename(_codegraph_dir) == ".codegraph":
            _project_root = _os.path.dirname(_codegraph_dir)

    try:
        # Get cross-language stats from metadata
        n_endpoints = store.get_metadata("cross_language_endpoints") or "0"
        n_calls = store.get_metadata("cross_language_calls") or "0"
        n_matches = store.get_metadata("cross_language_matches") or "0"

        # Get API_CALLS edges
        xl_edges = store.get_edges(
            kind=EdgeKind.API_CALLS,
            min_confidence=min_confidence,
        )

        if fmt == "json":
            data = {
                "summary": {
                    "endpoints_found": int(n_endpoints),
                    "api_calls_found": int(n_calls),
                    "matches": int(n_matches),
                    "edges": len(xl_edges),
                },
                "connections": [],
            }

            for edge in xl_edges:
                source_node = store.get_node(edge.source_id)
                target_node = store.get_node(edge.target_id)
                data["connections"].append({
                    "caller": {
                        "name": source_node.qualified_name if source_node else edge.source_id,
                        "file": source_node.file_path if source_node else None,
                    },
                    "endpoint": {
                        "name": target_node.qualified_name if target_node else edge.target_id,
                        "file": target_node.file_path if target_node else None,
                    },
                    "http_method": edge.metadata.get("http_method", "UNKNOWN"),
                    "call_url": edge.metadata.get("call_url", ""),
                    "endpoint_url": edge.metadata.get("endpoint_url", ""),
                    "match_strategy": edge.metadata.get("match_strategy", ""),
                    "confidence": edge.confidence,
                })

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            console.print(Panel(
                Text.assemble(
                    ("Cross-Language Connections", "bold cyan"),
                ),
                expand=False,
            ))

            console.print(f"  Endpoints found:  [bold]{n_endpoints}[/bold]")
            console.print(f"  API calls found:  [bold]{n_calls}[/bold]")
            console.print(f"  Matches:          [bold]{n_matches}[/bold]")
            console.print(f"  Edges:            [bold]{len(xl_edges)}[/bold]")

            if not xl_edges:
                console.print(
                    "\n[yellow]No cross-language connections found.[/yellow]\n"
                    "This requires a mixed-language project with backend API routes "
                    "and frontend API calls."
                )
                return

            console.print("\n[bold]Connections:[/bold]")

            # Group by match strategy
            by_strategy: dict[str, list] = {}
            for edge in xl_edges:
                strategy = edge.metadata.get("match_strategy", "unknown")
                by_strategy.setdefault(strategy, []).append(edge)

            strategy_order = ["exact", "parameterized", "prefix", "fuzzy", "unknown"]
            for strategy in strategy_order:
                edges_for_strategy = by_strategy.get(strategy, [])
                if not edges_for_strategy:
                    continue

                strategy_label = {
                    "exact": "✅ Exact Matches",
                    "parameterized": "🔄 Parameterized Matches",
                    "prefix": "🔗 Prefix Matches",
                    "fuzzy": "🔍 Fuzzy Matches",
                    "unknown": "❓ Other Matches",
                }.get(strategy, strategy)

                console.print(f"\n  [bold]{strategy_label}[/bold] ({len(edges_for_strategy)})")

                for edge in edges_for_strategy[:20]:
                    source_node = store.get_node(edge.source_id)
                    target_node = store.get_node(edge.target_id)

                    method = edge.metadata.get("http_method", "?")
                    call_url = edge.metadata.get("call_url", "?")
                    ep_url = edge.metadata.get("endpoint_url", "?")

                    caller_name = source_node.qualified_name if source_node else "?"
                    caller_file = source_node.file_path if source_node else "?"
                    handler_name = target_node.qualified_name if target_node else "?"
                    handler_file = target_node.file_path if target_node else "?"

                    # Clean up display names: extract short name from qualified_name
                    # e.g. "/path/to/file.ts/storeName" → "storeName"
                    if caller_name != "?" and caller_file != "?":
                        if caller_name.startswith(caller_file):
                            short = caller_name[len(caller_file):].lstrip("/")
                            if short:
                                caller_name = short
                    # Show relative paths if possible
                    _root = config.project_root or _project_root
                    if caller_file != "?" and _root:
                        import os as _os
                        try:
                            caller_file = _os.path.relpath(caller_file, _root)
                        except ValueError:
                            pass
                    if handler_file != "?" and _root:
                        import os as _os
                        try:
                            handler_file = _os.path.relpath(handler_file, _root)
                        except ValueError:
                            pass

                    console.print(
                        f"    [cyan]{method}[/cyan] {call_url} → {ep_url}\n"
                        f"      [dim]Caller:[/dim]  {caller_name} [dim]({caller_file})[/dim]\n"
                        f"      [dim]Handler:[/dim] {handler_name} [dim]({handler_file})[/dim]\n"
                        f"      [dim]Confidence:[/dim] {edge.confidence:.2f}"
                    )

                if len(edges_for_strategy) > 20:
                    console.print(
                        f"    [dim]... and {len(edges_for_strategy) - 20} more[/dim]"
                    )

    finally:
        store.close()



# ── serve ─────────────────────────────────────────────────────

@cli.command()
@click.argument("project_dir", default=".", type=click.Path(exists=True))
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="Override path to graph database (default: PROJECT_DIR/.codegraph/graph.db).",
)
@click.pass_context
def serve(ctx: click.Context, project_dir: str, db: str | None) -> None:
    """Start MCP server for LLM tool integration.

    Exposes the knowledge graph as MCP tools that LLMs can call
    to understand code structure and relationships.

    Uses stdio transport (for Claude Code, Cursor, etc.).
    Diagnostic messages are printed to stderr.

    PROJECT_DIR is the project root directory (default: current directory).
    """
    from pathlib import Path as _Path

    resolved_dir = str(_Path(project_dir).resolve())
    db_override = db or ctx.obj.get("db_override")

    from coderag.mcp.server import run_stdio_server
    run_stdio_server(resolved_dir, db_override)

# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    cli()
