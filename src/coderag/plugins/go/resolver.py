"""Go module resolver for CodeRAG."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from coderag.core.models import FileInfo, ResolutionResult, ResolutionStrategy
from coderag.core.registry import ModuleResolver

logger = logging.getLogger(__name__)

_GO_STDLIB = frozenset({
    "archive", "bufio", "builtin", "bytes", "cmp", "compress", "container",
    "context", "crypto", "database", "debug", "embed", "encoding", "errors",
    "expvar", "flag", "fmt", "go", "hash", "html", "image", "index", "io",
    "iter", "log", "maps", "math", "mime", "net", "os", "path", "plugin",
    "reflect", "regexp", "runtime", "slices", "sort", "strconv", "strings",
    "structs", "sync", "syscall", "testing", "text", "time", "unicode",
    "unique", "unsafe",
})

class GoResolver(ModuleResolver):
    """Resolve Go import paths to concrete files."""

    def __init__(self) -> None:
        self._project_root: str = "."
        self._module_path: str = ""
        self._file_index: dict[str, list[str]] = {}  # package_path -> [file_paths]

    def set_project_root(self, project_root: str) -> None:
        self._project_root = project_root
        self._read_go_mod()

    def _read_go_mod(self) -> None:
        go_mod_path = Path(self._project_root) / "go.mod"
        if go_mod_path.exists():
            try:
                content = go_mod_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("module "):
                        self._module_path = line[7:].strip()
                        break
            except Exception as e:
                logger.warning("Failed to read go.mod: %s", e)

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        top_level = import_path.split("/")[0]
        if top_level in _GO_STDLIB:
            return ResolutionResult(
                resolved_path=None,
                resolution_strategy=ResolutionStrategy.HEURISTIC,
                confidence=0.9,
                metadata={"stdlib": True, "module": import_path},
            )

        if self._module_path and import_path.startswith(self._module_path):
            rel_path = import_path[len(self._module_path):].lstrip("/")
            target_dir = Path(self._project_root) / rel_path
            if target_dir.is_dir():
                return ResolutionResult(
                    resolved_path=str(target_dir),
                    resolution_strategy=ResolutionStrategy.EXACT,
                    confidence=1.0,
                )

        return ResolutionResult(
            resolved_path=None,
            resolution_strategy=ResolutionStrategy.UNRESOLVED,
            confidence=0.0,
        )

    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        return ResolutionResult(
            resolved_path=None,
            resolution_strategy=ResolutionStrategy.UNRESOLVED,
            confidence=0.0,
        )

    def build_index(self, files: Sequence[FileInfo]) -> None:
        self._file_index.clear()
        for f in files:
            pkg_dir = os.path.dirname(f.path)
            if pkg_dir not in self._file_index:
                self._file_index[pkg_dir] = []
            self._file_index[pkg_dir].append(f.path)
