"""CSS module resolver for CodeRAG.

Handles CSS-specific resolution:
- @import path resolution (relative paths, url() references)
- var(--custom-property) cross-file resolution
- animation-name to @keyframes cross-file resolution
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from coderag.core.models import FileInfo, ResolutionResult, ResolutionStrategy
from coderag.core.registry import ModuleResolver

logger = logging.getLogger(__name__)


class CSSResolver(ModuleResolver):
    """Resolves CSS cross-file references."""

    def __init__(self) -> None:
        self._project_root: Path = Path(".")
        self._css_files: dict[str, str] = {}  # relative_path -> absolute_path
        self._file_basenames: dict[str, list[str]] = {}  # basename -> [relative_paths]

    def set_project_root(self, project_root: str) -> None:
        """Set the project root for path resolution."""
        self._project_root = Path(project_root)

    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build index of CSS files for resolution."""
        self._css_files.clear()
        self._file_basenames.clear()

        for fi in files:
            self._css_files[fi.relative_path] = fi.path
            basename = Path(fi.relative_path).name
            self._file_basenames.setdefault(basename, []).append(fi.relative_path)

        logger.debug("CSS resolver indexed %d files", len(self._css_files))

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a CSS @import path to a concrete file.

        Args:
            import_path: The import specifier (e.g., "reset.css", "../base/vars.css").
            from_file: Relative path of the file containing the import.
            context: Additional context (e.g., {"type": "css_import"}).

        Returns:
            ResolutionResult with resolved path and confidence.
        """
        # Skip external URLs
        if import_path.startswith(("http://", "https://", "//")):
            return ResolutionResult(
                resolved_path=None,
                confidence=0.0,
                resolution_strategy=ResolutionStrategy.UNRESOLVED,
                is_external=True,
                package_name=import_path,
            )

        # Skip data URIs
        if import_path.startswith("data:"):
            return ResolutionResult(
                resolved_path=None,
                confidence=0.0,
                resolution_strategy=ResolutionStrategy.UNRESOLVED,
                is_external=True,
            )

        # Try relative resolution from the importing file
        from_dir = Path(from_file).parent
        candidate = (from_dir / import_path).as_posix()
        # Normalize path (resolve ../ etc.)
        try:
            candidate = str(Path(candidate).resolve().relative_to(self._project_root))
        except (ValueError, RuntimeError):
            # Path is outside project root or can't be resolved
            candidate = str(Path(candidate))

        # Direct match
        if candidate in self._css_files:
            return ResolutionResult(
                resolved_path=candidate,
                confidence=1.0,
                resolution_strategy=ResolutionStrategy.EXACT,
            )

        # Try adding .css extension
        if not candidate.endswith(".css"):
            with_ext = candidate + ".css"
            if with_ext in self._css_files:
                return ResolutionResult(
                    resolved_path=with_ext,
                    confidence=0.95,
                    resolution_strategy=ResolutionStrategy.EXTENSION,
                )

        # Try basename matching (for non-relative paths)
        basename = Path(import_path).name
        if not basename.endswith(".css"):
            basename += ".css"
        matches = self._file_basenames.get(basename, [])
        if len(matches) == 1:
            return ResolutionResult(
                resolved_path=matches[0],
                confidence=0.7,
                resolution_strategy=ResolutionStrategy.HEURISTIC,
            )
        if len(matches) > 1:
            # Multiple matches - pick the one closest to the importing file
            best = self._pick_closest(from_file, matches)
            return ResolutionResult(
                resolved_path=best,
                confidence=0.5,
                resolution_strategy=ResolutionStrategy.HEURISTIC,
            )

        # Unresolved
        return ResolutionResult(
            resolved_path=None,
            confidence=0.0,
            resolution_strategy=ResolutionStrategy.UNRESOLVED,
        )

    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a CSS symbol reference (var, keyframes) to its definition file.

        Args:
            symbol_name: The symbol name (e.g., "--primary-color", "fadeIn").
            from_file: Relative path of the file containing the reference.
            context: Additional context with "type" key.

        Returns:
            ResolutionResult with resolved path and confidence.
        """
        # Symbol resolution for CSS is handled at the graph level
        # since we need to search across all extracted nodes.
        # Return unresolved - the pipeline's resolution phase handles this.
        return ResolutionResult(
            resolved_path=None,
            confidence=0.0,
            resolution_strategy=ResolutionStrategy.UNRESOLVED,
        )

    def _pick_closest(self, from_file: str, candidates: list[str]) -> str:
        """Pick the candidate path closest to the importing file."""
        from_parts = Path(from_file).parts
        best_score = -1
        best_path = candidates[0]

        for cand in candidates:
            cand_parts = Path(cand).parts
            # Count common prefix length
            common = 0
            for a, b in zip(from_parts, cand_parts):
                if a == b:
                    common += 1
                else:
                    break
            if common > best_score:
                best_score = common
                best_path = cand

        return best_path
