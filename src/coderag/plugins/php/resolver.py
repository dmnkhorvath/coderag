"""PHP module resolver — PSR-4 namespace-to-path resolution.

For P0 this provides basic namespace→directory mapping and
composer.json autoload support.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from typing import Any

from coderag.core.models import (
    FileInfo,
    ResolutionResult,
)
from coderag.core.registry import ModuleResolver

logger = logging.getLogger(__name__)


class PHPResolver(ModuleResolver):
    """Resolve PHP namespaces to file paths using PSR-4 conventions."""

    def __init__(self) -> None:
        self._project_root: str = ""
        # PSR-4 map: namespace_prefix -> list of base directories
        self._psr4_map: dict[str, list[str]] = {}
        # Qualified-name -> file path index built from discovered files
        self._qname_index: dict[str, str] = {}

    def set_project_root(self, project_root: str) -> None:
        self._project_root = project_root
        self._load_composer_autoload()

    # -- ModuleResolver interface -------------------------------------------

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a PHP namespace/class to a file path."""
        # Normalise separators
        fqn = import_path.replace("/", "\\").strip("\\")

        # 1. Check qname index (built from discovered files)
        if fqn in self._qname_index:
            return ResolutionResult(
                resolved_path=self._qname_index[fqn],
                confidence=0.95,
                resolution_strategy="qname_index",
            )

        # 2. Try PSR-4 resolution
        resolved = self._resolve_psr4(fqn)
        if resolved is not None:
            return ResolutionResult(
                resolved_path=resolved,
                confidence=0.85,
                resolution_strategy="psr4",
            )

        # 3. Unresolved
        return ResolutionResult(
            resolved_path=None,
            confidence=0.0,
            resolution_strategy="unresolved",
        )

    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a symbol reference to its definition file."""
        # For PHP, symbol resolution is essentially the same as import resolution
        return self.resolve(symbol_name, from_file, context)

    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build a namespace→file index from discovered PHP files.

        This is a simple heuristic: derive the expected namespace from
        the file path using PSR-4 conventions.
        """
        for fi in files:
            # Try to infer namespace from PSR-4 map
            for prefix, dirs in self._psr4_map.items():
                for base_dir in dirs:
                    abs_base = os.path.join(self._project_root, base_dir)
                    abs_file = os.path.abspath(fi.path)
                    if abs_file.startswith(os.path.abspath(abs_base)):
                        relative = os.path.relpath(abs_file, abs_base)
                        # Convert path to namespace
                        ns_part = relative.replace(os.sep, "\\")
                        if ns_part.endswith(".php"):
                            ns_part = ns_part[:-4]
                        fqn = prefix + ns_part
                        self._qname_index[fqn] = fi.path

    # -- Internal -----------------------------------------------------------

    def _load_composer_autoload(self) -> None:
        """Load PSR-4 mappings from composer.json."""
        composer_path = os.path.join(self._project_root, "composer.json")
        if not os.path.isfile(composer_path):
            # Default PSR-4 mapping for common structures
            self._psr4_map = {
                "App\\": ["app/"],
                "App\\Models\\": ["app/Models/"],
                "App\\Http\\": ["app/Http/"],
            }
            return

        try:
            with open(composer_path) as f:
                data = json.load(f)
            autoload = data.get("autoload", {})
            psr4 = autoload.get("psr-4", {})
            for prefix, paths in psr4.items():
                if isinstance(paths, str):
                    paths = [paths]
                self._psr4_map[prefix] = paths
            # Also check autoload-dev
            autoload_dev = data.get("autoload-dev", {})
            psr4_dev = autoload_dev.get("psr-4", {})
            for prefix, paths in psr4_dev.items():
                if isinstance(paths, str):
                    paths = [paths]
                self._psr4_map.setdefault(prefix, []).extend(paths)
            logger.info("Loaded %d PSR-4 mappings from composer.json", len(self._psr4_map))
        except Exception as exc:
            logger.warning("Failed to load composer.json: %s", exc)
            self._psr4_map = {"App\\": ["app/"]}

    def _resolve_psr4(self, fqn: str) -> str | None:
        """Attempt PSR-4 resolution of a fully-qualified name."""
        # Try longest prefix match first
        for prefix in sorted(self._psr4_map, key=len, reverse=True):
            norm_prefix = prefix.rstrip("\\")
            if fqn.startswith(norm_prefix):
                remainder = fqn[len(norm_prefix) :].lstrip("\\")
                for base_dir in self._psr4_map[prefix]:
                    candidate = os.path.join(
                        self._project_root,
                        base_dir,
                        remainder.replace("\\", os.sep) + ".php",
                    )
                    if os.path.isfile(candidate):
                        return candidate
        return None
