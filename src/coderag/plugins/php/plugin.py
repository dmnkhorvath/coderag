"""PHP language plugin for CodeRAG."""
from __future__ import annotations

import logging
from typing import Any

from coderag.core.models import Language
from coderag.core.registry import (
    ASTExtractor,
    FrameworkDetector,
    LanguagePlugin,
    ModuleResolver,
)
from coderag.plugins.php.extractor import PHPExtractor
from coderag.plugins.php.resolver import PHPResolver

logger = logging.getLogger(__name__)


class PHPPlugin(LanguagePlugin):
    """Language plugin for PHP source files."""

    def __init__(self) -> None:
        self._extractor: PHPExtractor | None = None
        self._resolver: PHPResolver | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "php"

    @property
    def language(self) -> Language:
        return Language.PHP

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".php"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the PHP plugin with project configuration."""
        self._extractor = PHPExtractor()
        self._resolver = PHPResolver()
        self._resolver.set_project_root(project_root)
        logger.info("PHP plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = PHPExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = PHPResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        # P0: no framework detectors yet
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
