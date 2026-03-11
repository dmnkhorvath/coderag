"""MCP Server for CodeRAG.

Creates and configures a FastMCP server that exposes the CodeRAG
knowledge graph to LLMs via the Model Context Protocol.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
from coderag.storage.sqlite_store import SQLiteStore

from .resources import register_resources
from .tools import register_tools

logger = logging.getLogger(__name__)

# Default database path relative to project root
_DEFAULT_DB_SUBPATH = ".codegraph/graph.db"


def _find_db_path(project_dir: str, db_path: str | None = None) -> Path:
    """Resolve the graph database path.

    Args:
        project_dir: Project root directory.
        db_path: Explicit database path (overrides default).

    Returns:
        Resolved Path to the database file.

    Raises:
        FileNotFoundError: If the database file does not exist.
    """
    if db_path:
        p = Path(db_path)
    else:
        p = Path(project_dir) / _DEFAULT_DB_SUBPATH

    if not p.exists():
        msg = (
            f"Graph database not found at {p}. "
            f"Run 'coderag parse {project_dir}' first to build the knowledge graph."
        )
        raise FileNotFoundError(msg)
    return p


def create_server(
    project_dir: str,
    db_path: str | None = None,
) -> tuple[FastMCP, SQLiteStore, NetworkXAnalyzer]:
    """Create and configure the MCP server.

    Initializes the SQLite store, loads the graph into NetworkX,
    and registers all tools and resources on the FastMCP instance.

    Args:
        project_dir: Path to the project root directory.
        db_path: Optional explicit path to the graph database.

    Returns:
        Tuple of (FastMCP server, SQLiteStore, NetworkXAnalyzer).

    Raises:
        FileNotFoundError: If the graph database does not exist.
    """
    resolved_db = _find_db_path(project_dir, db_path)

    # Initialize store
    store = SQLiteStore(str(resolved_db))
    store.initialize()

    # Load graph into analyzer
    analyzer = NetworkXAnalyzer()
    analyzer.load_from_store(store)

    # Get project info for server name
    try:
        summary = store.get_summary()
        project_name = summary.project_name or Path(project_dir).name
    except Exception:
        project_name = Path(project_dir).name

    # Create FastMCP server
    mcp = FastMCP(
        name=f"coderag-{project_name}",
    )

    # Register tools and resources
    register_tools(mcp, store, analyzer)
    register_resources(mcp, store, analyzer)

    stats = analyzer.get_statistics()
    logger.info(
        "CodeRAG MCP server initialized: %s (%d nodes, %d edges)",
        project_name,
        stats.get("node_count", 0),
        stats.get("edge_count", 0),
    )

    return mcp, store, analyzer


def run_stdio_server(
    project_dir: str,
    db_path: str | None = None,
) -> None:
    """Run the MCP server with stdio transport.

    This is the main entry point for the ``coderag serve`` command.
    Uses stdin/stdout for MCP communication (for Claude Code, Cursor, etc.).
    Diagnostic messages are printed to stderr.

    Args:
        project_dir: Path to the project root directory.
        db_path: Optional explicit path to the graph database.
    """
    # Print startup info to stderr (stdout is used by MCP protocol)
    print("CodeRAG MCP Server starting...", file=sys.stderr)
    print(f"Project: {project_dir}", file=sys.stderr)
    if db_path:
        print(f"Database: {db_path}", file=sys.stderr)

    try:
        mcp, store, analyzer = create_server(project_dir, db_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to initialize server: {exc}", file=sys.stderr)
        sys.exit(1)

    stats = analyzer.get_statistics()
    node_count = stats.get("node_count", 0)
    edge_count = stats.get("edge_count", 0)
    print(f"Ready: {node_count} nodes, {edge_count} edges", file=sys.stderr)
    print("Transport: stdio", file=sys.stderr)

    # Run the server
    asyncio.run(mcp.run_stdio_async())
