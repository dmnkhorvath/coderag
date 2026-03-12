"""Python module resolver for CodeRAG.

Handles Python's module resolution algorithm:
- Relative imports (from . import x, from ..pkg import y)
- Absolute imports (import os.path, from collections import OrderedDict)
- Package resolution via __init__.py
- src/ layout detection
- Standard library exclusion
- Virtual environment exclusion
"""

from __future__ import annotations

import logging
import sys
import sysconfig
from pathlib import Path
from typing import Any

from collections.abc import Sequence

from coderag.core.models import FileInfo, ResolutionResult, ResolutionStrategy
from coderag.core.registry import ModuleResolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standard library module names (frozen set for O(1) lookup)
# ---------------------------------------------------------------------------

_STDLIB_TOP_LEVEL: frozenset[str] | None = None


def _get_stdlib_modules() -> frozenset[str]:
    """Return the set of top-level standard library module names."""
    global _STDLIB_TOP_LEVEL  # noqa: PLW0603
    if _STDLIB_TOP_LEVEL is not None:
        return _STDLIB_TOP_LEVEL

    names: set[str] = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    # Fallback for older Python versions
    if not names:
        names = {
            "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
            "asyncore", "atexit", "base64", "bdb", "binascii", "binhex",
            "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk",
            "cmath", "cmd", "code", "codecs", "codeop", "collections",
            "colorsys", "compileall", "concurrent", "configparser",
            "contextlib", "contextvars", "copy", "copyreg", "cProfile",
            "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime",
            "dbm", "decimal", "difflib", "dis", "distutils", "doctest",
            "email", "encodings", "enum", "errno", "faulthandler", "fcntl",
            "filecmp", "fileinput", "fnmatch", "fractions", "ftplib",
            "functools", "gc", "getopt", "getpass", "gettext", "glob",
            "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
            "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect",
            "io", "ipaddress", "itertools", "json", "keyword", "lib2to3",
            "linecache", "locale", "logging", "lzma", "mailbox", "mailcap",
            "marshal", "math", "mimetypes", "mmap", "modulefinder",
            "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator",
            "optparse", "os", "ossaudiodev", "pathlib", "pdb", "pickle",
            "pickletools", "pipes", "pkgutil", "platform", "plistlib",
            "poplib", "posix", "posixpath", "pprint", "profile", "pstats",
            "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue",
            "quopri", "random", "re", "readline", "reprlib", "resource",
            "rlcompleter", "runpy", "sched", "secrets", "select",
            "selectors", "shelve", "shlex", "shutil", "signal", "site",
            "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
            "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
            "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig",
            "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
            "termios", "test", "textwrap", "threading", "time", "timeit",
            "tkinter", "token", "tokenize", "tomllib", "trace", "traceback",
            "tracemalloc", "tty", "turtle", "turtledemo", "types",
            "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
            "venv", "warnings", "wave", "weakref", "webbrowser", "winreg",
            "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
            "zipfile", "zipimport", "zlib", "_thread",
        }
    _STDLIB_TOP_LEVEL = frozenset(names)
    return _STDLIB_TOP_LEVEL


