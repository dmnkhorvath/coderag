"""Tests for the `coderag grep` CLI command and coderag_grep MCP tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderag.cli.main import cli
from coderag.core.models import NodeKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _make_mock_config():
    cfg = MagicMock()
    cfg.db_path_absolute = "/tmp/test/.codegraph/graph.db"
    cfg.db_path = ".codegraph/graph.db"
    cfg.project_root = "/tmp/test"
    cfg.project_name = "test-project"
    cfg.languages = {"php": {"enabled": True}}
    cfg.ignore_patterns = []
    return cfg


def _make_node(
    name="MyClass",
    qname="App/MyClass",
    kind=None,
    fpath="src/MyClass.php",
    start=10,
    end=50,
    source_text=None,
    pagerank=0.05,
    language="php",
):
    if kind is None:
        kind = NodeKind.CLASS
    node = MagicMock()
    node.id = f"node-{name}"
    node.name = name
    node.qualified_name = qname
    node.kind = kind
    node.language = language
    node.file_path = fpath
    node.start_line = start
    node.end_line = end
    node.source_text = source_text
    node.pagerank = pagerank
    return node


# ---------------------------------------------------------------------------
# CLI grep tests
# ---------------------------------------------------------------------------


class TestGrepCommand:
    """Tests for `coderag grep`."""

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_basic_match(self, mock_config, mock_store, runner):
        """Basic text search finds a match in source_text."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="AuthController",
            source_text="class AuthController:\n    def login(self):\n        # authenticate user\n        pass",
            start=1,
            end=4,
            pagerank=0.1,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "authenticate"])
        assert result.exit_code == 0
        assert "AuthController" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_no_matches(self, mock_config, mock_store, runner):
        """No matches returns a helpful message."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="MyClass",
            source_text="class MyClass:\n    pass",
            start=1,
            end=2,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "nonexistent_pattern_xyz"])
        assert result.exit_code == 0
        assert "No matches found" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_json_output(self, mock_config, mock_store, runner):
        """JSON output format works correctly."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="UserService",
            source_text="class UserService:\n    def create_user(self):\n        # TODO: validate input\n        pass",
            start=1,
            end=4,
            pagerank=0.08,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "TODO", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert data["pattern"] == "TODO"
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "UserService"

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_regex_mode(self, mock_config, mock_store, runner):
        """Regex search works correctly."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="TestHelper",
            source_text="def test_login():\n    assert True\ndef test_logout():\n    assert True",
            start=1,
            end=4,
            pagerank=0.02,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "-r", r"def test_\w+"])
        assert result.exit_code == 0
        assert "TestHelper" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_invalid_regex(self, mock_config, mock_store, runner):
        """Invalid regex pattern shows error."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        store.get_all_nodes.return_value = []
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "-r", "[invalid"])
        assert result.exit_code != 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_kind_filter(self, mock_config, mock_store, runner):
        """Kind filter restricts results to matching node types."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        func_node = _make_node(
            name="login",
            kind=NodeKind.FUNCTION,
            source_text="def login():\n    # authenticate\n    pass",
            start=1,
            end=3,
            pagerank=0.05,
        )
        store.find_nodes.return_value = [func_node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "authenticate", "--kind", "function"])
        assert result.exit_code == 0
        assert "login" in result.output
        store.find_nodes.assert_called_once()

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_invalid_kind(self, mock_config, mock_store, runner):
        """Invalid kind shows error with valid options."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "test", "--kind", "invalid_kind_xyz"])
        assert result.exit_code != 0

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_no_rank(self, mock_config, mock_store, runner):
        """--no-rank disables PageRank sorting."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node1 = _make_node(
            name="LowRank",
            source_text="# TODO: fix this",
            start=1,
            end=1,
            pagerank=0.01,
        )
        node2 = _make_node(
            name="HighRank",
            source_text="# TODO: fix that",
            start=1,
            end=1,
            pagerank=0.99,
        )
        store.get_all_nodes.return_value = [node1, node2]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "TODO", "--no-rank", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        # Without ranking, order should be insertion order (LowRank first)
        assert data["results"][0]["name"] == "LowRank"
        assert data["ranked_by_pagerank"] is False

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_context_lines(self, mock_config, mock_store, runner):
        """Context lines option controls surrounding lines."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        lines = "\n".join([f"line {i}" for i in range(1, 11)])
        node = _make_node(
            name="BigFunc",
            source_text=lines,
            start=1,
            end=10,
            pagerank=0.05,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "line 5", "-C", "1", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        # With context_lines=1, should have 3 lines (1 before, match, 1 after)
        assert len(data["results"][0]["context"]) == 3

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_limit(self, mock_config, mock_store, runner):
        """Limit option restricts number of results."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        nodes = [
            _make_node(
                name=f"Func{i}",
                source_text=f"def func{i}():\n    # TODO\n    pass",
                start=i * 10,
                end=i * 10 + 3,
                pagerank=0.01 * i,
            )
            for i in range(1, 6)
        ]
        store.get_all_nodes.return_value = nodes
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "TODO", "--limit", "2", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert len(data["results"]) == 2

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_excludes_external_nodes(self, mock_config, mock_store, runner):
        """External nodes are excluded from search."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        external = _make_node(
            name="ExternalLib",
            source_text="# TODO: external",
            fpath="<external>",
            start=1,
            end=1,
        )
        internal = _make_node(
            name="InternalClass",
            source_text="# TODO: internal",
            fpath="src/internal.php",
            start=1,
            end=1,
        )
        store.get_all_nodes.return_value = [external, internal]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "TODO", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "InternalClass"

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_case_insensitive(self, mock_config, mock_store, runner):
        """Text search is case-insensitive."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="MyClass",
            source_text="class MyClass:\n    IMPORTANT_CONSTANT = 42",
            start=1,
            end=2,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "important_constant", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert len(data["results"]) == 1

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_nodes_without_source_text_skipped(self, mock_config, mock_store, runner):
        """Nodes without source_text are skipped in strategy 1."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="NoSource",
            source_text=None,
            start=1,
            end=10,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""  # no project root, so no file fallback

        result = runner.invoke(cli, ["grep", "anything"])
        assert result.exit_code == 0
        assert "No matches found" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_pagerank_ranking(self, mock_config, mock_store, runner):
        """Results are sorted by PageRank by default."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        low = _make_node(
            name="LowRank",
            source_text="# TODO: low",
            start=1,
            end=1,
            pagerank=0.01,
        )
        high = _make_node(
            name="HighRank",
            source_text="# TODO: high",
            start=1,
            end=1,
            pagerank=0.99,
        )
        store.get_all_nodes.return_value = [low, high]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "TODO", "--format", "json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        # HighRank should be first due to PageRank sorting
        assert data["results"][0]["name"] == "HighRank"
        assert data["ranked_by_pagerank"] is True

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_markdown_output(self, mock_config, mock_store, runner):
        """Default markdown output includes table and context."""
        mock_config.return_value = _make_mock_config()
        store = MagicMock()
        mock_store.return_value = store

        node = _make_node(
            name="Router",
            source_text="class Router:\n    def dispatch(self):\n        # handle request\n        pass",
            start=1,
            end=4,
            pagerank=0.15,
        )
        store.get_all_nodes.return_value = [node]
        store.get_metadata.return_value = ""

        result = runner.invoke(cli, ["grep", "handle request"])
        assert result.exit_code == 0
        assert "Router" in result.output
        # Should contain context output
        assert "handle request" in result.output

    @patch("coderag.cli.main._open_store")
    @patch("coderag.cli.main._load_config")
    def test_grep_help(self, mock_config, mock_store, runner):
        """Grep help text is displayed."""
        result = runner.invoke(cli, ["grep", "--help"])
        assert result.exit_code == 0
        assert "Search source code content" in result.output
        assert "--regex" in result.output
        assert "--kind" in result.output
        assert "--context-lines" in result.output
        assert "--format" in result.output
        assert "--rank" in result.output
