"""
CodeRAG Configuration
=====================

Project configuration management with YAML loading, sensible defaults,
and validation. Configuration is loaded from ``codegraph.yaml`` in the
project root directory.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# =============================================================================
# DEFAULT VALUES
# =============================================================================

_DEFAULT_IGNORE_PATTERNS: list[str] = [
    "**/node_modules/**",
    "**/vendor/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/storage/**",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
]

_DEFAULT_LANGUAGES: dict[str, dict[str, Any]] = {
    "php": {"enabled": True},
    "javascript": {"enabled": True},
    "typescript": {"enabled": True},
}

_DEFAULT_FRAMEWORK_DETECTION: dict[str, Any] = {
    "enabled": True,
    "auto_detect": True,
    "frameworks": {},
}

_DEFAULT_CROSS_LANGUAGE: dict[str, Any] = {
    "enabled": True,
    "api_matching": True,
    "type_contracts": True,
    "min_confidence": 0.3,
}

_DEFAULT_ENRICHMENT: dict[str, Any] = {
    "pagerank": True,
    "community_detection": True,
    "git_metadata": False,
}

_DEFAULT_OUTPUT: dict[str, Any] = {
    "default_format": "markdown",
    "default_detail_level": "signatures",
    "default_token_budget": 8000,
}

_DEFAULT_PERFORMANCE: dict[str, Any] = {
    "max_workers": 4,
    "batch_size": 100,
    "max_file_size_bytes": 1_000_000,
    "extraction_workers": "auto",
    "io_workers": "auto",
    "sqlite_batch_size": 1000,
    "embedding_batch_size": 128,
    "max_memory_mb": 4096,
    "use_gpu": "auto",
}

_DEFAULT_SEMANTIC: dict[str, Any] = {
    "enabled": True,
    "model": "all-MiniLM-L6-v2",
    "batch_size": 128,
}

_DEFAULT_DB_PATH: str = ".codegraph/graph.db"


@dataclass
class PerformanceConfig:
    """Performance tuning configuration.

    Provides typed access to performance settings with auto-resolution
    of worker counts based on available CPU cores.
    """

    extraction_workers: int | str = "auto"
    io_workers: int | str = "auto"
    batch_size: int = 500
    sqlite_batch_size: int = 1000
    embedding_batch_size: int = 128
    max_memory_mb: int = 4096
    max_workers: int = 4
    max_file_size_bytes: int = 1_000_000
    use_gpu: str = "auto"

    @property
    def resolved_extraction_workers(self) -> int:
        """Resolve extraction worker count (CPU-bound tasks)."""
        if self.extraction_workers == "auto":
            import os

            return min(os.cpu_count() or 4, 8)
        return int(self.extraction_workers)

    @property
    def resolved_io_workers(self) -> int:
        """Resolve I/O worker count (I/O-bound tasks)."""
        if self.io_workers == "auto":
            import os

            return min((os.cpu_count() or 4) * 2, 16)
        return int(self.io_workers)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceConfig:
        """Create from a performance config dictionary."""
        return cls(
            extraction_workers=data.get("extraction_workers", "auto"),
            io_workers=data.get("io_workers", "auto"),
            batch_size=data.get("batch_size", 500),
            sqlite_batch_size=data.get("sqlite_batch_size", 1000),
            embedding_batch_size=data.get("embedding_batch_size", 128),
            max_memory_mb=data.get("max_memory_mb", 4096),
            max_workers=data.get("max_workers", 4),
            max_file_size_bytes=data.get("max_file_size_bytes", 1_000_000),
            use_gpu=data.get("use_gpu", "auto"),
        )


# =============================================================================
# CONFIGURATION DATACLASS
# =============================================================================


@dataclass(slots=True)
class CodeGraphConfig:
    """Top-level configuration for a CodeRAG project.

    Loaded from ``codegraph.yaml`` in the project root. All fields have
    sensible defaults so a minimal or empty config file is valid.

    Attributes:
        project_name: Human-readable project name.
        project_root: Absolute path to the project root.
        db_path: Path to the SQLite database file (relative to project root).
        languages: Enabled language plugins and their config.
        ignore_patterns: Glob patterns for files/dirs to ignore.
        framework_detection: Framework detection settings.
        cross_language: Cross-language matching settings.
        enrichment: Enrichment phase settings.
        output: Output formatting settings.
        performance: Performance tuning settings.
    """

    project_name: str = ""
    project_root: str = ""
    db_path: str = _DEFAULT_DB_PATH
    languages: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(_DEFAULT_LANGUAGES))
    ignore_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_IGNORE_PATTERNS))
    framework_detection: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_FRAMEWORK_DETECTION))
    cross_language: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_CROSS_LANGUAGE))
    enrichment: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_ENRICHMENT))
    output: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_OUTPUT))
    performance: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_PERFORMANCE))
    semantic: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_SEMANTIC))

    # ── Factory Methods ───────────────────────────────────────

    @classmethod
    def from_yaml(cls, yaml_path: str) -> CodeGraphConfig:
        """Load configuration from a YAML file.

        Merges the YAML contents with defaults so that any missing
        keys fall back to their default values.

        Args:
            yaml_path: Path to ``codegraph.yaml``.

        Returns:
            Populated ``CodeGraphConfig`` instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            ValueError: If the YAML is malformed or contains invalid values.
        """
        yaml_file = Path(yaml_path).resolve()
        if not yaml_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_file}")

        try:
            with open(yaml_file, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(f"Malformed YAML in {yaml_file}: {exc}") from exc

        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a YAML mapping at top level, got {type(raw).__name__}")

        # Resolve project root relative to the config file location
        project_root = raw.get("project_root", "")
        if not project_root:
            project_root = str(yaml_file.parent)
        elif not os.path.isabs(project_root):
            project_root = str((yaml_file.parent / project_root).resolve())

        config = cls(
            project_name=raw.get("project_name", yaml_file.parent.name),
            project_root=project_root,
            db_path=raw.get("db_path", _DEFAULT_DB_PATH),
            languages=_deep_merge(_DEFAULT_LANGUAGES, raw.get("languages", {})),
            ignore_patterns=raw.get("ignore_patterns", list(_DEFAULT_IGNORE_PATTERNS)),
            framework_detection=_deep_merge(
                _DEFAULT_FRAMEWORK_DETECTION,
                raw.get("framework_detection", {}),
            ),
            cross_language=_deep_merge(
                _DEFAULT_CROSS_LANGUAGE,
                raw.get("cross_language", {}),
            ),
            enrichment=_deep_merge(
                _DEFAULT_ENRICHMENT,
                raw.get("enrichment", {}),
            ),
            output=_deep_merge(
                _DEFAULT_OUTPUT,
                raw.get("output", {}),
            ),
            performance=_deep_merge(
                _DEFAULT_PERFORMANCE,
                raw.get("performance", {}),
            ),
            semantic=_deep_merge(
                _DEFAULT_SEMANTIC,
                raw.get("semantic", {}),
            ),
        )

        config.validate()
        return config

    @classmethod
    def default(cls) -> CodeGraphConfig:
        """Create a default configuration.

        Returns:
            A ``CodeGraphConfig`` with all default values.
        """
        return cls()

    # ── Derived Properties ────────────────────────────────────

    @property
    def db_path_absolute(self) -> str:
        """Absolute path to the SQLite database file."""
        if os.path.isabs(self.db_path):
            return self.db_path
        return str(Path(self.project_root) / self.db_path)

    @property
    def enabled_languages(self) -> list[str]:
        """List of language names that are enabled."""
        return [lang for lang, cfg in self.languages.items() if cfg.get("enabled", True)]

    @property
    def max_workers(self) -> int:
        """Maximum number of parallel workers."""
        return int(self.performance.get("max_workers", 4))

    @property
    def batch_size(self) -> int:
        """Batch size for bulk operations."""
        return int(self.performance.get("batch_size", 100))

    @property
    def max_file_size_bytes(self) -> int:
        """Maximum file size to process (in bytes)."""
        return int(self.performance.get("max_file_size_bytes", 1_000_000))

    @property
    def default_token_budget(self) -> int:
        """Default token budget for context assembly."""
        return int(self.output.get("default_token_budget", 8000))

    @property
    def default_detail_level(self) -> str:
        """Default detail level for output formatting."""
        return str(self.output.get("default_detail_level", "signatures"))

    @property
    def semantic_enabled(self) -> bool:
        """Whether semantic search is enabled."""
        return bool(self.semantic.get("enabled", True))

    @property
    def semantic_model(self) -> str:
        """Sentence-transformer model name for embeddings."""
        return str(self.semantic.get("model", "all-MiniLM-L6-v2"))

    @property
    def semantic_batch_size(self) -> int:
        """Batch size for embedding operations."""
        return int(self.semantic.get("batch_size", 128))

    @property
    def perf_config(self) -> PerformanceConfig:
        """Get typed performance configuration."""
        return PerformanceConfig.from_dict(self.performance)

    # ── Validation ────────────────────────────────────────────

    def validate(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If any configuration value is invalid.
        """
        if self.project_root and not Path(self.project_root).is_dir():
            logger.warning("Project root does not exist: %s", self.project_root)

        perf = self.performance
        if perf.get("max_workers", 4) < 1:
            raise ValueError("performance.max_workers must be >= 1")
        if perf.get("batch_size", 100) < 1:
            raise ValueError("performance.batch_size must be >= 1")
        if perf.get("max_file_size_bytes", 1_000_000) < 1:
            raise ValueError("performance.max_file_size_bytes must be >= 1")
        sqlite_bs = perf.get("sqlite_batch_size", 1000)
        if isinstance(sqlite_bs, int) and sqlite_bs < 1:
            raise ValueError("performance.sqlite_batch_size must be >= 1")
        max_mem = perf.get("max_memory_mb", 4096)
        if isinstance(max_mem, int) and max_mem < 64:
            raise ValueError("performance.max_memory_mb must be >= 64")

        cl = self.cross_language
        min_conf = cl.get("min_confidence", 0.3)
        if not (0.0 <= min_conf <= 1.0):
            raise ValueError(f"cross_language.min_confidence must be 0.0-1.0, got {min_conf}")

    # ── Serialization ─────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a plain dictionary."""
        return {
            "project_name": self.project_name,
            "project_root": self.project_root,
            "db_path": self.db_path,
            "languages": self.languages,
            "ignore_patterns": self.ignore_patterns,
            "framework_detection": self.framework_detection,
            "cross_language": self.cross_language,
            "enrichment": self.enrichment,
            "output": self.output,
            "performance": self.performance,
            "semantic": self.semantic,
        }

    def to_yaml(self, path: str) -> None:
        """Write configuration to a YAML file.

        Args:
            path: Destination file path.
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(
                self.to_dict(),
                fh,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*.

    - Dict values are merged recursively.
    - All other types in *override* replace the *base* value.
    - Keys in *base* not present in *override* are preserved.

    Args:
        base: Default values.
        override: User-provided overrides.

    Returns:
        New merged dictionary.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ["CodeGraphConfig", "PerformanceConfig"]
