"""Tests for PHPStan enrichment module."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from coderag.enrichment.phpstan import (
    EnrichmentReport,
    PHPStanEnricher,
    PHPStanResult,
    _extract_type_from_message,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path):
    """Create a temporary project root with PHP files."""
    php_dir = tmp_path / "app"
    php_dir.mkdir()
    (php_dir / "User.php").write_text(
        "<?php\nnamespace App;\nclass User {\n    public function getName() { return 1; }\n}\n"
    )
    (php_dir / "Controller.php").write_text(
        "<?php\nnamespace App;\nclass Controller {\n    public function index() { return 1; }\n}\n"
    )
    return str(tmp_path)


@pytest.fixture
def enricher(project_root):
    """Create a PHPStanEnricher instance."""
    return PHPStanEnricher(project_root=project_root, level=5)


@pytest.fixture
def sample_phpstan_output():
    """Sample PHPStan JSON output."""
    return json.dumps(
        {
            "totals": {"errors": 0, "file_errors": 3},
            "files": {
                "/tmp/project/app/User.php": {
                    "errors": 2,
                    "messages": [
                        {
                            "message": "Method App\\User::getName() has no return type specified.",
                            "line": 4,
                            "ignorable": True,
                            "identifier": "missingType.return",
                            "tip": "Add a return type to the method.",
                        },
                        {
                            "message": "Property App\\User::$name has no type specified.",
                            "line": 3,
                            "ignorable": True,
                            "identifier": "missingType.property",
                            "tip": None,
                        },
                    ],
                },
                "/tmp/project/app/Controller.php": {
                    "errors": 1,
                    "messages": [
                        {
                            "message": "Method App\\Controller::index() should return string but returns Illuminate\\View\\View.",
                            "line": 4,
                            "ignorable": False,
                            "identifier": "return.type",
                            "tip": None,
                        },
                    ],
                },
            },
            "errors": [],
        }
    )


@pytest.fixture
def mock_store():
    """Create a mock SQLiteStore."""
    store = MagicMock()
    return store


# ── PHPStanResult Tests ───────────────────────────────────────────


class TestPHPStanResult:
    """Tests for the PHPStanResult dataclass."""

    def test_create_result(self):
        result = PHPStanResult(
            file_path="app/User.php",
            line=10,
            message="Method has no return type.",
            identifier="missingType.return",
            tip="Add return type.",
        )
        assert result.file_path == "app/User.php"
        assert result.line == 10
        assert result.message == "Method has no return type."
        assert result.identifier == "missingType.return"
        assert result.tip == "Add return type."
        assert result.ignorable is True

    def test_result_is_frozen(self):
        result = PHPStanResult(file_path="test.php", line=1, message="test")
        with pytest.raises(AttributeError):
            result.line = 5  # type: ignore

    def test_result_defaults(self):
        result = PHPStanResult(file_path="test.php", line=1, message="test")
        assert result.identifier is None
        assert result.tip is None
        assert result.ignorable is True


# ── EnrichmentReport Tests ────────────────────────────────────────


class TestEnrichmentReport:
    """Tests for the EnrichmentReport dataclass."""

    def test_default_report(self):
        report = EnrichmentReport()
        assert report.files_analyzed == 0
        assert report.errors_found == 0
        assert report.nodes_enriched == 0
        assert report.duration_ms == 0.0
        assert report.phpstan_version == ""
        assert report.level == 5
        assert report.skipped_reason is None

    def test_report_with_values(self):
        report = EnrichmentReport(
            files_analyzed=10,
            errors_found=25,
            nodes_enriched=8,
            duration_ms=1500.5,
            phpstan_version="1.10.0",
            level=8,
        )
        assert report.files_analyzed == 10
        assert report.errors_found == 25
        assert report.nodes_enriched == 8
        assert report.duration_ms == 1500.5
        assert report.phpstan_version == "1.10.0"
        assert report.level == 8

    def test_report_skipped(self):
        report = EnrichmentReport(skipped_reason="PHPStan not available")
        assert report.skipped_reason == "PHPStan not available"


# ── Type Extraction Tests ─────────────────────────────────────────


class TestTypeExtraction:
    """Tests for _extract_type_from_message."""

    def test_extract_return_type_mismatch(self):
        msg = "Method App\\User::getName() should return string but returns int."
        info = _extract_type_from_message(msg)
        assert info["expected_return_type"] == "string"
        assert info["actual_return_type"] == "int"

    def test_extract_missing_return_type(self):
        msg = "Method App\\User::getName() has no return type specified."
        info = _extract_type_from_message(msg)
        assert info["missing"] == "return_type"

    def test_extract_missing_parameter_type(self):
        msg = "Parameter $name of method App\\User::setName() has no type specified."
        info = _extract_type_from_message(msg)
        assert info["missing"] == "parameter_type"
        assert info["parameter_name"] == "$name"

    def test_extract_missing_property_type(self):
        msg = "Property App\\User::$name has no type specified."
        info = _extract_type_from_message(msg)
        assert info["missing"] == "property_type"

    def test_extract_expects_given(self):
        msg = "Parameter #1 $id of method App\\User::find() expects int, string given."
        info = _extract_type_from_message(msg)
        assert info["expected_type"] == "int"

    def test_extract_missing_return_value_type(self):
        msg = "Method App\\User::getItems() return type has no value type specified in iterable type array."
        info = _extract_type_from_message(msg)
        assert info["missing"] == "return_value_type"

    def test_extract_phpdoc_return(self):
        msg = "PHPDoc tag @return with type Collection is not subtype of native type array."
        info = _extract_type_from_message(msg)
        assert info["phpdoc_return_type"] == "Collection"

    def test_extract_phpdoc_param(self):
        msg = "PHPDoc tag @param for parameter $user with type User is not subtype of native type Model."
        info = _extract_type_from_message(msg)
        assert info["phpdoc_param_type"] == "User"

    def test_extract_unknown_message(self):
        msg = "Some completely unrelated message."
        info = _extract_type_from_message(msg)
        assert info == {}


# ── PHPStanEnricher Availability Tests ────────────────────────────


class TestPHPStanAvailability:
    """Tests for PHPStan availability checking."""

    def test_available_when_phpstan_found(self, enricher):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHPStan - PHP Static Analysis Tool 1.10.0"

        with patch("subprocess.run", return_value=mock_result):
            assert enricher.is_available() is True

    def test_not_available_when_not_found(self, enricher):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert enricher.is_available() is False

    def test_not_available_on_timeout(self, enricher):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("phpstan", 10)):
            assert enricher.is_available() is False

    def test_not_available_on_nonzero_exit(self, enricher):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            assert enricher.is_available() is False

    def test_version_parsed(self, enricher):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHPStan - PHP Static Analysis Tool 1.10.0"

        with patch("subprocess.run", return_value=mock_result):
            enricher.is_available()
            assert enricher.get_version() == "1.10.0"

    def test_vendor_bin_fallback(self, project_root):
        """Test that enricher checks vendor/bin/phpstan as fallback."""
        enricher = PHPStanEnricher(project_root=project_root, phpstan_path="nonexistent")

        call_count = [0]

        def mock_run(cmd, **kwargs):
            call_count[0] += 1
            if "nonexistent" in cmd[0]:
                raise FileNotFoundError
            result = MagicMock()
            result.returncode = 0
            result.stdout = "PHPStan - PHP Static Analysis Tool 1.11.0"
            return result

        with patch("subprocess.run", side_effect=mock_run):
            assert enricher.is_available() is True
            assert call_count[0] == 2


# ── PHPStan JSON Parsing Tests ────────────────────────────────────


class TestPHPStanParsing:
    """Tests for PHPStan JSON output parsing."""

    def test_parse_valid_output(self, enricher, sample_phpstan_output):
        results = enricher._parse_json_output(sample_phpstan_output)
        assert len(results) == 2

    def test_parse_messages(self, enricher, sample_phpstan_output):
        enricher._project_root = "/tmp/project"
        results = enricher._parse_json_output(sample_phpstan_output)
        user_results = results.get("app/User.php", [])
        assert len(user_results) == 2
        assert user_results[0].line == 4
        assert "no return type" in user_results[0].message
        assert user_results[0].identifier == "missingType.return"
        assert user_results[0].tip == "Add a return type to the method."

    def test_parse_controller_results(self, enricher, sample_phpstan_output):
        enricher._project_root = "/tmp/project"
        results = enricher._parse_json_output(sample_phpstan_output)
        ctrl_results = results.get("app/Controller.php", [])
        assert len(ctrl_results) == 1
        assert ctrl_results[0].identifier == "return.type"
        assert ctrl_results[0].ignorable is False

    def test_parse_empty_output(self, enricher):
        results = enricher._parse_json_output("{}")
        assert results == {}

    def test_parse_invalid_json(self, enricher):
        results = enricher._parse_json_output("not json at all")
        assert results == {}

    def test_parse_json_with_prefix(self, enricher):
        """PHPStan sometimes prepends text before JSON."""
        enricher._project_root = "/tmp/project"
        data = {
            "totals": {"errors": 0, "file_errors": 1},
            "files": {
                "/tmp/project/app/Test.php": {
                    "errors": 1,
                    "messages": [
                        {
                            "message": "Test error.",
                            "line": 1,
                            "ignorable": True,
                        }
                    ],
                },
            },
            "errors": [],
        }
        prefixed = "Note: Using configuration file /tmp/phpstan.neon.\n" + json.dumps(data)
        results = enricher._parse_json_output(prefixed)
        assert len(results) == 1

    def test_parse_no_files(self, enricher):
        output = json.dumps(
            {
                "totals": {"errors": 0, "file_errors": 0},
                "files": {},
                "errors": [],
            }
        )
        results = enricher._parse_json_output(output)
        assert results == {}


# ── PHPStan Analysis Tests ────────────────────────────────────────


class TestPHPStanAnalysis:
    """Tests for running PHPStan analysis."""

    def test_analyze_raises_when_not_available(self, enricher):
        with patch.object(enricher, "is_available", return_value=False):
            with pytest.raises(RuntimeError, match="not available"):
                enricher.analyze()

    def test_analyze_runs_subprocess(self, enricher, sample_phpstan_output):
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "PHPStan - PHP Static Analysis Tool 1.10.0"

        analyze_result = MagicMock()
        analyze_result.returncode = 1
        analyze_result.stdout = sample_phpstan_output
        analyze_result.stderr = ""

        with patch("subprocess.run", side_effect=[version_result, analyze_result]):
            results = enricher.analyze()
            assert len(results) >= 1

    def test_analyze_with_specific_files(self, enricher, sample_phpstan_output):
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "PHPStan 1.10.0"

        analyze_result = MagicMock()
        analyze_result.returncode = 0
        analyze_result.stdout = sample_phpstan_output

        with patch("subprocess.run", side_effect=[version_result, analyze_result]) as mock_run:
            enricher.analyze(files=["app/User.php"])
            call_args = mock_run.call_args_list[1]
            assert "app/User.php" in call_args[0][0]

    def test_analyze_handles_timeout(self, enricher):
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "PHPStan 1.10.0"

        with patch(
            "subprocess.run",
            side_effect=[
                version_result,
                subprocess.TimeoutExpired("phpstan", 300),
            ],
        ):
            results = enricher.analyze()
            assert results == {}

    def test_analyze_handles_empty_output(self, enricher):
        version_result = MagicMock()
        version_result.returncode = 0
        version_result.stdout = "PHPStan 1.10.0"

        analyze_result = MagicMock()
        analyze_result.returncode = 0
        analyze_result.stdout = ""

        with patch("subprocess.run", side_effect=[version_result, analyze_result]):
            results = enricher.analyze()
            assert results == {}


# ── Node Enrichment Tests ─────────────────────────────────────────


class TestNodeEnrichment:
    """Tests for enriching nodes with PHPStan data."""

    def test_enrich_skips_when_not_available(self, enricher, mock_store):
        with patch.object(enricher, "is_available", return_value=False):
            report = enricher.enrich_nodes(mock_store)
            assert report.skipped_reason == "PHPStan not available"
            assert report.nodes_enriched == 0

    def test_enrich_with_matching_nodes(self, enricher, mock_store):
        """Test that nodes within PHPStan result line ranges get enriched."""
        enricher._project_root = "/tmp/project"
        enricher._last_results = {
            "app/User.php": [
                PHPStanResult(
                    file_path="/tmp/project/app/User.php",
                    line=4,
                    message="Method App\\User::getName() has no return type specified.",
                    identifier="missingType.return",
                ),
            ],
        }

        mock_node = MagicMock()
        mock_node.start_line = 3
        mock_node.end_line = 5
        mock_node.metadata = {}

        mock_store.find_nodes.return_value = [mock_node]

        with patch.object(enricher, "is_available", return_value=True):
            enricher._version = "1.10.0"
            report = enricher.enrich_nodes(mock_store)

        assert report.nodes_enriched == 1
        assert report.files_analyzed == 1
        assert report.errors_found == 1
        assert "phpstan" in mock_node.metadata
        assert mock_node.metadata["phpstan"]["issue_count"] == 1

    def test_enrich_no_matching_nodes(self, enricher, mock_store):
        """Test that nodes outside PHPStan result line ranges are not enriched."""
        enricher._project_root = "/tmp/project"
        enricher._last_results = {
            "app/User.php": [
                PHPStanResult(
                    file_path="/tmp/project/app/User.php",
                    line=100,
                    message="Some error.",
                ),
            ],
        }

        mock_node = MagicMock()
        mock_node.start_line = 1
        mock_node.end_line = 10
        mock_node.metadata = {}

        mock_store.find_nodes.return_value = [mock_node]

        with patch.object(enricher, "is_available", return_value=True):
            enricher._version = "1.10.0"
            report = enricher.enrich_nodes(mock_store)

        assert report.nodes_enriched == 0

    def test_enrich_type_info_extracted(self, enricher, mock_store):
        """Test that type information is extracted from messages."""
        enricher._project_root = "/tmp/project"
        enricher._last_results = {
            "app/User.php": [
                PHPStanResult(
                    file_path="/tmp/project/app/User.php",
                    line=4,
                    message="Method App\\User::getName() should return string but returns int.",
                    identifier="return.type",
                ),
            ],
        }

        mock_node = MagicMock()
        mock_node.start_line = 3
        mock_node.end_line = 6
        mock_node.metadata = {}

        mock_store.find_nodes.return_value = [mock_node]

        with patch.object(enricher, "is_available", return_value=True):
            enricher._version = "1.10.0"
            report = enricher.enrich_nodes(mock_store)

        assert report.nodes_enriched == 1
        phpstan_meta = mock_node.metadata["phpstan"]
        assert "types" in phpstan_meta
        assert phpstan_meta["types"]["expected_return_type"] == "string"

    def test_enrich_calls_upsert(self, enricher, mock_store):
        """Test that modified nodes are persisted via upsert_nodes."""
        enricher._project_root = "/tmp/project"
        enricher._last_results = {
            "app/User.php": [
                PHPStanResult(
                    file_path="/tmp/project/app/User.php",
                    line=4,
                    message="Test error.",
                    identifier="missingType.return",
                ),
            ],
        }

        mock_node = MagicMock()
        mock_node.start_line = 1
        mock_node.end_line = 10
        mock_node.metadata = {}

        mock_store.find_nodes.return_value = [mock_node]

        with patch.object(enricher, "is_available", return_value=True):
            enricher._version = "1.10.0"
            enricher.enrich_nodes(mock_store)

        mock_store.upsert_nodes.assert_called_once()

    def test_enrich_report_timing(self, enricher, mock_store):
        """Test that duration_ms is populated."""
        enricher._last_results = {}

        with patch.object(enricher, "is_available", return_value=True):
            enricher._version = "1.10.0"
            report = enricher.enrich_nodes(mock_store)

        assert report.duration_ms > 0


# ── Constructor Tests ─────────────────────────────────────────────


class TestPHPStanEnricherInit:
    """Tests for PHPStanEnricher initialization."""

    def test_default_init(self, project_root):
        enricher = PHPStanEnricher(project_root=project_root)
        assert enricher.project_root == project_root
        assert enricher.level == 5

    def test_custom_level(self, project_root):
        enricher = PHPStanEnricher(project_root=project_root, level=9)
        assert enricher.level == 9

    def test_level_clamped_high(self, project_root):
        enricher = PHPStanEnricher(project_root=project_root, level=15)
        assert enricher.level == 9

    def test_level_clamped_low(self, project_root):
        enricher = PHPStanEnricher(project_root=project_root, level=-3)
        assert enricher.level == 0

    def test_custom_phpstan_path(self, project_root):
        enricher = PHPStanEnricher(
            project_root=project_root,
            phpstan_path="/usr/local/bin/phpstan",
        )
        assert enricher._phpstan_path == "/usr/local/bin/phpstan"


# ── CLI Command Registration Test ────────────────────────────────


class TestCLIEnrichCommand:
    """Tests for the enrich CLI command registration."""

    def test_enrich_command_exists(self):
        """Verify the enrich command is registered in the CLI."""
        from coderag.cli.main import cli

        commands = cli.commands if hasattr(cli, "commands") else {}
        assert "enrich" in commands, f"enrich command not found. Available: {list(commands.keys())}"

    def test_enrich_command_has_phpstan_option(self):
        """Verify the --phpstan flag exists."""
        from coderag.cli.main import cli

        enrich_cmd = cli.commands["enrich"]
        param_names = [p.name for p in enrich_cmd.params]
        assert "phpstan" in param_names
        assert "level" in param_names
        assert "phpstan_path" in param_names

    def test_enrich_no_flags_shows_message(self):
        """Running enrich without flags should show a message."""
        from click.testing import CliRunner

        from coderag.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["enrich"])
        assert "No enrichment flags" in result.output or result.exit_code == 0