# Directories to skip during resolution
_VENV_DIRS = frozenset({
    "venv", ".venv", "env", ".env", "virtualenv",
    ".virtualenv", "site-packages", "__pypackages__",
})


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class PythonResolver(ModuleResolver):
    """Resolve Python import paths to concrete files."""

    def __init__(self) -> None:
        self._project_root: str = "."
        self._file_index: dict[str, str] = {}  # module_path -> file_path

    def set_project_root(self, project_root: str) -> None:
        """Set the project root for resolution."""
        self._project_root = project_root

    # -- ModuleResolver interface --------------------------------------------

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a Python import path to a file.

        Args:
            import_path: Dotted module path (e.g. ``"os.path"``,
                ``".models"`` for relative imports).
            from_file: Relative path of the importing file.
            context: Optional dict with keys:
                - ``project_root``: Absolute path to project root.
                - ``is_relative``: Whether this is a relative import.
                - ``level``: Number of leading dots for relative imports.

        Returns:
            :class:`ResolutionResult` with resolved path and strategy.
        """
        ctx = context or {}
        project_root = ctx.get("project_root", self._project_root)
        is_relative = ctx.get("is_relative", False)
        level = ctx.get("level", 0)

        # Check if this is a standard library module
        top_level = import_path.lstrip(".").split(".")[0] if import_path else ""
        if top_level and not is_relative and top_level in _get_stdlib_modules():
            return ResolutionResult(
                resolved_path=None,
                strategy=ResolutionStrategy.HEURISTIC,
                confidence=0.3,
                metadata={"stdlib": True, "module": import_path},
            )

        root = Path(project_root)

        # Handle relative imports
        if is_relative and level > 0:
            result = self._resolve_relative(import_path, from_file, root, level)
            if result is not None:
                return result

        # Handle absolute imports
        result = self._resolve_absolute(import_path, from_file, root)
        if result is not None:
            return result

        # Unresolved
        return ResolutionResult(
            resolved_path=None,
            strategy=ResolutionStrategy.UNRESOLVED,
            confidence=0.0,
            metadata={"import_path": import_path},
        )

    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a symbol reference to its definition file."""
        # For Python, symbol resolution is similar to import resolution
        # Try to find the symbol as a module path
        result = self.resolve(symbol_name, from_file, context)
        if result.resolved_path is not None:
            return result

        # Check the file index built during build_index
        if symbol_name in self._file_index:
            return ResolutionResult(
                resolved_path=self._file_index[symbol_name],
                strategy=ResolutionStrategy.INDEX,
                confidence=0.8,
            )

        return ResolutionResult(
            resolved_path=None,
            strategy=ResolutionStrategy.UNRESOLVED,
            confidence=0.0,
            metadata={"symbol": symbol_name},
        )

    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build a module index from discovered Python files.

        Maps dotted module paths to file paths for efficient resolution.
        """
        root = Path(self._project_root)
        self._file_index.clear()

        for fi in files:
            fpath = Path(fi.relative_path)
            # Convert file path to dotted module path
            # e.g. src/mypackage/utils.py -> mypackage.utils
            parts = list(fpath.with_suffix("").parts)

            # Strip common prefixes
            if parts and parts[0] == "src":
                parts = parts[1:]

            # Skip __init__.py — the package itself is the parent
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]

            if parts:
                module_path = ".".join(parts)
                self._file_index[module_path] = fi.relative_path

                # Also index the last component for simple name lookups
                self._file_index[parts[-1]] = fi.relative_path

        logger.debug("Built Python module index with %d entries", len(self._file_index))

    # -- Internal resolution methods ----------------------------------------

    def _resolve_relative(
        self,
        import_path: str,
        from_file: str,
        root: Path,
        level: int,
    ) -> ResolutionResult | None:
        """Resolve a relative import (from . import x, from ..pkg import y)."""
        from_dir = (root / from_file).parent

        # Go up `level - 1` directories (level=1 means current package)
        base_dir = from_dir
        for _ in range(level - 1):
            base_dir = base_dir.parent

        # Strip leading dots from the import path
        module_part = import_path.lstrip(".")
        return self._try_resolve_from_dir(module_part, base_dir, root)

    def _resolve_absolute(
        self,
        import_path: str,
        from_file: str,
        root: Path,
    ) -> ResolutionResult | None:
        """Resolve an absolute import."""
        # Try from project root directly
        result = self._try_resolve_from_dir(import_path, root, root)
        if result is not None:
            return result

        # Try from src/ layout
        src_dir = root / "src"
        if src_dir.is_dir():
            result = self._try_resolve_from_dir(import_path, src_dir, root)
            if result is not None:
                return result

        # Try from any top-level package directory that has __init__.py
        # (handles cases like mypackage.module where mypackage/ is at root)
        parts = import_path.split(".")
        if len(parts) >= 2:
            pkg_dir = root / parts[0]
            if pkg_dir.is_dir() and (pkg_dir / "__init__.py").exists():
                sub_path = ".".join(parts[1:])
                result = self._try_resolve_from_dir(sub_path, pkg_dir, root)
                if result is not None:
                    return result

        return None

    def _try_resolve_from_dir(
        self,
        dotted_path: str,
        base_dir: Path,
        root: Path,
    ) -> ResolutionResult | None:
        """Try to resolve a dotted module path from a base directory."""
        if not dotted_path:
            # Importing the package itself — look for __init__.py
            init = base_dir / "__init__.py"
            if init.exists():
                return ResolutionResult(
                    resolved_path=str(init.relative_to(root)),
                    strategy=ResolutionStrategy.INDEX,
                    confidence=0.9,
                )
            return None

        parts = dotted_path.split(".")
        rel = base_dir
        for part in parts:
            rel = rel / part

        # Check: rel.py
        py_file = rel.with_suffix(".py")
        if py_file.exists() and not self._is_venv(py_file, root):
            return ResolutionResult(
                resolved_path=str(py_file.relative_to(root)),
                strategy=ResolutionStrategy.EXTENSION,
                confidence=0.95,
            )

        # Check: rel.pyi (stub file)
        pyi_file = rel.with_suffix(".pyi")
        if pyi_file.exists() and not self._is_venv(pyi_file, root):
            return ResolutionResult(
                resolved_path=str(pyi_file.relative_to(root)),
                strategy=ResolutionStrategy.EXTENSION,
                confidence=0.9,
            )

        # Check: rel/__init__.py (package)
        init_file = rel / "__init__.py"
        if init_file.exists() and not self._is_venv(init_file, root):
            return ResolutionResult(
                resolved_path=str(init_file.relative_to(root)),
                strategy=ResolutionStrategy.INDEX,
                confidence=0.9,
            )

        return None

    @staticmethod
    def _is_venv(path: Path, root: Path) -> bool:
        """Check if a path is inside a virtual environment directory."""
        try:
            rel = path.relative_to(root)
        except ValueError:
            return False
        return any(part in _VENV_DIRS for part in rel.parts)
