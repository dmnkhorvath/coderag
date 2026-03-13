"""Hybrid Search — combine FTS5 full-text and vector semantic search.

Uses Reciprocal Rank Fusion (RRF) to merge two ranked result lists
into a single, unified ranking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from coderag.search.embedder import CodeEmbedder
    from coderag.search.vector_store import VectorStore
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# RRF constant — standard value from the original paper (Cormack et al.)
_RRF_K = 60


@dataclass(slots=True)
class SearchResult:
    """A single search result combining FTS5 and vector scores.

    Attributes:
        node_id: Unique node identifier.
        name: Short symbol name.
        kind: Node kind string (e.g. "class", "function").
        qualified_name: Fully-qualified name.
        file_path: Relative file path.
        language: Language identifier.
        score: Combined relevance score (higher is better).
        match_type: How this result was found.
        fts_rank: Rank in FTS5 results (1-based, 0 = not found).
        vector_rank: Rank in vector results (1-based, 0 = not found).
        vector_similarity: Raw cosine similarity from vector search.
    """

    node_id: str
    name: str
    kind: str
    qualified_name: str = ""
    file_path: str = ""
    language: str = ""
    score: float = 0.0
    match_type: Literal["fts", "vector", "both"] = "fts"
    fts_rank: int = 0
    vector_rank: int = 0
    vector_similarity: float = 0.0


class HybridSearcher:
    """Combine FTS5 full-text search with FAISS vector search.

    Uses Reciprocal Rank Fusion (RRF) to merge the two ranked lists.
    The ``alpha`` parameter controls the balance:

    - ``alpha = 0.0`` → pure FTS5 (keyword matching)
    - ``alpha = 0.5`` → equal weight (default)
    - ``alpha = 1.0`` → pure vector (semantic matching)

    Args:
        store: Initialised SQLiteStore for FTS5 queries.
        vector_store: Loaded VectorStore with FAISS index.
        embedder: CodeEmbedder for query embedding.
    """

    def __init__(
        self,
        store: SQLiteStore,
        vector_store: VectorStore,
        embedder: CodeEmbedder,
    ) -> None:
        self._store = store
        self._vector_store = vector_store
        self._embedder = embedder

    def search(
        self,
        query: str,
        k: int = 10,
        alpha: float = 0.5,
        kind: str | None = None,
    ) -> list[SearchResult]:
        """Run hybrid search combining FTS5 and vector results.

        Args:
            query: Natural-language or keyword search query.
            k: Maximum number of results to return.
            alpha: Balance between FTS5 (0.0) and vector (1.0).
            kind: Optional node-kind filter (e.g. "class").

        Returns:
            Sorted list of :class:`SearchResult` objects.
        """
        alpha = max(0.0, min(1.0, alpha))
        # Fetch more candidates than needed for better fusion
        fetch_k = k * 5

        # ── FTS5 results ──────────────────────────────────────
        fts_results: dict[str, int] = {}  # node_id -> rank
        if alpha < 1.0:
            fts_nodes = self._store.search_nodes(
                query,
                limit=fetch_k,
                kind=kind,
            )
            for rank, node in enumerate(fts_nodes, start=1):
                fts_results[node.id] = rank

        # ── Vector results ────────────────────────────────────
        vector_results: dict[str, tuple[int, float]] = {}  # node_id -> (rank, similarity)
        if alpha > 0.0 and self._vector_store.size > 0:
            query_vec = self._embedder.embed_text(query)
            vec_hits = self._vector_store.search(query_vec, k=fetch_k)
            for rank, (node_id, similarity) in enumerate(vec_hits, start=1):
                vector_results[node_id] = (rank, similarity)

        # ── Reciprocal Rank Fusion ────────────────────────────
        all_ids = set(fts_results.keys()) | set(vector_results.keys())
        if not all_ids:
            return []

        scored: dict[str, float] = {}
        fts_ranks: dict[str, int] = {}
        vec_ranks: dict[str, int] = {}
        vec_sims: dict[str, float] = {}

        for nid in all_ids:
            fts_rank = fts_results.get(nid, 0)
            vec_rank, vec_sim = vector_results.get(nid, (0, 0.0))

            fts_rrf = (1.0 - alpha) * (1.0 / (fts_rank + _RRF_K)) if fts_rank > 0 else 0.0
            vec_rrf = alpha * (1.0 / (vec_rank + _RRF_K)) if vec_rank > 0 else 0.0

            scored[nid] = fts_rrf + vec_rrf
            fts_ranks[nid] = fts_rank
            vec_ranks[nid] = vec_rank
            vec_sims[nid] = vec_sim

        # Sort by combined score descending
        ranked_ids = sorted(scored, key=scored.__getitem__, reverse=True)[:k]

        # ── Build SearchResult objects ────────────────────────
        results: list[SearchResult] = []
        for nid in ranked_ids:
            node = self._store.get_node(nid)
            if node is None:
                continue

            # Apply kind filter for vector-only results
            if kind:
                node_kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
                if node_kind != kind:
                    continue

            fts_r = fts_ranks.get(nid, 0)
            vec_r = vec_ranks.get(nid, 0)

            if fts_r > 0 and vec_r > 0:
                match_type: Literal["fts", "vector", "both"] = "both"
            elif fts_r > 0:
                match_type = "fts"
            else:
                match_type = "vector"

            node_kind_str = node.kind.value if hasattr(node.kind, "value") else str(node.kind)

            results.append(
                SearchResult(
                    node_id=nid,
                    name=node.name,
                    kind=node_kind_str,
                    qualified_name=node.qualified_name or "",
                    file_path=node.file_path or "",
                    language=node.language or "",
                    score=scored[nid],
                    match_type=match_type,
                    fts_rank=fts_r,
                    vector_rank=vec_r,
                    vector_similarity=vec_sims.get(nid, 0.0),
                )
            )

        return results

    def search_semantic(
        self,
        query: str,
        k: int = 10,
        kind: str | None = None,
    ) -> list[SearchResult]:
        """Pure semantic (vector) search — convenience wrapper."""
        return self.search(query, k=k, alpha=1.0, kind=kind)

    def search_fts(
        self,
        query: str,
        k: int = 10,
        kind: str | None = None,
    ) -> list[SearchResult]:
        """Pure FTS5 (keyword) search — convenience wrapper."""
        return self.search(query, k=k, alpha=0.0, kind=kind)
