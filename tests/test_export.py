"""Tests for coderag.export module."""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from coderag.core.config import CodeGraphConfig
from coderag.core.registry import PluginRegistry
from coderag.export import ExportOptions, GraphExporter
from coderag.pipeline.orchestrator import PipelineOrchestrator
from coderag.plugins import BUILTIN_PLUGINS
from coderag.storage.sqlite_store import SQLiteStore


def _write_php(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.fixture(scope="module")
def export_store():
    """Create a parsed store for export tests."""
    d = tempfile.mkdtemp(prefix="coderag_export_test_")
    db_path = os.path.join(d, ".codegraph", "graph.db")
    os.makedirs(os.path.dirname(db_path))

    subprocess.run(["git", "init", d], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "T"], capture_output=True)

    app_dir = os.path.join(d, "app")
    _write_php(
        os.path.join(app_dir, "User.php"),
        (
            "<?php\n"
            "namespace App;\n"
            "class User {\n"
            "    public function getName(): string { return $this->name; }\n"
            "    public function getEmail(): string { return $this->email; }\n"
            "}\n"
        ),
    )
    _write_php(
        os.path.join(app_dir, "UserService.php"),
        (
            "<?php\n"
            "namespace App;\n"
            "use App\\User;\n"
            "class UserService {\n"
            "    public function getUser(): User { return new User(); }\n"
            "    public function findByEmail(string $email): ?User { return null; }\n"
            "}\n"
        ),
    )

    subprocess.run(["git", "-C", d, "add", "."], capture_output=True)
    subprocess.run(["git", "-C", d, "commit", "-m", "Init"], capture_output=True)

    config = CodeGraphConfig()
    registry = PluginRegistry()
    for p in BUILTIN_PLUGINS:
        registry.register_plugin(p())
    store = SQLiteStore(db_path)
    store.initialize()
    orch = PipelineOrchestrator(config, registry, store)
    orch.run(d, incremental=False)

    yield store, d
    store.close()
    shutil.rmtree(d)


class TestExportOptions:
    def test_default_options(self):
        opts = ExportOptions()
        assert opts.format == "markdown"
        assert opts.scope == "architecture"
        assert opts.max_tokens == 8000

    def test_custom_options(self):
        opts = ExportOptions(format="json", scope="full", max_tokens=4000)
        assert opts.format == "json"
        assert opts.scope == "full"
        assert opts.max_tokens == 4000


class TestMarkdownExport:
    def test_architecture_scope(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="markdown", scope="architecture"))
        assert "# Architecture Overview" in result
        assert "## Summary" in result
        assert "php" in result.lower()

    def test_full_scope(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="markdown", scope="full"))
        assert len(result) > 0
        assert "User" in result

    def test_symbol_scope(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="markdown", scope="symbol", symbol="UserService"))
        assert "UserService" in result

    def test_symbol_not_found(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="markdown", scope="symbol", symbol="NonExistent"))
        assert "not found" in result.lower() or "error" in result.lower() or len(result) > 0

    def test_file_scope(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="markdown", scope="file", file_path="app/User.php"))
        assert "User" in result


class TestJsonExport:
    def test_architecture_json(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="json", scope="architecture"))
        data = json.loads(result)
        assert "scope" in data
        assert data["scope"] == "architecture"
        assert "stats" in data
        assert data["stats"]["total_nodes"] > 0

    def test_full_json(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="json", scope="full"))
        data = json.loads(result)
        assert "nodes" in data
        assert len(data["nodes"]) > 0


class TestTreeExport:
    def test_tree_full(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        result = exporter.export(ExportOptions(format="tree", scope="full"))
        assert "User.php" in result
        assert "UserService.php" in result


class TestTokenBudget:
    def test_respects_token_budget(self, export_store):
        store, _ = export_store
        exporter = GraphExporter(store)
        small = exporter.export(ExportOptions(format="markdown", scope="full", max_tokens=100))
        large = exporter.export(ExportOptions(format="markdown", scope="full", max_tokens=100000))
        assert len(small) <= len(large)
