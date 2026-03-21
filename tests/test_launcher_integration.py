"""Integration tests for coderag launch command."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderag.cli.main import cli
from coderag.launcher.detector import ProjectState, ProjectStateInfo


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fresh_project(tmp_path):
    """Project with source files but no database."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.php").write_text("<?php echo 1;")
    (src / "utils.js").write_text("export default {};")
    return tmp_path


@pytest.fixture
def ready_project(tmp_path):
    """Project with source files and a current database."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.php").write_text("<?php echo 1;")
    time.sleep(0.05)
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    (db_dir / "graph.db").write_text("fake-db")
    (tmp_path / "codegraph.yaml").write_text("project:\n  name: test-project\n  root: .\n")
    return tmp_path


def _make_ready_state_info(project_path):
    return ProjectStateInfo(
        state=ProjectState.READY,
        db_path=os.path.join(str(project_path), ".codegraph", "graph.db"),
        db_exists=True,
        db_mtime=1000.0,
        source_file_count=2,
        newest_source_mtime=999.0,
        stale_files=[],
    )


def _make_fresh_state_info(project_path):
    return ProjectStateInfo(
        state=ProjectState.FRESH,
        db_path=os.path.join(str(project_path), ".codegraph", "graph.db"),
        db_exists=False,
        source_file_count=2,
    )


class TestLaunchCommandHelp:
    """Test that the launch command is registered and shows help."""

    def test_launch_in_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "launch" in result.output

    def test_launch_help(self, runner):
        result = runner.invoke(cli, ["launch", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--context-only" in result.output
        assert "--token-budget" in result.output
        assert "--tool" in result.output


class TestLaunchDryRun:
    """Test launch --dry-run mode."""

    @patch("coderag.launcher.tool_config.write_tool_config")
    @patch("coderag.launcher.tool_config.detect_ai_tools")
    @patch("coderag.launcher.prompt_gen.write_project_prompt")
    @patch("coderag.launcher.prompt_gen.generate_project_prompt")
    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_dry_run_ready(
        self, mock_detect, mock_open_store, mock_bpc, mock_gpp, mock_wpp, mock_dat, mock_wtc, runner, ready_project
    ):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Context"
        mock_gpp.return_value = "# Prompt"
        mock_wpp.return_value = str(ready_project / "CLAUDE.md")
        mock_dat.return_value = ["claude"]
        mock_wtc.return_value = str(ready_project / ".claude" / "settings.local.json")

        result = runner.invoke(cli, ["launch", str(ready_project), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Dry Run Summary" in result.output

    @patch("coderag.launcher.detector.detect_project_state")
    @patch("coderag.cli.launch._run_parse")
    def test_dry_run_fresh_skips_parse(self, mock_parse, mock_detect, runner, fresh_project):
        mock_detect.return_value = _make_fresh_state_info(fresh_project)

        result = runner.invoke(cli, ["launch", str(fresh_project), "--dry-run"])
        # Dry run should NOT actually parse
        mock_parse.assert_not_called()
        # Should mention dry-run would parse
        assert "dry-run" in result.output.lower() or "would parse" in result.output.lower()


class TestLaunchContextOnly:
    """Test launch --context-only mode."""

    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_context_only_outputs_to_stdout(self, mock_detect, mock_open_store, mock_bpc, runner, ready_project):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Pre-loaded Context\n\nKey files and symbols."

        result = runner.invoke(cli, ["launch", str(ready_project), "--context-only"])
        assert result.exit_code == 0, result.output
        assert "Pre-loaded Context" in result.output

    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_context_only_with_query(self, mock_detect, mock_open_store, mock_bpc, runner, ready_project):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Context with routing info"

        result = runner.invoke(cli, ["launch", str(ready_project), "fix routing", "--context-only"])
        assert result.exit_code == 0, result.output
        mock_bpc.assert_called_once()
        call_kwargs = mock_bpc.call_args
        assert "fix routing" in str(call_kwargs)

    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_context_only_with_token_budget(self, mock_detect, mock_open_store, mock_bpc, runner, ready_project):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Small context"

        result = runner.invoke(cli, ["launch", str(ready_project), "--context-only", "--token-budget", "4000"])
        assert result.exit_code == 0, result.output
        call_kwargs = mock_bpc.call_args
        assert "4000" in str(call_kwargs)


class TestLaunchContextOnlyNoStore:
    """Test --context-only when no store is available."""

    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_context_only_no_db(self, mock_detect, mock_open_store, runner, fresh_project):
        mock_detect.return_value = _make_ready_state_info(fresh_project)
        mock_open_store.return_value = None

        result = runner.invoke(cli, ["launch", str(fresh_project), "--context-only"])
        assert result.exit_code == 0
        assert "No CodeRAG database" in result.output or "No database" in result.output


class TestLaunchConfigCreation:
    """Test that launch creates config files correctly."""

    @patch("coderag.launcher.tool_config.detect_ai_tools")
    @patch("coderag.launcher.prompt_gen.generate_project_prompt")
    @patch("coderag.launcher.prompt_gen.write_project_prompt")
    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_generates_prompt(
        self, mock_detect, mock_open_store, mock_bpc, mock_wpp, mock_gpp, mock_dat, runner, ready_project
    ):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Context"
        mock_gpp.return_value = "# Generated Prompt"
        mock_wpp.return_value = str(ready_project / "CLAUDE.md")
        mock_dat.return_value = []

        result = runner.invoke(cli, ["launch", str(ready_project), "--dry-run"])
        assert result.exit_code == 0, result.output
        mock_gpp.assert_called_once()
        mock_wpp.assert_called_once()


class TestLaunchToolSelection:
    """Test tool selection logic."""

    @patch("coderag.launcher.tool_config.write_tool_config")
    @patch("coderag.launcher.tool_config.detect_ai_tools")
    @patch("coderag.launcher.prompt_gen.write_project_prompt")
    @patch("coderag.launcher.prompt_gen.generate_project_prompt")
    @patch("coderag.launcher.preloader.build_preload_context")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.launcher.detector.detect_project_state")
    def test_explicit_tool_selection(
        self, mock_detect, mock_open_store, mock_bpc, mock_gpp, mock_wpp, mock_dat, mock_wtc, runner, ready_project
    ):
        mock_detect.return_value = _make_ready_state_info(ready_project)
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store
        mock_bpc.return_value = "# Context"
        mock_gpp.return_value = "# Prompt"
        mock_wpp.return_value = str(ready_project / "CLAUDE.md")
        mock_dat.return_value = ["claude", "cursor"]
        mock_wtc.return_value = "/tmp/config.json"

        result = runner.invoke(cli, ["launch", str(ready_project), "--tool", "cursor", "--dry-run"])
        assert result.exit_code == 0, result.output


class TestLaunchEdgeCases:
    """Test edge cases and error handling."""

    def test_nonexistent_path(self, runner):
        result = runner.invoke(cli, ["launch", "/nonexistent/path"])
        assert result.exit_code != 0

    def test_invalid_tool_choice(self, runner, tmp_path):
        result = runner.invoke(cli, ["launch", str(tmp_path), "--tool", "invalid"])
        assert result.exit_code != 0
