"""Go language plugin for CodeRAG."""

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
from coderag.plugins.go.extractor import GoExtractor
from coderag.plugins.go.resolver import GoResolver

logger = logging.getLogger(__name__)

class GoPlugin(LanguagePlugin):
    """Language plugin for Go source files."""

    def __init__(self) -> None:
        self._extractor: GoExtractor | None = None
        self._resolver: GoResolver | None = None

    @property
    def name(self) -> str:
        return "go"

    @property
    def language(self) -> Language:
        return Language.GO

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".go"})

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        self._extractor = GoExtractor()
        self._resolver = GoResolver()
        self._resolver.set_project_root(project_root)
        logger.info("Go plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = GoExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = GoResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
