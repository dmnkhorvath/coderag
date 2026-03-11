"""Pipeline orchestrator — runs the extraction pipeline.

For P0, implements phases 1-3 + 8:
  Phase 1: Discovery (FileScanner)
  Phase 2: Hash & diff (incremental)
  Phase 3: Extract (run plugin extractors)
  Phase 8: Persist (store in SQLite)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from coderag.core.config import CodeGraphConfig
from coderag.core.models import (
    ExtractionResult,
    FileInfo,
    PipelineSummary,
)
from coderag.core.registry import PluginRegistry
from coderag.pipeline.scanner import FileScanner
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrate the multi-phase extraction pipeline."""

    def __init__(
        self,
        config: CodeGraphConfig,
        registry: PluginRegistry,
        store: SQLiteStore,
    ) -> None:
        self._config = config
        self._registry = registry
        self._store = store

    def run(
        self,
        project_root: str,
        incremental: bool = True,
    ) -> PipelineSummary:
        """Execute the full pipeline on *project_root*."""
        t0 = time.perf_counter()
        logger.info("Pipeline starting on %s (incremental=%s)", project_root, incremental)

        # Collect all extensions from registered plugins
        all_extensions: set[str] = set()
        for plugin in self._registry.get_all_plugins():
            all_extensions.update(plugin.file_extensions)

        # ── Phase 1: Discovery ────────────────────────────────
        logger.info("Phase 1: Discovering files...")
        scanner = FileScanner(
            project_root=project_root,
            extensions=all_extensions,
            ignore_patterns=self._config.ignore_patterns,
        )

        # ── Phase 2: Hash & diff ──────────────────────────────
        logger.info("Phase 2: Computing hashes...")
        if incremental:
            files = scanner.scan_incremental(self._store.get_file_hash)
        else:
            files = scanner.scan()

        total_files = len(files)
        changed_files = [f for f in files if f.is_changed]
        skipped = total_files - len(changed_files)
        logger.info("Found %d files, %d changed, %d skipped", total_files, len(changed_files), skipped)

        # ── Phase 3: Extract ──────────────────────────────────
        logger.info("Phase 3: Extracting ASTs...")
        total_nodes = 0
        total_edges = 0
        files_parsed = 0
        files_errored = 0
        all_results: list[ExtractionResult] = []

        for fi in changed_files:
            plugin = self._registry.get_plugin_for_file(fi.path)
            if plugin is None:
                logger.debug("No plugin for %s", fi.path)
                continue

            try:
                source = self._read_file(fi.path)
                extractor = plugin.get_extractor()
                result = extractor.extract(fi.path, source)
                all_results.append(result)

                n_nodes = len(result.nodes)
                n_edges = len(result.edges)
                total_nodes += n_nodes
                total_edges += n_edges
                files_parsed += 1

                if result.errors:
                    for err in result.errors:
                        logger.warning(
                            "%s:%s: %s",
                            err.file_path, err.line_number, err.message,
                        )

                # ── Phase 8: Persist ──────────────────────────
                self._persist_result(result, fi, plugin.name)

            except Exception as exc:
                logger.error("Failed to process %s: %s", fi.path, exc)
                files_errored += 1

        elapsed = time.perf_counter() - t0
        summary = PipelineSummary(
            total_files=total_files,
            files_parsed=files_parsed,
            files_skipped=skipped,
            files_errored=files_errored,
            total_nodes=total_nodes,
            total_edges=total_edges,
            total_pipeline_time_ms=elapsed * 1000,
        )
        logger.info(
            "Pipeline complete: %d files, %d nodes, %d edges in %.1fs",
            files_parsed, total_nodes, total_edges, elapsed,
        )
        return summary

    def _persist_result(
        self,
        result: ExtractionResult,
        fi: FileInfo,
        plugin_name: str,
    ) -> None:
        """Store extraction results in SQLite."""
        # Delete old data for this file
        self._store.delete_nodes_for_file(fi.path)

        # Insert nodes and edges
        if result.nodes:
            self._store.upsert_nodes(result.nodes)
        if result.edges:
            self._store.upsert_edges(result.edges)

        # Update file hash
        self._store.set_file_hash(
            file_path=fi.path,
            content_hash=fi.content_hash,
            language=result.language,
            plugin_name=plugin_name,
            node_count=len(result.nodes),
            edge_count=len(result.edges),
            parse_time_ms=result.parse_time_ms,
        )

    @staticmethod
    def _read_file(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()
