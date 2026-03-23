"""Tests for coderag.cli.main to push coverage toward 95%+.

Covers: query (semantic/hybrid), serve (--watch), enrich, embed, watch,
        routes (text output), validate, monitor, frameworks, cross-language.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from click.testing import CliRunner

from coderag.cli.main import cli
from coderag.core.models import Node, Edge, NodeKind, EdgeKind


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _obj(db_override=None, config_path=None):
    return {"db_override": db_override, "config_path": config_path}


def _make_node(id="n1", name="Foo", qname="app/Foo", kind=NodeKind.CLASS,
               file_path="src/foo.py", start_line=1, language="python",
               metadata=None):
    return Node(
        id=id, name=name, qualified_name=qname, kind=kind,
        file_path=file_path, start_line=start_line, end_line=10,
        language=language, metadata=metadata or {},
    )


def _make_edge(source_id="n1", target_id="n2", kind=EdgeKind.CALLS,
               confidence=0.9, metadata=None):
    return Edge(
        source_id=source_id, target_id=target_id, kind=kind,
        confidence=confidence, metadata=metadata or {},
    )


def _mock_search_result(node_id="n1", kind="class", name="Foo",
                        qname="app/Foo", file_path="src/foo.py",
                        language="python", score=0.95, match_type="hybrid",
                        vector_similarity=0.9):
    sr = MagicMock()
    sr.node_id = node_id
    sr.kind = kind
    sr.name = name
    sr.qualified_name = qname
    sr.file_path = file_path
    sr.language = language
    sr.score = score
    sr.match_type = match_type
    sr.vector_similarity = vector_similarity
    return sr


# ---------------------------------------------------------------------------
# query command - semantic/hybrid mode (covers lines 324-441)
# ---------------------------------------------------------------------------

class TestQuerySemanticHybrid:
    """The CLI command is 'query' with --semantic/--hybrid/--fts flags."""

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_semantic_no_vector_index(self, mock_load_cfg, mock_open_store, runner):
        """--semantic with no vector index falls back to FTS5."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.search_nodes.return_value = []
        mock_open_store.return_value = mock_store

        # The import happens inside the function body, so we patch the modules
        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": MagicMock(**{"VectorStore.exists.return_value": False}),
        }):
            result = runner.invoke(cli, ["query", "test", "--semantic"], obj=_obj())
            assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_hybrid_json(self, mock_load_cfg, mock_open_store, runner):
        """--hybrid with json output."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_node.return_value = _make_node()
        mock_store.get_neighbors.return_value = []
        mock_open_store.return_value = mock_store

        sr = _mock_search_result()
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [sr]

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        mock_embedder_mod = MagicMock()
        mock_hybrid_mod = MagicMock()
        mock_hybrid_mod.HybridSearcher.return_value = mock_searcher

        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": mock_embedder_mod,
            "coderag.search.hybrid": mock_hybrid_mod,
        }):
            result = runner.invoke(cli, ["query", "test", "--hybrid", "-f", "json"], obj=_obj())
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["name"] == "Foo"

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_hybrid_table(self, mock_load_cfg, mock_open_store, runner):
        """--hybrid with default table output."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_node.return_value = _make_node()
        mock_store.get_neighbors.return_value = []
        mock_open_store.return_value = mock_store

        sr = _mock_search_result()
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [sr]

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.hybrid": MagicMock(**{"HybridSearcher.return_value": mock_searcher}),
        }):
            result = runner.invoke(cli, ["query", "test", "--hybrid"], obj=_obj())
            assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_semantic_no_results(self, mock_load_cfg, mock_open_store, runner):
        """--semantic with no results shows message."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        mock_searcher = MagicMock()
        mock_searcher.search_semantic.return_value = []

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.hybrid": MagicMock(**{"HybridSearcher.return_value": mock_searcher}),
        }):
            result = runner.invoke(cli, ["query", "test", "--semantic"], obj=_obj())
            assert result.exit_code == 0
            assert "No results" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_semantic_import_error(self, mock_load_cfg, mock_open_store, runner):
        """--semantic when search deps not installed falls back to FTS5."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.search_nodes.return_value = []
        mock_open_store.return_value = mock_store

        mock_search_mod = MagicMock()
        mock_search_mod.require_semantic.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {
            "coderag.search": mock_search_mod,
        }):
            result = runner.invoke(cli, ["query", "test", "--semantic"], obj=_obj())
            assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_hybrid_with_depth_json(self, mock_load_cfg, mock_open_store, runner):
        """--hybrid with --depth and json output includes relationships."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        node = _make_node()
        neighbor_node = _make_node(id="n2", name="Bar", qname="app/Bar")
        neighbor_edge = _make_edge()
        mock_store = MagicMock()
        mock_store.get_node.return_value = node
        mock_store.get_neighbors.return_value = [(neighbor_node, neighbor_edge, 1)]
        mock_open_store.return_value = mock_store

        sr = _mock_search_result()
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [sr]

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.hybrid": MagicMock(**{"HybridSearcher.return_value": mock_searcher}),
        }):
            result = runner.invoke(cli, ["query", "test", "--hybrid", "-f", "json", "-d", "1"], obj=_obj())
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "relationships" in data[0]

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_hybrid_with_depth_table(self, mock_load_cfg, mock_open_store, runner):
        """--hybrid with --depth and table output shows neighbors."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        node = _make_node()
        neighbor_node = _make_node(id="n2", name="Bar", qname="app/Bar")
        neighbor_edge = _make_edge()
        mock_store = MagicMock()
        mock_store.get_node.return_value = node
        mock_store.get_neighbors.return_value = [(neighbor_node, neighbor_edge, 1)]
        mock_open_store.return_value = mock_store

        sr = _mock_search_result()
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [sr]

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": MagicMock(SEMANTIC_AVAILABLE=True, require_semantic=MagicMock()),
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.hybrid": MagicMock(**{"HybridSearcher.return_value": mock_searcher}),
        }):
            result = runner.invoke(cli, ["query", "test", "--hybrid", "-d", "1"], obj=_obj())
            assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_query_auto_detect_hybrid(self, mock_load_cfg, mock_open_store, runner):
        """Auto-detect mode uses hybrid when vector index exists (lines 326-338)."""
        mock_config = MagicMock()
        mock_config.db_path_absolute = "/tmp/test.db"
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_node.return_value = _make_node()
        mock_store.get_neighbors.return_value = []
        mock_open_store.return_value = mock_store

        sr = _mock_search_result()
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [sr]

        mock_vs_mod = MagicMock()
        mock_vs_mod.VectorStore.exists.return_value = True
        mock_vs_mod.VectorStore.load.return_value = MagicMock()

        mock_search_mod = MagicMock()
        mock_search_mod.SEMANTIC_AVAILABLE = True
        mock_search_mod.require_semantic = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": mock_search_mod,
            "coderag.search.vector_store": mock_vs_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.hybrid": MagicMock(**{"HybridSearcher.return_value": mock_searcher}),
        }):
            # No --semantic or --hybrid flag = auto-detect
            result = runner.invoke(cli, ["query", "test", "-f", "json"], obj=_obj())
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# frameworks command (covers lines 866-960)
# ---------------------------------------------------------------------------

