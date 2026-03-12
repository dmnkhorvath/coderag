"""CSS language plugin for CodeRAG."""
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
from coderag.plugins.css.extractor import CSSExtractor
from coderag.plugins.css.resolver import CSSResolver

logger = logging.getLogger(__name__)


class CSSPlugin(LanguagePlugin):
    """Language plugin for CSS source files."""

    def __init__(self) -> None:
        self._extractor: CSSExtractor | None = None
        self._resolver: CSSResolver | None = None
        self._project_root: str = ""

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "css"

    @property
    def language(self) -> Language:
        return Language.CSS

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".css"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the CSS plugin with project configuration."""
        self._project_root = project_root
        self._extractor = CSSExtractor()
        self._resolver = CSSResolver()
        self._resolver.set_project_root(project_root)
        logger.info("CSS plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = CSSExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = CSSResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
