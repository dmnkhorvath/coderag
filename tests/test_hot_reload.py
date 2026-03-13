"""Tests for hot-reload functionality in MCP server."""

import os
import shutil
import subprocess
import tempfile
import time

import pytest

from coderag.core.config import CodeGraphConfig
from coderag.core.registry import PluginRegistry
from coderag.mcp.server import GraphContext, _AnalyzerProxy, _StoreProxy
from coderag.pipeline.orchestrator import PipelineOrchestrator
from coderag.plugins import BUILTIN_PLUGINS
from coderag.storage.sqlite_store import SQLiteStore


def _write_php(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _parse_project(project_dir, db_path):
    config = CodeGraphConfig()
    registry = PluginRegistry()
    for p in BUILTIN_PLUGINS:
        registry.register_plugin(p())
    store = SQLiteStore(db_path)
    store.initialize()
    orch = PipelineOrchestrator(config, registry, store)
    orch.run(project_dir, incremental=False)
    store.close()


@pytest.fixture
def graph_context():
    """Create a GraphContext with a minimal parsed project."""
    d = tempfile.mkdtemp(prefix="coderag_reload_")
    db_path = os.path.join(d, ".codegraph", "graph.db")
    os.makedirs(os.path.dirname(db_path))

    subprocess.run(["git", "init", d], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "T"], capture_output=True)

    _write_php(os.path.join(d, "app", "Foo.php"), "<?php\nnamespace App;\nclass Foo {}\n")

    subprocess.run(["git", "-C", d, "add", "."], capture_output=True)
    subprocess.run(["git", "-C", d, "commit", "-m", "Init"], capture_output=True)

    _parse_project(d, db_path)

    ctx = GraphContext(db_path)
    yield ctx, d, db_path
    ctx.close()
    shutil.rmtree(d)


class TestGraphContext:
    def test_initial_load(self, graph_context):
        ctx, _, _ = graph_context
        assert ctx.store is not None
        assert ctx.analyzer is not None
        stats = ctx.analyzer.get_statistics()
        assert stats.get("node_count", 0) > 0

    def test_check_no_change(self, graph_context):
        ctx, _, _ = graph_context
        reloaded = ctx.check_and_reload()
        assert reloaded is False

    def test_check_and_reload_on_change(self, graph_context):
        ctx, d, db_path = graph_context
        initial_count = ctx._load_count

        # Sleep to ensure mtime changes (filesystem resolution can be 1s)
        time.sleep(1.1)

        _write_php(os.path.join(d, "app", "Bar.php"), "<?php\nnamespace App;\nclass Bar {}\n")

        subprocess.run(["git", "-C", d, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", d, "commit", "-m", "Add Bar"], capture_output=True)

        _parse_project(d, db_path)

        # Force mtime to be clearly newer (filesystem resolution can be 1s)
        new_mtime = ctx.last_mtime + 2.0
        os.utime(db_path, (new_mtime, new_mtime))

        # Now check_and_reload should detect the change
        reloaded = ctx.check_and_reload()
        assert reloaded is True
        assert ctx._load_count == initial_count + 1


class TestStoreProxy:
    def test_proxy_delegates_to_store(self, graph_context):
        ctx, _, _ = graph_context
        proxy = _StoreProxy(ctx)
        summary = proxy.get_summary()
        assert summary.total_nodes > 0

    def test_proxy_follows_reload(self, graph_context):
        ctx, d, db_path = graph_context
        proxy = _StoreProxy(ctx)

        before = proxy.get_summary().total_nodes

        time.sleep(1.1)
        _write_php(
            os.path.join(d, "app", "Baz.php"), "<?php\nnamespace App;\nclass Baz { public function run(): void {} }\n"
        )

        subprocess.run(["git", "-C", d, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", d, "commit", "-m", "Add Baz"], capture_output=True)

        _parse_project(d, db_path)

        ctx.check_and_reload()
        after = proxy.get_summary().total_nodes
        assert after > before


class TestAnalyzerProxy:
    def test_proxy_delegates_to_analyzer(self, graph_context):
        ctx, _, _ = graph_context
        proxy = _AnalyzerProxy(ctx)
        stats = proxy.get_statistics()
        assert isinstance(stats, dict)
        assert "node_count" in stats
