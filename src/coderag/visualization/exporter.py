"""Graph data exporter for visualization.

Exports knowledge graph data from SQLite to JSON format
suitable for D3.js force-directed graph rendering.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Any

from coderag.core.models import Edge, Node
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class GraphExporter:
    """Export graph data to JSON for D3.js visualization.

    Supports full export, filtered export, and neighborhood export.
    Uses PageRank to select the most important nodes when limiting size.
    """

    # ── Public API ────────────────────────────────────────────

    @staticmethod
    def export_full(
        store: SQLiteStore,
        output_path: str | Path,
        *,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """Export the entire graph, limited to the top *max_nodes* by PageRank.

        Args:
            store: An initialised SQLiteStore.
            output_path: Destination JSON file path.
            max_nodes: Cap on the number of nodes (most important kept).

        Returns:
            The exported data dict.
        """
        nodes = store.get_all_nodes()
        nodes = _select_top_nodes(nodes, max_nodes)
        node_ids = {n.id for n in nodes}
        edges = _collect_edges(store, node_ids)
        data = _build_json(nodes, edges)
        _write_json(data, output_path)
        return data

    @staticmethod
    def export_filtered(
        store: SQLiteStore,
        output_path: str | Path,
        *,
        languages: list[str] | None = None,
        kinds: list[str] | None = None,
        file_pattern: str | None = None,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """Export a filtered subset of the graph.

        Args:
            store: An initialised SQLiteStore.
            output_path: Destination JSON file path.
            languages: Keep only nodes whose language is in this list.
            kinds: Keep only nodes whose kind is in this list.
            file_pattern: Keep only nodes whose file_path contains this substring.
            max_nodes: Cap on the number of nodes.

        Returns:
            The exported data dict.
        """
        nodes = store.get_all_nodes()

        if languages:
            lang_set = {lang.lower() for lang in languages}
            nodes = [n for n in nodes if n.language.lower() in lang_set]
        if kinds:
            kind_set = {k.lower() for k in kinds}
            nodes = [n for n in nodes if n.kind.value.lower() in kind_set]
        if file_pattern:
            nodes = [n for n in nodes if file_pattern in n.file_path]

        nodes = _select_top_nodes(nodes, max_nodes)
        node_ids = {n.id for n in nodes}
        edges = _collect_edges(store, node_ids)
        data = _build_json(nodes, edges)
        _write_json(data, output_path)
        return data

    @staticmethod
    def export_neighborhood(
        store: SQLiteStore,
        output_path: str | Path,
        symbol: str,
        *,
        depth: int = 2,
        max_nodes: int = 500,
    ) -> dict[str, Any]:
        """Export the N-hop neighbourhood of a symbol.

        Performs a BFS from every node matching *symbol* up to *depth* hops.

        Args:
            store: An initialised SQLiteStore.
            output_path: Destination JSON file path.
            symbol: Name or qualified name to search for.
            depth: Number of hops to traverse.
            max_nodes: Cap on the number of nodes.

        Returns:
            The exported data dict.

        Raises:
            ValueError: If no node matches *symbol*.
        """
        seed_nodes = store.search_nodes(symbol, limit=10)
        if not seed_nodes:
            raise ValueError(f"No node found matching '{symbol}'")

        # BFS to collect neighbourhood
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        for sn in seed_nodes:
            queue.append((sn.id, 0))
            visited.add(sn.id)

        while queue:
            nid, d = queue.popleft()
            if d >= depth:
                continue
            # outgoing
            for edge in store.get_edges(source_id=nid):
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    queue.append((edge.target_id, d + 1))
            # incoming
            for edge in store.get_edges(target_id=nid):
                if edge.source_id not in visited:
                    visited.add(edge.source_id)
                    queue.append((edge.source_id, d + 1))

        # Fetch actual Node objects for visited ids
        all_nodes = store.get_all_nodes()
        nodes = [n for n in all_nodes if n.id in visited]
        nodes = _select_top_nodes(nodes, max_nodes)
        node_ids = {n.id for n in nodes}
        edges = _collect_edges(store, node_ids)
        data = _build_json(nodes, edges)
        _write_json(data, output_path)
        return data


# ── Private helpers ───────────────────────────────────────────


def _select_top_nodes(nodes: list[Node], max_nodes: int) -> list[Node]:
    """Return the top *max_nodes* nodes sorted by PageRank descending."""
    nodes.sort(key=lambda n: n.pagerank, reverse=True)
    return nodes[:max_nodes]


def _collect_edges(store: SQLiteStore, node_ids: set[str]) -> list[Edge]:
    """Return all edges whose source AND target are in *node_ids*."""
    all_edges = store.get_edges()
    return [e for e in all_edges if e.source_id in node_ids and e.target_id in node_ids]


def _node_to_dict(node: Node) -> dict[str, Any]:
    """Serialise a Node to a JSON-friendly dict."""
    return {
        "id": node.id,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "kind": node.kind.value,
        "language": node.language,
        "file": node.file_path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "metrics": {
            "pagerank": round(node.pagerank, 6),
            "community_id": node.community_id,
        },
    }


def _edge_to_dict(edge: Edge) -> dict[str, Any]:
    """Serialise an Edge to a JSON-friendly dict."""
    return {
        "source": edge.source_id,
        "target": edge.target_id,
        "type": edge.kind.value,
        "confidence": round(edge.confidence, 4),
    }


def _build_json(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    """Build the final JSON structure."""
    languages: set[str] = set()
    kinds: set[str] = set()
    for n in nodes:
        languages.add(n.language)
        kinds.add(n.kind.value)

    return {
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "languages": sorted(languages),
            "kinds": sorted(kinds),
        },
    }


def _write_json(data: dict[str, Any], path: str | Path) -> None:
    """Write *data* as pretty-printed JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Exported %d nodes, %d edges → %s", len(data["nodes"]), len(data["edges"]), p)
