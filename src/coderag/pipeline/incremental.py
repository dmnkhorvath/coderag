"""Incremental parsing orchestrator — AST Incremental Parsing v2.

Coordinates :class:`ParseTreeCache` and :class:`EditComputer` to perform
tree-sitter incremental re-parsing when source files change.  Phase 1
(MVP) still does full extraction after the incremental re-parse; the
speedup comes from ``parser.parse(new_src, old_tree)`` being
significantly faster than a cold parse.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from coderag.core.models import ExtractionResult
from coderag.pipeline.edit_computer import EditComputer
from coderag.pipeline.parse_cache import ParseTreeCache

if TYPE_CHECKING:
    from coderag.core.config import CodeGraphConfig
    from coderag.core.registry import PluginRegistry
    from coderag.pipeline.events import EventEmitter
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Threshold: if total edit bytes exceed this fraction of file size,
# fall back to a full parse instead of incremental.
_INCREMENTAL_THRESHOLD = 0.50


@dataclass(slots=True)
class IncrementalSummary:
    """Statistics from an incremental processing run."""

    files_incremental: int = 0
    files_full: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_time_ms: float = 0.0


class IncrementalOrchestrator:
    """Orchestrate incremental re-parsing using cached parse trees.

    Parameters:
        config: Project configuration.
        registry: Plugin registry for looking up extractors.
        store: Graph store for persisting results.
        emitter: Optional event emitter.
        cache: Optional pre-existing :class:`ParseTreeCache`.
    """

    def __init__(
        self,
        config: CodeGraphConfig,
        registry: PluginRegistry,
        store: SQLiteStore,
        emitter: EventEmitter | None = None,
        cache: ParseTreeCache | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._store = store
        self._emitter = emitter
        self._cache = cache or ParseTreeCache()

    @property
    def cache(self) -> ParseTreeCache:
        """Return the underlying parse-tree cache."""
        return self._cache

    # -- public API ----------------------------------------------------------

    def process_changes(
        self,
        changed_files: dict[str, bytes],
        deleted_files: set[str] | None = None,
    ) -> IncrementalSummary:
        """Process a batch of file changes incrementally.

        Args:
            changed_files: Mapping of file path → new source bytes.
            deleted_files: Set of file paths that were deleted.

        Returns:
            :class:`IncrementalSummary` with processing statistics.
        """
        t0 = time.monotonic()
        summary = IncrementalSummary()
        deleted_files = deleted_files or set()

        # Handle deletions
        for path in deleted_files:
            self._cache.evict(path)
            summary.files_deleted += 1
            logger.debug("Incremental: deleted %s", path)

        # Process changed files
        results: dict[str, ExtractionResult] = {}
        for path, content in changed_files.items():
            content_hash = hashlib.sha256(content).hexdigest()

            # Check cache for existing tree
            cached = self._cache.get(path)
            if cached is not None:
                summary.cache_hits += 1
                # Skip if content hasn't actually changed
                if cached.content_hash == content_hash:
                    summary.files_skipped += 1
                    logger.debug("Incremental: skipped %s (unchanged)", path)
                    continue

                # Try incremental extraction
                result = self._incremental_extract(
                    path,
                    cached,
                    content,
                    content_hash,
                )
                if result is not None:
                    results[path] = result
                    summary.files_incremental += 1
                    continue
                # Fall through to full extract if incremental failed
            else:
                summary.cache_misses += 1

            # Full extraction
            result = self._full_extract(path, content, content_hash)
            if result is not None:
                results[path] = result
                summary.files_full += 1
            else:
                logger.warning("Incremental: no plugin for %s", path)

        # Persist results
        if results:
            self._persist_results(results)

        summary.total_time_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Incremental: %d incremental, %d full, %d skipped, %d deleted in %.1f ms",
            summary.files_incremental,
            summary.files_full,
            summary.files_skipped,
            summary.files_deleted,
            summary.total_time_ms,
        )
        return summary

    def warm_cache(self, project_root: str) -> int:
        """Pre-populate the cache by parsing all project files.

        Typically called after the first full pipeline run to seed the
        cache so that subsequent incremental runs benefit from
        ``parser.parse(new_src, old_tree)``.

        Returns:
            Number of files cached.
        """
        count = 0
        for plugin in self._registry.get_all_plugins():
            extractor = plugin.get_extractor()
            parser = getattr(extractor, "_parser", None)
            if parser is None:
                continue

            for ext in plugin.file_extensions:
                for dirpath, _dirnames, filenames in os.walk(project_root):
                    for fname in filenames:
                        if not fname.endswith(ext):
                            continue
                        abs_path = os.path.join(dirpath, fname)
                        try:
                            with open(abs_path, "rb") as f:
                                source = f.read()
                            tree = parser.parse(source)
                            content_hash = hashlib.sha256(source).hexdigest()
                            self._cache.put(
                                abs_path,
                                tree,
                                source,
                                content_hash,
                                plugin.name,
                            )
                            count += 1
                        except Exception:
                            logger.debug(
                                "warm_cache: failed to parse %s",
                                abs_path,
                                exc_info=True,
                            )
        logger.info("warm_cache: cached %d files", count)
        return count

    # -- internals -----------------------------------------------------------

    def _incremental_extract(
        self,
        path: str,
        cached: Any,  # CachedTree
        new_content: bytes,
        content_hash: str,
    ) -> ExtractionResult | None:
        """Attempt incremental re-parse using tree.edit().

        Returns ``None`` if incremental parsing is not feasible (e.g.
        edits exceed threshold) and the caller should fall back to full.
        """
        plugin = self._registry.get_plugin_for_file(path)
        if plugin is None:
            return None

        extractor = plugin.get_extractor()
        parser = getattr(extractor, "_parser", None)
        if parser is None:
            return None

        # Compute edits
        edits = EditComputer.compute_edits(cached.source, new_content)
        if not edits:
            # No real change detected by difflib
            self._cache.put(path, cached.tree, new_content, content_hash, cached.language)
            return None

        # Check threshold: if edits are too large, fall back to full
        total_edit_bytes = EditComputer.total_edit_bytes(edits)
        file_size = max(len(cached.source), len(new_content))
        if file_size > 0 and total_edit_bytes / file_size > _INCREMENTAL_THRESHOLD:
            logger.debug(
                "Incremental: edits too large for %s (%.0f%%), falling back to full",
                path,
                (total_edit_bytes / file_size) * 100,
            )
            return None

        try:
            # Copy the cached tree and apply edits
            old_tree = cached.tree.copy()
            EditComputer.apply_edits(old_tree, edits)

            # Incremental re-parse
            new_tree = parser.parse(new_content, old_tree)

            # Log changed ranges (for future use in Phase 4)
            try:
                changed_ranges = old_tree.changed_ranges(new_tree)
                logger.debug(
                    "Incremental: %s — %d changed range(s)",
                    path,
                    len(changed_ranges),
                )
            except Exception:
                logger.debug(
                    "Incremental: changed_ranges unavailable for %s",
                    path,
                )

            # Update cache with new tree
            self._cache.put(path, new_tree, new_content, content_hash, cached.language)

            # Phase 1 MVP: still do full extraction on the new source
            result = extractor.extract(path, new_content)
            return result

        except Exception:
            logger.warning(
                "Incremental: incremental parse failed for %s, falling back",
                path,
                exc_info=True,
            )
            return None

    def _full_extract(
        self,
        path: str,
        content: bytes,
        content_hash: str,
    ) -> ExtractionResult | None:
        """Perform a standard full parse and cache the result."""
        plugin = self._registry.get_plugin_for_file(path)
        if plugin is None:
            return None

        extractor = plugin.get_extractor()
        result = extractor.extract(path, content)

        # Cache the tree for future incremental use
        parser = getattr(extractor, "_parser", None)
        if parser is not None:
            try:
                tree = parser.parse(content)
                self._cache.put(path, tree, content, content_hash, plugin.name)
            except Exception:
                logger.debug(
                    "full_extract: failed to cache tree for %s",
                    path,
                    exc_info=True,
                )

        return result

    def _persist_results(self, results: dict[str, ExtractionResult]) -> None:
        """Persist extraction results to the store."""
        for path, result in results.items():
            try:
                # Remove old data for this file
                self._store.delete_nodes_for_file(path)
                # Store new nodes and edges
                for node in result.nodes:
                    self._store.upsert_node(node)
                for edge in result.edges:
                    self._store.upsert_edge(edge)
                # Update file hash
                if result.nodes:
                    content_hash = result.nodes[0].content_hash or ""
                    self._store.set_file_hash(path, content_hash)
            except Exception:
                logger.exception("Failed to persist results for %s", path)
