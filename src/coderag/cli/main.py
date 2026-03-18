"""CodeRAG CLI — Build knowledge graphs from your codebase.

Provides commands for parsing codebases, querying the knowledge graph,
and managing CodeRAG projects.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from coderag.core.config import CodeGraphConfig
from coderag.core.models import DetailLevel, Node, NodeKind
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
    "--config",
    "-c",
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
    "--verbose",
    "-v",
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

    console.print(
        Panel(
            Text.assemble(
                ("CodeRAG", "bold cyan"),
                (" \u2014 Parsing ", "dim"),
                (project_root, "bold white"),
            ),
            expand=False,
        )
    )
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
                    {"name": n, "qualified_name": q, "pagerank": p} for n, q, p in summary.top_nodes_by_pagerank
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
    "--kind",
    "-k",
    default=None,
    help="Filter by node kind (class, function, method, etc.).",
)
@click.option(
    "--depth",
    "-d",
    default=1,
    type=int,
    help="Neighbor traversal depth (default: 1).",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--limit",
    "-l",
    default=20,
    type=int,
    help="Maximum number of results.",
)
@click.option(
    "--semantic",
    "mode",
    flag_value="semantic",
    help="Use pure semantic (vector) search.",
)
@click.option(
    "--hybrid",
    "mode",
    flag_value="hybrid",
    help="Use hybrid search (FTS5 + vector). Default when vector index exists.",
)
@click.option(
    "--fts",
    "mode",
    flag_value="fts",
    help="Use pure FTS5 (keyword) search.",
)
@click.option(
    "--alpha",
    "-a",
    default=0.5,
    type=float,
    help="Hybrid search balance: 0.0=pure FTS, 1.0=pure vector (default: 0.5).",
)
@click.pass_context
def query(
    ctx: click.Context, search: str, kind: str | None, depth: int, fmt: str, limit: int, mode: str | None, alpha: float
) -> None:
    """Query the knowledge graph by searching for symbols.

    Supports three search modes: FTS5 (keyword), semantic (vector), and hybrid.
    When a vector index exists, hybrid mode is used by default.
    """
    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        # Determine search mode
        use_semantic = False
        use_hybrid = False
        vector_dir = os.path.dirname(config.db_path_absolute)

        if mode == "semantic":
            use_semantic = True
        elif mode == "hybrid":
            use_hybrid = True
        elif mode is None:
            # Auto-detect: use hybrid if vector index exists
            try:
                from coderag.search import SEMANTIC_AVAILABLE

                if SEMANTIC_AVAILABLE:
                    from coderag.search.vector_store import VectorStore

                    if VectorStore.exists(vector_dir):
                        use_hybrid = True
            except ImportError:
                pass

        # Semantic or hybrid search
        if use_semantic or use_hybrid:
            try:
                from coderag.search import SEMANTIC_AVAILABLE, require_semantic

                require_semantic()
                from coderag.search.embedder import CodeEmbedder
                from coderag.search.hybrid import HybridSearcher, SearchResult  # noqa: F401
                from coderag.search.vector_store import VectorStore

                if not VectorStore.exists(vector_dir):
                    console.print("[yellow]No vector index found. Run 'coderag embed' first.[/yellow]")
                    console.print("Falling back to FTS5 search...\n")
                    use_semantic = False
                    use_hybrid = False
                else:
                    embedder = CodeEmbedder(config.semantic_model)
                    vs = VectorStore.load(vector_dir)
                    searcher = HybridSearcher(store, vs, embedder)

                    if use_semantic:
                        search_results = searcher.search_semantic(search, k=limit, kind=kind.lower() if kind else None)
                    else:
                        search_results = searcher.search(
                            search, k=limit, alpha=alpha, kind=kind.lower() if kind else None
                        )

                    if fmt == "json":
                        data = []
                        for sr in search_results:
                            node = store.get_node(sr.node_id)
                            if node is None:
                                continue
                            node_data = {
                                "id": sr.node_id,
                                "kind": sr.kind,
                                "name": sr.name,
                                "qualified_name": sr.qualified_name,
                                "file_path": sr.file_path,
                                "language": sr.language,
                                "score": sr.score,
                                "match_type": sr.match_type,
                                "vector_similarity": sr.vector_similarity,
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
                        if not search_results:
                            console.print(f"[yellow]No results found for:[/yellow] [bold]{search}[/bold]")
                            return

                        mode_label = "semantic" if use_semantic else f"hybrid (alpha={alpha})"
                        console.print(f"[dim]Search mode: {mode_label}[/dim]\n")

                        table = Table(title=f"Search results for '{search}'")
                        table.add_column("#", style="dim", width=4)
                        table.add_column("Symbol", style="cyan")
                        table.add_column("Kind", style="green")
                        table.add_column("File", style="blue")
                        table.add_column("Match", style="magenta")
                        table.add_column("Score", style="yellow", justify="right")

                        for i, sr in enumerate(search_results, 1):
                            table.add_row(
                                str(i),
                                sr.qualified_name or sr.name,
                                sr.kind,
                                sr.file_path or "",
                                sr.match_type,
                                f"{sr.score:.4f}",
                            )
                        console.print(table)

                        if depth > 0:
                            console.print()
                            for sr in search_results:
                                node = store.get_node(sr.node_id)
                                if node is None:
                                    continue
                                neighbors = store.get_neighbors(node.id, max_depth=depth)
                                md = formatter.format_node_with_edges(node, neighbors, DetailLevel.SUMMARY)
                                formatter.render_to_console(md, console)
                                console.print("---")
                    return
            except ImportError:
                console.print(
                    "[yellow]Semantic search requires extra dependencies.[/yellow]\n"
                    "Install with: [bold]pip install coderag[semantic][/bold]\n"
                    "Falling back to FTS5 search...\n"
                )

        # FTS5 search (default fallback)
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
    "--languages",
    "-l",
    default="php,javascript,typescript",
    help="Comma-separated list of languages to enable.",
)
@click.option(
    "--name",
    "-n",
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
        extensions = ext_map.get(lang, "[]")
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
    "--depth",
    "-d",
    default=3,
    show_default=True,
    help="Maximum blast radius depth.",
)
@click.option(
    "--budget",
    "-b",
    default=4000,
    show_default=True,
    help="Token budget for context assembly.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
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
                        data["blast_radius"][str(d)].append(
                            {
                                "id": n.id,
                                "kind": n.kind.value if isinstance(n.kind, NodeKind) else n.kind,
                                "name": n.qualified_name,
                                "file": n.file_path,
                            }
                        )

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            # Use ContextAssembler for rich output
            assembler = ContextAssembler()
            result = assembler.assemble_impact_analysis(symbol, store, analyzer, token_budget=budget)
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
    "--top",
    "-t",
    default=20,
    show_default=True,
    help="Number of top nodes to show.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
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
            analyzer.pagerank()
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
            important_nodes: list[tuple[Node, float]] = []
            for nid, score in top_nodes_raw:
                node = store.get_node(nid)
                if node:
                    important_nodes.append((node, score))

            entry_points: list[Node] = []
            for nid in entry_point_ids:
                node = store.get_node(nid)
                if node:
                    entry_points.append(node)

            communities: list[tuple[int, list[Node]]] = []
            for i, comm_set in enumerate(communities_raw[:10]):
                comm_nodes = []
                for nid in list(comm_set)[:50]:  # Cap per community
                    node = store.get_node(nid)
                    if node:
                        comm_nodes.append(node)
                communities.append((i, comm_nodes))

            # Format and display
            md = MarkdownFormatter.format_architecture_overview(communities, important_nodes, entry_points)
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
    "--format",
    "fmt",
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
                for kind_name in (
                    "route",
                    "component",
                    "hook",
                    "model",
                    "event",
                    "listener",
                    "middleware",
                    "provider",
                    "controller",
                ):
                    try:
                        kind = NodeKind(kind_name)
                        nodes = store.find_nodes(kind=kind, limit=10000)
                        fw_nodes = [n for n in nodes if n.metadata.get("framework") == fw_name]
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
                    "[yellow]No frameworks detected.[/yellow]\nRun [cyan]coderag parse <path> --full[/cyan] first."
                )
                return

            console.print(
                Panel(
                    Text.assemble(
                        ("Detected Frameworks", "bold cyan"),
                    ),
                    expand=False,
                )
            )

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
                        fw_nodes = [n for n in nodes if n.metadata.get("framework") == fw_name]
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
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--min-confidence",
    "-c",
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
                data["connections"].append(
                    {
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
                    }
                )

            click.echo(json.dumps(data, indent=2, default=str))
        else:
            console.print(
                Panel(
                    Text.assemble(
                        ("Cross-Language Connections", "bold cyan"),
                    ),
                    expand=False,
                )
            )

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
                            short = caller_name[len(caller_file) :].lstrip("/")
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
                    console.print(f"    [dim]... and {len(edges_for_strategy) - 20} more[/dim]")

    finally:
        store.close()


# ── serve ─────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--format",
    "-f",
    type=click.Choice(["markdown", "json", "tree"]),
    default="markdown",
    help="Output format (default: markdown).",
)
@click.option(
    "--scope",
    "-s",
    type=click.Choice(["full", "architecture", "file", "symbol"]),
    default="architecture",
    help="Export scope (default: architecture).",
)
@click.option(
    "--symbol",
    default=None,
    help="Symbol name (required for symbol scope).",
)
@click.option(
    "--file",
    "file_path",
    default=None,
    help="File path (required for file scope).",
)
@click.option(
    "--tokens",
    default=8000,
    type=int,
    help="Token budget for output (default: 8000).",
)
@click.option(
    "--top",
    default=20,
    type=int,
    help="Top N items for architecture scope (default: 20).",
)
@click.option(
    "--depth",
    default=2,
    type=int,
    help="Traversal depth for symbol scope (default: 2).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output file path (default: stdout).",
)
@click.pass_context
def export(
    ctx: click.Context,
    format: str,
    scope: str,
    symbol: str | None,
    file_path: str | None,
    tokens: int,
    top: int,
    depth: int,
    output: str | None,
) -> None:
    """Export knowledge graph in various formats for LLM consumption.

    Supports markdown, JSON, and tree formats with configurable scopes
    (full, architecture, file, symbol) and token budgeting.

    Examples:

      coderag export                          # architecture overview in markdown

      coderag export -f json -s full          # full graph as JSON

      coderag export -s symbol --symbol User  # symbol context

      coderag export -s file --file app/User.php  # file context

      coderag export -f tree -s full          # repo map tree view

      coderag export --tokens 16000 -o out.md # larger budget, save to file
    """
    from coderag.export import ExportOptions, GraphExporter

    config = ctx.obj["config"]
    store = _open_store(config)

    try:
        options = ExportOptions(
            format=format,
            scope=scope,
            symbol=symbol,
            file_path=file_path,
            max_tokens=tokens,
            top_n=top,
            depth=depth,
        )
        exporter = GraphExporter(store)
        result = exporter.export(options)

        if output:
            import os

            os.makedirs(os.path.dirname(output) if os.path.dirname(output) else ".", exist_ok=True)
            with open(output, "w") as f:
                f.write(result)
            click.echo(f"Exported to {output} ({len(result)} chars, ~{len(result) // 4} tokens)", err=True)
        else:
            click.echo(result)
    finally:
        store.close()


@cli.command()
@click.argument("project_dir", default=".", type=click.Path(exists=True))
@click.option(
    "--db",
    default=None,
    type=click.Path(),
    help="Override path to graph database (default: PROJECT_DIR/.codegraph/graph.db).",
)
@click.option(
    "--no-reload",
    is_flag=True,
    default=False,
    help="Disable hot-reload (auto-reload when database changes).",
)
@click.option(
    "--watch",
    "watch_files",
    is_flag=True,
    default=False,
    help="Watch for file changes and auto-reparse alongside the MCP server.",
)
@click.option(
    "--debounce",
    default=2.0,
    type=float,
    help="Debounce interval in seconds for file watcher (default: 2.0).",
)
@click.pass_context
def serve(
    ctx: click.Context,
    project_dir: str,
    db: str | None,
    no_reload: bool,
    watch_files: bool,
    debounce: float,
) -> None:
    """Start MCP server for LLM tool integration.

    Exposes the knowledge graph as MCP tools that LLMs can call
    to understand code structure and relationships.

    Uses stdio transport (for Claude Code, Cursor, etc.).
    Diagnostic messages are printed to stderr.

    By default, the server watches the database file for changes and
    automatically reloads when it detects a re-parse. Use --no-reload
    to disable this behavior.

    Use --watch to also monitor the project for file changes and
    automatically reparse when source files are created, modified,
    or deleted. This combines `coderag serve` and `coderag watch`
    into a single process.

    PROJECT_DIR is the project root directory (default: current directory).
    """
    import sys as _sys
    from pathlib import Path as _Path

    resolved_dir = str(_Path(project_dir).resolve())
    db_override = db or ctx.obj.get("db_override")

    watcher = None
    if watch_files:
        from coderag.pipeline.events import EventEmitter
        from coderag.pipeline.watcher import FileWatcher
        from coderag.plugins import BUILTIN_PLUGINS
        from coderag.plugins.registry import PluginRegistry
        from coderag.storage.sqlite_store import SQLiteStore

        config = _load_config(ctx.obj["config_path"], resolved_dir)
        if db_override:
            config.db_path = db_override

        db_path = config.db_path_absolute
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        registry = PluginRegistry()
        for plugin_cls in BUILTIN_PLUGINS:
            registry.register(plugin_cls())

        store = SQLiteStore(db_path)
        store.initialize()

        emitter = EventEmitter()

        watcher = FileWatcher(config, registry, store, emitter, debounce_seconds=debounce)
        watcher.start(resolved_dir, blocking=False)
        print(
            f"File watcher: active (debounce={debounce}s)",
            file=_sys.stderr,
        )

    try:
        from coderag.mcp.server import run_stdio_server

        run_stdio_server(resolved_dir, db_override, hot_reload=not no_reload)
    finally:
        if watcher is not None:
            watcher.stop()
            store.close()


# ── Enrich Command ────────────────────────────────────────────────


@cli.command()
@click.option(
    "--phpstan",
    is_flag=True,
    default=False,
    help="Run PHPStan type enrichment on PHP files.",
)
@click.option(
    "--level",
    type=int,
    default=5,
    help="PHPStan analysis level (0-9, default: 5).",
)
@click.option(
    "--phpstan-path",
    type=str,
    default="phpstan",
    help="Path to PHPStan binary.",
)
@click.pass_context
def enrich(ctx: click.Context, phpstan: bool, level: int, phpstan_path: str) -> None:
    """Enrich the knowledge graph with additional metadata.

    Run optional enrichment phases on an already-parsed codebase.
    Currently supports PHPStan type enrichment for PHP projects.

    Examples:

        codegraph enrich --phpstan

        codegraph enrich --phpstan --level 8

        codegraph enrich --phpstan --phpstan-path vendor/bin/phpstan
    """
    from coderag.enrichment.phpstan import PHPStanEnricher

    console = Console()

    if not phpstan:
        console.print("[yellow]No enrichment flags specified. Use --phpstan to run PHPStan enrichment.[/yellow]")
        return

    # Use standard config/store pattern for consistent DB resolution
    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    # Infer project root from config
    project_dir = config.project_root or os.getcwd()

    console.print(f"\n[bold blue]PHPStan Enrichment[/bold blue] (level {level})")
    console.print(f"Project: {os.path.abspath(project_dir)}")
    console.print(f"Database: {config.db_path_absolute}\n")

    enricher = PHPStanEnricher(
        project_root=os.path.abspath(project_dir),
        phpstan_path=phpstan_path,
        level=level,
    )

    if not enricher.is_available():
        console.print(
            "[yellow]PHPStan is not available.[/yellow]\n"
            "Install it with: [bold]composer require --dev phpstan/phpstan[/bold]\n"
            "Or specify the path: [bold]--phpstan-path /path/to/phpstan[/bold]"
        )
        store.close()
        return

    console.print(f"PHPStan version: {enricher.get_version()}")

    try:
        with console.status("Running PHPStan analysis..."):
            report = enricher.enrich_nodes(store)

        # Display report
        if report.skipped_reason:
            console.print(f"[yellow]Skipped: {report.skipped_reason}[/yellow]")
        else:
            table = Table(title="PHPStan Enrichment Report")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green", justify="right")
            table.add_row("Files Analyzed", str(report.files_analyzed))
            table.add_row("Errors Found", str(report.errors_found))
            table.add_row("Nodes Enriched", str(report.nodes_enriched))
            table.add_row("Duration", f"{report.duration_ms:.0f}ms")
            table.add_row("PHPStan Version", report.phpstan_version)
            table.add_row("Analysis Level", str(report.level))
            console.print(table)
    finally:
        store.close()


# ── embed ─────────────────────────────────────────────────────


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--model",
    "-m",
    default=None,
    help="Sentence-transformer model name (default: from config or all-MiniLM-L6-v2).",
)
@click.option(
    "--batch-size",
    "-b",
    default=None,
    type=int,
    help="Embedding batch size (default: from config or 128).",
)
@click.pass_context
def embed(ctx: click.Context, path: str, model: str | None, batch_size: int | None) -> None:
    """Build or rebuild the semantic vector index for a project.

    Embeds all nodes in the knowledge graph using sentence-transformers
    and stores the FAISS index alongside the SQLite database.

    Example:
        coderag embed /path/to/project
        coderag embed /path/to/project --model all-mpnet-base-v2
    """
    try:
        from coderag.search import require_semantic

        require_semantic()
    except ImportError:
        console.print(
            "[red]Semantic search requires extra dependencies.[/red]\n"
            "Install with: [bold]pip install coderag[semantic][/bold]\n"
            "Or: [bold]pip install sentence-transformers faiss-cpu[/bold]"
        )
        raise SystemExit(1)

    from coderag.search.embedder import CodeEmbedder
    from coderag.search.vector_store import VectorStore

    config = _load_config(ctx.obj["config_path"], project_root=path)
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    # Resolve model and batch size from args or config
    model_name = model or config.semantic_model
    bs = batch_size or config.semantic_batch_size

    try:
        console.print(
            Panel(
                f"[bold]Semantic Index Builder[/bold]\n\n"
                f"Project: {os.path.abspath(path)}\n"
                f"Database: {config.db_path_absolute}\n"
                f"Model: {model_name}\n"
                f"Batch size: {bs}",
                title="CodeRAG Embed",
                border_style="blue",
            )
        )

        # Get all nodes
        stats = store.get_stats()
        total_nodes = stats.get("total_nodes", 0)
        if total_nodes == 0:
            console.print("[yellow]No nodes found. Run 'coderag parse' first.[/yellow]")
            return

        console.print(f"\n[bold]Loading {total_nodes} nodes...[/bold]")

        # Fetch all nodes from the store
        all_nodes = store.get_all_nodes()
        console.print(f"Loaded {len(all_nodes)} nodes")

        # Build parent context map for methods
        for node in all_nodes:
            # Check edges for containment to find parent names
            pass  # We'll use qualified_name splitting instead

        # Build text representations
        console.print("\n[bold]Building text representations...[/bold]")
        embedder = CodeEmbedder(model_name)
        texts: list[str] = []
        node_ids: list[str] = []

        for node in all_nodes:
            # Derive parent name from qualified_name
            parent_name = None
            if node.qualified_name and "." in node.qualified_name:
                parts = node.qualified_name.rsplit(".", 1)
                if len(parts) == 2:
                    parent_name = parts[0]
            elif node.qualified_name and "::" in node.qualified_name:
                parts = node.qualified_name.rsplit("::", 1)
                if len(parts) == 2:
                    parent_name = parts[0]

            text = embedder.build_node_text(node, parent_name=parent_name)
            texts.append(text)
            node_ids.append(node.id)

        console.print(f"Built {len(texts)} text representations")

        # Embed in batches with progress
        console.print(f"\n[bold]Embedding nodes...[/bold] (model: {model_name})")

        t0 = time.time()
        all_embeddings = embedder.embed_batch(texts, batch_size=bs)
        embed_time = time.time() - t0

        console.print(f"Embedded {len(texts)} nodes in {embed_time:.1f}s ({len(texts) / embed_time:.0f} nodes/sec)")

        # Build and save index
        console.print("\n[bold]Building FAISS index...[/bold]")
        vs = VectorStore(embedder.dimension)
        vs.build_index(all_embeddings, node_ids)

        vector_dir = os.path.dirname(config.db_path_absolute)
        vs.save(vector_dir)

        # Show stats
        index_path = os.path.join(vector_dir, "vectors.faiss")
        meta_path = os.path.join(vector_dir, "vectors_meta.json")
        index_size = os.path.getsize(index_path) if os.path.exists(index_path) else 0
        meta_size = os.path.getsize(meta_path) if os.path.exists(meta_path) else 0

        console.print()
        table = Table(title="Semantic Index Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")
        table.add_row("Model", model_name)
        table.add_row("Dimensions", str(embedder.dimension))
        table.add_row("Nodes Embedded", f"{vs.size:,}")
        table.add_row("Index Size", f"{index_size / 1024:.1f} KB")
        table.add_row("Metadata Size", f"{meta_size / 1024:.1f} KB")
        table.add_row("Embedding Time", f"{embed_time:.1f}s")
        table.add_row("Throughput", f"{len(texts) / embed_time:.0f} nodes/sec")
        console.print(table)

        console.print(
            f"\n[green]✓ Semantic index saved to {vector_dir}[/green]\n"
            f"Use [bold]coderag query 'your query' --semantic[/bold] to search."
        )

    finally:
        store.close()


# ── watch ──────────────────────────────────────────────────────


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--debounce",
    "-d",
    default=2.0,
    type=float,
    help="Debounce interval in seconds (default: 2.0).",
)
@click.option(
    "--incremental/--full",
    default=True,
    help="Incremental (default) or full re-parse on changes.",
)
@click.pass_context
def watch(ctx: click.Context, path: str, debounce: float, incremental: bool) -> None:
    """Watch a codebase for changes and auto-reparse.

    Monitors the project directory for file changes (create, modify,
    delete) and triggers incremental pipeline runs automatically.
    Respects the same ignore patterns as `coderag parse`.

    Press Ctrl+C to stop watching.
    """
    from coderag.pipeline.events import EventEmitter
    from coderag.pipeline.watcher import FileWatcher
    from coderag.plugins import BUILTIN_PLUGINS

    project_root = str(Path(path).resolve())
    config = _load_config(ctx.obj["config_path"], project_root)

    # Override DB path if specified
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    # Ensure DB directory exists
    db_path = config.db_path_absolute
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    console.print(
        Panel(
            Text.assemble(
                ("CodeRAG", "bold cyan"),
                (" — Watching ", "dim"),
                (project_root, "bold white"),
            ),
            expand=False,
        )
    )
    console.print(f"  Database:  [dim]{db_path}[/dim]")
    console.print(f"  Debounce:  [dim]{debounce}s[/dim]")
    mode_label = "incremental" if incremental else "full"
    console.print(f"  Mode:      [dim]{mode_label}[/dim]")
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

    # Create event emitter for pipeline events
    emitter = EventEmitter()

    def _on_reparse(stats: dict) -> None:
        console.print(
            f"  [green]✓[/green] Reparse complete: "
            f"[bold]{stats.get('files_parsed', 0)}[/bold] files, "
            f"[bold]{stats.get('total_nodes', 0)}[/bold] nodes, "
            f"[bold]{stats.get('total_edges', 0)}[/bold] edges"
        )

    watcher = FileWatcher(
        config=config,
        registry=registry,
        store=store,
        emitter=emitter,
        debounce_seconds=debounce,
        on_reparse=_on_reparse,
    )

    console.print("[bold green]Watching for changes...[/bold green] (Ctrl+C to stop)")
    console.print()

    try:
        watcher.start(project_root, blocking=True)
    except KeyboardInterrupt:
        pass
    finally:
        console.print()
        console.print(f"[bold]Watcher stopped.[/bold] {watcher.reparse_count} reparse(s) completed.")
        store.close()


# -- Find Usages Command ----------------------------------------------------


@cli.command("find-usages")
@click.argument("symbol")
@click.option(
    "--types",
    "-t",
    default="all",
    show_default=True,
    help="Comma-separated usage types: calls, imports, extends, implements, instantiates, type_references, all.",
)
@click.option(
    "--depth",
    "-d",
    default=1,
    show_default=True,
    help="Transitive traversal depth (1=direct, up to 5).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--budget",
    "-b",
    default=4000,
    show_default=True,
    help="Token budget for output.",
)
@click.pass_context
def find_usages(ctx: click.Context, symbol: str, types: str, depth: int, fmt: str, budget: int) -> None:
    """Find all usages of a symbol (calls, imports, extends, etc.).

    Shows where a symbol is called, imported, extended, implemented,
    or instantiated across the codebase.
    """
    from coderag.core.models import EdgeKind
    from coderag.mcp.tools import _USAGE_TYPE_TO_EDGE_KINDS, _format_candidates, _resolve_symbol

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        depth = min(max(depth, 1), 5)
        budget = min(max(budget, 500), 16000)

        node, candidates = _resolve_symbol(symbol, store)
        if node is None:
            if candidates:
                console.print(_format_candidates(candidates, symbol))
            else:
                console.print("[red]Symbol not found:[/red] " + symbol)
            return

        # Parse usage types
        usage_type_list = [t.strip() for t in types.split(",")]
        if "all" in usage_type_list:
            edge_kind_filter = None
        else:
            edge_kind_filter: list[EdgeKind] = []
            for ut in usage_type_list:
                edge_kind_filter.extend(_USAGE_TYPE_TO_EDGE_KINDS.get(ut, []))

        neighbors = store.get_neighbors(
            node_id=node.id,
            direction="incoming",
            edge_kinds=edge_kind_filter,
            max_depth=depth,
        )

        if not neighbors:
            kind = node.kind.value if isinstance(node.kind, NodeKind) else node.kind
            msg = f"No usages found for {node.qualified_name} ({kind}).\nDefined at {node.file_path}:{node.start_line}"
            console.print("[yellow]" + msg + "[/yellow]")
            return

        if fmt == "json":
            data = {
                "symbol": node.qualified_name,
                "kind": node.kind.value if isinstance(node.kind, NodeKind) else node.kind,
                "file": node.file_path,
                "line": node.start_line,
                "total_usages": len(neighbors),
                "usages": [],
            }
            for n, edge, d in neighbors:
                ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                data["usages"].append(
                    {
                        "qualified_name": n.qualified_name,
                        "kind": nk,
                        "edge_kind": ek,
                        "file": n.file_path,
                        "line": n.start_line,
                        "depth": d,
                    }
                )
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            kind = node.kind.value if isinstance(node.kind, NodeKind) else node.kind
            lines = [
                f"## Usages of `{node.qualified_name}`\n",
                f"**Kind**: {kind}  ",
                f"**Defined at**: `{node.file_path}:{node.start_line}`  ",
                f"**Total usages found**: {len(neighbors)}\n",
            ]

            by_depth: dict[int, list[tuple]] = {}
            for n, edge, d in neighbors:
                by_depth.setdefault(d, []).append((n, edge))

            for d in sorted(by_depth.keys()):
                items = by_depth[d]
                lines.append(f"### Depth {d} ({len(items)} usages)\n")

                by_kind: dict[str, list] = {}
                for n, edge in items:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    by_kind.setdefault(ek, []).append(n)

                for ek, nodes_list in sorted(by_kind.items()):
                    lines.append(f"**{ek}** ({len(nodes_list)}):\n")
                    for n in nodes_list:
                        nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                        lines.append(f"- `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)")
                    lines.append("")

            formatter.render_to_console("\n".join(lines), console)
    finally:
        store.close()


# -- Impact Command ----------------------------------------------------------


@cli.command()
@click.argument("symbol")
@click.option(
    "--depth",
    "-d",
    default=3,
    show_default=True,
    help="Impact analysis depth (1-5).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--budget",
    "-b",
    default=4000,
    show_default=True,
    help="Token budget for context assembly.",
)
@click.pass_context
def impact(ctx: click.Context, symbol: str, depth: int, fmt: str, budget: int) -> None:
    """Analyze the blast radius of changing a symbol.

    Shows all code that would be affected by a change,
    organized by depth level. Essential before refactoring.
    """
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
    from coderag.output.context import ContextAssembler

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        depth = min(max(depth, 1), 5)
        budget = min(max(budget, 500), 16000)

        with console.status("[bold cyan]Loading graph into analyzer..."):
            analyzer = NetworkXAnalyzer()
            analyzer.load_from_store(store)

        console.print(
            "[green]\u2713[/green] Graph loaded: "
            f"[bold]{analyzer.node_count:,}[/bold] nodes, "
            f"[bold]{analyzer.edge_count:,}[/bold] edges"
        )
        console.print()

        if fmt == "json":
            node = store.get_node_by_qualified_name(symbol)
            if not node:
                results = store.search_nodes(symbol, limit=1)
                node = results[0] if results else None

            if not node:
                console.print("[red]Symbol not found:[/red] " + symbol)
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
                        data["blast_radius"][str(d)].append(
                            {
                                "id": n.id,
                                "kind": n.kind.value if isinstance(n.kind, NodeKind) else n.kind,
                                "name": n.qualified_name,
                                "file": n.file_path,
                            }
                        )
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            assembler = ContextAssembler()
            result = assembler.assemble_impact_analysis(symbol, store, analyzer, token_budget=budget)
            formatter.render_to_console(result.text, console)

            console.print()
            console.print(
                f"[dim]Tokens: {result.tokens_used}/{result.token_budget} | Nodes: {result.nodes_included}/{result.nodes_available}[/dim]"
            )
    finally:
        store.close()


# -- File Context Command ----------------------------------------------------


@cli.command("file-context")
@click.argument("file_path")
@click.option(
    "--no-source",
    is_flag=True,
    default=False,
    help="Exclude source code snippets.",
)
@click.option(
    "--budget",
    "-b",
    default=4000,
    show_default=True,
    help="Token budget for context assembly.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.pass_context
def file_context(ctx: click.Context, file_path: str, no_source: bool, budget: int, fmt: str) -> None:
    """Get context for a file -- symbols, relationships, and importance.

    Shows all symbols defined in a file, their relationships,
    and how the file connects to the rest of the codebase.
    """
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
    from coderag.mcp.tools import _normalize_file_path
    from coderag.output.context import ContextAssembler

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        budget = min(max(budget, 500), 16000)

        resolved = _normalize_file_path(file_path, store)
        if resolved is None:
            conn = store.connection
            basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
            rows = conn.execute(
                "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE ? LIMIT 10",
                ("%" + basename + "%",),
            ).fetchall()
            if rows:
                console.print("[yellow]File not found. Similar files:[/yellow]")
                for r in rows:
                    console.print("  - " + r[0])
            else:
                console.print("[red]File not found:[/red] " + file_path)
            return

        if fmt == "json":
            nodes = store.find_nodes(file_path=resolved, limit=500)
            data = {
                "file": resolved,
                "total_symbols": len(nodes),
                "symbols": [],
            }
            for n in nodes:
                nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                data["symbols"].append(
                    {
                        "id": n.id,
                        "name": n.name,
                        "qualified_name": n.qualified_name,
                        "kind": nk,
                        "line": n.start_line,
                        "language": n.language,
                    }
                )
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            with console.status("[bold cyan]Loading graph into analyzer..."):
                analyzer = NetworkXAnalyzer()
                analyzer.load_from_store(store)

            assembler = ContextAssembler()
            result = assembler.assemble_for_file(
                file_path=resolved,
                store=store,
                analyzer=analyzer,
                token_budget=budget,
            )
            formatter.render_to_console(result.text, console)

            console.print()
            console.print(
                f"[dim]Tokens: {result.tokens_used}/{result.token_budget} | Nodes: {result.nodes_included}/{result.nodes_available}[/dim]"
            )
    finally:
        store.close()


# -- Routes Command ----------------------------------------------------------


@cli.command()
@click.argument("pattern")
@click.option(
    "--method",
    "-m",
    type=click.Choice(["GET", "POST", "PUT", "PATCH", "DELETE", "ANY"], case_sensitive=False),
    default=None,
    help="Filter by HTTP method.",
)
@click.option(
    "--no-frontend",
    is_flag=True,
    default=False,
    help="Exclude frontend API callers.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.pass_context
def routes(ctx: click.Context, pattern: str, method: str | None, no_frontend: bool, fmt: str) -> None:
    """Find API routes/endpoints matching a URL pattern.

    Supports glob patterns like /api/users/*.
    Shows route definitions and optionally frontend code that calls them.
    """
    import fnmatch as _fnmatch

    from coderag.core.models import EdgeKind

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        route_nodes = store.find_nodes(kind=NodeKind.ROUTE, limit=1000)

        if not route_nodes:
            console.print("[yellow]No routes found in the knowledge graph.[/yellow]")
            console.print("The codebase may not have been parsed with framework detection enabled.")
            return

        matched: list[Node] = []
        for rnode in route_nodes:
            route_url = rnode.metadata.get("url", rnode.name)
            if _fnmatch.fnmatch(route_url, pattern) or pattern in route_url:
                if method and method.upper() != "ANY":
                    node_method = rnode.metadata.get("http_method", "").upper()
                    if node_method != method.upper():
                        continue
                matched.append(rnode)

        if not matched:
            console.print("[yellow]No routes matching pattern found.[/yellow]")
            console.print(f"Total routes in graph: {len(route_nodes)}")
            return

        if fmt == "json":
            data: dict[str, Any] = {
                "pattern": pattern,
                "total_matched": len(matched),
                "routes": [],
            }
            for rnode in matched:
                route_data: dict[str, Any] = {
                    "url": rnode.metadata.get("url", rnode.name),
                    "method": rnode.metadata.get("http_method", "ANY"),
                    "file": rnode.file_path,
                    "line": rnode.start_line,
                    "controller": rnode.metadata.get("controller", ""),
                    "action": rnode.metadata.get("action", ""),
                }
                if not no_frontend:
                    incoming = store.get_edges(target_id=rnode.id)
                    callers = [
                        e
                        for e in incoming
                        if (e.kind == EdgeKind.API_CALLS or (isinstance(e.kind, str) and e.kind == "api_calls"))
                    ]
                    if callers:
                        route_data["frontend_callers"] = []
                        for edge in callers:
                            source = store.get_node(edge.source_id)
                            if source:
                                route_data["frontend_callers"].append(
                                    {
                                        "name": source.qualified_name,
                                        "file": source.file_path,
                                        "line": source.start_line,
                                    }
                                )
                data["routes"].append(route_data)
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            lines = [
                f"## Routes matching `{pattern}`\n",
                f"**Matched**: {len(matched)} routes\n",
            ]

            for rnode in matched:
                http_method = rnode.metadata.get("http_method", "ANY")
                url = rnode.metadata.get("url", rnode.name)
                controller = rnode.metadata.get("controller", "")
                action = rnode.metadata.get("action", "")

                lines.append(f"### {http_method} `{url}`")
                lines.append(f"- **File**: `{rnode.file_path}:{rnode.start_line}`")
                if controller:
                    lines.append(f"- **Controller**: `{controller}`")
                if action:
                    lines.append(f"- **Action**: `{action}`")

                outgoing = store.get_edges(source_id=rnode.id)
                for edge in outgoing:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    target_node = store.get_node(edge.target_id)
                    if target_node:
                        lines.append(
                            f"- **{ek}** -> `{target_node.qualified_name}` (`{target_node.file_path}:{target_node.start_line}`)"
                        )

                if not no_frontend:
                    incoming = store.get_edges(target_id=rnode.id)
                    api_callers = [
                        e
                        for e in incoming
                        if (e.kind == EdgeKind.API_CALLS or (isinstance(e.kind, str) and e.kind == "api_calls"))
                    ]
                    if api_callers:
                        lines.append("")
                        lines.append(f"  **Frontend callers** ({len(api_callers)}):")
                        for edge in api_callers:
                            source = store.get_node(edge.source_id)
                            if source:
                                call_url = edge.metadata.get("call_url", "")
                                entry = f"  - `{source.qualified_name}` (`{source.file_path}:{source.start_line}`)"
                                if call_url:
                                    entry += f" via `{call_url}`"
                                lines.append(entry)
                lines.append("")

            formatter.render_to_console("\n".join(lines), console)
    finally:
        store.close()


# -- Deps Command ------------------------------------------------------------


@cli.command()
@click.argument("target")
@click.option(
    "--direction",
    "-D",
    type=click.Choice(["dependencies", "dependents", "both"]),
    default="both",
    show_default=True,
    help="Show dependencies, dependents, or both.",
)
@click.option(
    "--depth",
    "-d",
    default=2,
    show_default=True,
    help="Traversal depth (1-5).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--budget",
    "-b",
    default=4000,
    show_default=True,
    help="Token budget for output.",
)
@click.pass_context
def deps(ctx: click.Context, target: str, direction: str, depth: int, fmt: str, budget: int) -> None:
    """Show the dependency graph for a symbol or file.

    Visualizes what depends on what, including transitive dependencies.
    Useful for understanding coupling and planning refactors.
    """
    from coderag.core.models import EdgeKind
    from coderag.mcp.tools import _format_candidates, _normalize_file_path, _resolve_symbol

    config = _load_config(ctx.obj["config_path"])
    if ctx.obj["db_override"]:
        config.db_path = ctx.obj["db_override"]

    store = _open_store(config)

    try:
        depth = min(max(depth, 1), 5)
        budget = min(max(budget, 500), 16000)

        node, candidates = _resolve_symbol(target, store)

        if node is None:
            resolved_path = _normalize_file_path(target, store)
            if resolved_path:
                file_nodes = store.find_nodes(file_path=resolved_path, limit=1)
                if file_nodes:
                    node = file_nodes[0]

        if node is None:
            if candidates:
                console.print(_format_candidates(candidates, target))
            else:
                console.print("[red]Target not found:[/red] " + target)
            return

        kind = node.kind.value if isinstance(node.kind, NodeKind) else node.kind

        deps_list: list[tuple] = []
        dependents_list: list[tuple] = []

        if direction in ("dependencies", "both"):
            deps_list = store.get_neighbors(
                node_id=node.id,
                direction="outgoing",
                max_depth=depth,
            )

        if direction in ("dependents", "both"):
            dependents_list = store.get_neighbors(
                node_id=node.id,
                direction="incoming",
                max_depth=depth,
            )

        if fmt == "json":
            data: dict[str, Any] = {
                "target": node.qualified_name,
                "kind": kind,
                "file": node.file_path,
                "line": node.start_line,
                "direction": direction,
                "max_depth": depth,
            }
            if direction in ("dependencies", "both"):
                data["dependencies"] = []
                for n, edge, d in deps_list:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                    data["dependencies"].append(
                        {
                            "qualified_name": n.qualified_name,
                            "kind": nk,
                            "edge_kind": ek,
                            "file": n.file_path,
                            "line": n.start_line,
                            "depth": d,
                        }
                    )
            if direction in ("dependents", "both"):
                data["dependents"] = []
                for n, edge, d in dependents_list:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                    data["dependents"].append(
                        {
                            "qualified_name": n.qualified_name,
                            "kind": nk,
                            "edge_kind": ek,
                            "file": n.file_path,
                            "line": n.start_line,
                            "depth": d,
                        }
                    )
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            lines = [
                f"## Dependency Graph: `{node.qualified_name}`\n",
                f"**Kind**: {kind}  ",
                f"**File**: `{node.file_path}:{node.start_line}`  ",
                f"**Direction**: {direction} | **Max depth**: {depth}\n",
            ]

            if direction in ("dependencies", "both"):
                lines.append(f"### Dependencies ({len(deps_list)} nodes)\n")
                if deps_list:
                    lines.append(f"What `{node.name}` depends on:\n")
                    by_depth: dict[int, list] = {}
                    for n, edge, d in deps_list:
                        by_depth.setdefault(d, []).append((n, edge))
                    for d in sorted(by_depth.keys()):
                        indent = "  " * (d - 1)
                        for n, edge in by_depth[d]:
                            ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                            nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                            lines.append(
                                f"{indent}  - **{ek}** -> `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)"
                            )
                else:
                    lines.append("No dependencies found.\n")
                lines.append("")

            if direction in ("dependents", "both"):
                lines.append(f"### Dependents ({len(dependents_list)} nodes)\n")
                if dependents_list:
                    lines.append(f"What depends on `{node.name}`:\n")
                    by_depth_dep: dict[int, list] = {}
                    for n, edge, d in dependents_list:
                        by_depth_dep.setdefault(d, []).append((n, edge))
                    for d in sorted(by_depth_dep.keys()):
                        indent = "  " * (d - 1)
                        for n, edge in by_depth_dep[d]:
                            ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                            nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                            lines.append(
                                f"{indent}  - **{ek}** <- `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)"
                            )
                else:
                    lines.append("No dependents found.\n")

            formatter.render_to_console("\n".join(lines), console)
    finally:
        store.close()


# ── Validate Command ──────────────────────────────────────────


@cli.command()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to codegraph.yaml (default: auto-detect).",
)
def validate(config_path: str | None) -> None:
    """Validate configuration, plugins, storage, and grammars.

    Checks that codegraph.yaml exists and is valid, configured language
    plugins are available, the storage backend is accessible, and
    tree-sitter grammars are installed.
    """
    issues: list[str] = []
    warnings: list[str] = []
    checks_passed = 0
    total_checks = 0

    # ── 1. Validate codegraph.yaml ────────────────────────────
    total_checks += 1
    config: CodeGraphConfig | None = None
    yaml_path = config_path
    if yaml_path is None:
        for candidate in ["codegraph.yaml", "codegraph.yml"]:
            if os.path.exists(candidate):
                yaml_path = candidate
                break

    if yaml_path is None:
        issues.append("No codegraph.yaml found in current directory. Run [bold]coderag init[/bold] to create one.")
    elif not os.path.exists(yaml_path):
        issues.append(f"Config file not found: {yaml_path}")
    else:
        try:
            config = CodeGraphConfig.from_yaml(yaml_path)
            console.print(f"  [green]✓[/green] Config file: {yaml_path}")
            checks_passed += 1
        except ValueError as exc:
            issues.append(f"Invalid config file: {exc}")
        except Exception as exc:
            issues.append(f"Error reading config: {exc}")

    # ── 2. Validate language plugins ──────────────────────────
    total_checks += 1
    try:
        registry = PluginRegistry()
        discovered = registry.discover_builtin_plugins()
        available_plugins = {p.lower() for p in discovered}

        if config is not None:
            configured_langs = list(config.languages.keys())
            missing_plugins = [lang for lang in configured_langs if lang.lower() not in available_plugins]
            if missing_plugins:
                issues.append(
                    f"Configured languages not available: {', '.join(missing_plugins)}. "
                    f"Available: {', '.join(sorted(available_plugins))}"
                )
            else:
                console.print(f"  [green]✓[/green] Language plugins: {', '.join(configured_langs)} (all available)")
                checks_passed += 1
        else:
            console.print(f"  [green]✓[/green] Built-in plugins discovered: {', '.join(sorted(available_plugins))}")
            checks_passed += 1
    except Exception as exc:
        issues.append(f"Plugin discovery failed: {exc}")

    # ── 3. Validate storage backend ───────────────────────────
    total_checks += 1
    if config is not None:
        raw_db_path = getattr(config, "db_path", None)
        if not isinstance(raw_db_path, str):
            raw_db_path = ".codegraph/graph.db"
        db_path = raw_db_path
        if not os.path.isabs(db_path):
            db_path = os.path.join(config.project_root or ".", db_path)
        db_dir = os.path.dirname(db_path)

        if os.path.exists(db_path):
            if os.access(db_path, os.R_OK | os.W_OK):
                console.print(f"  [green]✓[/green] Database: {db_path} (exists, writable)")
                checks_passed += 1
            else:
                issues.append(f"Database file not writable: {db_path}")
        elif db_dir and os.path.exists(db_dir):
            if os.access(db_dir, os.W_OK):
                console.print(f"  [green]✓[/green] Database directory: {db_dir} (writable, DB will be created)")
                checks_passed += 1
            else:
                issues.append(f"Database directory not writable: {db_dir}")
        else:
            # Directory doesn't exist yet — check if parent is writable
            parent = os.path.dirname(db_dir) if db_dir else "."
            if os.access(parent or ".", os.W_OK):
                console.print(f"  [green]✓[/green] Storage path: {db_path} (directory will be created)")
                checks_passed += 1
            else:
                issues.append(f"Cannot create database directory: {db_dir} (parent not writable)")
    else:
        warnings.append("Skipped storage check (no config loaded).")

    # ── 4. Validate tree-sitter grammars ──────────────────────
    grammar_packages = {
        "php": ("tree_sitter_php", "language_php"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "python": ("tree_sitter_python", "language"),
        "css": ("tree_sitter_css", "language"),
        "scss": ("tree_sitter_scss", "language"),
    }

    langs_to_check = list(config.languages.keys()) if config else list(grammar_packages.keys())
    grammar_ok = []
    grammar_fail = []

    for lang in langs_to_check:
        total_checks += 1
        pkg_info = grammar_packages.get(lang.lower())
        if pkg_info is None:
            warnings.append(f"No grammar check available for language: {lang}")
            checks_passed += 1  # Not a failure
            continue

        pkg_name, func_name = pkg_info
        try:
            import importlib

            mod = importlib.import_module(pkg_name)
            lang_func = getattr(mod, func_name)
            lang_func()  # Verify it returns a valid language pointer
            grammar_ok.append(lang)
            checks_passed += 1
        except ImportError:
            grammar_fail.append(f"{lang} (package '{pkg_name}' not installed)")
            issues.append(f"Tree-sitter grammar missing for {lang}: pip install {pkg_name.replace('_', '-')}")
        except Exception as exc:
            grammar_fail.append(f"{lang} ({exc})")
            issues.append(f"Tree-sitter grammar error for {lang}: {exc}")

    if grammar_ok:
        console.print(f"  [green]✓[/green] Tree-sitter grammars: {', '.join(grammar_ok)}")

    # ── Summary ───────────────────────────────────────────────
    console.print()
    if warnings:
        for w in warnings:
            console.print(f"  [yellow]⚠[/yellow] {w}")
        console.print()

    if issues:
        console.print(
            Panel(
                "\n".join(f"[red]✗[/red] {issue}" for issue in issues),
                title="[red]Validation Failed[/red]",
                border_style="red",
            )
        )
        console.print(f"\n  [red]{checks_passed}/{total_checks} checks passed, {len(issues)} issue(s) found.[/red]")
        raise SystemExit(1)
    else:
        console.print(
            Panel(
                f"[green]All {checks_passed} checks passed![/green]",
                title="[green]Validation Successful[/green]",
                border_style="green",
            )
        )


# ── Monitor Command (TUI Dashboard) ──────────────────────────


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--config", "-c", "config_path", type=click.Path(), default=None, help="Path to codegraph.yaml config file."
)
def monitor(path: str, config_path: str | None) -> None:
    """Launch the TUI monitoring dashboard for a parse run.

    Runs the full pipeline while displaying real-time progress,
    throughput metrics, and resource usage in a terminal UI.

    Requires: pip install coderag[tui]
    """
    try:
        from coderag.tui.app import CodeRAGApp
    except ImportError:
        console.print(
            "[red]Error:[/red] TUI dependencies not installed.\n"
            "Install with: [bold]pip install coderag[tui][/bold]\n"
            "Or: [bold]pip install textual psutil[/bold]"
        )
        raise SystemExit(1)

    project_root = str(Path(path).resolve())
    app = CodeRAGApp(project_root=project_root, config_path=config_path)
    app.run()


# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    cli()
