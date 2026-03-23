"""Tests for coderag.cli.launch to push coverage from 62% to 90%+.

Covers: _load_config_for_launch, _open_store_for_launch, _run_parse,
        _detect_best_tool, _check_for_updates_on_launch, launch command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from coderag.cli.launch import (
    _check_for_updates_on_launch,
    _detect_best_tool,
    _load_config_for_launch,
    _open_store_for_launch,
    _run_parse,
    launch,
)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _load_config_for_launch
# ---------------------------------------------------------------------------


class TestLoadConfigForLaunch:
    def test_explicit_config_path(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.core.config.CodeGraphConfig.from_yaml") as mock_from:
            mock_cfg = MagicMock()
            mock_from.return_value = mock_cfg
            result = _load_config_for_launch(str(tmp_path), config_path=str(cfg_file))
            mock_from.assert_called_once_with(str(cfg_file))
            assert result.project_root == str(Path(tmp_path).resolve())

    def test_common_location_yaml(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.core.config.CodeGraphConfig.from_yaml") as mock_from:
            mock_cfg = MagicMock()
            mock_from.return_value = mock_cfg
            result = _load_config_for_launch(str(tmp_path))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_common_location_yml(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.core.config.CodeGraphConfig.from_yaml") as mock_from:
            mock_cfg = MagicMock()
            mock_from.return_value = mock_cfg
            result = _load_config_for_launch(str(tmp_path))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_common_location_dot_codegraph(self, tmp_path):
        cfg_file = tmp_path / ".codegraph.yaml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.core.config.CodeGraphConfig.from_yaml") as mock_from:
            mock_cfg = MagicMock()
            mock_from.return_value = mock_cfg
            result = _load_config_for_launch(str(tmp_path))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_default_config(self, tmp_path):
        with patch("coderag.core.config.CodeGraphConfig.default") as mock_default:
            mock_cfg = MagicMock()
            mock_default.return_value = mock_cfg
            result = _load_config_for_launch(str(tmp_path))
            mock_default.assert_called_once()
            assert result.project_root == str(Path(tmp_path).resolve())
            assert result.project_name == Path(tmp_path).name


# ---------------------------------------------------------------------------
# _open_store_for_launch
# ---------------------------------------------------------------------------


class TestOpenStoreForLaunch:
    def test_returns_none_when_no_db(self, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "nonexistent.db")
        result = _open_store_for_launch(mock_config)
        assert result is None

    def test_opens_store_when_db_exists(self, tmp_path):
        db_file = tmp_path / "graph.db"
        db_file.write_text("")
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(db_file)
        mock_store = MagicMock()
        with patch("coderag.storage.sqlite_store.SQLiteStore", return_value=mock_store):
            result = _open_store_for_launch(mock_config)
            assert result == mock_store
            mock_store.initialize.assert_called_once()


# ---------------------------------------------------------------------------
# _run_parse
# ---------------------------------------------------------------------------


class TestRunParse:
    @patch("shutil.which", return_value="/usr/bin/coderag")
    @patch("subprocess.run")
    def test_run_parse_success(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _run_parse("/tmp/project")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/coderag"
        assert "parse" in cmd

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_run_parse_no_binary_uses_module(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _run_parse("/tmp/project")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "-m" in cmd

    @patch("shutil.which", return_value="/usr/bin/coderag")
    @patch("subprocess.run")
    def test_run_parse_with_config(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _run_parse("/tmp/project", config_path="/tmp/config.yaml")
        cmd = mock_run.call_args[0][0]
        assert "--config" in cmd
        assert "/tmp/config.yaml" in cmd

    @patch("shutil.which", return_value="/usr/bin/coderag")
    @patch("subprocess.run")
    def test_run_parse_failure(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1)
        result = _run_parse("/tmp/project")
        assert result is False

    @patch("shutil.which", return_value="/usr/bin/coderag")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="coderag", timeout=600))
    def test_run_parse_timeout(self, mock_run, mock_which):
        result = _run_parse("/tmp/project")
        assert result is False

    @patch("shutil.which", return_value="/usr/bin/coderag")
    @patch("subprocess.run", side_effect=OSError("No such file"))
    def test_run_parse_oserror(self, mock_run, mock_which):
        result = _run_parse("/tmp/project")
        assert result is False


# ---------------------------------------------------------------------------
# _detect_best_tool
# ---------------------------------------------------------------------------


class TestDetectBestTool:
    def test_detect_claude(self):
        with patch("coderag.launcher.tool_config.detect_ai_tools", return_value={"claude": "/usr/bin/claude"}):
            result = _detect_best_tool()
            assert result == "claude"

    def test_detect_cursor(self):
        with patch("coderag.launcher.tool_config.detect_ai_tools", return_value={"cursor": "/usr/bin/cursor"}):
            result = _detect_best_tool()
            assert result == "cursor"

    def test_detect_codex(self):
        with patch("coderag.launcher.tool_config.detect_ai_tools", return_value={"codex": "/usr/bin/codex"}):
            result = _detect_best_tool()
            assert result == "codex"

    def test_detect_none(self):
        with patch("coderag.launcher.tool_config.detect_ai_tools", return_value={}):
            result = _detect_best_tool()
            assert result is None

    def test_detect_prefers_claude(self):
        with patch(
            "coderag.launcher.tool_config.detect_ai_tools",
            return_value={"cursor": "/usr/bin/cursor", "claude": "/usr/bin/claude"},
        ):
            result = _detect_best_tool()
            assert result == "claude"


# ---------------------------------------------------------------------------
# _check_for_updates_on_launch
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    def test_no_update_available(self):
        mock_config = MagicMock()
        mock_config.auto_check = True
        mock_config.auto_install = False
        mock_checker = MagicMock()
        mock_checker.check.return_value = None
        with (
            patch("coderag.updater.config.UpdateConfig.load", return_value=mock_config),
            patch("coderag.updater.checker.UpdateChecker", return_value=mock_checker),
        ):
            _check_for_updates_on_launch()  # should not raise

    def test_update_available(self):
        mock_config = MagicMock()
        mock_config.auto_check = True
        mock_config.auto_install = False
        mock_info = MagicMock()
        mock_info.update_available = True
        mock_info.latest = "2.0.0"
        mock_info.current = "1.0.0"
        mock_checker = MagicMock()
        mock_checker.check.return_value = mock_info
        with (
            patch("coderag.updater.config.UpdateConfig.load", return_value=mock_config),
            patch("coderag.updater.checker.UpdateChecker", return_value=mock_checker),
        ):
            _check_for_updates_on_launch()  # should not raise

    def test_auto_install(self):
        mock_config = MagicMock()
        mock_config.auto_check = True
        mock_config.auto_install = True
        mock_info = MagicMock()
        mock_info.update_available = True
        mock_info.latest = "2.0.0"
        mock_info.current = "1.0.0"
        mock_checker = MagicMock()
        mock_checker.check.return_value = mock_info
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.new_version = "2.0.0"
        mock_installer = MagicMock()
        mock_installer.install.return_value = mock_result
        with (
            patch("coderag.updater.config.UpdateConfig.load", return_value=mock_config),
            patch("coderag.updater.checker.UpdateChecker", return_value=mock_checker),
            patch("coderag.updater.installer.UpdateInstaller", return_value=mock_installer),
        ):
            _check_for_updates_on_launch()  # should not raise

    def test_auto_check_disabled(self):
        mock_config = MagicMock()
        mock_config.auto_check = False
        with patch("coderag.updater.config.UpdateConfig.load", return_value=mock_config):
            _check_for_updates_on_launch()  # should return early

    def test_exception_swallowed(self):
        with patch("coderag.updater.config.UpdateConfig.load", side_effect=ImportError("no module")):
            _check_for_updates_on_launch()  # should not raise


# ---------------------------------------------------------------------------
# launch command
# ---------------------------------------------------------------------------


class TestLaunchCommand:
    def _mock_state(self, state_val="ready", source_files=10, stale_files=None):
        mock_state_info = MagicMock()
        mock_state_enum = MagicMock()
        mock_state_enum.value = state_val
        mock_state_info.state = mock_state_enum
        mock_state_info.source_file_count = source_files
        mock_state_info.stale_files = stale_files or []
        return mock_state_info

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_context_only(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        state_info = self._mock_state()

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="# Context here"),
        ):
            result = runner.invoke(launch, [str(tmp_path), "--context-only"], obj={})
            assert result.exit_code == 0
            assert "Context here" in result.output

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch", return_value=None)
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_no_store_context_only(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config

        state_info = self._mock_state()

        with patch("coderag.launcher.detector.detect_project_state", return_value=state_info):
            result = runner.invoke(launch, [str(tmp_path), "--context-only"], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch", return_value=None)
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_no_store_dry_run(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config

        state_info = self._mock_state()

        with patch("coderag.launcher.detector.detect_project_state", return_value=state_info):
            result = runner.invoke(launch, [str(tmp_path), "--dry-run"], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch", return_value=None)
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_no_store_exits(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config

        state_info = self._mock_state()

        with patch("coderag.launcher.detector.detect_project_state", return_value=state_info):
            result = runner.invoke(launch, [str(tmp_path)], obj={})
            assert result.exit_code != 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_dry_run(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        state_info = self._mock_state()

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.cli.launch._detect_best_tool", return_value="claude"),
            patch(
                "coderag.launcher.tool_config.write_tool_config", return_value=str(tmp_path / ".claude/settings.json")
            ),
        ):
            result = runner.invoke(launch, [str(tmp_path), "--dry-run"], obj={})
            assert result.exit_code == 0
            assert "Dry Run" in result.output

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._run_parse", return_value=True)
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_fresh_project_parses(
        self, mock_load_cfg, mock_open_store, mock_parse, mock_updates, runner, tmp_path
    ):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        # Create a "fresh" state
        from coderag.launcher.detector import ProjectState

        state_info = MagicMock()
        state_info.state = ProjectState.FRESH
        state_info.source_file_count = 10
        state_info.stale_files = []

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.cli.launch._detect_best_tool", return_value=None),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=None),
        ):
            result = runner.invoke(launch, [str(tmp_path)], obj={})
            assert result.exit_code == 0
            mock_parse.assert_called_once()

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._run_parse", return_value=True)
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_stale_project_parses(
        self, mock_load_cfg, mock_open_store, mock_parse, mock_updates, runner, tmp_path
    ):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        from coderag.launcher.detector import ProjectState

        state_info = MagicMock()
        state_info.state = ProjectState.STALE
        state_info.source_file_count = 10
        state_info.stale_files = ["file1.py", "file2.py"]

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.cli.launch._detect_best_tool", return_value=None),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=None),
        ):
            result = runner.invoke(launch, [str(tmp_path)], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._run_parse", return_value=False)
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_parse_failure_exits(
        self, mock_load_cfg, mock_open_store, mock_parse, mock_updates, runner, tmp_path
    ):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        from coderag.launcher.detector import ProjectState

        state_info = MagicMock()
        state_info.state = ProjectState.FRESH
        state_info.source_file_count = 10
        state_info.stale_files = []

        with patch("coderag.launcher.detector.detect_project_state", return_value=state_info):
            result = runner.invoke(launch, [str(tmp_path)], obj={})
            assert result.exit_code != 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_with_tool_and_prompt(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        state_info = self._mock_state()
        mock_mcp_proc = MagicMock()
        mock_mcp_proc.pid = 123
        mock_tool_proc = MagicMock()
        mock_tool_proc.pid = 456

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=str(tmp_path / "config.json")),
            patch("coderag.launcher.runner.launch_mcp_server", return_value=mock_mcp_proc),
            patch("coderag.launcher.runner.launch_tool", return_value=mock_tool_proc),
            patch("coderag.launcher.runner.stop_process"),
        ):
            result = runner.invoke(launch, [str(tmp_path), "test prompt", "--tool", "claude-code"], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_mcp_server_fails(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        state_info = self._mock_state()
        mock_tool_proc = MagicMock()
        mock_tool_proc.pid = 456

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=str(tmp_path / "config.json")),
            patch("coderag.launcher.runner.launch_mcp_server", side_effect=FileNotFoundError("not found")),
            patch("coderag.launcher.runner.launch_tool", return_value=mock_tool_proc),
            patch("coderag.launcher.runner.stop_process"),
        ):
            result = runner.invoke(launch, [str(tmp_path), "--tool", "claude-code"], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_tool_fails(self, mock_load_cfg, mock_open_store, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        state_info = self._mock_state()
        mock_mcp_proc = MagicMock()
        mock_mcp_proc.pid = 123

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=str(tmp_path / "config.json")),
            patch("coderag.launcher.runner.launch_mcp_server", return_value=mock_mcp_proc),
            patch("coderag.launcher.runner.launch_tool", side_effect=FileNotFoundError("not found")),
            patch("coderag.launcher.runner.stop_process"),
        ):
            result = runner.invoke(launch, [str(tmp_path), "--tool", "claude-code"], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.launch._check_for_updates_on_launch")
    @patch("coderag.cli.launch._run_parse", return_value=True)
    @patch("coderag.cli.launch._open_store_for_launch")
    @patch("coderag.cli.launch._load_config_for_launch")
    def test_launch_fresh_dry_run(self, mock_load_cfg, mock_open_store, mock_parse, mock_updates, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        from coderag.launcher.detector import ProjectState

        state_info = MagicMock()
        state_info.state = ProjectState.FRESH
        state_info.source_file_count = 10
        state_info.stale_files = []

        with (
            patch("coderag.launcher.detector.detect_project_state", return_value=state_info),
            patch("coderag.launcher.preloader.build_preload_context", return_value="ctx"),
            patch("coderag.launcher.prompt_gen.generate_project_prompt", return_value="prompt"),
            patch("coderag.launcher.prompt_gen.write_project_prompt", return_value=str(tmp_path / "CLAUDE.md")),
            patch("coderag.cli.launch._detect_best_tool", return_value=None),
            patch("coderag.launcher.tool_config.write_tool_config", return_value=None),
        ):
            result = runner.invoke(launch, [str(tmp_path), "test prompt", "--dry-run"], obj={})
            assert result.exit_code == 0
            assert "dry-run" in result.output.lower() or "Dry Run" in result.output
