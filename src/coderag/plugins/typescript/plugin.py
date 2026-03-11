"""TypeScript language plugin for CodeRAG."""
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
from coderag.plugins.typescript.extractor import TypeScriptExtractor
from coderag.plugins.typescript.resolver import TSResolver

logger = logging.getLogger(__name__)


class TypeScriptPlugin(LanguagePlugin):
    """Language plugin for TypeScript source files."""

    def __init__(self) -> None:
        self._extractor: TypeScriptExtractor | None = None
        self._resolver: TSResolver | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def language(self) -> Language:
        return Language.TYPESCRIPT

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".ts", ".tsx", ".mts", ".cts"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the TypeScript plugin with project configuration."""
        self._extractor = TypeScriptExtractor()
        self._resolver = TSResolver()
        self._resolver.set_project_root(project_root)
        logger.info("TypeScript plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = TypeScriptExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = TSResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        # P1: no framework detectors yet
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
