"""Tests for the graph visualization module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from coderag.core.models import Edge, EdgeKind, Node, NodeKind
from coderag.visualization.exporter import (
    GraphExporter,
    _build_json,
    _collect_edges,
    _edge_to_dict,
    _node_to_dict,
    _select_top_nodes,
    _write_json,
)
from coderag.visualization.renderer import GraphRenderer, _escape_html

# ── Helpers ───────────────────────────────────────────────────


def _make_node(
    idx: int,
    *,
    kind: NodeKind = NodeKind.CLASS,
    language: str = "python",
    pagerank: float = 0.0,
    community_id: int | None = None,
    file_path: str | None = None,
) -> Node:
    """Create a test Node with sensible defaults."""
    return Node(
        id=f"test/{idx}:1:{kind.value}:TestSymbol{idx}",
        kind=kind,
        name=f"TestSymbol{idx}",
        qualified_name=f"app.models.TestSymbol{idx}",
        file_path=file_path or f"app/models/test{idx}.py",
        start_line=1,
        end_line=50,
        language=language,
        pagerank=pagerank,
        community_id=community_id,
    )


def _make_edge(
    source_idx: int,
    target_idx: int,
    *,
    kind: EdgeKind = EdgeKind.CALLS,
    confidence: float = 0.85,
) -> Edge:
    """Create a test Edge."""
    return Edge(
        source_id=f"test/{source_idx}:1:class:TestSymbol{source_idx}",
        target_id=f"test/{target_idx}:1:class:TestSymbol{target_idx}",
        kind=kind,
        confidence=confidence,
    )


def _make_mock_store(nodes=None, edges=None):
    """Create a mock SQLiteStore with proper method signatures."""
    store = MagicMock()

    if nodes is None:
        nodes = [_make_node(i, pagerank=1.0 - i * 0.1) for i in range(10)]
    if edges is None:
        edges = [_make_edge(i, (i + 1) % 10) for i in range(10)]

    store.get_all_nodes.return_value = list(nodes)

    # get_edges must handle keyword args: source_id=, target_id=, kind=, min_confidence=
    def _get_edges(source_id=None, target_id=None, kind=None, min_confidence=0.0):
        result = list(edges)
        if source_id is not None:
            result = [e for e in result if e.source_id == source_id]
        if target_id is not None:
            result = [e for e in result if e.target_id == target_id]
        if kind is not None:
            result = [e for e in result if e.kind == kind]
        result = [e for e in result if e.confidence >= min_confidence]
        return result

    store.get_edges.side_effect = _get_edges

    # search_nodes returns nodes matching query in name
    def _search_nodes(query, limit=10, kind=None):
        matches = [n for n in nodes if query.lower() in n.name.lower()]
        return matches[:limit]

    store.search_nodes.side_effect = _search_nodes

    return store


# ── Private Helper Tests ──────────────────────────────────────


class TestPrivateHelpers:
    """Tests for private helper functions in exporter."""

    def test_select_top_nodes_sorts_by_pagerank(self):
        nodes = [
            _make_node(0, pagerank=0.1),
            _make_node(1, pagerank=0.9),
            _make_node(2, pagerank=0.5),
        ]
        result = _select_top_nodes(nodes, 10)
        assert result[0].pagerank == 0.9
        assert result[1].pagerank == 0.5
        assert result[2].pagerank == 0.1

    def test_select_top_nodes_limits(self):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.01) for i in range(20)]
        result = _select_top_nodes(nodes, 5)
        assert len(result) == 5

    def test_select_top_nodes_empty(self):
        assert _select_top_nodes([], 10) == []

    def test_select_top_nodes_max_larger_than_list(self):
        nodes = [_make_node(i) for i in range(3)]
        result = _select_top_nodes(nodes, 100)
        assert len(result) == 3

    def test_collect_edges_filters_by_node_ids(self):
        store = _make_mock_store()
        # Only include nodes 0 and 1
        node_ids = {
            "test/0:1:class:TestSymbol0",
            "test/1:1:class:TestSymbol1",
        }
        result = _collect_edges(store, node_ids)
        # Only edge 0->1 should match (both source and target in set)
        assert all(e.source_id in node_ids and e.target_id in node_ids for e in result)

    def test_collect_edges_empty_node_ids(self):
        store = _make_mock_store()
        result = _collect_edges(store, set())
        assert result == []

    def test_node_to_dict_structure(self):
        node = _make_node(0, pagerank=0.123456, community_id=3)
        d = _node_to_dict(node)
        assert d["id"] == node.id
        assert d["name"] == "TestSymbol0"
        assert d["qualified_name"] == "app.models.TestSymbol0"
        assert d["kind"] == "class"
        assert d["language"] == "python"
        assert d["file"] == "app/models/test0.py"
        assert d["start_line"] == 1
        assert d["end_line"] == 50
        assert d["metrics"]["pagerank"] == 0.123456
        assert d["metrics"]["community_id"] == 3

    def test_node_to_dict_none_community(self):
        node = _make_node(0, community_id=None)
        d = _node_to_dict(node)
        assert d["metrics"]["community_id"] is None

    def test_edge_to_dict_structure(self):
        edge = _make_edge(0, 1, confidence=0.87654)
        d = _edge_to_dict(edge)
        assert d["source"] == edge.source_id
        assert d["target"] == edge.target_id
        assert d["type"] == "calls"
        assert d["confidence"] == 0.8765  # rounded to 4 decimals

    def test_build_json_structure(self):
        nodes = [_make_node(0, language="python"), _make_node(1, language="javascript", kind=NodeKind.FUNCTION)]
        edges = [_make_edge(0, 1)]
        data = _build_json(nodes, edges)
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["metadata"]["total_nodes"] == 2
        assert data["metadata"]["total_edges"] == 1
        assert "python" in data["metadata"]["languages"]
        assert "javascript" in data["metadata"]["languages"]
        assert "class" in data["metadata"]["kinds"]
        assert "function" in data["metadata"]["kinds"]

    def test_build_json_empty(self):
        data = _build_json([], [])
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["metadata"]["total_nodes"] == 0

    def test_write_json_creates_file(self, tmp_path):
        data = {"nodes": [{"id": "n1"}], "edges": [{"source": "n1"}]}
        out = tmp_path / "sub" / "output.json"
        _write_json(data, out)
        assert out.exists()
        assert json.loads(out.read_text()) == data

    def test_write_json_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "a" / "b" / "c" / "output.json"
        _write_json({"nodes": [], "edges": []}, out)
        assert out.exists()


# ── GraphExporter Tests ───────────────────────────────────────


class TestGraphExporter:
    """Tests for GraphExporter."""

    def test_export_full_basic(self, tmp_path):
        store = _make_mock_store()
        output = tmp_path / "graph.json"
        data = GraphExporter.export_full(store, str(output))
        assert output.exists()
        loaded = json.loads(output.read_text())
        assert len(loaded["nodes"]) == 10
        assert len(loaded["edges"]) > 0
        assert loaded["metadata"]["total_nodes"] == 10

    def test_export_full_returns_dict(self, tmp_path):
        store = _make_mock_store()
        result = GraphExporter.export_full(store, tmp_path / "g.json")
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert "metadata" in result

    def test_export_full_max_nodes(self, tmp_path):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.01) for i in range(20)]
        store = _make_mock_store(nodes=nodes)
        data = GraphExporter.export_full(store, tmp_path / "g.json", max_nodes=5)
        assert len(data["nodes"]) == 5

    def test_export_full_node_structure(self, tmp_path):
        store = _make_mock_store()
        data = GraphExporter.export_full(store, tmp_path / "g.json")
        node = data["nodes"][0]
        assert "id" in node
        assert "name" in node
        assert "qualified_name" in node
        assert "kind" in node
        assert "language" in node
        assert "file" in node
        assert "start_line" in node
        assert "end_line" in node
        assert "metrics" in node

    def test_export_full_edge_structure(self, tmp_path):
        store = _make_mock_store()
        data = GraphExporter.export_full(store, tmp_path / "g.json")
        if data["edges"]:
            edge = data["edges"][0]
            assert "source" in edge
            assert "target" in edge
            assert "type" in edge
            assert "confidence" in edge

    def test_export_full_empty_store(self, tmp_path):
        store = _make_mock_store(nodes=[], edges=[])
        data = GraphExporter.export_full(store, tmp_path / "g.json")
        assert len(data["nodes"]) == 0
        assert len(data["edges"]) == 0

    def test_export_filtered_by_language(self, tmp_path):
        nodes = [
            _make_node(0, language="python", pagerank=0.9),
            _make_node(1, language="javascript", pagerank=0.8),
            _make_node(2, language="python", pagerank=0.7),
        ]
        edges = [_make_edge(0, 1), _make_edge(0, 2)]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_filtered(store, tmp_path / "g.json", languages=["python"])
        for node in data["nodes"]:
            assert node["language"] == "python"

    def test_export_filtered_by_kind(self, tmp_path):
        nodes = [
            _make_node(0, kind=NodeKind.CLASS, pagerank=0.9),
            _make_node(1, kind=NodeKind.FUNCTION, pagerank=0.8),
            _make_node(2, kind=NodeKind.CLASS, pagerank=0.7),
        ]
        store = _make_mock_store(nodes=nodes, edges=[])
        data = GraphExporter.export_filtered(store, tmp_path / "g.json", kinds=["class"])
        for node in data["nodes"]:
            assert node["kind"] == "class"

    def test_export_filtered_by_file_pattern(self, tmp_path):
        nodes = [
            _make_node(0, file_path="src/models/user.py", pagerank=0.9),
            _make_node(1, file_path="src/views/home.py", pagerank=0.8),
            _make_node(2, file_path="src/models/post.py", pagerank=0.7),
        ]
        store = _make_mock_store(nodes=nodes, edges=[])
        data = GraphExporter.export_filtered(store, tmp_path / "g.json", file_pattern="models")
        for node in data["nodes"]:
            assert "models" in node["file"]

    def test_export_filtered_combined(self, tmp_path):
        nodes = [
            _make_node(0, kind=NodeKind.CLASS, language="python", file_path="src/models/user.py", pagerank=0.9),
            _make_node(1, kind=NodeKind.FUNCTION, language="python", file_path="src/models/utils.py", pagerank=0.8),
            _make_node(2, kind=NodeKind.CLASS, language="javascript", file_path="src/views/app.js", pagerank=0.7),
        ]
        store = _make_mock_store(nodes=nodes, edges=[])
        data = GraphExporter.export_filtered(
            store,
            tmp_path / "g.json",
            languages=["python"],
            kinds=["class"],
            file_pattern="models",
        )
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["name"] == "TestSymbol0"

    def test_export_filtered_no_filters(self, tmp_path):
        store = _make_mock_store()
        data = GraphExporter.export_filtered(store, tmp_path / "g.json")
        assert len(data["nodes"]) == 10  # no filtering applied

    def test_export_filtered_max_nodes(self, tmp_path):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.01) for i in range(20)]
        store = _make_mock_store(nodes=nodes)
        data = GraphExporter.export_filtered(store, tmp_path / "g.json", max_nodes=3)
        assert len(data["nodes"]) == 3

    def test_export_neighborhood_basic(self, tmp_path):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.1) for i in range(5)]
        edges = [_make_edge(0, 1), _make_edge(1, 2), _make_edge(2, 3), _make_edge(3, 4)]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_neighborhood(
            store,
            tmp_path / "g.json",
            symbol="TestSymbol0",
            depth=1,
        )
        assert len(data["nodes"]) > 0

    def test_export_neighborhood_depth_2(self, tmp_path):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.1) for i in range(5)]
        edges = [_make_edge(0, 1), _make_edge(1, 2), _make_edge(2, 3), _make_edge(3, 4)]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_neighborhood(
            store,
            tmp_path / "g.json",
            symbol="TestSymbol0",
            depth=2,
        )
        # Should include node 0, 1 (depth 1), and 2 (depth 2)
        node_names = {n["name"] for n in data["nodes"]}
        assert "TestSymbol0" in node_names

    def test_export_neighborhood_no_match_raises(self, tmp_path):
        store = _make_mock_store()
        with pytest.raises(ValueError, match="No node found matching"):
            GraphExporter.export_neighborhood(
                store,
                tmp_path / "g.json",
                symbol="NonExistentSymbol",
            )

    def test_export_neighborhood_max_nodes(self, tmp_path):
        nodes = [_make_node(i, pagerank=1.0 - i * 0.01) for i in range(50)]
        edges = [_make_edge(i, i + 1) for i in range(49)]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_neighborhood(
            store,
            tmp_path / "g.json",
            symbol="TestSymbol0",
            depth=10,
            max_nodes=5,
        )
        assert len(data["nodes"]) <= 5

    def test_export_neighborhood_incoming_edges(self, tmp_path):
        """Test BFS traverses incoming edges too."""
        nodes = [_make_node(i, pagerank=0.5) for i in range(3)]
        # Edge goes 1->0 and 2->0, so searching for 0 should find 1 and 2 via incoming
        edges = [
            Edge(
                source_id=nodes[1].id,
                target_id=nodes[0].id,
                kind=EdgeKind.CALLS,
                confidence=0.9,
            ),
            Edge(
                source_id=nodes[2].id,
                target_id=nodes[0].id,
                kind=EdgeKind.CALLS,
                confidence=0.9,
            ),
        ]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_neighborhood(
            store,
            tmp_path / "g.json",
            symbol="TestSymbol0",
            depth=1,
        )
        assert len(data["nodes"]) == 3  # node 0 + incoming from 1 and 2


# ── GraphRenderer Tests ───────────────────────────────────────


class TestGraphRenderer:
    """Tests for GraphRenderer."""

    def _sample_data(self):
        return {
            "nodes": [
                {
                    "id": "n1",
                    "name": "ClassA",
                    "kind": "class",
                    "language": "python",
                    "file": "a.py",
                    "start_line": 1,
                    "end_line": 10,
                    "metrics": {},
                },
                {
                    "id": "n2",
                    "name": "func_b",
                    "kind": "function",
                    "language": "javascript",
                    "file": "b.js",
                    "start_line": 1,
                    "end_line": 5,
                    "metrics": {},
                },
            ],
            "edges": [
                {"source": "n1", "target": "n2", "type": "calls", "confidence": 0.9},
            ],
            "metadata": {"total_nodes": 2, "total_edges": 1, "languages": ["python", "javascript"]},
        }

    def test_render_creates_html(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        assert output.exists()
        content = output.read_text()
        assert "<!DOCTYPE html>" in content

    def test_render_embeds_data(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        content = output.read_text()
        assert "ClassA" in content
        assert "func_b" in content

    def test_render_custom_title(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output), title="My Custom Graph")
        content = output.read_text()
        assert "My Custom Graph" in content

    def test_render_default_title(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        content = output.read_text()
        assert "CodeRAG Visualization" in content

    def test_render_contains_d3(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        content = output.read_text()
        assert "d3" in content.lower()

    def test_render_self_contained(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        content = output.read_text()
        # D3 should be inlined, not loaded from CDN
        assert len(content) > 10000  # D3 is ~280KB minified

    def test_render_with_string_data(self, tmp_path):
        output = tmp_path / "graph.html"
        result = GraphRenderer.render(json.dumps(self._sample_data()), str(output))
        assert output.exists()
        assert isinstance(result, Path)

    def test_render_returns_resolved_path(self, tmp_path):
        output = tmp_path / "graph.html"
        result = GraphRenderer.render(self._sample_data(), str(output))
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_render_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "sub" / "dir" / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output))
        assert output.exists()

    def test_render_large_dataset(self, tmp_path):
        data = {
            "nodes": [
                {
                    "id": f"n{i}",
                    "name": f"Node{i}",
                    "kind": "class",
                    "language": "python",
                    "file": f"f{i}.py",
                    "start_line": 1,
                    "end_line": 10,
                    "metrics": {},
                }
                for i in range(200)
            ],
            "edges": [
                {"source": f"n{i}", "target": f"n{(i + 1) % 200}", "type": "calls", "confidence": 0.8}
                for i in range(200)
            ],
            "metadata": {"total_nodes": 200, "total_edges": 200},
        }
        output = tmp_path / "graph.html"
        GraphRenderer.render(data, str(output))
        assert output.exists()
        assert output.stat().st_size > 1000

    def test_render_empty_graph(self, tmp_path):
        data = {"nodes": [], "edges": [], "metadata": {"total_nodes": 0, "total_edges": 0}}
        output = tmp_path / "graph.html"
        GraphRenderer.render(data, str(output))
        assert output.exists()

    def test_render_special_chars_in_title(self, tmp_path):
        output = tmp_path / "graph.html"
        GraphRenderer.render(self._sample_data(), str(output), title="<b>My & Title</b>")
        content = output.read_text()
        # Title should be HTML-escaped in the <title> tag
        assert "&lt;b&gt;My &amp; Title&lt;/b&gt;" in content


class TestEscapeHtml:
    """Tests for _escape_html helper."""

    def test_escapes_ampersand(self):
        assert _escape_html("a & b") == "a &amp; b"

    def test_escapes_lt_gt(self):
        assert _escape_html("<div>") == "&lt;div&gt;"

    def test_escapes_quotes(self):
        assert _escape_html('say "hello"') == "say &quot;hello&quot;"

    def test_no_escaping_needed(self):
        assert _escape_html("plain text") == "plain text"

    def test_combined(self):
        assert _escape_html('<a href="x">&') == "&lt;a href=&quot;x&quot;&gt;&amp;"


# ── CLI Tests ─────────────────────────────────────────────────


class TestVisualizeCLI:
    """Tests for the visualize CLI command."""

    def test_cli_import(self):
        from coderag.cli.visualize import visualize

        assert callable(visualize)

    def test_cli_help(self):
        from click.testing import CliRunner

        from coderag.cli.visualize import visualize

        runner = CliRunner()
        result = runner.invoke(visualize, ["--help"])
        assert result.exit_code == 0
        assert "visualization" in result.output.lower() or "graph" in result.output.lower()

    def test_cli_format_options(self):
        from click.testing import CliRunner

        from coderag.cli.visualize import visualize

        runner = CliRunner()
        result = runner.invoke(visualize, ["--help"])
        assert "html" in result.output
        assert "json" in result.output

    def test_cli_symbol_option(self):
        from click.testing import CliRunner

        from coderag.cli.visualize import visualize

        runner = CliRunner()
        result = runner.invoke(visualize, ["--help"])
        assert "--symbol" in result.output

    def test_cli_max_nodes_option(self):
        from click.testing import CliRunner

        from coderag.cli.visualize import visualize

        runner = CliRunner()
        result = runner.invoke(visualize, ["--help"])
        assert "--max-nodes" in result.output


# ── Integration Tests ─────────────────────────────────────────


class TestVisualizationIntegration:
    """Integration tests using mock store data."""

    def test_export_and_render_pipeline(self, tmp_path):
        store = _make_mock_store()
        json_path = tmp_path / "graph.json"
        html_path = tmp_path / "graph.html"

        data = GraphExporter.export_full(store, str(json_path))
        assert json_path.exists()

        GraphRenderer.render(data, str(html_path))
        assert html_path.exists()

        content = html_path.read_text()
        assert "TestSymbol0" in content

    def test_filtered_export_and_render(self, tmp_path):
        store = _make_mock_store()
        json_path = tmp_path / "graph.json"
        html_path = tmp_path / "graph.html"

        data = GraphExporter.export_filtered(
            store,
            str(json_path),
            max_nodes=3,
        )
        GraphRenderer.render(data, str(html_path), title="Filtered View")
        content = html_path.read_text()
        assert "Filtered View" in content

    def test_neighborhood_export_and_render(self, tmp_path):
        store = _make_mock_store()
        json_path = tmp_path / "graph.json"
        html_path = tmp_path / "graph.html"

        data = GraphExporter.export_neighborhood(
            store,
            str(json_path),
            symbol="TestSymbol0",
            depth=2,
        )
        GraphRenderer.render(data, str(html_path), title="Neighborhood")
        assert html_path.exists()

    def test_json_roundtrip(self, tmp_path):
        """Test that exported JSON can be loaded and re-rendered."""
        store = _make_mock_store()
        json_path = tmp_path / "graph.json"
        html_path = tmp_path / "graph.html"

        GraphExporter.export_full(store, str(json_path))
        loaded = json.loads(json_path.read_text())
        GraphRenderer.render(loaded, str(html_path))
        assert html_path.exists()

    def test_multi_language_export(self, tmp_path):
        nodes = [
            _make_node(0, language="python", kind=NodeKind.CLASS, pagerank=0.9),
            _make_node(1, language="javascript", kind=NodeKind.FUNCTION, pagerank=0.8),
            _make_node(2, language="php", kind=NodeKind.METHOD, pagerank=0.7),
            _make_node(3, language="typescript", kind=NodeKind.INTERFACE, pagerank=0.6),
        ]
        edges = [_make_edge(0, 1), _make_edge(2, 3)]
        store = _make_mock_store(nodes=nodes, edges=edges)
        data = GraphExporter.export_full(store, tmp_path / "g.json")
        assert set(data["metadata"]["languages"]) == {"python", "javascript", "php", "typescript"}
        assert set(data["metadata"]["kinds"]) == {"class", "function", "method", "interface"}


# ── Docker File Validation ────────────────────────────────────


class TestDockerFiles:
    """Validate Docker configuration files."""

    @pytest.fixture
    def repo_root(self):
        return Path("/tmp/coderag")

    def test_dockerfile_exists(self, repo_root):
        assert (repo_root / "Dockerfile").exists()

    def test_dockerfile_has_multistage(self, repo_root):
        content = (repo_root / "Dockerfile").read_text()
        assert content.count("FROM ") >= 2, "Should have multi-stage build"

    def test_dockerfile_has_entrypoint(self, repo_root):
        content = (repo_root / "Dockerfile").read_text()
        assert "ENTRYPOINT" in content or "entrypoint" in content.lower()

    def test_docker_compose_exists(self, repo_root):
        assert (repo_root / "docker-compose.yml").exists()

    def test_docker_compose_valid_yaml(self, repo_root):
        import yaml

        with open(repo_root / "docker-compose.yml") as f:
            data = yaml.safe_load(f)
        assert "services" in data

    def test_docker_compose_has_services(self, repo_root):
        import yaml

        with open(repo_root / "docker-compose.yml") as f:
            data = yaml.safe_load(f)
        assert "coderag" in data["services"]

    def test_dockerignore_exists(self, repo_root):
        assert (repo_root / ".dockerignore").exists()

    def test_dockerignore_has_key_entries(self, repo_root):
        content = (repo_root / ".dockerignore").read_text()
        for entry in [".git", "__pycache__", "node_modules"]:
            assert entry in content

    def test_entrypoint_exists(self, repo_root):
        entrypoint = repo_root / "scripts" / "docker-entrypoint.sh"
        assert entrypoint.exists()

    def test_entrypoint_executable(self, repo_root):
        entrypoint = repo_root / "scripts" / "docker-entrypoint.sh"
        assert os.access(str(entrypoint), os.X_OK)
