"""Rust module resolver for CodeRAG."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from coderag.core.models import FileInfo, ResolutionResult, ResolutionStrategy
from coderag.core.registry import ModuleResolver

_RUST_STDLIB = frozenset({"std", "core", "alloc", "proc_macro", "test"})


class RustResolver(ModuleResolver):
    """Resolve Rust module paths to concrete files."""

    def __init__(self) -> None:
        self._project_root: str = "."
        self._file_index: dict[str, list[str]] = {}

    def set_project_root(self, project_root: str) -> None:
        self._project_root = project_root

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        if not import_path:
            return ResolutionResult(None, ResolutionStrategy.UNRESOLVED, 0.0)

        top = import_path.split("::")[0]
        if top in _RUST_STDLIB:
            return ResolutionResult(
                resolved_path=None,
                resolution_strategy=ResolutionStrategy.HEURISTIC,
                confidence=0.9,
                metadata={"stdlib": True, "module": import_path},
            )

        base_dir = Path(self._project_root) / os.path.dirname(from_file)
        parts = import_path.split("::")

        if parts[0] == "crate":
            rel = parts[1:]
            return self._resolve_relative_to_root(rel)
        if parts[0] == "self":
            rel = parts[1:]
            return self._resolve_candidates(base_dir, rel)
        if parts[0] == "super":
            rel = parts[1:]
            parent = base_dir.parent
            return self._resolve_candidates(parent, rel)

        return self._resolve_relative_to_root(parts)

    def _resolve_relative_to_root(self, parts: list[str]) -> ResolutionResult:
        root = Path(self._project_root)
        return self._resolve_candidates(root, parts)

    def _resolve_candidates(self, base: Path, parts: list[str]) -> ResolutionResult:
        if not parts:
            return ResolutionResult(None, ResolutionStrategy.UNRESOLVED, 0.0)
        dir_candidate = base.joinpath(*parts)
        file_candidate = base.joinpath(*parts[:-1], f"{parts[-1]}.rs")
        mod_candidate = base.joinpath(*parts, "mod.rs")
        for candidate in (file_candidate, mod_candidate, dir_candidate):
            if candidate.exists():
                return ResolutionResult(
                    resolved_path=str(candidate),
                    resolution_strategy=ResolutionStrategy.EXACT,
                    confidence=1.0,
                )
        return ResolutionResult(None, ResolutionStrategy.UNRESOLVED, 0.0)

    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        return ResolutionResult(None, ResolutionStrategy.UNRESOLVED, 0.0)

    def build_index(self, files: Sequence[FileInfo]) -> None:
        self._file_index.clear()
        for f in files:
            pkg_dir = os.path.dirname(f.path)
            self._file_index.setdefault(pkg_dir, []).append(f.path)
