"""NetworkX Graph Analyzer for CodeRAG.

Provides graph analysis algorithms including PageRank, centrality,
community detection, cycle finding, blast radius, and relevance scoring.
Designed to handle 100K+ node graphs efficiently.
"""

from __future__ import annotations

import json
import logging
import signal
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Node kind importance weights for relevance scoring
_NODE_KIND_WEIGHTS: dict[str, float] = {
    "class": 1.0,
    "interface": 0.95,
    "trait": 0.9,
    "enum": 0.85,
    "function": 0.8,
    "method": 0.75,
    "component": 0.9,
    "route": 0.85,
    "hook": 0.8,
    "model": 0.9,
    "middleware": 0.8,
    "event": 0.75,
    "module": 0.7,
    "namespace": 0.6,
    "file": 0.5,
    "directory": 0.3,
    "package": 0.4,
    "property": 0.5,
    "constant": 0.5,
    "type_alias": 0.7,
    "variable": 0.4,
    "parameter": 0.3,
    "import": 0.2,
    "export": 0.3,
    "decorator": 0.5,
}


class NetworkXAnalyzer:
    """Graph analyzer powered by NetworkX.

    Loads the knowledge graph from SQLiteStore into a NetworkX DiGraph
    and provides various graph analysis algorithms.

    Example::

        analyzer = NetworkXAnalyzer()
        analyzer.load_from_store(store)
        top = analyzer.pagerank()
        communities = analyzer.community_detection()
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._loaded: bool = False
        self._pagerank_cache: dict[str, float] | None = None
        self._betweenness_cache: dict[str, float] | None = None

    # ── Properties ────────────────────────────────────────────

    @property
    def graph(self) -> nx.DiGraph:
        """The underlying NetworkX directed graph."""
        return self._graph

    @property
    def is_loaded(self) -> bool:
        """Whether the graph has been loaded from a store."""
        return self._loaded

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    # ── Loading ───────────────────────────────────────────────

    def load_from_store(self, store: SQLiteStore) -> None:
        """Load all nodes and edges from SQLiteStore into a NetworkX DiGraph.

        Queries SQLite directly for bulk efficiency rather than using
        the store\'s individual accessor methods.

        Args:
            store: An initialized SQLiteStore instance.
        """
        self._graph = nx.DiGraph()
        self._pagerank_cache = None
        self._betweenness_cache = None

        conn = store.connection

        # Bulk load nodes
        node_count = 0
        null_count = 0
        cursor = conn.execute("SELECT * FROM nodes")
        for row in cursor:
            node_id = row["id"]
            if node_id is None:
                null_count += 1
                continue
            try:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}

            self._graph.add_node(
                node_id,
                kind=row["kind"],
                name=row["name"],
                qualified_name=row["qualified_name"],
                file_path=row["file_path"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                language=row["language"],
                metadata=meta,
                pagerank=row["pagerank"] or 0.0,
                community_id=row["community_id"],
            )
            node_count += 1

        if null_count:
            logger.warning(
                "Skipped %d nodes with NULL id (corrupted data)",
                null_count,
            )

        # Bulk load edges
        edge_count = 0
        cursor = conn.execute("SELECT * FROM edges")
        for row in cursor:
            src, tgt = row["source_id"], row["target_id"]
            # Only add edges where both endpoints exist in the graph
            if src in self._graph and tgt in self._graph:
                try:
                    meta = json.loads(row["metadata"]) if row["metadata"] else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}

                self._graph.add_edge(
                    src,
                    tgt,
                    kind=row["kind"],
                    confidence=row["confidence"] or 1.0,
                    metadata=meta,
                )
                edge_count += 1

        self._loaded = True
        logger.info(
            "Loaded graph: %d nodes, %d edges",
            node_count,
            edge_count,
        )

    def _ensure_loaded(self) -> None:
        """Raise if graph not loaded."""
        if not self._loaded:
            raise RuntimeError("Graph not loaded. Call load_from_store() first.")

    # ── PageRank ──────────────────────────────────────────────

    def pagerank(
        self,
        personalization: dict[str, float] | None = None,
        alpha: float = 0.85,
        max_iter: int = 100,
    ) -> dict[str, float]:
        """Compute PageRank scores for all nodes.

        Args:
            personalization: Optional personalization vector.
            alpha: Damping factor (default 0.85).
            max_iter: Maximum iterations.

        Returns:
            Dict mapping node IDs to PageRank scores.
        """
        self._ensure_loaded()

        if self._graph.number_of_nodes() == 0:
            return {}

        if personalization is None and self._pagerank_cache is not None:
            return self._pagerank_cache

        try:
            scores = nx.pagerank(
                self._graph,
                alpha=alpha,
                personalization=personalization,
                max_iter=max_iter,
            )
        except nx.PowerIterationFailedConvergence:
            logger.warning("PageRank did not converge, using approximate values")
            scores = nx.pagerank(
                self._graph,
                alpha=alpha,
                personalization=personalization,
                max_iter=max_iter * 2,
                tol=1e-4,
            )

        if personalization is None:
            self._pagerank_cache = scores

        return scores

    # ── Betweenness Centrality ────────────────────────────────

    def betweenness_centrality(
        self,
        k: int | None = None,
    ) -> dict[str, float]:
        """Compute betweenness centrality for all nodes.

        For large graphs (>10K nodes), uses sampling (k=min(500, n))
        for performance.

        Args:
            k: Number of sample nodes. None = auto-select.

        Returns:
            Dict mapping node IDs to centrality scores.
        """
        self._ensure_loaded()

        if self._graph.number_of_nodes() == 0:
            return {}

        if self._betweenness_cache is not None and k is None:
            return self._betweenness_cache

        n = self._graph.number_of_nodes()
        if k is None and n > 10_000:
            k = min(500, n)
            logger.info(
                "Large graph (%d nodes), sampling k=%d for betweenness",
                n,
                k,
            )

        scores = nx.betweenness_centrality(self._graph, k=k)

        if k is None:
            self._betweenness_cache = scores

        return scores

    # ── Community Detection ───────────────────────────────────

    def community_detection(self) -> list[set[str]]:
        """Detect communities using tiered algorithm selection.

        Algorithm selection based on graph size:
        - < 10K nodes: greedy modularity (best quality, O(n² log n))
        - 10K-500K nodes: Leiden algorithm (excellent quality, O(n log n))
        - > 500K nodes: label propagation (good quality, O(n + m))

        Returns:
            List of sets, each set containing node IDs in a community.
            Sorted by community size (largest first).
        """
        self._ensure_loaded()
        if self._graph.number_of_nodes() == 0:
            return []

        undirected = self._graph.to_undirected()
        isolates = list(nx.isolates(undirected))
        if isolates:
            undirected.remove_nodes_from(isolates)
        if undirected.number_of_nodes() == 0:
            return []

        node_count = undirected.number_of_nodes()

        try:
            if node_count < 10_000:
                logger.info("Community detection: using greedy modularity (%d nodes)", node_count)
                from networkx.algorithms.community import greedy_modularity_communities
                communities = list(greedy_modularity_communities(undirected))
            elif node_count < 500_000:
                logger.info("Community detection: using Leiden algorithm (%d nodes)", node_count)
                communities = self._leiden_communities(undirected)
            else:
                logger.info("Community detection: using label propagation (%d nodes)", node_count)
                from networkx.algorithms.community import label_propagation_communities
                communities = [set(c) for c in label_propagation_communities(undirected)]
        except Exception as exc:
            logger.warning("Community detection failed: %s", exc)
            communities = [set(c) for c in nx.connected_components(undirected)]

        communities.sort(key=len, reverse=True)
        return communities

    def _leiden_communities(self, undirected: nx.Graph) -> list[set[str]]:
        """Run Leiden community detection via igraph."""
        import igraph as ig
        import leidenalg

        # Convert NetworkX graph to igraph
        g = ig.Graph.from_networkx(undirected)
        node_names = g.vs["_nx_name"]

        # Run Leiden with modularity optimization
        partition = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition)

        # Convert partition to list of sets
        communities = []
        for community_indices in partition:
            community_set = {node_names[i] for i in community_indices}
            communities.append(community_set)

        return communities

    # ── Shortest Path ─────────────────────────────────────────

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str] | None:
        """Find the shortest path between two nodes.

        Args:
            source_id: Starting node ID.
            target_id: Ending node ID.

        Returns:
            List of node IDs forming the path, or None if no path exists.
        """
        self._ensure_loaded()

        if source_id not in self._graph or target_id not in self._graph:
            return None

        try:
            return nx.shortest_path(self._graph, source_id, target_id)
        except nx.NetworkXNoPath:
            return None

    # ── Cycle Detection ───────────────────────────────────────

    def find_cycles(
        self,
        edge_kinds: list[str] | None = None,
        max_length: int = 10,
        limit: int = 100,
    ) -> list[list[str]]:
        """Find circular dependencies in the graph.

        Args:
            edge_kinds: Optional filter — only consider edges of these kinds.
            max_length: Maximum cycle length to report.
            limit: Maximum number of cycles to return.

        Returns:
            List of cycles, each cycle is a list of node IDs.
        """
        self._ensure_loaded()

        # Build a filtered subgraph if edge_kinds specified
        if edge_kinds:
            filtered = nx.DiGraph()
            filtered.add_nodes_from(self._graph.nodes(data=True))
            for u, v, data in self._graph.edges(data=True):
                if data.get("kind") in edge_kinds:
                    filtered.add_edge(u, v, **data)
            g = filtered
        else:
            g = self._graph

        cycles: list[list[str]] = []
        try:
            for cycle in nx.simple_cycles(g, length_bound=max_length):
                cycles.append(list(cycle))
                if len(cycles) >= limit:
                    break
        except Exception as exc:
            logger.warning("Cycle detection error: %s", exc)

        # Sort by length
        cycles.sort(key=len)
        return cycles

    # ── Blast Radius ──────────────────────────────────────────

    def blast_radius(
        self,
        node_id: str,
        max_depth: int = 3,
    ) -> dict[int, list[str]]:
        """Compute the blast radius of a node change via BFS.

        Follows incoming edges ("who depends on this node?") to find
        all nodes that would be affected by a change.

        Args:
            node_id: The node to analyze.
            max_depth: Maximum BFS depth.

        Returns:
            Dict mapping depth level to list of affected node IDs.
        """
        self._ensure_loaded()

        if node_id not in self._graph:
            return {}

        result: dict[int, list[str]] = {}
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}

        for depth in range(1, max_depth + 1):
            next_frontier: set[str] = set()
            for nid in frontier:
                # Predecessors = nodes that have edges pointing TO this node
                # i.e., nodes that depend on / reference this node
                for pred in self._graph.predecessors(nid):
                    if pred not in visited:
                        next_frontier.add(pred)
                        visited.add(pred)

            if next_frontier:
                result[depth] = sorted(next_frontier)

            frontier = next_frontier
            if not frontier:
                break

        return result

    # ── Relevance Scoring ─────────────────────────────────────

    def relevance_score(
        self,
        node_id: str,
        query_context: str | None = None,
    ) -> float:
        """Compute a multi-factor relevance score for a node.

        Combines:
        - PageRank (graph importance)
        - Degree centrality (connectivity)
        - Node kind importance weight
        - Name match bonus (if query_context provided)

        Args:
            node_id: The node to score.
            query_context: Optional search query for name matching.

        Returns:
            Relevance score (0.0 to 1.0).
        """
        self._ensure_loaded()

        if node_id not in self._graph:
            return 0.0

        attrs = self._graph.nodes[node_id]

        # Factor 1: PageRank (normalized)
        pr_scores = self.pagerank()
        pr = pr_scores.get(node_id, 0.0)
        max_pr = max(pr_scores.values()) if pr_scores else 1.0
        pr_normalized = pr / max_pr if max_pr > 0 else 0.0

        # Factor 2: Degree centrality
        in_deg = self._graph.in_degree(node_id)
        out_deg = self._graph.out_degree(node_id)
        total_deg = in_deg + out_deg
        max_deg = max(
            (self._graph.in_degree(n) + self._graph.out_degree(n) for n in self._graph.nodes),
            default=1,
        )
        deg_normalized = total_deg / max_deg if max_deg > 0 else 0.0

        # Factor 3: Node kind importance
        kind = attrs.get("kind", "")
        kind_weight = _NODE_KIND_WEIGHTS.get(kind, 0.5)

        # Factor 4: Name match bonus
        name_bonus = 0.0
        if query_context:
            qc_lower = query_context.lower()
            name = attrs.get("name", "").lower()
            qname = attrs.get("qualified_name", "").lower()
            if qc_lower == name:
                name_bonus = 1.0
            elif qc_lower in name or qc_lower in qname:
                name_bonus = 0.5

        # Weighted combination
        score = 0.30 * pr_normalized + 0.25 * deg_normalized + 0.25 * kind_weight + 0.20 * name_bonus

        return min(1.0, score)

    # ── Subgraph Extraction ───────────────────────────────────

    def get_connected_subgraph(
        self,
        node_id: str,
        max_depth: int = 2,
    ) -> nx.DiGraph:
        """Extract a subgraph around a node up to max_depth hops.

        Args:
            node_id: Center node.
            max_depth: Maximum distance from center.

        Returns:
            A new DiGraph containing the neighborhood.
        """
        self._ensure_loaded()

        if node_id not in self._graph:
            return nx.DiGraph()

        # Use ego_graph on undirected view for reachability,
        # then extract the directed subgraph
        undirected = self._graph.to_undirected(as_view=True)
        ego_nodes = nx.ego_graph(undirected, node_id, radius=max_depth).nodes()

        return self._graph.subgraph(ego_nodes).copy()

    # ── Graph Statistics ──────────────────────────────────────

    def get_statistics(self) -> dict[str, Any]:
        """Compute graph-level statistics.

        Returns:
            Dict with density, avg degree, connected components,
            node/edge counts by kind, and other metrics.
        """
        self._ensure_loaded()

        g = self._graph
        n = g.number_of_nodes()
        m = g.number_of_edges()

        if n == 0:
            return {
                "node_count": 0,
                "edge_count": 0,
                "density": 0.0,
                "avg_in_degree": 0.0,
                "avg_out_degree": 0.0,
                "weakly_connected_components": 0,
                "strongly_connected_components": 0,
                "nodes_by_kind": {},
                "edges_by_kind": {},
                "isolate_count": 0,
            }

        # Degree stats
        in_degrees = [d for _, d in g.in_degree()]
        out_degrees = [d for _, d in g.out_degree()]

        # Nodes by kind
        nodes_by_kind: dict[str, int] = defaultdict(int)
        for _, data in g.nodes(data=True):
            nodes_by_kind[data.get("kind", "unknown")] += 1

        # Edges by kind
        edges_by_kind: dict[str, int] = defaultdict(int)
        for _, _, data in g.edges(data=True):
            edges_by_kind[data.get("kind", "unknown")] += 1

        # Connected components
        wcc = nx.number_weakly_connected_components(g)
        scc = nx.number_strongly_connected_components(g)

        # Isolates
        isolate_count = nx.number_of_isolates(g)

        return {
            "node_count": n,
            "edge_count": m,
            "density": nx.density(g),
            "avg_in_degree": sum(in_degrees) / n,
            "avg_out_degree": sum(out_degrees) / n,
            "max_in_degree": max(in_degrees),
            "max_out_degree": max(out_degrees),
            "weakly_connected_components": wcc,
            "strongly_connected_components": scc,
            "isolate_count": isolate_count,
            "nodes_by_kind": dict(nodes_by_kind),
            "edges_by_kind": dict(edges_by_kind),
            "is_dag": nx.is_directed_acyclic_graph(g),
        }

    # ── Utility Methods ───────────────────────────────────────

    def get_top_nodes(
        self,
        metric: str = "pagerank",
        limit: int = 10,
        kind_filter: str | None = None,
    ) -> list[tuple[str, float]]:
        """Get top nodes by a given metric.

        Args:
            metric: One of "pagerank", "betweenness", "in_degree", "out_degree".
            limit: Number of results.
            kind_filter: Optional node kind filter.

        Returns:
            List of (node_id, score) tuples sorted descending.
        """
        self._ensure_loaded()

        if metric == "pagerank":
            scores = self.pagerank()
        elif metric == "betweenness":
            scores = self.betweenness_centrality()
        elif metric == "in_degree":
            scores = {n: float(d) for n, d in self._graph.in_degree()}
        elif metric == "out_degree":
            scores = {n: float(d) for n, d in self._graph.out_degree()}
        else:
            raise ValueError(f"Unknown metric: {metric}")

        if kind_filter:
            scores = {nid: s for nid, s in scores.items() if self._graph.nodes[nid].get("kind") == kind_filter}

        sorted_nodes = sorted(scores.items(), key=lambda x: -x[1])
        return sorted_nodes[:limit]

    def get_entry_points(self, limit: int = 20) -> list[str]:
        """Find likely entry points (nodes with high out-degree, low in-degree).

        Entry points are nodes that are referenced by many others but
        don\'t themselves reference much — typically top-level classes,
        controllers, or main functions.

        Returns:
            List of node IDs likely to be entry points.
        """
        self._ensure_loaded()

        candidates: list[tuple[str, float]] = []
        for node_id in self._graph.nodes:
            in_deg = self._graph.in_degree(node_id)
            out_deg = self._graph.out_degree(node_id)
            kind = self._graph.nodes[node_id].get("kind", "")

            # Entry points have high in-degree (many depend on them)
            # and are important node kinds
            if in_deg == 0 and out_deg == 0:
                continue

            kind_weight = _NODE_KIND_WEIGHTS.get(kind, 0.5)
            # Score: high in-degree + kind importance
            score = in_deg * kind_weight
            candidates.append((node_id, score))

        candidates.sort(key=lambda x: -x[1])
        return [nid for nid, _ in candidates[:limit]]

    def get_node_info(self, node_id: str) -> dict[str, Any] | None:
        """Get all attributes for a node."""
        if node_id not in self._graph:
            return None
        return dict(self._graph.nodes[node_id])

    # ── Persistence ───────────────────────────────────────────

    @staticmethod
    def _timeout_handler(signum, frame):
        raise TimeoutError("Community detection timed out")

    def persist_scores_to_store(self, store: SQLiteStore) -> None:
        """Batch-update pagerank and community_id columns in the nodes table.

        Computes PageRank scores and community assignments, then writes
        them back to the SQLite ``nodes`` table in a single transaction.
        PageRank is persisted first so it is never blocked by slow
        community detection on large graphs.

        Args:
            store: The SQLiteStore instance to persist scores to.
        """
        self._ensure_loaded()

        conn = store.connection

        # ── Phase 1: PageRank (fast, always runs) ─────────────
        scores = self.pagerank()
        if scores:
            conn.executemany(
                "UPDATE nodes SET pagerank = ? WHERE id = ?",
                [(score, node_id) for node_id, score in scores.items()],
            )
            conn.commit()
            logger.info("Persisted %d PageRank scores", len(scores))

        # ── Phase 2: Community detection (always runs with timeout) ──
        community_map: dict[str, int] = {}

        try:
            old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)
            signal.alarm(120)  # 120 second timeout
            community_sets = self.community_detection()
            signal.alarm(0)  # Cancel alarm
            signal.signal(signal.SIGALRM, old_handler)
            for community_id, members in enumerate(community_sets):
                for node_id in members:
                    community_map[node_id] = community_id
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            signal.alarm(0)
            logger.warning("Community detection failed or timed out: %s", exc)

        if community_map:
            conn.executemany(
                "UPDATE nodes SET community_id = ? WHERE id = ?",
                [(cid, node_id) for node_id, cid in community_map.items()],
            )
            conn.commit()
            logger.info("Persisted %d community assignments", len(community_map))

        logger.info(
            "Persist complete: %d pagerank, %d community assignments",
            len(scores),
            len(community_map),
        )

    def __repr__(self) -> str:
        return f"NetworkXAnalyzer(nodes={self.node_count}, edges={self.edge_count}, loaded={self._loaded})"
