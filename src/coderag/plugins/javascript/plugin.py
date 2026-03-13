"""JavaScript language plugin for CodeRAG."""

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
from coderag.plugins.javascript.extractor import JavaScriptExtractor
from coderag.plugins.javascript.resolver import JSResolver

logger = logging.getLogger(__name__)


class JavaScriptPlugin(LanguagePlugin):
    """Language plugin for JavaScript source files."""

    def __init__(self) -> None:
        self._extractor: JavaScriptExtractor | None = None
        self._resolver: JSResolver | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "javascript"

    @property
    def language(self) -> Language:
        return Language.JAVASCRIPT

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".js", ".jsx", ".mjs", ".cjs"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the JavaScript plugin with project configuration."""
        self._extractor = JavaScriptExtractor()
        self._resolver = JSResolver()
        self._resolver.set_project_root(project_root)
        logger.info("JavaScript plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = JavaScriptExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = JSResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        from coderag.plugins.javascript.frameworks.express import ExpressDetector
        from coderag.plugins.javascript.frameworks.nextjs import NextJSDetector
        from coderag.plugins.javascript.frameworks.react import ReactDetector
        from coderag.plugins.javascript.frameworks.vue import VueDetector

        return [ExpressDetector(), NextJSDetector(), ReactDetector(), VueDetector()]

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
