"""Tests for coderag.launcher.tool_config module."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from coderag.launcher.tool_config import (
    _find_coderag_bin,
    detect_ai_tools,
    write_claude_config,
    write_codex_config,
    write_cursor_config,
    write_tool_config,
)


class TestDetectAiTools:
    """Test detect_ai_tools function."""

    @patch("shutil.which")
    def test_no_tools(self, mock_which):
        mock_which.return_value = None
        tools = detect_ai_tools()
        assert tools == []

    @patch("shutil.which")
    def test_claude_found(self, mock_which):
        def which_side_effect(name):
            return "/usr/bin/claude" if name == "claude" else None

        mock_which.side_effect = which_side_effect
        tools = detect_ai_tools()
        assert "claude" in tools
        assert "cursor" not in tools

    @patch("shutil.which")
    def test_all_tools_found(self, mock_which):
        mock_which.return_value = "/usr/bin/tool"
        tools = detect_ai_tools()
        assert "claude" in tools
        assert "cursor" in tools
        assert "codex" in tools

    @patch("shutil.which")
    def test_cursor_only(self, mock_which):
        def which_side_effect(name):
            return "/usr/bin/cursor" if name == "cursor" else None

        mock_which.side_effect = which_side_effect
        tools = detect_ai_tools()
        assert tools == ["cursor"]


class TestFindCoderagBin:
    """Test _find_coderag_bin helper."""

    @patch("shutil.which")
    def test_found(self, mock_which):
        mock_which.return_value = "/usr/local/bin/coderag"
        assert _find_coderag_bin() == "/usr/local/bin/coderag"

    @patch("shutil.which")
    def test_not_found_fallback(self, mock_which):
        mock_which.return_value = None
        assert _find_coderag_bin() == "coderag"


class TestWriteClaudeConfig:
    """Test write_claude_config function."""

    def test_creates_config(self, tmp_path):
        result = write_claude_config(str(tmp_path), coderag_bin="/usr/bin/coderag")
        assert os.path.isfile(result)
        assert result.endswith("settings.local.json")

        with open(result) as f:
            config = json.load(f)
        assert "mcpServers" in config
        assert "coderag" in config["mcpServers"]
        assert config["mcpServers"]["coderag"]["command"] == "/usr/bin/coderag"

    def test_creates_directory(self, tmp_path):
        write_claude_config(str(tmp_path), coderag_bin="coderag")
        assert os.path.isdir(tmp_path / ".claude")

    def test_preserves_existing_config(self, tmp_path):
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        existing = {"mcpServers": {"other": {"command": "other"}}, "custom": True}
        (config_dir / "settings.local.json").write_text(json.dumps(existing))

        write_claude_config(str(tmp_path), coderag_bin="coderag")

        with open(config_dir / "settings.local.json") as f:
            config = json.load(f)
        assert "other" in config["mcpServers"]
        assert "coderag" in config["mcpServers"]
        assert config["custom"] is True

    def test_handles_corrupt_existing(self, tmp_path):
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        (config_dir / "settings.local.json").write_text("not json")

        result = write_claude_config(str(tmp_path), coderag_bin="coderag")
        with open(result) as f:
            config = json.load(f)
        assert "coderag" in config["mcpServers"]

    def test_includes_project_path_in_args(self, tmp_path):
        write_claude_config(str(tmp_path), coderag_bin="coderag")
        with open(tmp_path / ".claude" / "settings.local.json") as f:
            config = json.load(f)
        args = config["mcpServers"]["coderag"]["args"]
        assert str(tmp_path) in args
        assert "serve" in args


class TestWriteCursorConfig:
    """Test write_cursor_config function."""

    def test_creates_config(self, tmp_path):
        result = write_cursor_config(str(tmp_path), coderag_bin="/usr/bin/coderag")
        assert os.path.isfile(result)
        assert result.endswith("mcp.json")

        with open(result) as f:
            config = json.load(f)
        assert "mcpServers" in config
        assert "coderag" in config["mcpServers"]

    def test_creates_directory(self, tmp_path):
        write_cursor_config(str(tmp_path), coderag_bin="coderag")
        assert os.path.isdir(tmp_path / ".cursor")

    def test_preserves_existing(self, tmp_path):
        config_dir = tmp_path / ".cursor"
        config_dir.mkdir()
        existing = {"mcpServers": {"other": {"command": "other"}}}
        (config_dir / "mcp.json").write_text(json.dumps(existing))

        write_cursor_config(str(tmp_path), coderag_bin="coderag")

        with open(config_dir / "mcp.json") as f:
            config = json.load(f)
        assert "other" in config["mcpServers"]
        assert "coderag" in config["mcpServers"]

    def test_valid_json_output(self, tmp_path):
        result = write_cursor_config(str(tmp_path), coderag_bin="coderag")
        with open(result) as f:
            config = json.load(f)
        assert isinstance(config, dict)


class TestWriteCodexConfig:
    """Test write_codex_config function."""

    def test_creates_config(self, tmp_path):
        result = write_codex_config(str(tmp_path), coderag_bin="/usr/bin/coderag")
        assert os.path.isfile(result)
        assert result.endswith("codex.json")

        with open(result) as f:
            config = json.load(f)
        assert "mcpServers" in config
        assert "coderag" in config["mcpServers"]

    def test_no_subdirectory(self, tmp_path):
        """Codex config is at project root, not in a subdirectory."""
        write_codex_config(str(tmp_path), coderag_bin="coderag")
        assert os.path.isfile(tmp_path / "codex.json")

    def test_preserves_existing(self, tmp_path):
        existing = {"mcpServers": {"other": {"command": "other"}}, "extra": 42}
        (tmp_path / "codex.json").write_text(json.dumps(existing))

        write_codex_config(str(tmp_path), coderag_bin="coderag")

        with open(tmp_path / "codex.json") as f:
            config = json.load(f)
        assert "other" in config["mcpServers"]
        assert "coderag" in config["mcpServers"]
        assert config["extra"] == 42


class TestWriteToolConfig:
    """Test write_tool_config dispatcher."""

    def test_claude(self, tmp_path):
        result = write_tool_config("claude", str(tmp_path), coderag_bin="coderag")
        assert result is not None
        assert "settings.local.json" in result

    def test_cursor(self, tmp_path):
        result = write_tool_config("cursor", str(tmp_path), coderag_bin="coderag")
        assert result is not None
        assert "mcp.json" in result

    def test_codex(self, tmp_path):
        result = write_tool_config("codex", str(tmp_path), coderag_bin="coderag")
        assert result is not None
        assert "codex.json" in result

    def test_unknown_tool(self, tmp_path):
        result = write_tool_config("unknown", str(tmp_path), coderag_bin="coderag")
        assert result is None

    @patch("shutil.which")
    def test_auto_detect_bin(self, mock_which, tmp_path):
        mock_which.return_value = "/usr/local/bin/coderag"
        result = write_tool_config("claude", str(tmp_path))
        assert result is not None
        with open(result) as f:
            config = json.load(f)
        assert config["mcpServers"]["coderag"]["command"] == "/usr/local/bin/coderag"
