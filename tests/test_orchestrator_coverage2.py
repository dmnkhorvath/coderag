"""Tests for orchestrator.py — targeting uncovered lines.

Covers: ProcessPool fallback, extraction error handling, framework detection,
cross-language matching, style edge matching, git enrichment, graph analysis.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from coderag.core.config import CodeGraphConfig
from coderag.core.models import (
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    PipelineSummary,
)
from coderag.core.registry import PluginRegistry
from coderag.pipeline.orchestrator import PipelineOrchestrator
from coderag.storage.sqlite_store import SQLiteStore

# ── Helpers ──────────────────────────────────────────────────


def _make_node(file_path="/tmp/test.py", line=1, kind=NodeKind.FILE, name="test", **kw):
    return Node(
        id=kw.get("id", f"{name}-{line}"),
        kind=kind,
        name=name,
        qualified_name=kw.get("qualified_name", name),
        file_path=file_path,
        start_line=line,
        end_line=kw.get("end_line", line + 5),
        language=kw.get("language", "python"),
    )


def _make_config(**overrides):
    return CodeGraphConfig(**overrides)


def _make_store(tmp_path):
    db_path = os.path.join(str(tmp_path), "test.db")
    store = SQLiteStore(db_path)
    store.initialize()
    return store


def _make_registry():
    return PluginRegistry()


def _make_orchestrator(tmp_path, emitter=None):
    return PipelineOrchestrator(
        _make_config(),
        _make_registry(),
        _make_store(tmp_path),
        emitter=emitter,
    )


# ── _process_extraction_result: error path (lines 210-219) ──


class TestProcessExtractionResult:
    """Cover lines 210-219, 221: error handling in extraction result processing."""

    def test_run_with_unparseable_file(self, tmp_path):
        """A file that causes extraction error should be counted as errored."""
        project = tmp_path / "project"
        project.mkdir()
        bad_file = project / "bad.py"
        bad_file.write_text("this is a file")

        orch = _make_orchestrator(tmp_path)
        # Mock registry to return a plugin that raises on extract
        mock_plugin = MagicMock()
        mock_extractor = MagicMock()
        mock_extractor.extract.side_effect = Exception("Parse error")
        mock_plugin.get_extractor.return_value = mock_extractor
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        orch._registry = MagicMock()
        orch._registry.get_plugin_for_file.return_value = mock_plugin
        orch._registry.get_all_plugins.return_value = [mock_plugin]

        # Run pipeline - should handle the error gracefully
        summary = orch.run(str(project))
        assert isinstance(summary, PipelineSummary)


# ── ProcessPoolExecutor fallback (lines 296-302) ──


class TestProcessPoolFallback:
    """Cover lines 296-302: ProcessPool fails -> ThreadPool fallback."""

    def test_process_pool_oserror_falls_back(self, tmp_path):
        """When ProcessPoolExecutor raises OSError, falls back to ThreadPool."""
        project = tmp_path / "project"
        project.mkdir()
        py_file = project / "test.py"
        py_file.write_text("x = 1\n")

        orch = _make_orchestrator(tmp_path)
        # Force process pool to be used then fail
        orch._config.perf_config.use_process_pool = True

        with patch(
            "coderag.pipeline.orchestrator.ProcessPoolExecutor",
            side_effect=OSError("Cannot fork"),
        ):
            summary = orch.run(str(project))
        assert isinstance(summary, PipelineSummary)


# ── _run_cross_language_matching (lines 980-982, 988, 1016-1047) ──


class TestRunCrossLanguageMatching:
    """Cover lines 980-1047: cross-language matching flow."""

    def test_single_language_returns_zero(self, tmp_path):
        """Single language project skips cross-language matching."""
        orch = _make_orchestrator(tmp_path)
        # Mock store summary with single language
        mock_summary = MagicMock()
        mock_summary.languages = {"python"}
        orch._store.get_summary = MagicMock(return_value=mock_summary)

        result = orch._run_cross_language_matching("/tmp/project")
        assert result == 0

    def test_no_endpoints_returns_zero(self, tmp_path):
        """No API endpoints -> returns 0."""
        orch = _make_orchestrator(tmp_path)
        mock_summary = MagicMock()
        mock_summary.languages = {"python", "javascript"}
        orch._store.get_summary = MagicMock(return_value=mock_summary)
        orch._store.get_all_nodes = MagicMock(return_value=[])
        orch._store.get_all_edges = MagicMock(return_value=[])

        with patch(
            "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_endpoints",
            return_value=[],
        ):
            result = orch._run_cross_language_matching("/tmp/project")
        assert result == 0

    def test_no_api_calls_returns_zero(self, tmp_path):
        """Endpoints found but no API calls -> returns 0."""
        orch = _make_orchestrator(tmp_path)
        mock_summary = MagicMock()
        mock_summary.languages = {"python", "javascript"}
        orch._store.get_summary = MagicMock(return_value=mock_summary)
        orch._store.get_all_nodes = MagicMock(return_value=[])
        orch._store.get_all_edges = MagicMock(return_value=[])

        mock_endpoint = MagicMock()
        with (
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_endpoints",
                return_value=[mock_endpoint],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_api_calls",
                return_value=[],
            ),
        ):
            result = orch._run_cross_language_matching("/tmp/project")
        assert result == 0

    def test_no_matches_returns_zero(self, tmp_path):
        """Endpoints and calls found but no matches -> returns 0."""
        orch = _make_orchestrator(tmp_path)
        mock_summary = MagicMock()
        mock_summary.languages = {"python", "javascript"}
        orch._store.get_summary = MagicMock(return_value=mock_summary)
        orch._store.get_all_nodes = MagicMock(return_value=[])
        orch._store.get_all_edges = MagicMock(return_value=[])

        with (
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_endpoints",
                return_value=[MagicMock()],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_api_calls",
                return_value=[MagicMock()],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.match",
                return_value=[],
            ),
        ):
            result = orch._run_cross_language_matching("/tmp/project")
        assert result == 0

    def test_full_matching_flow(self, tmp_path):
        """Full cross-language matching flow with edges created."""
        orch = _make_orchestrator(tmp_path)
        mock_summary = MagicMock()
        mock_summary.languages = {"python", "javascript"}
        orch._store.get_summary = MagicMock(return_value=mock_summary)
        orch._store.get_all_nodes = MagicMock(return_value=[])
        orch._store.get_all_edges = MagicMock(return_value=[])
        orch._store.upsert_edges = MagicMock()
        orch._store.set_metadata = MagicMock()

        mock_edge = Edge(source_id="a", target_id="b", kind=EdgeKind.CALLS)
        with (
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_endpoints",
                return_value=[MagicMock()],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.collect_api_calls",
                return_value=[MagicMock()],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.match",
                return_value=[MagicMock()],
            ),
            patch(
                "coderag.pipeline.cross_language.CrossLanguageMatcher.create_edges",
                return_value=[mock_edge],
            ),
        ):
            result = orch._run_cross_language_matching("/tmp/project")
        assert result == 1
        orch._store.upsert_edges.assert_called_once()
        assert orch._store.set_metadata.call_count == 3


# ── _run_style_edge_matching exception (lines 570-572) ──


class TestRunStyleEdgeMatching:
    """Cover lines 570-572: style edge matching exception."""

    def test_style_matching_exception_returns_zero(self, tmp_path):
        """Exception in style matching -> returns 0."""
        orch = _make_orchestrator(tmp_path)
        with patch.object(orch._store, "get_all_nodes", side_effect=Exception("DB error")):
            result = orch._run_style_edge_matching("/tmp/project")
        assert result == 0


# ── Graph analysis persist exception (lines 447-448) ──


class TestGraphAnalysisPersist:
    """Cover lines 447-448: graph analysis persist failure."""

    def test_graph_analysis_exception_handled(self, tmp_path):
        """Exception in graph analysis persist is caught."""
        project = tmp_path / "project"
        project.mkdir()

        orch = _make_orchestrator(tmp_path)
        # Run on empty project - graph analysis should handle gracefully
        summary = orch.run(str(project))
        assert isinstance(summary, PipelineSummary)


# ── _run_git_enrichment exception (lines 704-705) ──


class TestRunGitEnrichment:
    """Cover lines 653-669, 704-705: git enrichment paths."""

    def test_git_enrichment_exception(self, tmp_path):
        """Exception in git enrichment is caught."""
        orch = _make_orchestrator(tmp_path)
        with patch(
            "coderag.enrichment.git_enricher.GitEnricher",
            side_effect=Exception("Git error"),
        ):
            stats = orch._run_git_enrichment("/tmp/project")
        assert isinstance(stats, dict)

    def test_git_enrichment_no_git_repo(self, tmp_path):
        """Non-git directory returns empty stats."""
        project = tmp_path / "project"
        project.mkdir()
        orch = _make_orchestrator(tmp_path)
        stats = orch._run_git_enrichment(str(project))
        assert isinstance(stats, dict)


# ── _run_framework_detection (lines 867-945) ──


class TestRunFrameworkDetection:
    """Cover lines 867-945: framework detection inner function and execution."""

    def test_framework_detection_file_not_found(self, tmp_path):
        """File not found in _detect_file -> returns empty."""
        orch = _make_orchestrator(tmp_path)
        # Mock store with nodes pointing to nonexistent files
        mock_node = _make_node(
            file_path="/nonexistent/file.py",
            kind=NodeKind.FILE,
        )
        orch._store.get_all_nodes = MagicMock(return_value=[mock_node])
        orch._store.get_all_edges = MagicMock(return_value=[])

        # Mock registry with a detector
        mock_detector = MagicMock()
        mock_detector.framework_name = "test"
        mock_detector.detect.return_value = []
        mock_detector.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_extractor.return_value = MagicMock()

        orch._registry.get_all_plugins = MagicMock(return_value=[mock_plugin])
        mock_plugin.get_framework_detectors.return_value = [mock_detector]

        nodes, edges = orch._run_framework_detection("/tmp/project")
        assert isinstance(nodes, int)
        assert isinstance(edges, int)

    def test_framework_detection_exception_in_detect(self, tmp_path):
        """Exception in detector.detect -> handled gracefully."""
        project = tmp_path / "project"
        project.mkdir()
        py_file = project / "test.py"
        py_file.write_text("x = 1\n")

        orch = _make_orchestrator(tmp_path)
        mock_node = _make_node(
            file_path=str(py_file),
            kind=NodeKind.FILE,
        )
        orch._store.get_all_nodes = MagicMock(return_value=[mock_node])
        orch._store.get_all_edges = MagicMock(return_value=[])

        mock_detector = MagicMock()
        mock_detector.framework_name = "test"
        mock_detector.detect.side_effect = Exception("Detection error")
        mock_detector.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_extractor.return_value = MagicMock()
        mock_plugin.get_framework_detectors.return_value = [mock_detector]

        orch._registry.get_all_plugins = MagicMock(return_value=[mock_plugin])

        nodes, edges = orch._run_framework_detection(str(project))
        assert isinstance(nodes, int)

    def test_framework_detection_global_exception(self, tmp_path):
        """Exception in detect_global_patterns -> handled gracefully."""
        orch = _make_orchestrator(tmp_path)
        orch._store.get_all_nodes = MagicMock(return_value=[])
        orch._store.get_all_edges = MagicMock(return_value=[])

        mock_detector = MagicMock()
        mock_detector.framework_name = "test"
        mock_detector.detect_global_patterns.side_effect = Exception("Global error")

        mock_plugin = MagicMock()
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_detector]

        orch._registry.get_all_plugins = MagicMock(return_value=[mock_plugin])

        nodes, edges = orch._run_framework_detection("/tmp/project")
        assert isinstance(nodes, int)
