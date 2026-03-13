"""Python language plugin for CodeRAG."""

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
from coderag.plugins.python.extractor import PythonExtractor
from coderag.plugins.python.resolver import PythonResolver

logger = logging.getLogger(__name__)


class PythonPlugin(LanguagePlugin):
    """Language plugin for Python source files."""

    def __init__(self) -> None:
        self._extractor: PythonExtractor | None = None
        self._resolver: PythonResolver | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def name(self) -> str:
        return "python"

    @property
    def language(self) -> Language:
        return Language.PYTHON

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".py", ".pyi"})

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the Python plugin with project configuration."""
        self._extractor = PythonExtractor()
        self._resolver = PythonResolver()
        self._resolver.set_project_root(project_root)
        logger.info("Python plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = PythonExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = PythonResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        from coderag.plugins.python.frameworks.django import DjangoDetector
        from coderag.plugins.python.frameworks.fastapi import FastAPIDetector
        from coderag.plugins.python.frameworks.flask import FlaskDetector

        return [DjangoDetector(), FlaskDetector(), FastAPIDetector()]

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
