"""MCP Server for CodeRAG.

Creates and configures a FastMCP server that exposes the CodeRAG
knowledge graph to LLMs via the Model Context Protocol.

Supports hot-reload: when the database file changes (e.g., after
a re-parse), the server automatically reloads the store and analyzer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
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

# Hot-reload polling interval in seconds
_RELOAD_POLL_INTERVAL = 2.0


class GraphContext:
    """Mutable holder for store and analyzer, enabling hot-reload.

    Tools and resources reference this context object. When the database
    file changes, the context reloads the store and analyzer in-place,
    so all registered tools automatically use the updated data.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._store: SQLiteStore | None = None
        self._analyzer: NetworkXAnalyzer | None = None
        self._last_mtime: float = 0.0
        self._load_count: int = 0
        self.load()

    def load(self) -> None:
        """Load (or reload) the store and analyzer from the database."""
        with self._lock:
            # Close existing store if any
            if self._store is not None:
                try:
                    self._store.close()
                except Exception:
                    pass

            self._store = SQLiteStore(self._db_path)
            self._store.initialize()

            self._analyzer = NetworkXAnalyzer()
            self._analyzer.load_from_store(self._store)

            try:
                self._last_mtime = os.path.getmtime(self._db_path)
            except OSError:
                self._last_mtime = 0.0

            self._load_count += 1
            stats = self._analyzer.get_statistics()
            logger.info(
                "GraphContext loaded (reload #%d): %d nodes, %d edges",
                self._load_count,
                stats.get("node_count", 0),
                stats.get("edge_count", 0),
            )

    @property
    def store(self) -> SQLiteStore:
        """Current store instance (thread-safe)."""
        with self._lock:
            assert self._store is not None
            return self._store

    @property
    def analyzer(self) -> NetworkXAnalyzer:
        """Current analyzer instance (thread-safe)."""
        with self._lock:
            assert self._analyzer is not None
            return self._analyzer

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def last_mtime(self) -> float:
        return self._last_mtime

    def check_and_reload(self) -> bool:
        """Check if the database file changed and reload if so.

        Returns:
            True if a reload was performed.
        """
        try:
            current_mtime = os.path.getmtime(self._db_path)
        except OSError:
            return False

        if current_mtime > self._last_mtime:
            print(
                f"[hot-reload] Database changed (mtime {current_mtime:.1f} > {self._last_mtime:.1f}), reloading...",
                file=sys.stderr,
            )
            self.load()
            stats = self._analyzer.get_statistics()
            print(
                f"[hot-reload] Reloaded: {stats.get('node_count', 0)} nodes, {stats.get('edge_count', 0)} edges",
                file=sys.stderr,
            )
            return True
        return False

    def close(self) -> None:
        """Close the store."""
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None


class _StoreProxy:
    """Proxy that delegates attribute access to the current store in GraphContext.

    This allows tools/resources to hold a single reference that always
    points to the latest store after a hot-reload.
    """

    def __init__(self, ctx: GraphContext) -> None:
        object.__setattr__(self, "_ctx", ctx)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_ctx").store, name)


class _AnalyzerProxy:
    """Proxy that delegates attribute access to the current analyzer in GraphContext."""

    def __init__(self, ctx: GraphContext) -> None:
        object.__setattr__(self, "_ctx", ctx)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_ctx").analyzer, name)


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
        msg = f"Graph database not found at {p}. Run 'coderag parse {project_dir}' first to build the knowledge graph."
        raise FileNotFoundError(msg)
    return p


def create_server(
    project_dir: str,
    db_path: str | None = None,
    hot_reload: bool = False,
) -> tuple[FastMCP, GraphContext]:
    """Create and configure the MCP server.

    Initializes the SQLite store, loads the graph into NetworkX,
    and registers all tools and resources on the FastMCP instance.

    When ``hot_reload`` is True, tools and resources use proxy objects
    that automatically pick up database changes.

    Args:
        project_dir: Path to the project root directory.
        db_path: Optional explicit path to the graph database.
        hot_reload: Enable hot-reload proxies for store/analyzer.

    Returns:
        Tuple of (FastMCP server, GraphContext).

    Raises:
        FileNotFoundError: If the graph database does not exist.
    """
    resolved_db = _find_db_path(project_dir, db_path)

    # Initialize context
    ctx = GraphContext(str(resolved_db))

    # Use proxies for hot-reload, direct references otherwise
    if hot_reload:
        store_ref = _StoreProxy(ctx)
        analyzer_ref = _AnalyzerProxy(ctx)
    else:
        store_ref = ctx.store
        analyzer_ref = ctx.analyzer

    # Get project info for server name
    try:
        summary = ctx.store.get_summary()
        project_name = summary.project_name or Path(project_dir).name
    except Exception:
        project_name = Path(project_dir).name

    # Create FastMCP server
    mcp = FastMCP(
        name=f"coderag-{project_name}",
    )

    # Register tools and resources (they capture store_ref/analyzer_ref)
    register_tools(mcp, store_ref, analyzer_ref)
    register_resources(mcp, store_ref, analyzer_ref)

    stats = ctx.analyzer.get_statistics()
    logger.info(
        "CodeRAG MCP server initialized: %s (%d nodes, %d edges)%s",
        project_name,
        stats.get("node_count", 0),
        stats.get("edge_count", 0),
        " [hot-reload enabled]" if hot_reload else "",
    )

    return mcp, ctx


async def _hot_reload_watcher(ctx: GraphContext, interval: float) -> None:
    """Background async task that polls the database file for changes."""
    while True:
        await asyncio.sleep(interval)
        try:
            ctx.check_and_reload()
        except Exception as exc:
            print(f"[hot-reload] Error during reload: {exc}", file=sys.stderr)


def run_stdio_server(
    project_dir: str,
    db_path: str | None = None,
    hot_reload: bool = True,
) -> None:
    """Run the MCP server with stdio transport.

    This is the main entry point for the ``coderag serve`` command.
    Uses stdin/stdout for MCP communication (for Claude Code, Cursor, etc.).
    Diagnostic messages are printed to stderr.

    When ``hot_reload`` is True (default), the server watches the database
    file for changes and automatically reloads when it detects a re-parse.

    Args:
        project_dir: Path to the project root directory.
        db_path: Optional explicit path to the graph database.
        hot_reload: Enable automatic database reload on changes.
    """
    # Print startup info to stderr (stdout is used by MCP protocol)
    print("CodeRAG MCP Server starting...", file=sys.stderr)
    print(f"Project: {project_dir}", file=sys.stderr)
    if db_path:
        print(f"Database: {db_path}", file=sys.stderr)

    try:
        mcp, ctx = create_server(project_dir, db_path, hot_reload=hot_reload)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to initialize server: {exc}", file=sys.stderr)
        sys.exit(1)

    stats = ctx.analyzer.get_statistics()
    node_count = stats.get("node_count", 0)
    edge_count = stats.get("edge_count", 0)
    print(f"Ready: {node_count} nodes, {edge_count} edges", file=sys.stderr)
    print("Transport: stdio", file=sys.stderr)
    if hot_reload:
        print(
            f"Hot-reload: enabled (polling every {_RELOAD_POLL_INTERVAL}s)",
            file=sys.stderr,
        )

    async def _run() -> None:
        if hot_reload:
            # Start watcher as background task
            asyncio.create_task(_hot_reload_watcher(ctx, _RELOAD_POLL_INTERVAL))
        await mcp.run_stdio_async()

    try:
        asyncio.run(_run())
    finally:
        ctx.close()
