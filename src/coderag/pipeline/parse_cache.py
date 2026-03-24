"""In-memory LRU cache for tree-sitter parse trees.

Maps file paths to their last parse tree and source bytes so that
incremental re-parsing can reuse the previous tree via ``tree.edit()``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tree_sitter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedTree:
    """A cached parse tree with associated metadata.

    Attributes:
        tree: The tree-sitter parse tree.
        source: The raw source bytes that produced this tree.
        content_hash: SHA-256 hex digest of *source*.
        language: Language identifier (e.g. ``"python"``).
        last_accessed: Monotonic timestamp of last cache hit.
        size_bytes: Estimated memory footprint (``len(source) * 3``).
    """

    tree: tree_sitter.Tree
    source: bytes
    content_hash: str
    language: str
    last_accessed: float = field(default_factory=time.monotonic)
    size_bytes: int = 0

    def __post_init__(self) -> None:
        if self.size_bytes == 0:
            self.size_bytes = len(self.source) * 3


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Snapshot of cache statistics."""

    entries: int
    total_bytes: int
    max_bytes: int
    hit_count: int
    miss_count: int
    eviction_count: int


class ParseTreeCache:
    """Thread-safe LRU cache for tree-sitter parse trees.

    Parameters:
        max_memory_mb: Maximum memory budget in megabytes (default 512).
    """

    def __init__(self, max_memory_mb: int = 512) -> None:
        self._max_bytes = max_memory_mb * 1024 * 1024
        self._entries: dict[str, CachedTree] = {}
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0
        self._eviction_count = 0

    # -- public API ----------------------------------------------------------

    def get(self, file_path: str) -> CachedTree | None:
        """Return the cached tree for *file_path*, or ``None`` on miss."""
        with self._lock:
            entry = self._entries.get(file_path)
            if entry is None:
                self._miss_count += 1
                return None
            entry.last_accessed = time.monotonic()
            self._hit_count += 1
            return entry

    def put(
        self,
        file_path: str,
        tree: tree_sitter.Tree,
        source: bytes,
        content_hash: str,
        language: str,
    ) -> None:
        """Store a parse tree in the cache, evicting LRU entries if needed."""
        entry = CachedTree(
            tree=tree,
            source=source,
            content_hash=content_hash,
            language=language,
        )
        with self._lock:
            # Replace existing entry for same path
            self._entries.pop(file_path, None)
            self._entries[file_path] = entry
            self._evict_lru()
        logger.debug(
            "ParseTreeCache: stored %s (%d bytes est.)",
            file_path,
            entry.size_bytes,
        )

    def evict(self, file_path: str) -> None:
        """Remove a specific entry from the cache."""
        with self._lock:
            removed = self._entries.pop(file_path, None)
        if removed:
            logger.debug("ParseTreeCache: evicted %s", file_path)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._entries.clear()
            self._hit_count = 0
            self._miss_count = 0
            self._eviction_count = 0
        logger.debug("ParseTreeCache: cleared")

    def stats(self) -> CacheStats:
        """Return a snapshot of cache statistics."""
        with self._lock:
            total = sum(e.size_bytes for e in self._entries.values())
            return CacheStats(
                entries=len(self._entries),
                total_bytes=total,
                max_bytes=self._max_bytes,
                hit_count=self._hit_count,
                miss_count=self._miss_count,
                eviction_count=self._eviction_count,
            )

    # -- internals -----------------------------------------------------------

    def _evict_lru(self) -> None:
        """Evict least-recently-accessed entries until under memory limit.

        Must be called while holding ``self._lock``.
        """
        total = sum(e.size_bytes for e in self._entries.values())
        while total > self._max_bytes and self._entries:
            # Find LRU entry
            lru_path = min(self._entries, key=lambda p: self._entries[p].last_accessed)
            removed = self._entries.pop(lru_path)
            total -= removed.size_bytes
            self._eviction_count += 1
            logger.debug(
                "ParseTreeCache: LRU-evicted %s (freed %d bytes)",
                lru_path,
                removed.size_bytes,
            )
