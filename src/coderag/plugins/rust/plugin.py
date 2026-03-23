"""Rust language plugin for CodeRAG."""

from __future__ import annotations

import logging
from typing import Any

from coderag.core.models import Language
from coderag.core.registry import ASTExtractor, FrameworkDetector, LanguagePlugin, ModuleResolver
from coderag.plugins.rust.extractor import RustExtractor
from coderag.plugins.rust.resolver import RustResolver

logger = logging.getLogger(__name__)


class RustPlugin(LanguagePlugin):
    """Language plugin for Rust source files."""

    def __init__(self) -> None:
        self._extractor: RustExtractor | None = None
        self._resolver: RustResolver | None = None

    @property
    def name(self) -> str:
        return "rust"

    @property
    def language(self) -> Language:
        return Language.RUST

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".rs"})

    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        self._extractor = RustExtractor()
        self._resolver = RustResolver()
        self._resolver.set_project_root(project_root)
        logger.info("Rust plugin initialized for %s", project_root)

    def get_extractor(self) -> ASTExtractor:
        if self._extractor is None:
            self._extractor = RustExtractor()
        return self._extractor

    def get_resolver(self) -> ModuleResolver:
        if self._resolver is None:
            self._resolver = RustResolver()
        return self._resolver

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        return []

    def cleanup(self) -> None:
        self._extractor = None
        self._resolver = None
