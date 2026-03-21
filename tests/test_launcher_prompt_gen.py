"""Tests for coderag.launcher.prompt_gen module."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from unittest.mock import MagicMock

from coderag.launcher.prompt_gen import (
    _MCP_TOOLS,
    _get_cross_language_summary,
    _get_frameworks_summary,
    _get_languages_summary,
    _get_top_modules,
    generate_project_prompt,
    write_project_prompt,
)

# ── Mock helpers ──────────────────────────────────────────────


@dataclass
class MockGraphSummary:
    project_name: str = "TestProject"
    project_root: str = "/tmp/test"
    db_path: str = "/tmp/test/.codegraph/graph.db"
    db_size_bytes: int = 1024
    last_parsed: str = "2024-01-01"
    total_nodes: int = 100
    total_edges: int = 200
    nodes_by_kind: dict = field(default_factory=lambda: {"class": 10, "function": 50})
    edges_by_kind: dict = field(default_factory=lambda: {"calls": 100, "imports": 100})
    files_by_language: dict = field(default_factory=lambda: {"php": 30, "javascript": 20})
    frameworks: list = field(default_factory=lambda: ["laravel", "react"])
    communities: int = 5
    avg_confidence: float = 0.95
    top_nodes_by_pagerank: list = field(
        default_factory=lambda: [
            ("UserService", "App\\Services\\UserService", 0.05),
            ("Router", "App\\Router", 0.03),
        ]
    )


def _make_mock_store(summary=None):
    store = MagicMock()
    store.get_summary.return_value = summary or MockGraphSummary()
    store.get_stats.return_value = {"total_nodes": 100, "total_edges": 200}
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    store.connection = mock_conn
    return store


def _make_mock_config(name="TestProject", root="/tmp/test"):
    config = MagicMock()
    config.project_name = name
    config.project_root = root
    return config


# ── Tests ─────────────────────────────────────────────────────


class TestGetLanguagesSummary:
    def test_with_languages(self):
        store = _make_mock_store()
        result = _get_languages_summary(store)
        assert "php" in result
        assert "javascript" in result

    def test_no_languages(self):
        summary = MockGraphSummary(files_by_language={})
        store = _make_mock_store(summary=summary)
        result = _get_languages_summary(store)
        assert result == "Unknown"

    def test_error_handling(self):
        store = MagicMock()
        store.get_summary.side_effect = RuntimeError("DB error")
        result = _get_languages_summary(store)
        assert result == "Unknown"


class TestGetFrameworksSummary:
    def test_with_frameworks(self):
        store = _make_mock_store()
        result = _get_frameworks_summary(store)
        assert "laravel" in result
        assert "react" in result

    def test_no_frameworks(self):
        summary = MockGraphSummary(frameworks=[])
        store = _make_mock_store(summary=summary)
        result = _get_frameworks_summary(store)
        assert result == "None detected"

    def test_error_handling(self):
        store = MagicMock()
        store.get_summary.side_effect = RuntimeError("DB error")
        result = _get_frameworks_summary(store)
        assert result == "None detected"


class TestGetTopModules:
    def test_with_modules(self):
        store = _make_mock_store()
        result = _get_top_modules(store)
        assert len(result) == 2
        assert result[0][0] == "UserService"

    def test_limit(self):
        store = _make_mock_store()
        result = _get_top_modules(store, limit=1)
        assert len(result) == 1

    def test_error_handling(self):
        store = MagicMock()
        store.get_summary.side_effect = RuntimeError("DB error")
        result = _get_top_modules(store)
        assert result == []


class TestGetCrossLanguageSummary:
    def test_no_cross_language(self):
        store = _make_mock_store()
        result = _get_cross_language_summary(store)
        assert result == "None detected"

    def test_with_cross_language(self):
        store = _make_mock_store()
        store.connection.execute.return_value.fetchall.return_value = [
            ("api_calls", 5),
            ("api_serves", 3),
        ]
        result = _get_cross_language_summary(store)
        assert "api_calls" in result
        assert "5" in result

    def test_error_handling(self):
        store = MagicMock()
        store.get_stats.side_effect = RuntimeError("DB error")
        store.connection.execute.side_effect = RuntimeError("DB error")
        result = _get_cross_language_summary(store)
        assert result == "None detected"


class TestGenerateProjectPrompt:
    def test_basic_prompt(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "# TestProject" in result
        assert "MCP Tools" in result
        assert isinstance(result, str)

    def test_contains_languages(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "php" in result.lower()

    def test_contains_frameworks(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "laravel" in result.lower()

    def test_contains_mcp_tools(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        for tool_name, _ in _MCP_TOOLS:
            assert tool_name in result

    def test_contains_top_modules(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "UserService" in result

    def test_contains_tips(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "Tips" in result

    def test_fallback_project_name(self):
        store = _make_mock_store()
        config = _make_mock_config(name="", root="/tmp/my-project")
        result = generate_project_prompt(store, config)
        assert "my-project" in result

    def test_no_cross_language_section_when_none(self):
        store = _make_mock_store()
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "Cross-Language" not in result

    def test_with_cross_language_connections(self):
        store = _make_mock_store()
        store.connection.execute.return_value.fetchall.return_value = [
            ("api_calls", 5),
        ]
        config = _make_mock_config()
        result = generate_project_prompt(store, config)
        assert "Cross-Language" in result


class TestWriteProjectPrompt:
    def test_writes_file(self, tmp_path):
        content = "# Test Project\n\nSome content."
        result = write_project_prompt(str(tmp_path), content)
        assert os.path.isfile(result)
        assert result.endswith("CLAUDE.md")
        with open(result) as f:
            assert f.read() == content

    def test_custom_filename(self, tmp_path):
        content = "# Test"
        result = write_project_prompt(str(tmp_path), content, filename=".cursorrules")
        assert result.endswith(".cursorrules")
        assert os.path.isfile(result)

    def test_overwrites_existing(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("old content")
        write_project_prompt(str(tmp_path), "new content")
        with open(tmp_path / "CLAUDE.md") as f:
            assert f.read() == "new content"

    def test_returns_path(self, tmp_path):
        result = write_project_prompt(str(tmp_path), "content")
        assert isinstance(result, str)
        assert os.path.isabs(result) or os.path.exists(result)
