"""PHPStan type enrichment — optional Phase 8 of the pipeline.

Runs PHPStan static analysis on PHP files and enriches the knowledge
graph with type information extracted from the analysis results.

Requires PHPStan to be installed and accessible in the system PATH
or at a specified path. Gracefully degrades when PHPStan is not available.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Data Classes ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PHPStanResult:
    """A single PHPStan analysis result.

    Attributes:
        file_path: Absolute or relative path to the file.
        line: Line number where the issue/info was found.
        message: PHPStan message (error, type info, suggestion).
        identifier: PHPStan error identifier (e.g., "missingType.return").
        tip: Optional tip for fixing the issue.
        ignorable: Whether this result can be safely ignored.
    """

    file_path: str
    line: int
    message: str
    identifier: str | None = None
    tip: str | None = None
    ignorable: bool = True


@dataclass(slots=True)
class EnrichmentReport:
    """Summary report from a PHPStan enrichment run.

    Attributes:
        files_analyzed: Number of PHP files analyzed by PHPStan.
        errors_found: Total number of errors/results from PHPStan.
        nodes_enriched: Number of graph nodes enriched with type info.
        duration_ms: Total time spent on enrichment in milliseconds.
        phpstan_version: Detected PHPStan version string.
        level: PHPStan analysis level used.
        skipped_reason: If enrichment was skipped, the reason why.
    """

    files_analyzed: int = 0
    errors_found: int = 0
    nodes_enriched: int = 0
    duration_ms: float = 0.0
    phpstan_version: str = ""
    level: int = 5
    skipped_reason: str | None = None


# ── Type Extraction Patterns ──────────────────────────────────────

# PHPStan message patterns that contain useful type information
_TYPE_PATTERNS: dict[str, str] = {
    "missingType.return": "return_type",
    "missingType.parameter": "parameter_type",
    "missingType.property": "property_type",
    "missingType.iterableValue": "iterable_type",
    "return.type": "return_type",
    "param.type": "parameter_type",
    "property.type": "property_type",
    "assign.propertyType": "property_type",
    "method.returnType": "return_type",
    "argument.type": "parameter_type",
}


def _extract_type_from_message(message: str) -> dict[str, str]:
    """Extract type information from a PHPStan message.

    Parses common PHPStan message formats to extract type names.

    Args:
        message: The PHPStan error/info message.

    Returns:
        Dict with extracted type info (may be empty).
    """
    info: dict[str, str] = {}

    # Pattern: "Method X::Y() should return A but returns B."
    if "should return" in message and "but returns" in message:
        parts = message.split("should return ")
        if len(parts) > 1:
            expected = parts[1].split(" but ")[0].strip().rstrip(".")
            info["expected_return_type"] = expected
        parts2 = message.split("but returns ")
        if len(parts2) > 1:
            actual = parts2[1].strip().rstrip(".")
            info["actual_return_type"] = actual

    # Pattern: "Method X::Y() has no return type specified."
    elif "has no return type" in message:
        info["missing"] = "return_type"

    # Pattern: "Parameter $x of method X::Y() has no type specified."
    elif "has no type specified" in message and "Parameter" in message:
        info["missing"] = "parameter_type"
        # Extract parameter name
        if "$" in message:
            param = message.split("$")[1].split(" ")[0].strip()
            info["parameter_name"] = f"${param}"

    # Pattern: "Property X::$y has no type specified."
    elif "has no type specified" in message and "Property" in message:
        info["missing"] = "property_type"

    # Pattern: "has typehint with deprecated class"
    elif "deprecated class" in message:
        info["deprecated_type"] = True

    # Pattern: "Parameter #N $name of method ... expects A, B given."
    elif "expects" in message and "given" in message:
        parts = message.split("expects ")
        if len(parts) > 1:
            expected = parts[1].split(",")[0].strip()
            info["expected_type"] = expected
        parts2 = message.split("given")
        if len(parts2) > 0:
            # Get the part before "given"
            before_given = message.split(" given")[0]
            actual = before_given.split(", ")[-1].strip()
            if actual != expected:
                info["actual_type"] = actual

    # Pattern: "Method X::Y() return type has no value type specified"
    elif "return type has no value type" in message:
        info["missing"] = "return_value_type"

    # Pattern: "PHPDoc tag @return with type X is not subtype of"
    elif "@return with type" in message:
        parts = message.split("@return with type ")
        if len(parts) > 1:
            phpdoc_type = parts[1].split(" ")[0].strip()
            info["phpdoc_return_type"] = phpdoc_type

    # Pattern: "PHPDoc tag @param ... with type X is not subtype of"
    elif "@param" in message and "with type" in message:
        parts = message.split("with type ")
        if len(parts) > 1:
            phpdoc_type = parts[1].split(" ")[0].strip()
            info["phpdoc_param_type"] = phpdoc_type

    return info


# ── PHPStan Enricher ──────────────────────────────────────────────


class PHPStanEnricher:
    """Enrich PHP nodes with type information from PHPStan.

    Runs PHPStan static analysis on the project and uses the results
    to add type information to nodes in the knowledge graph.

    Example::

        enricher = PHPStanEnricher("/path/to/project")
        if enricher.is_available():
            results = enricher.analyze()
            report = enricher.enrich_nodes(store)
    """

    # Default PHPStan arguments
    _DEFAULT_ARGS = [
        "--error-format=json",
        "--no-progress",
        "--no-interaction",
    ]

    def __init__(
        self,
        project_root: str,
        phpstan_path: str = "phpstan",
        level: int = 5,
        memory_limit: str = "512M",
    ) -> None:
        """Initialize with project root and optional PHPStan binary path.

        Args:
            project_root: Absolute path to the PHP project root.
            phpstan_path: Path to the PHPStan binary (default: "phpstan").
            level: PHPStan analysis level 0-9 (default: 5).
            memory_limit: PHP memory limit for PHPStan (default: "512M").
        """
        self._project_root = os.path.abspath(project_root)
        self._phpstan_path = phpstan_path
        self._level = max(0, min(9, level))
        self._memory_limit = memory_limit
        self._version: str | None = None
        self._last_results: dict[str, list[PHPStanResult]] = {}

    @property
    def project_root(self) -> str:
        """Return the project root path."""
        return self._project_root

    @property
    def level(self) -> int:
        """Return the configured PHPStan level."""
        return self._level

    def is_available(self) -> bool:
        """Check if PHPStan is installed and accessible.

        Tries to run `phpstan --version` to verify availability.

        Returns:
            True if PHPStan is accessible, False otherwise.
        """
        # Check common locations
        paths_to_try = [
            self._phpstan_path,
            os.path.join(self._project_root, "vendor", "bin", "phpstan"),
        ]

        for path in paths_to_try:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=self._project_root,
                )
                if result.returncode == 0:
                    self._phpstan_path = path
                    version_output = result.stdout.strip()
                    # Parse version from output like "PHPStan - PHP Static Analysis Tool 1.10.0"
                    if "PHPStan" in version_output:
                        parts = version_output.split()
                        self._version = parts[-1] if parts else version_output
                    else:
                        self._version = version_output
                    logger.info("PHPStan found: %s (version: %s)", path, self._version)
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue

        logger.info("PHPStan not available at any checked path.")
        return False

    def get_version(self) -> str | None:
        """Return the detected PHPStan version, or None if not available."""
        if self._version is None:
            self.is_available()
        return self._version

    def analyze(
        self,
        files: list[str] | None = None,
    ) -> dict[str, list[PHPStanResult]]:
        """Run PHPStan analysis and return results grouped by file.

        Args:
            files: Optional list of specific files to analyze.
                   If None, analyzes the entire project.

        Returns:
            Dict mapping file paths to lists of PHPStanResult.

        Raises:
            RuntimeError: If PHPStan is not available.
        """
        if not self.is_available():
            raise RuntimeError("PHPStan is not available. Install it with: composer require --dev phpstan/phpstan")

        cmd = [
            self._phpstan_path,
            "analyse",
            f"--level={self._level}",
            f"--memory-limit={self._memory_limit}",
        ] + self._DEFAULT_ARGS

        if files:
            cmd.extend(files)

        logger.info(
            "Running PHPStan (level %d) on %s...",
            self._level,
            self._project_root,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd=self._project_root,
            )
        except subprocess.TimeoutExpired:
            logger.error("PHPStan timed out after 300 seconds.")
            return {}
        except OSError as exc:
            logger.error("Failed to run PHPStan: %s", exc)
            return {}

        # PHPStan returns exit code 1 when errors are found (normal)
        # Exit code 0 means no errors, exit code > 1 means PHPStan itself failed
        output = result.stdout.strip()
        if not output:
            if result.returncode > 1:
                logger.error("PHPStan failed (exit %d): %s", result.returncode, result.stderr)
            else:
                logger.info("PHPStan found no issues.")
            return {}

        return self._parse_json_output(output)

    def _parse_json_output(
        self,
        output: str,
    ) -> dict[str, list[PHPStanResult]]:
        """Parse PHPStan JSON output into structured results.

        Args:
            output: Raw JSON output from PHPStan.

        Returns:
            Dict mapping file paths to lists of PHPStanResult.
        """
        results: dict[str, list[PHPStanResult]] = {}

        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse PHPStan JSON output: %s", exc)
            # Try to find JSON in the output (PHPStan sometimes prepends text)
            json_start = output.find("{")
            if json_start > 0:
                try:
                    data = json.loads(output[json_start:])
                except json.JSONDecodeError:
                    return results
            else:
                return results

        # PHPStan JSON format: {"totals": {...}, "files": {"path": {"errors": N, "messages": [...]}}}
        files_data = data.get("files", {})

        for file_path, file_info in files_data.items():
            messages = file_info.get("messages", [])
            file_results: list[PHPStanResult] = []

            for msg in messages:
                phpstan_result = PHPStanResult(
                    file_path=file_path,
                    line=msg.get("line", 0),
                    message=msg.get("message", ""),
                    identifier=msg.get("identifier"),
                    tip=msg.get("tip"),
                    ignorable=msg.get("ignorable", True),
                )
                file_results.append(phpstan_result)

            if file_results:
                # Normalize path relative to project root
                rel_path = os.path.relpath(file_path, self._project_root)
                results[rel_path] = file_results

        self._last_results = results
        total_errors = sum(len(v) for v in results.values())
        logger.info(
            "PHPStan found %d issues in %d files.",
            total_errors,
            len(results),
        )
        return results

    def enrich_nodes(
        self,
        store: Any,  # SQLiteStore — avoid circular import
    ) -> EnrichmentReport:
        """Enrich existing nodes with PHPStan type information.

        Runs PHPStan analysis (if not already run) and updates node
        metadata with type information extracted from the results.

        Args:
            store: SQLiteStore instance containing the knowledge graph.

        Returns:
            EnrichmentReport with enrichment statistics.
        """
        t0 = time.perf_counter()
        report = EnrichmentReport(level=self._level)

        # Check availability
        if not self.is_available():
            report.skipped_reason = "PHPStan not available"
            report.duration_ms = (time.perf_counter() - t0) * 1000
            logger.info("PHPStan enrichment skipped: not available.")
            return report

        report.phpstan_version = self._version or ""

        # Run analysis if we don't have cached results
        if not self._last_results:
            self._last_results = self.analyze()

        results = self._last_results
        report.files_analyzed = len(results)
        report.errors_found = sum(len(v) for v in results.values())

        if not results:
            report.duration_ms = (time.perf_counter() - t0) * 1000
            return report

        # Enrich nodes with type information
        enriched_count = 0

        for rel_path, file_results in results.items():
            # Build a line -> results mapping for efficient lookup
            line_results: dict[int, list[PHPStanResult]] = {}
            for r in file_results:
                line_results.setdefault(r.line, []).append(r)

            # Find nodes in this file
            abs_path = os.path.join(self._project_root, rel_path)
            file_nodes = store.find_nodes(file_path=abs_path, limit=5000)
            if not file_nodes:
                file_nodes = store.find_nodes(file_path=rel_path, limit=5000)

            if not file_nodes:
                continue

            nodes_modified = False
            for node in file_nodes:
                # Check if any PHPStan results fall within this node's line range
                node_results: list[dict[str, Any]] = []
                type_info: dict[str, Any] = {}

                for line_no, results_at_line in line_results.items():
                    if node.start_line <= line_no <= node.end_line:
                        for r in results_at_line:
                            # Extract type information from the message
                            extracted = _extract_type_from_message(r.message)
                            if extracted:
                                type_info.update(extracted)

                            # Categorize by identifier
                            category = "unknown"
                            if r.identifier:
                                category = _TYPE_PATTERNS.get(r.identifier, r.identifier)

                            node_results.append(
                                {
                                    "line": r.line,
                                    "message": r.message,
                                    "category": category,
                                    "identifier": r.identifier,
                                }
                            )

                if node_results or type_info:
                    # Update node metadata with PHPStan info
                    phpstan_meta: dict[str, Any] = {}
                    if type_info:
                        phpstan_meta["types"] = type_info
                    if node_results:
                        phpstan_meta["issues"] = node_results
                        phpstan_meta["issue_count"] = len(node_results)

                    node.metadata["phpstan"] = phpstan_meta
                    nodes_modified = True
                    enriched_count += 1

            if nodes_modified:
                store.upsert_nodes(file_nodes)

        report.nodes_enriched = enriched_count
        report.duration_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "PHPStan enrichment complete: %d files, %d errors, %d nodes enriched in %.1fms",
            report.files_analyzed,
            report.errors_found,
            report.nodes_enriched,
            report.duration_ms,
        )

        return report
