"""CodeRAG SQLite Storage Backend
================================

Production-quality SQLite storage implementing the ``GraphStore`` interface.
Features:

- WAL mode for concurrent read access during writes.
- FTS5 virtual table for full-text search on node names and docblocks.
- Batch upsert operations with configurable batch sizes.
- Incremental update support via content-hash tracking.
- Transaction management with context-manager support.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from coderag.core.models import (
    Edge,
    EdgeKind,
    GraphSummary,
    Node,
    NodeKind,
)

logger = logging.getLogger(__name__)

# =============================================================================
# SCHEMA
# =============================================================================

_SCHEMA_VERSION = "1"

_SCHEMA_SQL = """
-- Enable WAL mode for concurrent reads
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA cache_size = -64000;  -- 64MB cache
PRAGMA wal_autocheckpoint = 10000;  -- Reduce checkpoint frequency for bulk writes
PRAGMA mmap_size = 268435456;  -- 256MB memory-mapped I/O
PRAGMA temp_store = MEMORY;  -- Keep temp tables in memory

-- Nodes table
CREATE TABLE IF NOT EXISTS nodes (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    language        TEXT NOT NULL,
    docblock        TEXT,
    source_text     TEXT,
    content_hash    TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    pagerank        REAL NOT NULL DEFAULT 0.0,
    community_id    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_language ON nodes(language);
CREATE INDEX IF NOT EXISTS idx_nodes_qualified_name ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_pagerank ON nodes(pagerank DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_file_kind ON nodes(file_path, kind);
CREATE INDEX IF NOT EXISTS idx_nodes_kind_pagerank ON nodes(kind, pagerank DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_lang_kind ON nodes(language, kind);

-- Edges table
CREATE TABLE IF NOT EXISTS edges (
    source_id       TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    line_number     INTEGER,
    metadata        TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_id, target_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_confidence ON edges(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_source_conf ON edges(source_id, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_edges_target_conf ON edges(target_id, confidence DESC);

-- File hash tracking for incremental updates
CREATE TABLE IF NOT EXISTS files (
    file_path       TEXT PRIMARY KEY,
    content_hash    TEXT NOT NULL,
    language        TEXT NOT NULL,
    plugin_name     TEXT NOT NULL,
    node_count      INTEGER NOT NULL DEFAULT 0,
    edge_count      INTEGER NOT NULL DEFAULT 0,
    parse_time_ms   REAL NOT NULL DEFAULT 0.0,
    last_parsed     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Key-value metadata store
CREATE TABLE IF NOT EXISTS metadata (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);
"""

_FTS_SQL = """
-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    name,
    qualified_name,
    docblock,
    content='nodes',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, name, qualified_name, docblock)
    VALUES (new.rowid, new.name, new.qualified_name, new.docblock);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, docblock)
    VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docblock);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, docblock)
    VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docblock);
    INSERT INTO nodes_fts(rowid, name, qualified_name, docblock)
    VALUES (new.rowid, new.name, new.qualified_name, new.docblock);
END;
"""


# =============================================================================
# SQLITE STORE
# =============================================================================


class SQLiteStore:
    """SQLite-backed knowledge graph storage.

    Implements the ``GraphStore`` interface with SQLite, using WAL mode
    for concurrent reads and FTS5 for full-text search.

    Args:
        db_path: Path to the SQLite database file. Parent directories
                 are created automatically. Use ``:memory:`` for an
                 in-memory database.
        batch_size: Number of rows per batch in bulk operations.

    Example::

        store = SQLiteStore("/path/to/graph.db")
        store.initialize()
        store.upsert_nodes(nodes)
        results = store.search_nodes("UserService")
        store.close()
    """

    def __init__(self, db_path: str, batch_size: int = 500) -> None:
        self._db_path = db_path
        self._batch_size = batch_size
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the database, tables, indexes, and FTS5 virtual table.

        Safe to call multiple times (idempotent).
        """
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row

        # Execute schema
        self._conn.executescript(_SCHEMA_SQL)

        # Runtime performance pragmas (not persisted in schema)
        try:
            self._conn.execute("PRAGMA threads = 4")
        except sqlite3.OperationalError:
            pass  # Not all SQLite builds support this

        # FTS5 setup (separate because it may already exist)
        try:
            self._conn.executescript(_FTS_SQL)
        except sqlite3.OperationalError as exc:
            # Triggers may already exist in older SQLite versions
            if "already exists" not in str(exc).lower():
                raise
            logger.debug("FTS triggers already exist, skipping: %s", exc)

        # Store schema version
        self.set_metadata("schema_version", _SCHEMA_VERSION)

        logger.info("SQLiteStore initialized at %s", self._db_path)

    def close(self) -> None:
        """Close the database connection and release resources."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                logger.exception("Error closing database")
            finally:
                self._conn = None

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the active database connection.

        Raises:
            RuntimeError: If the store has not been initialized.
        """
        if self._conn is None:
            raise RuntimeError("SQLiteStore not initialized. Call initialize() first.")
        return self._conn

    # ── Node Operations ───────────────────────────────────────

    def upsert_node(self, node: Node) -> None:
        """Insert or update a single node."""
        self.connection.execute(
            """INSERT INTO nodes
               (id, kind, name, qualified_name, file_path, start_line,
                end_line, language, docblock, source_text, content_hash,
                metadata, pagerank, community_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                kind=excluded.kind,
                name=excluded.name,
                qualified_name=excluded.qualified_name,
                file_path=excluded.file_path,
                start_line=excluded.start_line,
                end_line=excluded.end_line,
                language=excluded.language,
                docblock=excluded.docblock,
                source_text=excluded.source_text,
                content_hash=excluded.content_hash,
                metadata=excluded.metadata,
                pagerank=excluded.pagerank,
                community_id=excluded.community_id""",
            self._node_to_row(node),
        )
        self.connection.commit()

    def upsert_nodes(self, nodes: Sequence[Node]) -> int:
        """Bulk insert or update nodes in a single transaction."""
        if not nodes:
            return 0

        count = 0
        conn = self.connection
        try:
            conn.execute("BEGIN")
            for i in range(0, len(nodes), self._batch_size):
                batch = nodes[i : i + self._batch_size]
                conn.executemany(
                    """INSERT INTO nodes
                       (id, kind, name, qualified_name, file_path, start_line,
                        end_line, language, docblock, source_text, content_hash,
                        metadata, pagerank, community_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        name=excluded.name,
                        qualified_name=excluded.qualified_name,
                        file_path=excluded.file_path,
                        start_line=excluded.start_line,
                        end_line=excluded.end_line,
                        language=excluded.language,
                        docblock=excluded.docblock,
                        source_text=excluded.source_text,
                        content_hash=excluded.content_hash,
                        metadata=excluded.metadata,
                        pagerank=excluded.pagerank,
                        community_id=excluded.community_id""",
                    [self._node_to_row(n) for n in batch],
                )
                count += len(batch)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return count

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by its ID."""
        row = self.connection.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def get_node_by_qualified_name(self, qualified_name: str) -> Node | None:
        """Get a node by its fully-qualified name (highest PageRank wins)."""
        row = self.connection.execute(
            "SELECT * FROM nodes WHERE qualified_name = ? ORDER BY pagerank DESC LIMIT 1",
            (qualified_name,),
        ).fetchone()
        return self._row_to_node(row) if row else None

    def get_all_nodes(self) -> list[Node]:
        """Return every node in the graph.

        Used by the semantic embedding pipeline to build the vector index.
        Nodes are returned in insertion order (rowid).
        """
        rows = self.connection.execute("SELECT * FROM nodes").fetchall()
        return [self._row_to_node(r) for r in rows]

    def find_nodes(
        self,
        kind: NodeKind | None = None,
        language: str | None = None,
        file_path: str | None = None,
        name_pattern: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Node]:
        """Find nodes matching filter criteria (AND-combined)."""
        conditions: list[str] = []
        params: list[Any] = []

        if kind is not None:
            conditions.append("kind = ?")
            params.append(kind.value if isinstance(kind, NodeKind) else kind)
        if language is not None:
            conditions.append("language = ?")
            params.append(language)
        if file_path is not None:
            conditions.append("file_path = ?")
            params.append(file_path)
        if name_pattern is not None:
            conditions.append("name LIKE ?")
            params.append(name_pattern)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = self.connection.execute(
            f"SELECT * FROM nodes WHERE {where} ORDER BY pagerank DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [self._row_to_node(r) for r in rows]

    def search_nodes(self, query: str, limit: int = 20, kind: str | None = None) -> list[Node]:
        """Full-text search across node names, qualified names, and docblocks.

        Uses FTS5 first, then falls back to LIKE-based search if FTS
        returns no results (handles camelCase/PascalCase edge cases).
        Optionally filters by node kind at the SQL level.
        """
        # When kind filter is active, search more broadly then filter
        search_limit = limit * 10 if kind else limit

        results = []

        # Try FTS5 first
        safe_query = self._sanitize_fts_query(query)
        if safe_query:
            try:
                if kind:
                    rows = self.connection.execute(
                        """SELECT n.* FROM nodes_fts fts
                           JOIN nodes n ON n.rowid = fts.rowid
                           WHERE nodes_fts MATCH ? AND n.kind = ?
                           ORDER BY rank
                           LIMIT ?""",
                        (safe_query, kind, search_limit),
                    ).fetchall()
                else:
                    rows = self.connection.execute(
                        """SELECT n.* FROM nodes_fts fts
                           JOIN nodes n ON n.rowid = fts.rowid
                           WHERE nodes_fts MATCH ?
                           ORDER BY rank
                           LIMIT ?""",
                        (safe_query, search_limit),
                    ).fetchall()
                if rows:
                    results = [self._row_to_node(r) for r in rows]
            except Exception:
                pass  # Fall through to LIKE search

        # Fallback: LIKE-based search on name and qualified_name
        if not results:
            like_pattern = f"%{query}%"
            if kind:
                rows = self.connection.execute(
                    """SELECT * FROM nodes
                       WHERE (name LIKE ? OR qualified_name LIKE ?) AND kind = ?
                       ORDER BY
                           CASE WHEN name = ? THEN 0
                                WHEN name LIKE ? THEN 1
                                ELSE 2
                           END,
                           pagerank DESC
                       LIMIT ?""",
                    (like_pattern, like_pattern, kind, query, f"{query}%", search_limit),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    """SELECT * FROM nodes
                       WHERE name LIKE ? OR qualified_name LIKE ?
                       ORDER BY
                           CASE WHEN name = ? THEN 0
                                WHEN name LIKE ? THEN 1
                                ELSE 2
                           END,
                           pagerank DESC
                       LIMIT ?""",
                    (like_pattern, like_pattern, query, f"{query}%", search_limit),
                ).fetchall()
            results = [self._row_to_node(r) for r in rows]

        return results[:limit]

    def delete_nodes_for_file(self, file_path: str) -> int:
        """Delete all nodes and their edges for a given file."""
        conn = self.connection

        # Get node IDs for this file
        node_ids = [row[0] for row in conn.execute("SELECT id FROM nodes WHERE file_path = ?", (file_path,)).fetchall()]

        if not node_ids:
            return 0

        placeholders = ",".join("?" * len(node_ids))

        try:
            conn.execute("BEGIN")
            # Delete edges referencing these nodes
            conn.execute(
                f"DELETE FROM edges WHERE source_id IN ({placeholders})",
                node_ids,
            )
            conn.execute(
                f"DELETE FROM edges WHERE target_id IN ({placeholders})",
                node_ids,
            )
            # Delete nodes
            count = conn.execute(
                f"DELETE FROM nodes WHERE id IN ({placeholders})",
                node_ids,
            ).rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return count

    # ── Edge Operations ───────────────────────────────────────

    def upsert_edge(self, edge: Edge) -> None:
        """Insert or update a single edge."""
        self.connection.execute(
            """INSERT INTO edges
               (source_id, target_id, kind, confidence, line_number, metadata)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, kind) DO UPDATE SET
                confidence=excluded.confidence,
                line_number=excluded.line_number,
                metadata=excluded.metadata""",
            self._edge_to_row(edge),
        )
        self.connection.commit()

    def upsert_edges(self, edges: Sequence[Edge]) -> int:
        """Bulk insert or update edges in a single transaction."""
        if not edges:
            return 0

        count = 0
        conn = self.connection
        try:
            conn.execute("BEGIN")
            for i in range(0, len(edges), self._batch_size):
                batch = edges[i : i + self._batch_size]
                conn.executemany(
                    """INSERT INTO edges
                       (source_id, target_id, kind, confidence, line_number, metadata)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_id, target_id, kind) DO UPDATE SET
                        confidence=excluded.confidence,
                        line_number=excluded.line_number,
                        metadata=excluded.metadata""",
                    [self._edge_to_row(e) for e in batch],
                )
                count += len(batch)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return count

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: EdgeKind | None = None,
        min_confidence: float = 0.0,
    ) -> list[Edge]:
        """Get edges matching filter criteria."""
        conditions: list[str] = ["confidence >= ?"]
        params: list[Any] = [min_confidence]

        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id is not None:
            conditions.append("target_id = ?")
            params.append(target_id)
        if kind is not None:
            conditions.append("kind = ?")
            params.append(kind.value if isinstance(kind, EdgeKind) else kind)

        where = " AND ".join(conditions)
        rows = self.connection.execute(
            f"SELECT * FROM edges WHERE {where} ORDER BY confidence DESC",
            params,
        ).fetchall()

        return [self._row_to_edge(r) for r in rows]

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        edge_kinds: Sequence[EdgeKind] | None = None,
        max_depth: int = 1,
        min_confidence: float = 0.0,
    ) -> list[tuple[Node, Edge, int]]:
        """Get neighboring nodes with their connecting edges.

        Supports multi-hop traversal up to ``max_depth``.

        Returns:
            List of ``(node, edge, depth)`` tuples, ordered by depth
            then PageRank.
        """
        results: list[tuple[Node, Edge, int]] = []
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}

        kind_filter = ""
        kind_params: list[Any] = []
        if edge_kinds:
            placeholders = ",".join("?" * len(edge_kinds))
            kind_filter = f" AND e.kind IN ({placeholders})"
            kind_params = [ek.value if isinstance(ek, EdgeKind) else ek for ek in edge_kinds]

        for depth in range(1, max_depth + 1):
            if not frontier:
                break

            next_frontier: set[str] = set()
            placeholders = ",".join("?" * len(frontier))

            # Outgoing edges
            if direction in ("both", "outgoing"):
                rows = self.connection.execute(
                    f"""SELECT e.*, n.*
                        FROM edges e
                        JOIN nodes n ON n.id = e.target_id
                        WHERE e.source_id IN ({placeholders})
                          AND e.confidence >= ?
                          {kind_filter}""",
                    list(frontier) + [min_confidence] + kind_params,
                ).fetchall()

                for row in rows:
                    edge = self._row_to_edge(row)
                    if edge.target_id not in visited:
                        node = self._row_to_node_from_offset(row, 6)
                        results.append((node, edge, depth))
                        visited.add(edge.target_id)
                        next_frontier.add(edge.target_id)

            # Incoming edges
            if direction in ("both", "incoming"):
                rows = self.connection.execute(
                    f"""SELECT e.*, n.*
                        FROM edges e
                        JOIN nodes n ON n.id = e.source_id
                        WHERE e.target_id IN ({placeholders})
                          AND e.confidence >= ?
                          {kind_filter}""",
                    list(frontier) + [min_confidence] + kind_params,
                ).fetchall()

                for row in rows:
                    edge = self._row_to_edge(row)
                    if edge.source_id not in visited:
                        node = self._row_to_node_from_offset(row, 6)
                        results.append((node, edge, depth))
                        visited.add(edge.source_id)
                        next_frontier.add(edge.source_id)

            frontier = next_frontier

        # Sort by depth, then PageRank descending
        results.sort(key=lambda x: (x[2], -x[0].pagerank))
        return results

    def blast_radius(
        self,
        node_id: str,
        max_depth: int = 3,
        min_confidence: float = 0.3,
    ) -> dict[int, list[Node]]:
        """Compute the blast radius of changing a node."""
        result: dict[int, list[Node]] = {}
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}

        for depth in range(1, max_depth + 1):
            if not frontier:
                break

            next_frontier: set[str] = set()
            depth_nodes: list[Node] = []
            placeholders = ",".join("?" * len(frontier))

            # Find all nodes that depend on the frontier (incoming edges)
            rows = self.connection.execute(
                f"""SELECT DISTINCT n.*
                    FROM edges e
                    JOIN nodes n ON n.id = e.source_id
                    WHERE e.target_id IN ({placeholders})
                      AND e.confidence >= ?
                      AND e.source_id NOT IN ({",".join("?" * len(visited))})""",
                list(frontier) + [min_confidence] + list(visited),
            ).fetchall()

            for row in rows:
                node = self._row_to_node(row)
                depth_nodes.append(node)
                visited.add(node.id)
                next_frontier.add(node.id)

            if depth_nodes:
                depth_nodes.sort(key=lambda n: -n.pagerank)
                result[depth] = depth_nodes

            frontier = next_frontier

        return result

    # ── File Hash Tracking ────────────────────────────────────

    def get_file_hash(self, file_path: str) -> str | None:
        """Get the stored content hash for a file."""
        row = self.connection.execute(
            "SELECT content_hash FROM files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row[0] if row else None

    def set_file_hash(
        self,
        file_path: str,
        content_hash: str,
        language: str,
        plugin_name: str,
        node_count: int,
        edge_count: int,
        parse_time_ms: float,
    ) -> None:
        """Store the content hash and metadata for a parsed file."""
        self.connection.execute(
            """INSERT INTO files
               (file_path, content_hash, language, plugin_name,
                node_count, edge_count, parse_time_ms, last_parsed)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(file_path) DO UPDATE SET
                content_hash=excluded.content_hash,
                language=excluded.language,
                plugin_name=excluded.plugin_name,
                node_count=excluded.node_count,
                edge_count=excluded.edge_count,
                parse_time_ms=excluded.parse_time_ms,
                last_parsed=excluded.last_parsed""",
            (file_path, content_hash, language, plugin_name, node_count, edge_count, parse_time_ms),
        )
        self.connection.commit()

    def get_stale_files(self, current_files: set[str]) -> set[str]:
        """Find files that were previously parsed but no longer exist."""
        stored = {row[0] for row in self.connection.execute("SELECT file_path FROM files").fetchall()}
        return stored - current_files

    # ── Graph Metadata ────────────────────────────────────────

    def get_summary(self) -> GraphSummary:
        """Get a summary of the current graph state."""
        conn = self.connection

        total_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        nodes_by_kind = {
            row[0]: row[1] for row in conn.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall()
        }

        edges_by_kind = {
            row[0]: row[1] for row in conn.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind").fetchall()
        }

        files_by_language = {
            row[0]: row[1] for row in conn.execute("SELECT language, COUNT(*) FROM files GROUP BY language").fetchall()
        }

        avg_conf_row = conn.execute("SELECT AVG(confidence) FROM edges").fetchone()
        avg_confidence = avg_conf_row[0] if avg_conf_row[0] is not None else 0.0

        communities = conn.execute(
            "SELECT COUNT(DISTINCT community_id) FROM nodes WHERE community_id IS NOT NULL"
        ).fetchone()[0]

        top_nodes = conn.execute(
            "SELECT name, qualified_name, pagerank FROM nodes ORDER BY pagerank DESC LIMIT 10"
        ).fetchall()

        last_parsed = self.get_metadata("last_parsed")
        project_name = self.get_metadata("project_name") or ""
        project_root = self.get_metadata("project_root") or ""

        db_size = 0
        if self._db_path != ":memory:" and os.path.exists(self._db_path):
            db_size = os.path.getsize(self._db_path)

        frameworks_raw = self.get_metadata("frameworks")
        frameworks = json.loads(frameworks_raw) if frameworks_raw else []

        return GraphSummary(
            project_name=project_name,
            project_root=project_root,
            db_path=self._db_path,
            db_size_bytes=db_size,
            last_parsed=last_parsed,
            total_nodes=total_nodes,
            total_edges=total_edges,
            nodes_by_kind=nodes_by_kind,
            edges_by_kind=edges_by_kind,
            files_by_language=files_by_language,
            frameworks=frameworks,
            communities=communities,
            avg_confidence=avg_confidence,
            top_nodes_by_pagerank=[(row[0], row[1], row[2]) for row in top_nodes],
        )

    def set_metadata(self, key: str, value: str) -> None:
        """Store a metadata key-value pair."""
        self.connection.execute(
            """INSERT INTO metadata (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )
        self.connection.commit()

    def get_metadata(self, key: str) -> str | None:
        """Retrieve a metadata value."""
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    # ── Transactions ──────────────────────────────────────────

    def begin_transaction(self) -> None:
        """Begin a write transaction."""
        self.connection.execute("BEGIN")

    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        self.connection.execute("COMMIT")

    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        self.connection.execute("ROLLBACK")

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager for atomic transactions.

        Example::

            with store.transaction():
                store.upsert_nodes(nodes)
                store.upsert_edges(edges)
        """
        self.begin_transaction()
        try:
            yield
            self.commit_transaction()
        except Exception:
            self.rollback_transaction()
            raise

    # ── Statistics ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get detailed storage statistics."""
        conn = self.connection
        return {
            "total_nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "total_edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "total_files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "db_path": self._db_path,
            "db_size_bytes": (
                os.path.getsize(self._db_path) if self._db_path != ":memory:" and os.path.exists(self._db_path) else 0
            ),
            "schema_version": self.get_metadata("schema_version"),
        }

    # ── Private Helpers ───────────────────────────────────────

    @staticmethod
    def _node_to_row(node: Node) -> tuple:
        """Convert a Node to a database row tuple."""
        return (
            node.id,
            node.kind.value if isinstance(node.kind, NodeKind) else node.kind,
            node.name,
            node.qualified_name,
            node.file_path,
            node.start_line,
            node.end_line,
            node.language,
            node.docblock,
            node.source_text,
            node.content_hash,
            json.dumps(node.metadata, default=str),
            node.pagerank,
            node.community_id,
        )

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        """Convert a database row to a Node."""
        return Node(
            id=row["id"],
            kind=NodeKind(row["kind"]),
            name=row["name"],
            qualified_name=row["qualified_name"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            language=row["language"],
            docblock=row["docblock"],
            source_text=row["source_text"],
            content_hash=row["content_hash"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            pagerank=row["pagerank"],
            community_id=row["community_id"],
        )

    @staticmethod
    def _row_to_node_from_offset(row: sqlite3.Row, offset: int) -> Node:
        """Convert a joined row to a Node, reading columns from an offset."""
        # When joining edges + nodes, node columns start at offset
        return Node(
            id=row[offset + 0],
            kind=NodeKind(row[offset + 1]),
            name=row[offset + 2],
            qualified_name=row[offset + 3],
            file_path=row[offset + 4],
            start_line=row[offset + 5],
            end_line=row[offset + 6],
            language=row[offset + 7],
            docblock=row[offset + 8],
            source_text=row[offset + 9],
            content_hash=row[offset + 10],
            metadata=json.loads(row[offset + 11]) if row[offset + 11] else {},
            pagerank=row[offset + 12],
            community_id=row[offset + 13],
        )

    @staticmethod
    def _edge_to_row(edge: Edge) -> tuple:
        """Convert an Edge to a database row tuple."""
        return (
            edge.source_id,
            edge.target_id,
            edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind,
            edge.confidence,
            edge.line_number,
            json.dumps(edge.metadata, default=str),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        """Convert a database row to an Edge."""
        return Edge(
            source_id=row["source_id"] if isinstance(row, sqlite3.Row) else row[0],
            target_id=row["target_id"] if isinstance(row, sqlite3.Row) else row[1],
            kind=EdgeKind(row["kind"] if isinstance(row, sqlite3.Row) else row[2]),
            confidence=row["confidence"] if isinstance(row, sqlite3.Row) else row[3],
            line_number=row["line_number"] if isinstance(row, sqlite3.Row) else row[4],
            metadata=json.loads(row["metadata"] if isinstance(row, sqlite3.Row) else row[5])
            if (row["metadata"] if isinstance(row, sqlite3.Row) else row[5])
            else {},
        )

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a query string for FTS5.

        Escapes special characters and wraps terms for prefix matching.
        Handles camelCase/PascalCase by splitting into sub-tokens.
        """
        import re as _re

        # Remove FTS5 special characters that could cause syntax errors
        special = {"(", ")", "{", "}", "[", "]", "^", "~", "@", ":", ";", "!", "&", "|", "\\", '"', "'"}
        cleaned = "".join(c for c in query if c not in special)
        cleaned = cleaned.strip()

        if not cleaned:
            return ""

        # Split camelCase/PascalCase into sub-tokens
        # e.g. "HttpKernel" -> ["Http", "Kernel"], "WP_Query" -> ["WP", "Query"]
        all_tokens = []
        for term in cleaned.split():
            # Split on underscores and camelCase boundaries
            sub = _re.sub(r"([a-z])([A-Z])", r"\1 \2", term)
            sub = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", sub)
            sub = sub.replace("_", " ")
            parts = [p.strip() for p in sub.split() if p.strip()]
            all_tokens.extend(parts)
            # Also keep the original term as-is for exact matching
            if len(parts) > 1:
                all_tokens.append(term)

        if not all_tokens:
            return ""

        # Use unquoted terms with * for prefix matching (works with porter stemmer)
        fts_terms = [f"{t}*" for t in all_tokens if t]
        return " OR ".join(fts_terms)

    # ── Dunder Methods ────────────────────────────────────────

    def __repr__(self) -> str:
        return f"SQLiteStore(db_path={self._db_path!r})"

    def __enter__(self) -> SQLiteStore:
        self.initialize()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ["SQLiteStore"]
