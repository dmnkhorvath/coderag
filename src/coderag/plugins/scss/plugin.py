"""SCSS language plugin for CodeRAG."""

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
from coderag.plugins.scss.extractor import SCSSExtractor
from coderag.plugins.scss.resolver import SCSSResolver

logger = logging.getLogger(__name__)


class SCSSPlugin(LanguagePlugin):
    """Language plugin for SCSS/Sass source files."""

    def __init__(self) -> None:
        self._extractor: SCSSExtractor | None = None
        self._resolver: SCSSResolver | None = None
        self._project_root: str = ""

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "scss"

    @property
    def language(self) -> Language:
        return Language.SCSS

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".scss", ".sass"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the SCSS plugin with project configuration."""
        self._project_root = project_root
        self._extractor = SCSSExtractor()
        self._resolver = SCSSResolver()
        self._resolver.set_project_root(project_root)
        logger.info("SCSS plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = SCSSExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = SCSSResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
