"""Code Embedder — convert code nodes to vector embeddings.

Uses sentence-transformers to produce dense vector representations
of code symbols for semantic search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from coderag.search import require_semantic

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from coderag.core.models import Node

logger = logging.getLogger(__name__)

# Default model — small, fast, 384 dimensions
DEFAULT_MODEL = "all-MiniLM-L6-v2"


class CodeEmbedder:
    """Produce vector embeddings for code graph nodes.

    The underlying *sentence-transformers* model is loaded lazily on
    first use so that importing this module is essentially free.

    Args:
        model_name: HuggingFace model identifier.  Defaults to
            ``all-MiniLM-L6-v2`` (384-d, ~80 MB).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    # ── Properties ────────────────────────────────────────────

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        """Embedding dimensionality (loads model if needed)."""
        return self._get_model().get_sentence_embedding_dimension()  # type: ignore[return-value]

    # ── Lazy model loading ────────────────────────────────────

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            require_semantic()
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            logger.info(
                "Model loaded — dimension=%d",
                self._model.get_sentence_embedding_dimension(),
            )
        return self._model

    # ── Text construction ─────────────────────────────────────

    @staticmethod
    def build_node_text(node: Node, parent_name: str | None = None) -> str:
        """Build a searchable text representation of a graph node.

        Combines the node's kind, name, file path, docstring,
        signature information, and parent context into a single
        string suitable for embedding.

        Args:
            node: The graph node to represent.
            parent_name: Optional parent symbol name for context
                (e.g. the class name for a method).

        Returns:
            A descriptive text string.
        """
        parts: list[str] = []

        # Kind and name
        kind_str = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        parts.append(f"{kind_str}: {node.name}")

        # File path context
        if node.file_path:
            parts.append(f"in {node.file_path}")

        # Parent context
        if parent_name:
            parts.append(f"({kind_str} of {parent_name})")

        # Qualified name (if different from name)
        if node.qualified_name and node.qualified_name != node.name:
            parts.append(f"[{node.qualified_name}]")

        # Docblock / docstring
        if node.docblock:
            # Truncate very long docblocks
            doc = node.docblock.strip()
            if len(doc) > 500:
                doc = doc[:500] + "..."
            parts.append(f". {doc}")

        # Metadata: parameters, return type, decorators
        meta = node.metadata or {}

        params = meta.get("parameters") or meta.get("params")
        if params:
            if isinstance(params, list):
                param_str = ", ".join(p if isinstance(p, str) else p.get("name", str(p)) for p in params)
            else:
                param_str = str(params)
            parts.append(f". Parameters: {param_str}")

        return_type = meta.get("return_type") or meta.get("returns")
        if return_type:
            parts.append(f". Returns: {return_type}")

        decorators = meta.get("decorators")
        if decorators:
            if isinstance(decorators, list):
                dec_str = ", ".join(str(d) for d in decorators)
            else:
                dec_str = str(decorators)
            parts.append(f". Decorators: {dec_str}")

        # Superclasses / interfaces
        extends = meta.get("extends") or meta.get("superclass")
        if extends:
            parts.append(f". Extends: {extends}")

        implements = meta.get("implements")
        if implements:
            if isinstance(implements, list):
                impl_str = ", ".join(str(i) for i in implements)
            else:
                impl_str = str(implements)
            parts.append(f". Implements: {impl_str}")

        return " ".join(parts)

    # ── Embedding ─────────────────────────────────────────────

    def embed_text(self, text: str) -> np.ndarray:
        """Embed a single text string.

        Returns:
            1-D float32 array of shape ``(dimension,)``.
        """
        model = self._get_model()
        vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)

    def embed_batch(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        """Embed a batch of texts efficiently.

        Args:
            texts: List of text strings to embed.
            batch_size: Encoding batch size (passed to the model).

        Returns:
            2-D float32 array of shape ``(len(texts), dimension)``.
        """
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        model = self._get_model()
        vecs = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=batch_size,
        )
        return np.asarray(vecs, dtype=np.float32)
