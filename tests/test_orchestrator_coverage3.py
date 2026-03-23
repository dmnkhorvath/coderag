"""Additional orchestrator tests — targeting remaining uncovered lines.

Covers: _run_framework_detection inner function, parallel/sequential execution,
global detection, git enrichment parallel paths, style edge exception,
cross-language matching, and various run() method paths.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from concurrent.futures import Future
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

from coderag.core.config import CodeGraphConfig
from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionResult,
    FileInfo,
    Node,
    NodeKind,
    PipelineSummary,
)
from coderag.core.registry import PluginRegistry
from coderag.pipeline.events import (
    EventEmitter,
    FileError,
    PhaseCompleted,
    PhaseProgress,
    PhaseStarted,
    PipelinePhase,
)
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


def _make_store(tmp_path):
    db_path = os.path.join(str(tmp_path), "test.db")
    store = SQLiteStore(db_path)
    store.initialize()
    return store


def _make_orchestrator(tmp_path, emitter=None, config=None):
    return PipelineOrchestrator(
        config or CodeGraphConfig(),
        PluginRegistry(),
        _make_store(tmp_path),
        emitter=emitter,
    )


# ── _run_style_edge_matching: exception path (lines 570-572) ──


class TestStyleEdgeMatchingException:
    """Cover lines 570-572: StyleEdgeMatcher.match() raises exception."""

    def test_style_edge_matcher_exception(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        # Insert CSS file nodes so the has_css check passes
        css_node = _make_node(
            file_path="style.css", kind=NodeKind.FILE, name="style.css",
            language="css", id="css-1",
        )
        orch._store.upsert_nodes([css_node])

        mock_matcher = MagicMock()
        mock_matcher.match.side_effect = RuntimeError("Style matching failed")

        with patch(
            "coderag.pipeline.style_edges.StyleEdgeMatcher",
            return_value=mock_matcher,
        ) as mock_cls:
            result = orch._run_style_edge_matching("/tmp/project")

        assert result == 0


# ── _run_git_enrichment: parallel path (lines 653-659, 667-669, 704-705) ──


class TestGitEnrichmentParallel:
    """Cover git enrichment parallel execution with >10 files."""

    def test_git_enrichment_parallel_many_files(self, tmp_path):
        """When file_metrics has >10 entries, use ThreadPoolExecutor."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        # Create .git directory
        os.makedirs(os.path.join(project_root, ".git"))

        # Insert nodes for many files
        nodes = []
        for i in range(15):
            n = _make_node(
                file_path=f"src/file_{i}.py",
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                id=f"func-{i}",
                language="python",
            )
            nodes.append(n)
        orch._store.upsert_nodes(nodes)

        # Mock GitEnricher to return many file_metrics
        file_metrics = {f"src/file_{i}.py": {"commit_count": i + 1} for i in range(15)}
        mock_result = {
            "file_metrics": file_metrics,
            "co_changes": [
                {"file_a": "src/file_0.py", "file_b": "src/file_1.py", "count": 5}
            ],
            "stats": {
                "total_commits_analyzed": 100,
                "total_authors": 5,
                "hot_files": 3,
            },
        }

        mock_enricher = MagicMock()
        mock_enricher.enrich_to_dicts.return_value = mock_result

        with patch(
            "coderag.enrichment.git_enricher.GitEnricher",
            return_value=mock_enricher,
        ):
            stats = orch._run_git_enrichment(project_root)

        assert stats["co_change_pairs"] == 1
        assert stats["hot_files"] == 3
        assert stats["total_authors"] == 5

    def test_git_enrichment_parallel_exception(self, tmp_path):
        """Cover lines 667-669: exception in parallel git enrichment."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)
        os.makedirs(os.path.join(project_root, ".git"))

        # Insert nodes
        nodes = []
        for i in range(15):
            n = _make_node(
                file_path=f"src/file_{i}.py",
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                id=f"func-{i}",
                language="python",
            )
            nodes.append(n)
        orch._store.upsert_nodes(nodes)

        # Mock GitEnricher with file_metrics that will cause exceptions
        file_metrics = {f"src/file_{i}.py": {"commit_count": i + 1} for i in range(15)}
        mock_result = {
            "file_metrics": file_metrics,
            "co_changes": [],
            "stats": {"total_commits_analyzed": 50, "total_authors": 2, "hot_files": 1},
        }

        mock_enricher = MagicMock()
        mock_enricher.enrich_to_dicts.return_value = mock_result

        # Make find_nodes raise an exception to trigger the parallel exception handler
        original_find = orch._store.find_nodes
        call_count = [0]

        def flaky_find(**kwargs):
            call_count[0] += 1
            if call_count[0] > 2 and kwargs.get("file_path"):
                raise RuntimeError("DB error")
            return original_find(**kwargs)

        with patch(
            "coderag.enrichment.git_enricher.GitEnricher",
            return_value=mock_enricher,
        ):
            with patch.object(orch._store, "find_nodes", side_effect=flaky_find):
                stats = orch._run_git_enrichment(project_root)

        # Should still complete without raising
        assert isinstance(stats, dict)

    def test_git_enrichment_sequential_few_files(self, tmp_path):
        """When file_metrics has <=10 entries, use sequential loop."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)
        os.makedirs(os.path.join(project_root, ".git"))

        # Insert nodes for a few files
        nodes = []
        for i in range(3):
            n = _make_node(
                file_path=f"src/file_{i}.py",
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                id=f"func-{i}",
                language="python",
            )
            nodes.append(n)
        orch._store.upsert_nodes(nodes)

        file_metrics = {f"src/file_{i}.py": {"commit_count": i + 1} for i in range(3)}
        mock_result = {
            "file_metrics": file_metrics,
            "co_changes": [],
            "stats": {"total_commits_analyzed": 10, "total_authors": 1, "hot_files": 0},
        }

        mock_enricher = MagicMock()
        mock_enricher.enrich_to_dicts.return_value = mock_result

        with patch(
            "coderag.enrichment.git_enricher.GitEnricher",
            return_value=mock_enricher,
        ):
            stats = orch._run_git_enrichment(project_root)

        assert stats["total_authors"] == 1


