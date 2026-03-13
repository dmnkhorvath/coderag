"""File scanner for discovering source files in a project.

Respects ignore patterns and supports incremental mode via
content-hash comparison.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from typing import Any

from coderag.core.models import FileInfo, compute_content_hash

logger = logging.getLogger(__name__)

# Default patterns to ignore
DEFAULT_IGNORE_PATTERNS: list[str] = [
    "node_modules/*",
    "vendor/*",
    ".git/*",
    ".svn/*",
    "__pycache__/*",
    ".idea/*",
    ".vscode/*",
    "*.min.js",
    "*.min.css",
    "dist/*",
    "build/*",
    "storage/*",
    "cache/*",
    ".codegraph/*",
]


class FileScanner:
    """Discover source files in a project directory."""

    def __init__(
        self,
        project_root: str,
        extensions: frozenset[str] | set[str] | None = None,
        ignore_patterns: list[str] | None = None,
    ) -> None:
        self._root = os.path.abspath(project_root)
        self._extensions = extensions or frozenset()
        self._ignore = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS

    def scan(self) -> list[FileInfo]:
        """Scan the project root and return FileInfo for each matching file."""
        results: list[FileInfo] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            # Prune ignored directories in-place
            rel_dir = os.path.relpath(dirpath, self._root)
            dirnames[:] = [d for d in dirnames if not self._is_ignored(os.path.join(rel_dir, d) + "/")]

            for fname in filenames:
                abs_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(abs_path, self._root)

                # Check ignore patterns
                if self._is_ignored(rel_path):
                    continue

                # Check extension
                _, ext = os.path.splitext(fname)
                if self._extensions and ext not in self._extensions:
                    continue

                try:
                    content = self._read_file(abs_path)
                    content_hash = compute_content_hash(content)
                    size_bytes = len(content)
                except Exception as exc:
                    logger.warning("Cannot read %s: %s", abs_path, exc)
                    continue

                results.append(
                    FileInfo(
                        path=abs_path,
                        relative_path=rel_path,
                        language="",  # filled by orchestrator
                        plugin_name="",  # filled by orchestrator
                        content_hash=content_hash,
                        size_bytes=size_bytes,
                    )
                )

        logger.info("Scanned %d files in %s", len(results), self._root)
        return results

    def scan_incremental(
        self,
        get_stored_hash: Any,  # Callable[[str], str | None]
    ) -> list[FileInfo]:
        """Scan and mark files as changed based on stored hashes.

        Args:
            get_stored_hash: callable(file_path) -> stored_hash or None
        """
        all_files = self.scan()
        for fi in all_files:
            stored = get_stored_hash(fi.path)
            if stored is None or stored != fi.content_hash:
                # FileInfo.is_changed defaults to True, so new/changed files are already marked
                pass
            else:
                # File unchanged — create a new FileInfo with is_changed=False
                # Since FileInfo is frozen, we need to reconstruct
                all_files[all_files.index(fi)] = FileInfo(
                    path=fi.path,
                    relative_path=fi.relative_path,
                    language=fi.language,
                    plugin_name=fi.plugin_name,
                    content_hash=fi.content_hash,
                    size_bytes=fi.size_bytes,
                    is_changed=False,
                )
        changed = sum(1 for f in all_files if f.is_changed)
        logger.info("%d/%d files changed", changed, len(all_files))
        return all_files

    def _is_ignored(self, rel_path: str) -> bool:
        """Check if a relative path matches any ignore pattern."""
        # Normalise to forward slashes for matching
        norm = rel_path.replace(os.sep, "/")
        if norm.startswith("./"):
            norm = norm[2:]
        for pattern in self._ignore:
            if fnmatch.fnmatch(norm, pattern):
                return True
            # Also check just the filename
            if fnmatch.fnmatch(os.path.basename(norm), pattern):
                return True
            # Check if any path component matches directory pattern
            parts = norm.split("/")
            for part in parts:
                if fnmatch.fnmatch(part + "/", pattern):
                    return True
                if fnmatch.fnmatch(part, pattern.rstrip("/").rstrip("/*")):
                    return True
        return False

    @staticmethod
    def _read_file(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()
