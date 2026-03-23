"""Pipeline orchestrator — runs the extraction pipeline.

Implements phases 1-6 + 8:
  Phase 1: Discovery (FileScanner)
  Phase 2: Hash & diff (incremental)
  Phase 3: Extract (run plugin extractors)
  Phase 4: Resolve (resolve cross-file references into edges)
  Phase 5: Framework detection (run framework detectors)
  Phase 6: Cross-language matching (match API endpoints to calls)
  Phase 7: Enrichment (git metadata, metrics)
  Phase 8: Persist (store in SQLite)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any

from coderag.core.config import CodeGraphConfig
from coderag.core.models import (
    ExtractionResult,
    FileInfo,
    NodeKind,
    PipelineSummary,
)
from coderag.core.registry import FrameworkDetector, PluginRegistry
from coderag.pipeline.events import (
    EventEmitter,
    FileCompleted,
    FileError,
    PhaseCompleted,
    PhaseProgress,
    PhaseStarted,
    PipelinePhase,
    PipelineStarted,
)
from coderag.pipeline.events import (
    PipelineCompleted as PipelineCompletedEvent,
)
from coderag.pipeline.resolver import ReferenceResolver
from coderag.pipeline.scanner import FileScanner
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


# =============================================================================
# MODULE-LEVEL WORKER FUNCTIONS (for ProcessPoolExecutor pickling)
# =============================================================================

_worker_registry: PluginRegistry | None = None


def _init_extraction_worker() -> None:
    """Initialize plugin registry in each worker process.

    Called once per worker by ProcessPoolExecutor's initializer.
    """
    global _worker_registry
    _worker_registry = PluginRegistry()
    _worker_registry.discover_builtin_plugins()


def _extract_worker(file_path: str) -> tuple[str, ExtractionResult | None, str | None, str | None]:
    """Extract a single file in a worker process.

    Must be a top-level function for ProcessPoolExecutor pickling.

    Args:
        file_path: Absolute path to the file to extract.

    Returns:
        Tuple of (file_path, result, plugin_name, error_string).
    """
    global _worker_registry
    if _worker_registry is None:
        _init_extraction_worker()

    plugin = _worker_registry.get_plugin_for_file(file_path)
    if plugin is None:
        return file_path, None, None, None
    try:
        with open(file_path, "rb") as f:
            source = f.read()
        extractor = plugin.get_extractor()
        result = extractor.extract(file_path, source)
        return file_path, result, plugin.name, None
    except Exception as exc:
        return file_path, None, None, str(exc)


class PipelineOrchestrator:
    """Orchestrate the multi-phase extraction pipeline."""

    def __init__(
        self,
        config: CodeGraphConfig,
        registry: PluginRegistry,
        store: SQLiteStore,
        emitter: EventEmitter | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._store = store
        self._emitter = emitter

    def _emit(self, event) -> None:
        """Emit an event if an emitter is configured."""
        if self._emitter is not None:
            self._emitter.emit(event)

    def run(
        self,
        project_root: str,
        incremental: bool = True,
    ) -> PipelineSummary:
        """Execute the full pipeline on *project_root*."""
        t0 = time.perf_counter()
        logger.info("Pipeline starting on %s (incremental=%s)", project_root, incremental)
        self._emit(PipelineStarted(project_root=project_root))

        # Collect all extensions from registered plugins
        all_extensions: set[str] = set()
        for plugin in self._registry.get_all_plugins():
            all_extensions.update(plugin.file_extensions)

        # ── Phase 1: Discovery ────────────────────────────────
        logger.info("Phase 1: Discovering files...")
        self._emit(PhaseStarted(phase=PipelinePhase.DISCOVERY))
        scanner = FileScanner(
            project_root=project_root,
            extensions=all_extensions,
            ignore_patterns=self._config.ignore_patterns,
        )

        # ── Phase 2: Hash & diff ──────────────────────────────
        logger.info("Phase 2: Computing hashes...")
        self._emit(PhaseStarted(phase=PipelinePhase.HASHING))
        if incremental:
            files = scanner.scan_incremental(self._store.get_file_hash)
        else:
            files = scanner.scan()

        total_files = len(files)
        changed_files = [f for f in files if f.is_changed]
        skipped = total_files - len(changed_files)
        logger.info("Found %d files, %d changed, %d skipped", total_files, len(changed_files), skipped)
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.DISCOVERY,
                summary={"total_files": total_files},
            )
        )
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.HASHING,
                summary={"changed": len(changed_files), "skipped": skipped},
            )
        )

        # ── Phase 3: Extract (parallel) ───────────────────────
        logger.info("Phase 3: Extracting ASTs (parallel)...")
        self._emit(
            PhaseStarted(
                phase=PipelinePhase.EXTRACTION,
                total_items=len(changed_files),
            )
        )
        total_nodes = 0
        total_edges = 0
        files_parsed = 0
        files_errored = 0
        all_results: list[ExtractionResult] = []
        parse_time_ms = 0.0

        # Build a lookup from file_path -> FileInfo for persistence
        fi_lookup = {fi.path: fi for fi in changed_files}
        perf = self._config.perf_config
        batch_size = perf.batch_size
        extraction_workers = min(
            perf.resolved_extraction_workers,
            max(1, len(changed_files)),
        )

        def _extract_single_thread(fi: FileInfo) -> tuple[FileInfo, ExtractionResult | None, str | None, str | None]:
            """Fallback extraction using ThreadPoolExecutor."""
            plugin = self._registry.get_plugin_for_file(fi.path)
            if plugin is None:
                return fi, None, None, None
            try:
                source = self._read_file(fi.path)
                extractor = plugin.get_extractor()
                result = extractor.extract(fi.path, source)
                return fi, result, plugin.name, None
            except Exception as exc:
                return fi, None, None, str(exc)

        def _process_extraction_result(
            file_path: str,
            result: ExtractionResult | None,
            plugin_name: str | None,
            error: str | None,
        ) -> None:
            """Process a single extraction result (shared by both executors)."""
            nonlocal total_nodes, total_edges, files_parsed, files_errored, parse_time_ms

            if error:
                logger.error("Failed to process %s: %s", file_path, error)
                files_errored += 1
                self._emit(
                    FileError(
                        phase=PipelinePhase.EXTRACTION,
                        file_path=file_path,
                        error=error or "unknown error",
                    )
                )
                return
            if result is None:
                return

            all_results.append(result)
            n_nodes = len(result.nodes)
            n_edges = len(result.edges)
            total_nodes += n_nodes
            total_edges += n_edges
            parse_time_ms += result.parse_time_ms
            files_parsed += 1

            self._emit(
                FileCompleted(
                    phase=PipelinePhase.EXTRACTION,
                    file_path=file_path,
                    language=result.language,
                    nodes_count=n_nodes,
                    edges_count=n_edges,
                    duration_ms=result.parse_time_ms,
                )
            )
            self._emit(
                PhaseProgress(
                    phase=PipelinePhase.EXTRACTION,
                    current=files_parsed,
                    total=len(changed_files),
                    message=f"Parsed {file_path}",
                    file_path=file_path,
                )
            )

            if result.errors:
                for err in result.errors:
                    logger.warning(
                        "%s:%s: %s",
                        err.file_path,
                        err.line_number,
                        err.message,
                    )

            # ── Phase 8a: Persist nodes & containment edges ──
            fi = fi_lookup.get(file_path)
            if fi and plugin_name:
                self._persist_result(result, fi, plugin_name)

        # Try ProcessPoolExecutor first (CPU-bound tree-sitter parsing)
        use_process_pool = extraction_workers > 1 and len(changed_files) > 1

        if use_process_pool:
            try:
                logger.info(
                    "Phase 3: Using ProcessPoolExecutor with %d workers, batch_size=%d",
                    extraction_workers,
                    batch_size,
                )
                # Process files in chunks to bound memory
                for chunk_start in range(0, len(changed_files), batch_size):
                    chunk = changed_files[chunk_start : chunk_start + batch_size]
                    file_paths = [fi.path for fi in chunk]

                    with ProcessPoolExecutor(
                        max_workers=extraction_workers,
                        initializer=_init_extraction_worker,
                    ) as executor:
                        futures = {executor.submit(_extract_worker, fp): fp for fp in file_paths}
                        for future in as_completed(futures):
                            file_path, result, plugin_name, error = future.result()
                            _process_extraction_result(
                                file_path,
                                result,
                                plugin_name,
                                error,
                            )

                logger.debug("ProcessPoolExecutor extraction completed successfully.")

            except (OSError, RuntimeError, BrokenPipeError) as exc:
                # Fall back to ThreadPoolExecutor if ProcessPool fails
                logger.warning(
                    "ProcessPoolExecutor failed (%s), falling back to ThreadPoolExecutor.",
                    exc,
                )
                use_process_pool = False

        if not use_process_pool:
            # Fallback: ThreadPoolExecutor (also used for single-file case)
            logger.info(
                "Phase 3: Using ThreadPoolExecutor with %d workers",
                extraction_workers,
            )
            with ThreadPoolExecutor(max_workers=extraction_workers) as executor:
                futures = {executor.submit(_extract_single_thread, fi): fi for fi in changed_files}
                for future in as_completed(futures):
                    fi, result, plugin_name, error = future.result()
                    _process_extraction_result(
                        fi.path,
                        result,
                        plugin_name,
                        error,
                    )

        logger.info(
            "Phase 3 complete: %d files parsed, %d errors, %d nodes, %d edges in %.1fms",
            files_parsed,
            files_errored,
            total_nodes,
            total_edges,
            parse_time_ms,
        )
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.EXTRACTION,
                summary={"parsed": files_parsed, "errors": files_errored, "nodes": total_nodes, "edges": total_edges},
                duration_ms=parse_time_ms,
            )
        )

        # ── Phase 4: Reference Resolution (parallel) ─────────
        self._emit(PhaseStarted(phase=PipelinePhase.RESOLUTION))
        resolved_edge_count = 0
        unresolved_edge_count = 0
        total_unresolved_refs = sum(len(r.unresolved_references) for r in all_results)

        if total_unresolved_refs > 0:
            logger.info(
                "Phase 4: Resolving %d cross-file references (parallel)...",
                total_unresolved_refs,
            )
            resolver = ReferenceResolver(self._store)
            resolver.build_symbol_table()

            # Parallel resolution: group refs by result and resolve in threads
            io_workers = self._config.perf_config.resolved_io_workers
            if total_unresolved_refs > 50 and len(all_results) > 1:
                resolved_edges, placeholder_nodes, resolved_count, unresolved_count = self._parallel_resolve(
                    resolver, all_results, io_workers
                )
            else:
                resolved_edges, placeholder_nodes, resolved_count, unresolved_count = resolver.resolve(all_results)

            resolved_edge_count = resolved_count
            unresolved_edge_count = unresolved_count

            # Persist placeholder nodes for external references
            if placeholder_nodes:
                logger.info("Persisting %d placeholder nodes for external refs", len(placeholder_nodes))
                self._store.upsert_nodes(placeholder_nodes)

            # Persist resolved edges
            if resolved_edges:
                logger.info("Persisting %d resolved edges", len(resolved_edges))
                self._store.upsert_edges(resolved_edges)
                total_edges += len(resolved_edges)

            logger.info(
                "Phase 4 complete: %d resolved, %d unresolved (of %d total refs)",
                resolved_count,
                unresolved_count,
                total_unresolved_refs,
            )
        else:
            logger.info("Phase 4: No unresolved references to process.")
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.RESOLUTION,
                summary={"resolved": resolved_edge_count, "unresolved": unresolved_edge_count},
            )
        )

        # ── Phase 5: Framework Detection ──────────────────────
        self._emit(PhaseStarted(phase=PipelinePhase.FRAMEWORK_DETECTION))
        fw_nodes, fw_edges = self._run_framework_detection(project_root)
        if fw_nodes or fw_edges:
            total_nodes += fw_nodes
            total_edges += fw_edges
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.FRAMEWORK_DETECTION,
                summary={"nodes": fw_nodes, "edges": fw_edges},
            )
        )

        # ── Phase 6: Cross-Language Matching ───────────────────
        self._emit(PhaseStarted(phase=PipelinePhase.CROSS_LANGUAGE))
        xl_edges = self._run_cross_language_matching(project_root)
        if xl_edges:
            total_edges += xl_edges
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.CROSS_LANGUAGE,
                summary={"edges": xl_edges or 0},
            )
        )

        # ── Phase 6b: Style Edge Matching ─────────────────────
        self._emit(PhaseStarted(phase=PipelinePhase.STYLE_MATCHING))
        style_edges = self._run_style_edge_matching(project_root)
        if style_edges:
            total_edges += style_edges
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.STYLE_MATCHING,
                summary={"edges": style_edges or 0},
            )
        )

        # ── Phase 7: Git Enrichment ────────────────────────────
        self._emit(PhaseStarted(phase=PipelinePhase.GIT_ENRICHMENT))
        git_enrichment_stats = self._run_git_enrichment(project_root)
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.GIT_ENRICHMENT,
                summary=git_enrichment_stats,
            )
        )

        # ── Phase 7b: PHPStan Enrichment (optional) ───────────
        self._run_phpstan_enrichment(project_root)

        # ── Phase 9: Persist graph analysis scores ────────────
        try:
            from coderag.analysis.networkx_analyzer import NetworkXAnalyzer

            analyzer = NetworkXAnalyzer()
            analyzer.load_from_store(self._store)
            analyzer.persist_scores_to_store(self._store)
            logger.info("Phase 9: Persisted PageRank and community scores")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Phase 9: Graph analysis persist failed: %s", exc)

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
            "Pipeline complete: %d files, %d nodes, %d edges (%d resolved, %d unresolved) in %.1fs",
            files_parsed,
            total_nodes,
            total_edges,
            resolved_edge_count,
            unresolved_edge_count,
            elapsed,
        )
        self._emit(
            PipelineCompletedEvent(
                total_files=files_parsed,
                total_nodes=total_nodes,
                total_edges=total_edges,
                total_errors=files_errored,
                duration_s=elapsed,
            )
        )
        return summary

    # ── Phase 4: Parallel Reference Resolution ────────────

    def _parallel_resolve(
        self,
        resolver: ReferenceResolver,
        all_results: list,
        max_workers: int,
    ) -> tuple:
        """Resolve references in parallel using ThreadPoolExecutor.

        Groups extraction results into chunks and resolves each chunk
        in a separate thread.  The resolver's symbol table is read-only
        after build_symbol_table(), so concurrent reads are safe.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        resolved_edges: list = []
        placeholder_nodes: list = []
        resolved_count = 0
        unresolved_count = 0

        if not all_results:
            return resolved_edges, placeholder_nodes, resolved_count, unresolved_count

        # Chunk results for parallel processing
        chunk_size = max(1, len(all_results) // max_workers)
        chunks = [all_results[i : i + chunk_size] for i in range(0, len(all_results), chunk_size)]

        def _resolve_chunk(chunk):
            return resolver.resolve(chunk)

        with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as pool:
            futures = {pool.submit(_resolve_chunk, chunk): i for i, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                try:
                    edges, placeholders, res_count, unres_count = future.result()
                    resolved_edges.extend(edges)
                    placeholder_nodes.extend(placeholders)
                    resolved_count += res_count
                    unresolved_count += unres_count
                except Exception as exc:
                    logger.error("Parallel resolution chunk failed: %s", exc)

        return resolved_edges, placeholder_nodes, resolved_count, unresolved_count

    def _run_style_edge_matching(self, project_root: str) -> int:
        """Run style edge matching to connect JS/TS components to CSS/SCSS.

        Returns:
            Number of style edges added.
        """
        logger.info("Phase 6b: Style edge matching...")
        t0 = time.perf_counter()

        try:
            from coderag.pipeline.style_edges import StyleEdgeMatcher
        except ImportError:
            logger.warning("Phase 6b: StyleEdgeMatcher not available.")
            return 0

        # Check if we have CSS/SCSS files in the project
        has_css = bool(
            self._store.find_nodes(
                kind=NodeKind.FILE,
                language="css",
                limit=1,
            )
        )
        has_scss = bool(
            self._store.find_nodes(
                kind=NodeKind.FILE,
                language="scss",
                limit=1,
            )
        )

        if not has_css and not has_scss:
            logger.info("Phase 6b: No CSS/SCSS files found, skipping.")
            return 0

        try:
            matcher = StyleEdgeMatcher(self._store, project_root)
            edge_count = matcher.match()
            elapsed = time.perf_counter() - t0
            logger.info(
                "Phase 6b complete: %d style edges in %.1fs",
                edge_count,
                elapsed,
            )
            return edge_count
        except Exception:
            logger.exception("Phase 6b: Style edge matching failed.")
            return 0

    # ── Phase 7: Git Enrichment ───────────────────────────

    def _run_git_enrichment(self, project_root: str) -> dict:
        """Run git metadata enrichment on the project.

        Analyzes git history to add change frequency, co-change,
        ownership, and churn metrics to the knowledge graph.

        Returns:
            Dict with enrichment statistics.
        """
        logger.info("Phase 7: Git enrichment...")
        t0 = time.perf_counter()
        stats = {
            "files_enriched": 0,
            "co_change_pairs": 0,
            "hot_files": 0,
            "total_authors": 0,
        }

        try:
            from coderag.enrichment.git_enricher import GitEnricher
        except ImportError:
            logger.warning("Phase 7: GitEnricher not available.")
            return stats

        # Check if project is a git repo
        import os

        if not os.path.isdir(os.path.join(project_root, ".git")):
            logger.info("Phase 7: Not a git repository, skipping.")
            return stats

        try:
            # Get known file paths from the store for filtering
            known_files = set()
            # Get all unique file paths from stored nodes (any kind)
            all_nodes = self._store.find_nodes(limit=200000)
            for node in all_nodes:
                if node.file_path:
                    rel = os.path.relpath(node.file_path, project_root)
                    known_files.add(rel)

            enricher = GitEnricher(
                repo_root=project_root,
                file_filter=known_files if known_files else None,
            )
            result = enricher.enrich_to_dicts()

            # Store per-file git metrics in node metadata
            file_metrics = result.get("file_metrics", {})
            enriched_count = 0

            # Parallel per-file git enrichment
            import threading as _threading

            _enrich_lock = _threading.Lock()

            def _enrich_file(rel_path, metrics):
                """Enrich a single file's nodes with git metrics (thread worker)."""
                abs_p = os.path.join(project_root, rel_path)
                fnodes = self._store.find_nodes(
                    file_path=abs_p,
                    limit=1000,
                )
                if not fnodes:
                    fnodes = self._store.find_nodes(
                        file_path=rel_path,
                        limit=1000,
                    )
                if fnodes:
                    for node in fnodes:
                        node.metadata["git"] = metrics
                    self._store.upsert_nodes(fnodes)
                    return 1
                return 0

            io_workers = self._config.perf_config.resolved_io_workers
            if len(file_metrics) > 10:
                with ThreadPoolExecutor(max_workers=io_workers) as pool:
                    futures = {pool.submit(_enrich_file, rp, m): rp for rp, m in file_metrics.items()}
                    for future in as_completed(futures):
                        try:
                            enriched_count += future.result()
                        except Exception as exc:
                            logger.debug("Git enrichment failed for %s: %s", futures[future], exc)
            else:
                for rel_path, metrics in file_metrics.items():
                    enriched_count += _enrich_file(rel_path, metrics)

            # Store co-change data as metadata
            co_changes = result.get("co_changes", [])
            if co_changes:
                import json

                self._store.set_metadata(
                    "git_co_changes",
                    json.dumps(co_changes[:100]),  # Top 100 pairs
                )

            # Store global git stats
            git_stats = result.get("stats", {})
            self._store.set_metadata(
                "git_total_commits",
                str(git_stats.get("total_commits_analyzed", 0)),
            )
            self._store.set_metadata(
                "git_total_authors",
                str(git_stats.get("total_authors", 0)),
            )
            self._store.set_metadata(
                "git_hot_files",
                str(git_stats.get("hot_files", 0)),
            )

            stats["files_enriched"] = enriched_count
            stats["co_change_pairs"] = len(co_changes)
            stats["hot_files"] = git_stats.get("hot_files", 0)
            stats["total_authors"] = git_stats.get("total_authors", 0)

            elapsed = time.perf_counter() - t0
            logger.info(
                "Phase 7 complete: %d files enriched, %d co-change pairs, %d hot files, %d authors in %.1fs",
                enriched_count,
                len(co_changes),
                stats["hot_files"],
                stats["total_authors"],
                elapsed,
            )

        except Exception as exc:
            logger.error("Phase 7 git enrichment failed: %s", exc)

        return stats

    # ── Phase 7b: PHPStan Enrichment ──────────────────────

    def _run_phpstan_enrichment(self, project_root: str) -> dict:
        """Run optional PHPStan type enrichment on PHP files.

        Checks if PHPStan is available and runs type analysis to
        enrich PHP nodes with type information. Gracefully skips
        if PHPStan is not installed.

        Returns:
            Dict with enrichment statistics.
        """
        stats: dict = {
            "files_analyzed": 0,
            "errors_found": 0,
            "nodes_enriched": 0,
            "skipped_reason": None,
        }

        try:
            from coderag.enrichment.phpstan import PHPStanEnricher
        except ImportError:
            logger.debug("PHPStan enrichment module not available.")
            stats["skipped_reason"] = "module_not_available"
            return stats

        try:
            enricher = PHPStanEnricher(project_root=project_root)

            if not enricher.is_available():
                logger.info("Phase 7b: PHPStan not available, skipping.")
                stats["skipped_reason"] = "phpstan_not_installed"
                return stats

            logger.info("Phase 7b: PHPStan enrichment (level %d)...", enricher.level)
            report = enricher.enrich_nodes(self._store)

            stats["files_analyzed"] = report.files_analyzed
            stats["errors_found"] = report.errors_found
            stats["nodes_enriched"] = report.nodes_enriched
            stats["duration_ms"] = report.duration_ms
            stats["phpstan_version"] = report.phpstan_version

            if report.skipped_reason:
                stats["skipped_reason"] = report.skipped_reason
                logger.info("Phase 7b: Skipped — %s", report.skipped_reason)
            else:
                logger.info(
                    "Phase 7b complete: %d files, %d errors, %d nodes enriched in %.1fms",
                    report.files_analyzed,
                    report.errors_found,
                    report.nodes_enriched,
                    report.duration_ms,
                )

        except Exception as exc:
            logger.error("Phase 7b PHPStan enrichment failed: %s", exc)
            stats["skipped_reason"] = f"error: {exc}"

        return stats

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
                    plugin.name,
                    exc,
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
                        det.framework_name,
                        plugin.name,
                    )
                    active_detectors.append((det, plugin))
            except Exception as exc:
                logger.warning(
                    "Framework detection failed for %s: %s",
                    det.framework_name,
                    exc,
                )

        if not active_detectors:
            logger.info("Phase 5: No frameworks detected in project.")
            return 0, 0

        total_fw_nodes = 0
        total_fw_edges = 0

        # ── Phase 5a: Per-file detection ──────────────────────
        # Get all files from the store grouped by language
        file_nodes = self._store.find_nodes(
            kind=None,
            limit=100000,
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

        # Process each file with active detectors (parallel)
        import os

        io_workers = self._config.perf_config.resolved_io_workers

        def _detect_file(det, plugin, file_path, nodes):
            """Run framework detection on a single file (thread worker)."""
            ext = os.path.splitext(file_path)[1]
            if ext not in plugin.file_extensions:
                return [], []
            abs_path = file_path
            if not os.path.isabs(file_path):
                abs_path = os.path.join(project_root, file_path)
            if not os.path.isfile(abs_path):
                return [], []
            try:
                source = self._read_file(abs_path)
                extractor = plugin.get_extractor()
                tree = None
                if hasattr(extractor, "_parser") and extractor._parser is not None:
                    tree = extractor._parser.parse(source)
                file_edges = file_edge_map.get(file_path, [])
                patterns = det.detect(
                    file_path=file_path,
                    tree=tree,
                    source=source,
                    nodes=nodes,
                    edges=file_edges,
                )
                result_nodes = []
                result_edges = []
                for pattern in patterns:
                    if pattern.nodes:
                        result_nodes.extend(pattern.nodes)
                    if pattern.edges:
                        result_edges.extend(pattern.edges)
                return result_nodes, result_edges
            except Exception as exc:
                logger.debug(
                    "Framework detection failed for %s in %s: %s",
                    det.framework_name,
                    file_path,
                    exc,
                )
                return [], []

        # Build work items
        work_items = []
        for det, plugin in active_detectors:
            for file_path, nodes in file_node_map.items():
                work_items.append((det, plugin, file_path, nodes))

        if len(work_items) > 10:
            # Parallel execution for large workloads
            with ThreadPoolExecutor(max_workers=io_workers) as pool:
                futures = [pool.submit(_detect_file, det, plugin, fp, nodes) for det, plugin, fp, nodes in work_items]
                for future in as_completed(futures):
                    try:
                        fw_n, fw_e = future.result()
                        if fw_n:
                            self._store.upsert_nodes(fw_n)
                            total_fw_nodes += len(fw_n)
                        if fw_e:
                            self._store.upsert_edges(fw_e)
                            total_fw_edges += len(fw_e)
                    except Exception as exc:
                        logger.debug("Parallel framework detection failed: %s", exc)
        else:
            # Sequential for small workloads
            for det, plugin, file_path, nodes in work_items:
                fw_n, fw_e = _detect_file(det, plugin, file_path, nodes)
                if fw_n:
                    self._store.upsert_nodes(fw_n)
                    total_fw_nodes += len(fw_n)
                if fw_e:
                    self._store.upsert_edges(fw_e)
                    total_fw_edges += len(fw_e)

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
                    det.framework_name,
                    exc,
                )

        elapsed = time.perf_counter() - t0
        logger.info(
            "Phase 5 complete: %d framework nodes, %d framework edges in %.1fs",
            total_fw_nodes,
            total_fw_edges,
            elapsed,
        )

        # Store detected frameworks as metadata (deduplicated)
        fw_names = list(dict.fromkeys(det.framework_name for det, _ in active_detectors))
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
        if hasattr(summary, "languages"):
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
            "Phase 6 complete: %d endpoints, %d API calls, %d matches, %d cross-language edges in %.1fs",
            len(endpoints),
            len(api_calls),
            len(matches),
            len(xl_edges),
            elapsed,
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