# ── _run_framework_detection: inner function + parallel/sequential (lines 867-943) ──


class TestFrameworkDetectionPaths:
    """Cover _run_framework_detection inner function and execution paths."""

    def _setup_orch_with_nodes(self, tmp_path, num_files=3):
        """Create orchestrator with file nodes and source files."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        nodes = []
        for i in range(num_files):
            fp = os.path.join(project_root, f"src/file_{i}.py")
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w") as f:
                f.write(f"def func_{i}(): pass\n")
            n = _make_node(
                file_path=fp,
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                id=f"func-{i}",
                language="python",
            )
            nodes.append(n)
        orch._store.upsert_nodes(nodes)
        return orch, project_root

    def test_framework_detection_sequential(self, tmp_path):
        """Cover sequential framework detection (<=10 work items)."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        # Create mock detector and plugin
        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []  # No patterns found
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added == 0
        assert edges_added == 0

    def test_framework_detection_with_patterns(self, tmp_path):
        """Cover sequential detection returning nodes and edges."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        fw_node = _make_node(
            file_path="src/file_0.py",
            kind=NodeKind.FUNCTION,
            name="route_handler",
            id="fw-node-1",
        )
        fw_edge = Edge(
            source_id="fw-node-1",
            target_id="func-0",
            kind=EdgeKind.CALLS,
        )

        mock_pattern = MagicMock()
        mock_pattern.nodes = [fw_node]
        mock_pattern.edges = [fw_edge]

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = [mock_pattern]
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added >= 1
        assert edges_added >= 1

    def test_framework_detection_parallel_many_items(self, tmp_path):
        """Cover parallel framework detection (>10 work items)."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=12)

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added == 0
        assert edges_added == 0

    def test_framework_detection_file_not_found(self, tmp_path):
        """Cover _detect_file when file doesn't exist."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        # Insert node with non-existent file
        n = _make_node(
            file_path="nonexistent.py",
            kind=NodeKind.FUNCTION,
            name="func",
            id="func-1",
        )
        orch._store.upsert_nodes([n])

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added == 0

    def test_framework_detection_wrong_extension(self, tmp_path):
        """Cover _detect_file when file extension doesn't match."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".js"}  # Won't match .py files
        mock_plugin.get_framework_detectors.return_value = [mock_det]

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added == 0

    def test_framework_detection_detect_exception(self, tmp_path):
        """Cover _detect_file exception handler."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.side_effect = RuntimeError("Detection failed")
        mock_det.detect_global_patterns.return_value = []

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added == 0

    def test_global_detection_with_patterns(self, tmp_path):
        """Cover Phase 5b global detection returning patterns."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        global_node = _make_node(
            file_path="global.py",
            kind=NodeKind.FUNCTION,
            name="global_pattern",
            id="global-1",
        )
        global_edge = Edge(
            source_id="global-1",
            target_id="func-0",
            kind=EdgeKind.CALLS,
        )

        mock_global_pattern = MagicMock()
        mock_global_pattern.nodes = [global_node]
        mock_global_pattern.edges = [global_edge]

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []
        mock_det.detect_global_patterns.return_value = [mock_global_pattern]

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        assert nodes_added >= 1
        assert edges_added >= 1

    def test_global_detection_exception(self, tmp_path):
        """Cover Phase 5b global detection exception handler."""
        orch, project_root = self._setup_orch_with_nodes(tmp_path, num_files=3)

        mock_det = MagicMock()
        mock_det.framework_name = "TestFramework"
        mock_det.detect_framework.return_value = True
        mock_det.detect.return_value = []
        mock_det.detect_global_patterns.side_effect = RuntimeError("Global failed")

        mock_plugin = MagicMock()
        mock_plugin.name = "test_plugin"
        mock_plugin.file_extensions = {".py"}
        mock_plugin.get_framework_detectors.return_value = [mock_det]
        mock_plugin.get_extractor.return_value = MagicMock(_parser=None)

        with patch.object(orch._registry, "get_all_plugins", return_value=[mock_plugin]):
            nodes_added, edges_added = orch._run_framework_detection(project_root)

        # Should not raise, just log warning
        assert nodes_added == 0
        assert edges_added == 0


