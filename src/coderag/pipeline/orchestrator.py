"""Pipeline orchestrator — runs the extraction pipeline.

Implements phases 1-6 + 8:
  Phase 1: Discovery (FileScanner)
  Phase 2: Hash & diff (incremental)
  Phase 3: Extract (run plugin extractors)
  Phase 4: Resolve (resolve cross-file references into edges)
  Phase 5: Framework detection (run framework detectors)
  Phase 6: Cross-language matching (match API endpoints to calls)
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
from coderag.core.registry import FrameworkDetector, PluginRegistry
from coderag.pipeline.resolver import ReferenceResolver
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
        parse_time_ms = 0.0

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
                parse_time_ms += result.parse_time_ms
                files_parsed += 1

                if result.errors:
                    for err in result.errors:
                        logger.warning(
                            "%s:%s: %s",
                            err.file_path, err.line_number, err.message,
                        )

                # ── Phase 8a: Persist nodes & containment edges ──
                self._persist_result(result, fi, plugin.name)

            except Exception as exc:
                logger.error("Failed to process %s: %s", fi.path, exc)
                files_errored += 1

        # ── Phase 4: Reference Resolution ─────────────────────
        resolved_edge_count = 0
        unresolved_edge_count = 0
        total_unresolved_refs = sum(
            len(r.unresolved_references) for r in all_results
        )

        if total_unresolved_refs > 0:
            logger.info(
                "Phase 4: Resolving %d cross-file references...",
                total_unresolved_refs,
            )
            resolver = ReferenceResolver(self._store)
            resolver.build_symbol_table()

            resolved_edges, placeholder_nodes, resolved_count, unresolved_count = (
                resolver.resolve(all_results)
            )

            resolved_edge_count = resolved_count
            unresolved_edge_count = unresolved_count

            # Persist placeholder nodes for external references
            if placeholder_nodes:
                logger.info("Persisting %d placeholder nodes for external refs",
                            len(placeholder_nodes))
                self._store.upsert_nodes(placeholder_nodes)

            # Persist resolved edges
            if resolved_edges:
                logger.info("Persisting %d resolved edges", len(resolved_edges))
                self._store.upsert_edges(resolved_edges)
                total_edges += len(resolved_edges)

            logger.info(
                "Phase 4 complete: %d resolved, %d unresolved (of %d total refs)",
                resolved_count, unresolved_count, total_unresolved_refs,
            )
        else:
            logger.info("Phase 4: No unresolved references to process.")

        # ── Phase 5: Framework Detection ──────────────────────
        fw_nodes, fw_edges = self._run_framework_detection(project_root)
        if fw_nodes or fw_edges:
            total_nodes += fw_nodes
            total_edges += fw_edges

        # ── Phase 6: Cross-Language Matching ───────────────────
        xl_edges = self._run_cross_language_matching(project_root)
        if xl_edges:
            total_edges += xl_edges

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
            "Pipeline complete: %d files, %d nodes, %d edges "
            "(%d resolved, %d unresolved) in %.1fs",
            files_parsed, total_nodes, total_edges,
            resolved_edge_count, unresolved_edge_count, elapsed,
        )
        return summary

    # ── Phase 5: Framework Detection ──────────────────────────

    def _run_framework_detection(self, project_root: str) -> tuple[int, int]:
        """Run framework detectors on the project.

        Phase 5 has two sub-phases:
        5a. Per-file detection: re-read files, re-parse with tree-sitter,
            and run each active detector's detect() method.
        5b. Global detection: run each active detector's
            detect_global_patterns() method for cross-file patterns.

        Returns:
            Tuple of (nodes_added, edges_added).
        """
        logger.info("Phase 5: Framework detection...")
        t0 = time.perf_counter()

        # Collect all framework detectors from all plugins
        detectors: list[tuple[FrameworkDetector, Any]] = []  # (detector, plugin)
        for plugin in self._registry.get_all_plugins():
            try:
                plugin_detectors = plugin.get_framework_detectors()
                for det in plugin_detectors:
                    detectors.append((det, plugin))
            except Exception as exc:
                logger.warning(
                    "Failed to get framework detectors from %s: %s",
                    plugin.name, exc,
                )

        if not detectors:
            logger.info("Phase 5: No framework detectors registered.")
            return 0, 0

        # Determine which frameworks are active in this project
        active_detectors: list[tuple[FrameworkDetector, Any]] = []
        for det, plugin in detectors:
            try:
                if det.detect_framework(project_root):
                    logger.info(
                        "Phase 5: Detected framework '%s' (plugin: %s)",
                        det.framework_name, plugin.name,
                    )
                    active_detectors.append((det, plugin))
            except Exception as exc:
                logger.warning(
                    "Framework detection failed for %s: %s",
                    det.framework_name, exc,
                )

        if not active_detectors:
            logger.info("Phase 5: No frameworks detected in project.")
            return 0, 0

        total_fw_nodes = 0
        total_fw_edges = 0

        # ── Phase 5a: Per-file detection ──────────────────────
        # Get all files from the store grouped by language
        file_nodes = self._store.find_nodes(
            kind=None, limit=100000,
        )

        # Build a map of file_path -> nodes for that file
        from collections import defaultdict
        file_node_map: dict[str, list] = defaultdict(list)
        for node in file_nodes:
            if node.file_path:
                file_node_map[node.file_path].append(node)

        # Get all edges
        all_edges = self._store.get_edges()
        file_edge_map: dict[str, list] = defaultdict(list)
        for edge in all_edges:
            # Associate edge with source node's file
            for node in file_nodes:
                if node.id == edge.source_id and node.file_path:
                    file_edge_map[node.file_path].append(edge)
                    break

        # Process each file with active detectors
        import os
        processed_files = set()
        for det, plugin in active_detectors:
            for file_path, nodes in file_node_map.items():
                # Only process files matching this plugin's extensions
                ext = os.path.splitext(file_path)[1]
                if ext not in plugin.file_extensions:
                    continue

                abs_path = file_path
                if not os.path.isabs(file_path):
                    abs_path = os.path.join(project_root, file_path)

                if not os.path.isfile(abs_path):
                    continue

                try:
                    source = self._read_file(abs_path)
                    # Re-parse with tree-sitter
                    extractor = plugin.get_extractor()
                    tree = None
                    if hasattr(extractor, '_parser') and extractor._parser is not None:
                        tree = extractor._parser.parse(source)

                    file_edges = file_edge_map.get(file_path, [])
                    patterns = det.detect(
                        file_path=file_path,
                        tree=tree,
                        source=source,
                        nodes=nodes,
                        edges=file_edges,
                    )

                    for pattern in patterns:
                        if pattern.nodes:
                            self._store.upsert_nodes(pattern.nodes)
                            total_fw_nodes += len(pattern.nodes)
                        if pattern.edges:
                            self._store.upsert_edges(pattern.edges)
                            total_fw_edges += len(pattern.edges)

                except Exception as exc:
                    logger.debug(
                        "Framework detection failed for %s in %s: %s",
                        det.framework_name, file_path, exc,
                    )

        # ── Phase 5b: Global detection ────────────────────────
        for det, plugin in active_detectors:
            try:
                patterns = det.detect_global_patterns(self._store)
                for pattern in patterns:
                    if pattern.nodes:
                        self._store.upsert_nodes(pattern.nodes)
                        total_fw_nodes += len(pattern.nodes)
                    if pattern.edges:
                        self._store.upsert_edges(pattern.edges)
                        total_fw_edges += len(pattern.edges)
            except Exception as exc:
                logger.warning(
                    "Global framework detection failed for %s: %s",
                    det.framework_name, exc,
                )

        elapsed = time.perf_counter() - t0
        logger.info(
            "Phase 5 complete: %d framework nodes, %d framework edges in %.1fs",
            total_fw_nodes, total_fw_edges, elapsed,
        )

        # Store detected frameworks as metadata
        fw_names = [det.framework_name for det, _ in active_detectors]
        self._store.set_metadata("detected_frameworks", ",".join(fw_names))

        return total_fw_nodes, total_fw_edges

    # ── Phase 6: Cross-Language Matching ──────────────────────

    def _run_cross_language_matching(self, project_root: str) -> int:
        """Run cross-language matching to connect backend APIs to frontend calls.

        Returns:
            Number of cross-language edges added.
        """
        logger.info("Phase 6: Cross-language matching...")
        t0 = time.perf_counter()

        try:
            from coderag.pipeline.cross_language import CrossLanguageMatcher
        except ImportError:
            logger.warning("Phase 6: CrossLanguageMatcher not available.")
            return 0

        # Check if we have multiple languages in the project
        summary = self._store.get_summary()
        languages = set()
        if hasattr(summary, 'languages'):
            languages = summary.languages
        else:
            # Detect languages from file extensions in the store
            for plugin in self._registry.get_all_plugins():
                nodes = self._store.find_nodes(language=plugin.name, limit=1)
                if nodes:
                    languages.add(plugin.name)

        if len(languages) < 2:
            logger.info(
                "Phase 6: Only %d language(s) detected, skipping cross-language matching.",
                len(languages),
            )
            return 0

        # Load all nodes and edges from store
        all_nodes = self._store.find_nodes(limit=200000)
        all_edges = self._store.get_edges()

        matcher = CrossLanguageMatcher()

        # Collect endpoints (from ROUTE nodes)
        endpoints = matcher.collect_endpoints(all_nodes, all_edges)
        if not endpoints:
            logger.info("Phase 6: No API endpoints found.")
            return 0

        # Collect API calls (from JS/TS source files)
        api_calls = matcher.collect_api_calls(all_nodes, all_edges, project_root)
        if not api_calls:
            logger.info("Phase 6: No API calls found.")
            return 0

        # Match endpoints to calls
        matches = matcher.match(endpoints, api_calls)
        if not matches:
            logger.info("Phase 6: No cross-language matches found.")
            return 0

        # Create and persist edges
        xl_edges = matcher.create_edges(matches)
        if xl_edges:
            self._store.upsert_edges(xl_edges)

        elapsed = time.perf_counter() - t0
        logger.info(
            "Phase 6 complete: %d endpoints, %d API calls, %d matches, "
            "%d cross-language edges in %.1fs",
            len(endpoints), len(api_calls), len(matches),
            len(xl_edges), elapsed,
        )

        # Store cross-language stats as metadata
        self._store.set_metadata("cross_language_endpoints", str(len(endpoints)))
        self._store.set_metadata("cross_language_calls", str(len(api_calls)))
        self._store.set_metadata("cross_language_matches", str(len(matches)))

        return len(xl_edges)

    # ── Persistence helpers ───────────────────────────────────

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
