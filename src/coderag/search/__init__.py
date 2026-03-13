"""CodeRAG Semantic Search Package.

Provides vector embedding-based semantic search alongside FTS5 full-text
search.  Requires optional dependencies::

    pip install coderag[semantic]

When the dependencies are not installed every public symbol is still
importable but constructing the concrete classes raises a helpful error.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------

_SEMANTIC_AVAILABLE = False
_IMPORT_ERROR: str | None = None

try:
    import faiss  # noqa: F401
    import sentence_transformers  # noqa: F401

    _SEMANTIC_AVAILABLE = True
except ImportError as exc:
    _IMPORT_ERROR = (
        f"Semantic search dependencies not installed ({exc}). Install them with:  pip install coderag[semantic]"
    )


# Public alias for direct import
SEMANTIC_AVAILABLE: bool = _SEMANTIC_AVAILABLE


def is_semantic_available() -> bool:
    """Return *True* when sentence-transformers **and** faiss-cpu are importable."""
    return _SEMANTIC_AVAILABLE


def require_semantic() -> None:
    """Raise *ImportError* with a helpful message when deps are missing."""
    if not _SEMANTIC_AVAILABLE:
        raise ImportError(_IMPORT_ERROR)


# ---------------------------------------------------------------------------
# Lazy public API
# ---------------------------------------------------------------------------


def __getattr__(name: str):
    """Lazy import so the package is always importable."""
    if name == "CodeEmbedder":
        from coderag.search.embedder import CodeEmbedder

        return CodeEmbedder
    if name == "VectorStore":
        from coderag.search.vector_store import VectorStore

        return VectorStore
    if name == "HybridSearcher":
        from coderag.search.hybrid import HybridSearcher

        return HybridSearcher
    if name == "SearchResult":
        from coderag.search.hybrid import SearchResult

        return SearchResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SEMANTIC_AVAILABLE",
    "is_semantic_available",
    "require_semantic",
    "CodeEmbedder",
    "VectorStore",
    "HybridSearcher",
    "SearchResult",
]
