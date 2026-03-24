"""Tests for updater CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from coderag.cli.main import cli


class TestCheckCommand:
    """Tests for coderag update check."""

    def test_check_update_available(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateChecker") as MockChecker, patch("coderag.cli.update.UpdateConfig"):
            mock_info = MagicMock()
            mock_info.current = "0.1.0"
            mock_info.latest = "1.0.0"
            mock_info.update_available = True
            mock_info.release_url = "https://example.com"
            mock_info.published_at = "2026-01-01"
            MockChecker.return_value.check.return_value = mock_info
            result = runner.invoke(cli, ["update", "check"])
            assert result.exit_code == 0
            assert "1.0.0" in result.output
            assert "Update Available" in result.output or "update" in result.output.lower()

    def test_check_up_to_date(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateChecker") as MockChecker, patch("coderag.cli.update.UpdateConfig"):
            mock_info = MagicMock()
            mock_info.current = "0.1.0"
            mock_info.latest = "0.1.0"
            mock_info.update_available = False
            mock_info.release_url = ""
            mock_info.published_at = ""
            MockChecker.return_value.check.return_value = mock_info
            result = runner.invoke(cli, ["update", "check"])
            assert result.exit_code == 0
            assert "Up to date" in result.output or "0.1.0" in result.output

    def test_check_network_error(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateChecker") as MockChecker, patch("coderag.cli.update.UpdateConfig"):
            MockChecker.return_value.check.return_value = None
            result = runner.invoke(cli, ["update", "check"])
            assert result.exit_code == 0
            assert "Could not check" in result.output or "network" in result.output.lower()

    def test_check_force_flag(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateChecker") as MockChecker, patch("coderag.cli.update.UpdateConfig"):
            mock_info = MagicMock()
            mock_info.current = "0.1.0"
            mock_info.latest = "0.1.0"
            mock_info.update_available = False
            mock_info.release_url = ""
            mock_info.published_at = ""
            MockChecker.return_value.check.return_value = mock_info
            result = runner.invoke(cli, ["update", "check", "--force"])
            assert result.exit_code == 0
            MockChecker.return_value.check.assert_called_once_with(force=True)


class TestInstallCommand:
    """Tests for coderag update install."""

    def test_install_success(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateInstaller") as MockInstaller:
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.message = "Updated from 0.1.0 to 1.0.0"
            MockInstaller.return_value.install.return_value = mock_result
            MockInstaller.return_value.strategy = MagicMock()
            MockInstaller.return_value.strategy.value = "pypi"
            result = runner.invoke(cli, ["update", "install"])
            assert result.exit_code == 0
            assert "Updated" in result.output or "Successful" in result.output

    def test_install_failure(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateInstaller") as MockInstaller:
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.message = "pip install failed"
            MockInstaller.return_value.install.return_value = mock_result
            MockInstaller.return_value.strategy = MagicMock()
            MockInstaller.return_value.strategy.value = "pypi"
            result = runner.invoke(cli, ["update", "install"])
            assert result.exit_code == 0
            assert "Failed" in result.output or "failed" in result.output.lower()

    def test_install_with_strategy_git(self):
        runner = CliRunner()
        with (
            patch("coderag.cli.update.UpdateInstaller") as MockInstaller,
            patch("coderag.cli.update.UpdateStrategy") as MockStrategy,
        ):
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.message = "Updated via git"
            MockInstaller.return_value.install.return_value = mock_result
            MockInstaller.return_value.strategy = MagicMock()
            MockInstaller.return_value.strategy.value = "git"
            result = runner.invoke(cli, ["update", "install", "--strategy", "git"])
            assert result.exit_code == 0


class TestConfigCommand:
    """Tests for coderag update config."""

    def test_config_show(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateConfig") as MockConfig:
            mock_cfg = MagicMock()
            mock_cfg.auto_check = True
            mock_cfg.auto_install = False
            mock_cfg.channel = "stable"
            mock_cfg.check_interval = 3600
            mock_cfg.github_repo = "dmnkhorvath/coderag-cli"
            MockConfig.load.return_value = mock_cfg
            result = runner.invoke(cli, ["update", "config"])
            assert result.exit_code == 0
            assert "stable" in result.output
            assert "3600" in result.output

    def test_config_modify(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateConfig") as MockConfig:
            mock_cfg = MagicMock()
            mock_cfg.auto_check = True
            mock_cfg.auto_install = False
            mock_cfg.channel = "stable"
            mock_cfg.check_interval = 3600
            mock_cfg.github_repo = "dmnkhorvath/coderag-cli"
            MockConfig.load.return_value = mock_cfg
            result = runner.invoke(cli, ["update", "config", "--channel", "beta", "--interval", "7200"])
            assert result.exit_code == 0
            mock_cfg.save.assert_called_once()

    def test_config_auto_check_toggle(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateConfig") as MockConfig:
            mock_cfg = MagicMock()
            mock_cfg.auto_check = True
            mock_cfg.auto_install = False
            mock_cfg.channel = "stable"
            mock_cfg.check_interval = 3600
            mock_cfg.github_repo = "dmnkhorvath/coderag-cli"
            MockConfig.load.return_value = mock_cfg
            result = runner.invoke(cli, ["update", "config", "--no-auto-check"])
            assert result.exit_code == 0
            assert mock_cfg.auto_check is False
            mock_cfg.save.assert_called_once()


class TestClearCacheCommand:
    """Tests for coderag update clear-cache."""

    def test_clear_cache(self):
        runner = CliRunner()
        with patch("coderag.cli.update.UpdateChecker") as MockChecker:
            result = runner.invoke(cli, ["update", "clear-cache"])
            assert result.exit_code == 0
            assert "cleared" in result.output.lower()
            MockChecker.return_value.clear_cache.assert_called_once()


class TestUpdateGroupHelp:
    """Tests for update command group."""

    def test_update_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["update", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output
        assert "install" in result.output
        assert "config" in result.output
        assert "clear-cache" in result.output
