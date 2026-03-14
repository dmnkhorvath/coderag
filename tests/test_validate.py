"""Tests for the `coderag validate` CLI command."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from coderag.cli.main import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory with codegraph.yaml."""
    config = tmp_path / "codegraph.yaml"
    config.write_text(
        "project_name: test-project\nlanguages:\n  php:\n    enabled: true\n  python:\n    enabled: true\n"
    )
    return tmp_path


class TestValidateCommand:
    """Tests for `coderag validate`."""

    def test_validate_no_config(self, runner: CliRunner, tmp_path: Path) -> None:
        """Validate fails when no codegraph.yaml exists."""
        os.chdir(tmp_path)
        result = runner.invoke(cli, ["validate"], catch_exceptions=False)
        assert result.exit_code == 1 or "No codegraph.yaml" in result.output

    def test_validate_with_config(self, runner: CliRunner, tmp_project: Path) -> None:
        """Validate succeeds with a valid config file."""
        result = runner.invoke(
            cli,
            ["validate", "--config", str(tmp_project / "codegraph.yaml")],
            catch_exceptions=False,
        )
        assert "Config file" in result.output or "Validation" in result.output

    def test_validate_explicit_config_path(self, runner: CliRunner, tmp_project: Path) -> None:
        """Validate works with explicit --config path."""
        result = runner.invoke(
            cli,
            ["validate", "--config", str(tmp_project / "codegraph.yaml")],
            catch_exceptions=False,
        )
        assert "Config file" in result.output

    def test_validate_missing_config_path(self, runner: CliRunner) -> None:
        """Validate fails with a non-existent config path."""
        result = runner.invoke(
            cli,
            ["validate", "--config", "/nonexistent/codegraph.yaml"],
            catch_exceptions=False,
        )
        assert result.exit_code == 1 or "not found" in result.output

    def test_validate_invalid_yaml(self, runner: CliRunner, tmp_path: Path) -> None:
        """Validate fails with invalid YAML content."""
        bad_config = tmp_path / "codegraph.yaml"
        bad_config.write_text(": invalid: yaml: [[[")
        result = runner.invoke(
            cli,
            ["validate", "--config", str(bad_config)],
            catch_exceptions=False,
        )
        assert (
            result.exit_code == 1
            or "Invalid" in result.output
            or "Malformed" in result.output
            or "Error" in result.output
        )

    def test_validate_plugins_discovered(self, runner: CliRunner, tmp_project: Path) -> None:
        """Validate reports on plugin discovery."""
        result = runner.invoke(
            cli,
            ["validate", "--config", str(tmp_project / "codegraph.yaml")],
            catch_exceptions=False,
        )
        assert "plugin" in result.output.lower() or "language" in result.output.lower()

    def test_validate_shows_in_help(self, runner: CliRunner) -> None:
        """Validate command appears in CLI help."""
        result = runner.invoke(cli, ["--help"])
        assert "validate" in result.output

    def test_validate_help(self, runner: CliRunner) -> None:
        """Validate --help shows usage information."""
        result = runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate" in result.output or "validate" in result.output