# ── _run_cross_language_matching (lines 980-982) ──


class TestCrossLanguageMatchingPaths:
    """Cover cross-language matching paths."""

    def test_cross_language_no_multiple_languages(self, tmp_path):
        """When project has only one language, skip matching."""
        orch = _make_orchestrator(tmp_path)
        # Insert only Python nodes
        nodes = [
            _make_node(file_path="a.py", name="a", id="a", language="python"),
            _make_node(file_path="b.py", name="b", id="b", language="python"),
        ]
        orch._store.upsert_nodes(nodes)

        result = orch._run_cross_language_matching("/tmp/project")
        assert result == 0

    def test_cross_language_import_error(self, tmp_path):
        """When CrossLanguageMatcher is not available."""
        orch = _make_orchestrator(tmp_path)

        with patch.dict("sys.modules", {"coderag.pipeline.cross_language": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module"),
            ):
                result = orch._run_cross_language_matching("/tmp/project")

        # Should return 0 gracefully
        assert result == 0


# ── run() method: various phase paths (lines 393-448) ──


class TestRunMethodPaths:
    """Cover various paths in the run() method."""

    def test_run_with_framework_detection_results(self, tmp_path):
        """Cover lines 393-394: fw_nodes or fw_edges truthy."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        # Create a minimal source file
        os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
        with open(os.path.join(project_root, "src", "test.py"), "w") as f:
            f.write("def hello(): pass\n")

        # Mock all phases to return quickly
        with patch.object(orch, "_run_framework_detection", return_value=(5, 3)):
            with patch.object(orch, "_run_cross_language_matching", return_value=2):
                with patch.object(orch, "_run_style_edge_matching", return_value=1):
                    with patch.object(orch, "_run_git_enrichment", return_value={}):
                        with patch.object(orch, "_run_phpstan_enrichment", return_value={}):
                            summary = orch.run(project_root)

        assert isinstance(summary, PipelineSummary)

    def test_run_with_cross_language_edges(self, tmp_path):
        """Cover lines 406: xl_edges truthy."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
        with open(os.path.join(project_root, "src", "test.py"), "w") as f:
            f.write("def hello(): pass\n")

        with patch.object(orch, "_run_framework_detection", return_value=(0, 0)):
            with patch.object(orch, "_run_cross_language_matching", return_value=10):
                with patch.object(orch, "_run_style_edge_matching", return_value=0):
                    with patch.object(orch, "_run_git_enrichment", return_value={}):
                        with patch.object(orch, "_run_phpstan_enrichment", return_value={}):
                            summary = orch.run(project_root)

        assert isinstance(summary, PipelineSummary)

    def test_run_with_style_edges(self, tmp_path):
        """Cover lines 418: style_edges truthy."""
        orch = _make_orchestrator(tmp_path)
        project_root = str(tmp_path)

        os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
        with open(os.path.join(project_root, "src", "test.py"), "w") as f:
            f.write("def hello(): pass\n")

        with patch.object(orch, "_run_framework_detection", return_value=(0, 0)):
            with patch.object(orch, "_run_cross_language_matching", return_value=0):
                with patch.object(orch, "_run_style_edge_matching", return_value=7):
                    with patch.object(orch, "_run_git_enrichment", return_value={}):
                        with patch.object(orch, "_run_phpstan_enrichment", return_value={}):
                            summary = orch.run(project_root)

        assert isinstance(summary, PipelineSummary)