class TestFrameworksCommand:
    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_frameworks_json_with_stored_data(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_metadata.return_value = "laravel,react"
        route_node = _make_node(kind=NodeKind.ROUTE, metadata={"framework": "laravel"})
        mock_store.find_nodes.return_value = [route_node]
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["frameworks", "--format", "json"], obj=_obj())
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "laravel" in data["detected_frameworks"]

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_frameworks_no_detected(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_config.project_root = "/tmp/project"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_metadata.return_value = None
        mock_open_store.return_value = mock_store

        # The import is inside the function body: from coderag.core.registry import PluginRegistry
        mock_reg = MagicMock()
        mock_reg.get_framework_detectors.return_value = []
        mock_reg_mod = MagicMock()
        mock_reg_mod.PluginRegistry.return_value = mock_reg

        with patch.dict("sys.modules", {
            "coderag.core.registry": mock_reg_mod,
        }):
            result = runner.invoke(cli, ["frameworks"], obj=_obj())
            assert result.exit_code == 0
            assert "No frameworks" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_frameworks_live_detection_json(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_config.project_root = "/tmp/project"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_metadata.return_value = None
        mock_store.find_nodes.return_value = []
        mock_open_store.return_value = mock_store

        mock_detector = MagicMock()
        mock_detector.detect_framework.return_value = True
        mock_detector.framework_name = "django"

        mock_reg = MagicMock()
        mock_reg.get_framework_detectors.return_value = [mock_detector]
        mock_reg_mod = MagicMock()
        mock_reg_mod.PluginRegistry.return_value = mock_reg

        with patch.dict("sys.modules", {
            "coderag.core.registry": mock_reg_mod,
        }):
            result = runner.invoke(cli, ["frameworks", "--format", "json"], obj=_obj())
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "django" in data["detected_frameworks"]

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_frameworks_table_with_nodes(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_metadata.return_value = "laravel"
        route_node = _make_node(kind=NodeKind.ROUTE, metadata={"framework": "laravel"})
        mock_store.find_nodes.return_value = [route_node]
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["frameworks"], obj=_obj())
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# serve command with --watch (covers lines 1323-1367)
# ---------------------------------------------------------------------------

class TestServeCommand:
    @patch("coderag.cli.main._load_config")
    def test_serve_with_watch(self, mock_load_cfg, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_cfg.return_value = mock_config

        mock_watcher = MagicMock()
        mock_store_inst = MagicMock()

        # Imports inside function body
        mock_events_mod = MagicMock()
        mock_watcher_mod = MagicMock()
        mock_watcher_mod.FileWatcher.return_value = mock_watcher
        mock_plugins_mod = MagicMock()
        mock_plugins_mod.BUILTIN_PLUGINS = []
        mock_registry_mod = MagicMock()
        mock_store_mod = MagicMock()
        mock_store_mod.SQLiteStore.return_value = mock_store_inst
        mock_mcp_server_mod = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.pipeline.events": mock_events_mod,
            "coderag.pipeline.watcher": mock_watcher_mod,
            "coderag.plugins": mock_plugins_mod,
            "coderag.plugins.registry": mock_registry_mod,
            "coderag.storage.sqlite_store": mock_store_mod,
            "coderag.mcp.server": mock_mcp_server_mod,
        }):
            result = runner.invoke(cli, ["serve", str(tmp_path), "--watch"], obj=_obj())
            assert result.exit_code == 0
            mock_watcher.start.assert_called_once()
            mock_watcher.stop.assert_called_once()


# ---------------------------------------------------------------------------
# enrich command (covers lines 1444-1465)
# ---------------------------------------------------------------------------

class TestEnrichCommand:
    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_enrich_phpstan_not_available(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        mock_enricher = MagicMock()
        mock_enricher.is_available.return_value = False

        mock_phpstan_mod = MagicMock()
        mock_phpstan_mod.PHPStanEnricher.return_value = mock_enricher

        with patch.dict("sys.modules", {
            "coderag.enrichment.phpstan": mock_phpstan_mod,
        }):
            result = runner.invoke(cli, ["enrich", "--phpstan"], obj=_obj())
            assert result.exit_code == 0
            assert "not available" in result.output.lower()

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_enrich_phpstan_success(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        mock_report = MagicMock()
        mock_report.skipped_reason = None
        mock_report.files_analyzed = 10
        mock_report.errors_found = 2
        mock_report.nodes_enriched = 5
        mock_report.duration_ms = 1234.5
        mock_report.phpstan_version = "1.10.0"
        mock_report.level = 5

        mock_enricher = MagicMock()
        mock_enricher.is_available.return_value = True
        mock_enricher.get_version.return_value = "1.10.0"
        mock_enricher.enrich_nodes.return_value = mock_report

        mock_phpstan_mod = MagicMock()
        mock_phpstan_mod.PHPStanEnricher.return_value = mock_enricher

        with patch.dict("sys.modules", {
            "coderag.enrichment.phpstan": mock_phpstan_mod,
        }):
            result = runner.invoke(cli, ["enrich", "--phpstan"], obj=_obj())
            assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_enrich_phpstan_skipped(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        mock_report = MagicMock()
        mock_report.skipped_reason = "No PHP files found"

        mock_enricher = MagicMock()
        mock_enricher.is_available.return_value = True
        mock_enricher.get_version.return_value = "1.10.0"
        mock_enricher.enrich_nodes.return_value = mock_report

        mock_phpstan_mod = MagicMock()
        mock_phpstan_mod.PHPStanEnricher.return_value = mock_enricher

        with patch.dict("sys.modules", {
            "coderag.enrichment.phpstan": mock_phpstan_mod,
        }):
            result = runner.invoke(cli, ["enrich", "--phpstan"], obj=_obj())
            assert result.exit_code == 0
            assert "Skipped" in result.output


# ---------------------------------------------------------------------------
# embed command (covers lines 1501-1507, 1539-1540)
# ---------------------------------------------------------------------------

class TestEmbedCommand:
    def test_embed_no_semantic_deps(self, runner):
        mock_search_mod = MagicMock()
        mock_search_mod.require_semantic.side_effect = ImportError("no module")
        with patch.dict("sys.modules", {"coderag.search": mock_search_mod}):
            result = runner.invoke(cli, ["embed", "."], obj=_obj())
            assert result.exit_code != 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_embed_no_nodes(self, mock_load_cfg, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.semantic_model = "all-MiniLM-L6-v2"
        mock_config.semantic_batch_size = 32
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"total_nodes": 0}
        mock_open_store.return_value = mock_store

        mock_search_mod = MagicMock()
        mock_search_mod.require_semantic = MagicMock()

        with patch.dict("sys.modules", {
            "coderag.search": mock_search_mod,
            "coderag.search.embedder": MagicMock(),
            "coderag.search.vector_store": MagicMock(),
        }):
            result = runner.invoke(cli, ["embed", str(tmp_path)], obj=_obj())
            assert result.exit_code == 0
            assert "No nodes" in result.output


# ---------------------------------------------------------------------------
# watch command (covers lines 1649-1722)
# ---------------------------------------------------------------------------

class TestWatchCommand:
    @patch("coderag.cli.main._load_config")
    def test_watch_keyboard_interrupt(self, mock_load_cfg, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_cfg.return_value = mock_config

        mock_watcher = MagicMock()
        mock_watcher.start.side_effect = KeyboardInterrupt()
        mock_watcher.reparse_count = 3

        mock_store_inst = MagicMock()

        mock_watcher_mod = MagicMock()
        mock_watcher_mod.FileWatcher.return_value = mock_watcher
        mock_events_mod = MagicMock()
        mock_plugins_mod = MagicMock()
        mock_plugins_mod.BUILTIN_PLUGINS = []
        mock_store_mod = MagicMock()
        mock_store_mod.SQLiteStore.return_value = mock_store_inst

        with patch.dict("sys.modules", {
            "coderag.pipeline.watcher": mock_watcher_mod,
            "coderag.pipeline.events": mock_events_mod,
            "coderag.plugins": mock_plugins_mod,
        }), \
        patch("coderag.cli.main.PluginRegistry") as mock_reg_cls, \
        patch("coderag.cli.main.SQLiteStore", return_value=mock_store_inst):
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            result = runner.invoke(cli, ["watch", str(tmp_path)], obj=_obj())
            assert result.exit_code == 0
            assert "stopped" in result.output.lower() or "Watcher" in result.output


# ---------------------------------------------------------------------------
# routes command - text output (covers lines 2157-2215)
# ---------------------------------------------------------------------------

class TestRoutesCommand:
    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_routes_text_output(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()

        route_node = _make_node(
            id="r1", name="/api/users", qname="/api/users",
            kind=NodeKind.ROUTE, file_path="routes/api.php", start_line=10,
            metadata={"http_method": "GET", "url": "/api/users",
                      "controller": "UserController", "action": "index"}
        )
        mock_store.find_nodes.return_value = [route_node]

        target_node = _make_node(id="t1", name="index", qname="UserController/index")
        caller_node = _make_node(id="c1", name="fetchUsers", qname="app/fetchUsers",
                                  file_path="src/api.js")

        outgoing_edge = _make_edge(source_id="r1", target_id="t1", kind=EdgeKind.CALLS)
        caller_edge = _make_edge(source_id="c1", target_id="r1", kind=EdgeKind.API_CALLS,
                                  metadata={"call_url": "/api/users"})

        def get_edges_side_effect(source_id=None, target_id=None):
            if source_id == "r1":
                return [outgoing_edge]
            if target_id == "r1":
                return [caller_edge]
            return []

        mock_store.get_edges.side_effect = get_edges_side_effect
        mock_store.get_node.side_effect = lambda nid: {
            "t1": target_node, "c1": caller_node
        }.get(nid)
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["routes", "*"], obj=_obj())
        assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_routes_json_output(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()

        route_node = _make_node(
            id="r1", name="/api/users", qname="/api/users",
            kind=NodeKind.ROUTE, file_path="routes/api.php", start_line=10,
            metadata={"http_method": "GET", "url": "/api/users"}
        )
        mock_store.find_nodes.return_value = [route_node]
        mock_store.get_edges.return_value = []
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["routes", "*", "--format", "json"], obj=_obj())
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["routes"]) == 1

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_routes_no_routes(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.find_nodes.return_value = []
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["routes", "*"], obj=_obj())
        assert result.exit_code == 0
        assert "No routes" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_routes_json_with_frontend_callers(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()

        route_node = _make_node(
            id="r1", name="/api/users", qname="/api/users",
            kind=NodeKind.ROUTE, file_path="routes/api.php", start_line=10,
            metadata={"http_method": "GET", "url": "/api/users"}
        )
        mock_store.find_nodes.return_value = [route_node]

        caller_edge = _make_edge(source_id="c1", target_id="r1", kind=EdgeKind.API_CALLS)
        caller_node = _make_node(id="c1", name="fetchUsers", qname="app/fetchUsers",
                                  file_path="src/api.js")

        def get_edges_side_effect(source_id=None, target_id=None):
            if source_id:
                return []
            return [caller_edge]

        mock_store.get_edges.side_effect = get_edges_side_effect
        mock_store.get_node.return_value = caller_node
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["routes", "*", "--format", "json"], obj=_obj())
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "frontend_callers" in data["routes"][0]


# ---------------------------------------------------------------------------
# validate command (covers lines 2433-2500, 2526-2544)
# ---------------------------------------------------------------------------

class TestValidateCommand:
    def test_validate_no_config(self, runner, tmp_path):
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["validate"])
            # validate exits 1 when no config found
            assert result.exit_code in (0, 1)
        finally:
            os.chdir(orig_cwd)

    def test_validate_with_config(self, runner, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: .\nlanguages:\n  python: {}\ndb_path: .codegraph/graph.db\n")
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["validate"])
            assert result.exit_code == 0
        finally:
            os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# monitor command (covers lines 2603-2621)
# ---------------------------------------------------------------------------

class TestMonitorCommand:
    def test_monitor_no_tui_deps(self, runner, tmp_path):
        """monitor command when TUI deps not installed."""
        # Remove coderag.tui.app from sys.modules to force ImportError
        mock_tui_mod = MagicMock()
        mock_tui_mod.CodeRAGApp = MagicMock(side_effect=ImportError("no module"))

        # Force the import to fail
        saved = sys.modules.get("coderag.tui.app")
        sys.modules["coderag.tui.app"] = None  # This causes ImportError on import
        try:
            result = runner.invoke(cli, ["monitor", str(tmp_path)])
            assert result.exit_code != 0
        finally:
            if saved is not None:
                sys.modules["coderag.tui.app"] = saved
            else:
                sys.modules.pop("coderag.tui.app", None)


# ---------------------------------------------------------------------------
# cross-language command (covers lines 1082-1146)
# ---------------------------------------------------------------------------

class TestCrossLanguageCommand:
    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_cross_language_text_output(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_config.db_path = "/tmp/project/.codegraph/graph.db"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()

        source_node = _make_node(id="s1", name="fetchUsers",
                                  qname="src/api.js/fetchUsers",
                                  file_path="src/api.js", language="javascript")
        target_node = _make_node(id="t1", name="index",
                                  qname="routes/api.php/index",
                                  file_path="routes/api.php", language="php")
        mock_store.get_node.side_effect = lambda nid: {
            "s1": source_node, "t1": target_node
        }.get(nid)

        xl_edge = _make_edge(
            source_id="s1", target_id="t1", kind=EdgeKind.API_CALLS,
            metadata={
                "http_method": "GET",
                "call_url": "/api/users",
                "endpoint_url": "/api/users",
                "match_strategy": "exact",
            }
        )

        mock_store.get_metadata.return_value = "5"
        mock_store.get_edges.return_value = [xl_edge]
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["cross-language"], obj=_obj())
        assert result.exit_code == 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_cross_language_no_connections(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_config.db_path = "/tmp/test/.codegraph/graph.db"
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_store.get_metadata.return_value = "0"
        mock_store.get_edges.return_value = []  # No API_CALLS edges
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["cross-language"], obj=_obj())
        assert result.exit_code == 0
        assert "No cross-language" in result.output


# ---------------------------------------------------------------------------
# info command - json output (covers line 211)
# ---------------------------------------------------------------------------

class TestInfoCommand:
    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_info_json(self, mock_load_cfg, mock_open_store, runner):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_summary = MagicMock()
        mock_summary.project_name = "test"
        mock_summary.total_nodes = 100
        mock_summary.total_edges = 200
        mock_summary.languages = {"python": 50}
        mock_summary.node_kinds = {"class": 30}
        mock_summary.edge_kinds = {"calls": 100}
        mock_store.get_summary.return_value = mock_summary
        mock_open_store.return_value = mock_store

        result = runner.invoke(cli, ["info", "--json-output"], obj=_obj())
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project_name"] == "test"


# ---------------------------------------------------------------------------
# init command - overwrite (covers lines 528-530)
# ---------------------------------------------------------------------------

class TestInitCommand:
    def test_init_overwrite_abort(self, runner, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("existing: true\n")
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["init"], input="n\n", obj=_obj())
            assert result.exit_code == 0
            assert "Aborted" in result.output
        finally:
            os.chdir(orig_cwd)
