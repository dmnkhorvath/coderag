"""Vector Store — FAISS-backed vector index for semantic search.

Stores and retrieves normalized embeddings using Facebook AI Similarity
Search (FAISS).  The index is persisted as two files:

- ``vectors.faiss`` — the raw FAISS index
- ``vectors_meta.json`` — mapping between node IDs and index positions
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np

from coderag.search import require_semantic

logger = logging.getLogger(__name__)

# File names used for persistence
_INDEX_FILE = "vectors.faiss"
_META_FILE = "vectors_meta.json"


class VectorStore:
    """FAISS-backed vector store with node-ID mapping.

    Uses ``IndexFlatIP`` (inner-product) which is equivalent to cosine
    similarity when all vectors are L2-normalised (which the
    :class:`CodeEmbedder` guarantees).

    Args:
        dimension: Embedding dimensionality (e.g. 384 for MiniLM).
    """

    def __init__(self, dimension: int) -> None:
        require_semantic()
        import faiss

        self._dimension = dimension
        self._index: faiss.IndexFlatIP = faiss.IndexFlatIP(dimension)
        # Ordered list of node IDs — position matches FAISS row
        self._node_ids: list[str] = []
        # Reverse lookup: node_id -> index position
        self._id_to_pos: dict[str, int] = {}
        # Content hashes for incremental updates
        self._content_hashes: dict[str, str] = {}

    # ── Properties ────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def size(self) -> int:
        """Number of vectors currently in the index."""
        return self._index.ntotal

    @property
    def node_ids(self) -> list[str]:
        """Ordered list of node IDs in the index."""
        return list(self._node_ids)

    # ── Build / search ────────────────────────────────────────

    def build_index(
        self,
        embeddings: np.ndarray,
        node_ids: list[str],
        content_hashes: dict[str, str] | None = None,
    ) -> None:
        """Build the index from scratch.

        Args:
            embeddings: 2-D float32 array of shape ``(n, dimension)``.
            node_ids: Parallel list of node IDs.
            content_hashes: Optional mapping of node_id -> content_hash
                for incremental update tracking.

        Raises:
            ValueError: If shapes are inconsistent.
        """
        import faiss

        if len(embeddings) != len(node_ids):
            raise ValueError(f"embeddings ({len(embeddings)}) and node_ids ({len(node_ids)}) must have the same length")
        if embeddings.ndim != 2 or embeddings.shape[1] != self._dimension:
            raise ValueError(f"Expected embeddings of shape (n, {self._dimension}), got {embeddings.shape}")

        # Rebuild from scratch
        self._index = faiss.IndexFlatIP(self._dimension)
        self._index.add(embeddings.astype(np.float32))
        self._node_ids = list(node_ids)
        self._id_to_pos = {nid: i for i, nid in enumerate(node_ids)}
        self._content_hashes = dict(content_hashes) if content_hashes else {}

        logger.info("Built vector index with %d vectors (dim=%d)", self.size, self._dimension)

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
    ) -> list[tuple[str, float]]:
        """Search for the *k* nearest neighbours.

        Args:
            query_embedding: 1-D float32 array of shape ``(dimension,)``.
            k: Number of results to return.

        Returns:
            List of ``(node_id, similarity_score)`` tuples, sorted by
            descending similarity.
        """
        if self.size == 0:
            return []

        k = min(k, self.size)
        query = query_embedding.reshape(1, -1).astype(np.float32)
        scores, indices = self._index.search(query, k)

        results: list[tuple[str, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for missing results
                continue
            results.append((self._node_ids[idx], float(score)))
        return results

    # ── Incremental updates ───────────────────────────────────

    def add_vectors(
        self,
        embeddings: np.ndarray,
        node_ids: list[str],
        content_hashes: dict[str, str] | None = None,
    ) -> None:
        """Add new vectors to the index.

        If a node_id already exists it is **replaced** (removed then
        re-added at the end).

        Args:
            embeddings: 2-D float32 array.
            node_ids: Parallel list of node IDs.
            content_hashes: Optional content hashes for the new nodes.
        """
        if len(embeddings) != len(node_ids):
            raise ValueError("embeddings and node_ids length mismatch")
        if len(embeddings) == 0:
            return

        # Remove any existing entries first
        existing = [nid for nid in node_ids if nid in self._id_to_pos]
        if existing:
            self.remove_vectors(existing)

        # Append new vectors
        self._index.add(embeddings.astype(np.float32))
        start = len(self._node_ids)
        for i, nid in enumerate(node_ids):
            self._node_ids.append(nid)
            self._id_to_pos[nid] = start + i

        if content_hashes:
            self._content_hashes.update(content_hashes)

        logger.debug("Added %d vectors (total: %d)", len(node_ids), self.size)

    def remove_vectors(self, node_ids: list[str]) -> None:
        """Remove vectors by node ID.

        Because ``IndexFlatIP`` does not support in-place removal we
        rebuild the index from the remaining vectors.  This is fast
        for typical incremental updates.
        """
        import faiss

        remove_set = set(node_ids)
        if not remove_set:
            return

        # Collect surviving vectors
        keep_ids: list[str] = []
        keep_indices: list[int] = []
        for i, nid in enumerate(self._node_ids):
            if nid not in remove_set:
                keep_ids.append(nid)
                keep_indices.append(i)

        if not keep_ids:
            self._index = faiss.IndexFlatIP(self._dimension)
            self._node_ids = []
            self._id_to_pos = {}
            for nid in node_ids:
                self._content_hashes.pop(nid, None)
            return

        # Reconstruct vectors from the existing index
        all_vecs = np.empty((self._index.ntotal, self._dimension), dtype=np.float32)
        for i in range(self._index.ntotal):
            all_vecs[i] = self._index.reconstruct(i)

        keep_vecs = all_vecs[keep_indices]

        self._index = faiss.IndexFlatIP(self._dimension)
        self._index.add(keep_vecs)
        self._node_ids = keep_ids
        self._id_to_pos = {nid: i for i, nid in enumerate(keep_ids)}

        for nid in node_ids:
            self._content_hashes.pop(nid, None)

        logger.debug(
            "Removed %d vectors (remaining: %d)",
            len(remove_set),
            self.size,
        )

    def get_content_hash(self, node_id: str) -> str | None:
        """Return the stored content hash for a node, or *None*."""
        return self._content_hashes.get(node_id)

    # ── Persistence ───────────────────────────────────────────

    def save(self, directory: str) -> None:
        """Persist the index and metadata to *directory*.

        Creates two files:
        - ``vectors.faiss``
        - ``vectors_meta.json``
        """
        import faiss

        os.makedirs(directory, exist_ok=True)

        index_path = os.path.join(directory, _INDEX_FILE)
        meta_path = os.path.join(directory, _META_FILE)

        faiss.write_index(self._index, index_path)

        meta: dict[str, Any] = {
            "dimension": self._dimension,
            "node_ids": self._node_ids,
            "content_hashes": self._content_hashes,
        }
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)

        index_size = os.path.getsize(index_path)
        logger.info(
            "Saved vector index: %d vectors, %.1f KB",
            self.size,
            index_size / 1024,
        )

    @classmethod
    def load(cls, directory: str) -> VectorStore:
        """Load a previously saved index from *directory*.

        Raises:
            FileNotFoundError: If the index files do not exist.
        """
        require_semantic()
        import faiss

        index_path = os.path.join(directory, _INDEX_FILE)
        meta_path = os.path.join(directory, _META_FILE)

        if not os.path.exists(index_path) or not os.path.exists(meta_path):
            raise FileNotFoundError(f'Vector index not found in {directory}. Run "coderag embed" first.')

        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)

        dimension = meta["dimension"]
        store = cls.__new__(cls)
        store._dimension = dimension
        store._index = faiss.read_index(index_path)
        store._node_ids = meta["node_ids"]
        store._id_to_pos = {nid: i for i, nid in enumerate(store._node_ids)}
        store._content_hashes = meta.get("content_hashes", {})

        logger.info(
            "Loaded vector index: %d vectors (dim=%d)",
            store.size,
            dimension,
        )
        return store

    @staticmethod
    def exists(directory: str) -> bool:
        """Return *True* if a saved index exists in *directory*."""
        return os.path.exists(os.path.join(directory, _INDEX_FILE)) and os.path.exists(
            os.path.join(directory, _META_FILE)
        )
