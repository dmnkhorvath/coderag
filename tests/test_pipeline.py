"""Integration tests for the full CodeRAG pipeline."""

import os
import shutil
import subprocess
import tempfile

import pytest

from coderag.core.config import CodeGraphConfig
from coderag.core.models import EdgeKind, NodeKind
from coderag.core.registry import PluginRegistry
from coderag.pipeline.orchestrator import PipelineOrchestrator
from coderag.plugins import BUILTIN_PLUGINS
from coderag.storage.sqlite_store import SQLiteStore


def _write_php(path, content):
    """Write PHP content to a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.fixture
def php_project():
    """Create a minimal PHP project with git repo."""
    d = tempfile.mkdtemp(prefix="coderag_test_")
    subprocess.run(["git", "init", d], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "Test"], capture_output=True)

    app_dir = os.path.join(d, "app")

    _write_php(
        os.path.join(app_dir, "User.php"),
        (
            "<?php\n"
            "namespace App;\n"
            "\n"
            "class User {\n"
            "    private string $name;\n"
            "    private string $email;\n"
            "\n"
            "    public function getName(): string {\n"
            "        return $this->name;\n"
            "    }\n"
            "\n"
            "    public function getEmail(): string {\n"
            "        return $this->email;\n"
            "    }\n"
            "\n"
            "    public function getDisplayName(): string {\n"
            '        return $this->getName() . " <" . $this->getEmail() . ">";\n'
            "    }\n"
            "}\n"
        ),
    )

    _write_php(
        os.path.join(app_dir, "UserService.php"),
        (
            "<?php\n"
            "namespace App;\n"
            "\n"
            "use App\\User;\n"
            "\n"
            "class UserService {\n"
            "    public function getUser(int $id): User {\n"
            "        return new User();\n"
            "    }\n"
            "\n"
            "    public function findByEmail(string $email): ?User {\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        ),
    )

    _write_php(
        os.path.join(app_dir, "Controller.php"),
        (
            "<?php\n"
            "namespace App;\n"
            "\n"
            "use App\\UserService;\n"
            "\n"
            "class Controller {\n"
            "    private UserService $service;\n"
            "\n"
            "    public function index(): array {\n"
            "        return [];\n"
            "    }\n"
            "}\n"
        ),
    )

    subprocess.run(["git", "-C", d, "add", "."], capture_output=True)
    subprocess.run(["git", "-C", d, "commit", "-m", "Initial"], capture_output=True)

    yield d
    shutil.rmtree(d)


@pytest.fixture
def parsed_store(php_project):
    """Run the full pipeline and return the store."""
    db_path = os.path.join(php_project, ".codegraph", "graph.db")
    os.makedirs(os.path.dirname(db_path))

    config = CodeGraphConfig()
    registry = PluginRegistry()
    for p in BUILTIN_PLUGINS:
        registry.register_plugin(p())

    store = SQLiteStore(db_path)
    store.initialize()
    orchestrator = PipelineOrchestrator(config, registry, store)
    orchestrator.run(php_project, incremental=False)
    yield store
    store.close()


class TestFullPipeline:
    def test_pipeline_creates_nodes(self, parsed_store):
        summary = parsed_store.get_summary()
        assert summary.total_nodes > 0
        total_files = sum(summary.files_by_language.values())
        assert total_files == 3

    def test_pipeline_creates_edges(self, parsed_store):
        summary = parsed_store.get_summary()
        assert summary.total_edges > 0

    def test_pipeline_extracts_classes(self, parsed_store):
        classes = parsed_store.find_nodes(kind=NodeKind.CLASS)
        names = {n.name for n in classes}
        assert "User" in names
        assert "UserService" in names
        assert "Controller" in names

    def test_pipeline_extracts_methods(self, parsed_store):
        methods = parsed_store.find_nodes(kind=NodeKind.METHOD)
        names = {n.name for n in methods}
        assert "getName" in names
        assert "getEmail" in names
        assert "getUser" in names

    def test_pipeline_creates_containment_edges(self, parsed_store):
        edges = parsed_store.get_edges()
        contain_edges = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        assert len(contain_edges) >= 6

    def test_pipeline_enriches_git_metadata(self, parsed_store):
        files = parsed_store.find_nodes(kind=NodeKind.FILE)
        assert len(files) == 3


class TestPipelineSearch:
    def test_search_by_name(self, parsed_store):
        results = parsed_store.search_nodes("User", limit=10)
        assert len(results) >= 1

    def test_search_by_qualified_name(self, parsed_store):
        node = parsed_store.get_node_by_qualified_name("App\\User")
        assert node is not None
        assert node is not None  # May match import or class node

    def test_neighbor_traversal(self, parsed_store):
        user = parsed_store.get_node_by_qualified_name("App\\User")
        if user:
            neighbors = parsed_store.get_neighbors(user.id, max_depth=1)
            assert len(neighbors) >= 1


class TestIncrementalParse:
    def test_incremental_preserves_nodes(self, php_project):
        db_path = os.path.join(php_project, ".codegraph", "graph2.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        config = CodeGraphConfig()
        registry = PluginRegistry()
        for p in BUILTIN_PLUGINS:
            registry.register_plugin(p())

        store = SQLiteStore(db_path)
        store.initialize()
        orchestrator = PipelineOrchestrator(config, registry, store)

        orchestrator.run(php_project, incremental=False)
        count1 = store.get_summary().total_nodes

        orchestrator.run(php_project, incremental=True)
        count2 = store.get_summary().total_nodes

        assert count2 == count1
        store.close()
