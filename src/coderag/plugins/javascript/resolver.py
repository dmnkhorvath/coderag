"""JavaScript module resolver — Node.js module resolution algorithm.

Implements the Node.js module resolution algorithm for:
- Relative imports (./foo, ../bar)
- Package imports (node_modules lookup)
- Built-in modules (fs, path, http, etc.)
- Alias imports (@/utils, ~/components)
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

# Node.js built-in modules (core modules)
_NODE_BUILTINS: frozenset[str] = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster",
    "console", "constants", "crypto", "dgram", "diagnostics_channel",
    "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl",
    "stream", "string_decoder", "sys", "timers", "tls", "trace_events",
    "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
    # Node.js prefixed versions
    "node:assert", "node:async_hooks", "node:buffer",
    "node:child_process", "node:cluster", "node:console",
    "node:constants", "node:crypto", "node:dgram",
    "node:diagnostics_channel", "node:dns", "node:domain",
    "node:events", "node:fs", "node:http", "node:http2",
    "node:https", "node:inspector", "node:module", "node:net",
    "node:os", "node:path", "node:perf_hooks", "node:process",
    "node:punycode", "node:querystring", "node:readline",
    "node:repl", "node:stream", "node:string_decoder", "node:sys",
    "node:timers", "node:tls", "node:trace_events", "node:tty",
    "node:url", "node:util", "node:v8", "node:vm", "node:wasi",
    "node:worker_threads", "node:zlib",
})

# Extensions to try when resolving relative imports
_JS_EXTENSIONS: tuple[str, ...] = (".js", ".jsx", ".mjs", ".cjs")

# Index file names to try when resolving directories
_INDEX_FILES: tuple[str, ...] = (
    "index.js", "index.jsx", "index.mjs", "index.cjs",
)


class JSResolver(ModuleResolver):
    """Resolve JavaScript imports to file paths using Node.js conventions."""

    def __init__(self) -> None:
        self._project_root: str = ""
        # Set of all known file paths (relative) for quick lookup
        self._known_files: set[str] = set()
        # Set of all known file paths (absolute) for quick lookup
        self._known_abs: set[str] = set()
        # Module type from package.json ("module" or "commonjs")
        self._module_type: str = "commonjs"
        # Alias map: prefix -> replacement path
        self._aliases: dict[str, str] = {}
        # Package name -> main entry point (relative to package dir)
        self._package_mains: dict[str, str] = {}

    def set_project_root(self, project_root: str) -> None:
        self._project_root = project_root
        self._load_package_json()
        self._load_aliases()

    # -- ModuleResolver interface -------------------------------------------

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a JavaScript import specifier to a file path."""
        # 1. Check for Node.js built-in modules
        bare = import_path.removeprefix("node:")
        if import_path in _NODE_BUILTINS or bare in _NODE_BUILTINS:
            return ResolutionResult(
                resolved_path=None,
                confidence=1.0,
                resolution_strategy="builtin",
                metadata={"package_name": bare, "is_external": True},
            )

        # 2. Check aliases (e.g., @/utils -> src/utils)
        resolved_alias = self._try_alias(import_path)
        if resolved_alias is not None:
            # Convert alias to relative-like path and resolve
            result = self._resolve_relative(resolved_alias, self._project_root)
            if result is not None:
                return ResolutionResult(
                    resolved_path=result,
                    confidence=0.85,
                    resolution_strategy="alias",
                )

        # 3. Relative imports (./foo, ../bar)
        if import_path.startswith("."):
            from_dir = os.path.dirname(
                os.path.join(self._project_root, from_file)
            )
            result = self._resolve_relative(import_path, from_dir)
            if result is not None:
                return ResolutionResult(
                    resolved_path=result,
                    confidence=0.95,
                    resolution_strategy="relative",
                )
            return ResolutionResult(
                resolved_path=None,
                confidence=0.0,
                resolution_strategy="unresolved",
            )

        # 4. Package imports (bare specifiers)
        result = self._resolve_package(import_path, from_file)
        if result is not None:
            return result

        # 5. Unresolved
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
        # For JS, symbol resolution is essentially import resolution
        return self.resolve(symbol_name, from_file, context)

    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build a file path index from discovered JavaScript files."""
        self._known_files.clear()
        self._known_abs.clear()
        for fi in files:
            self._known_files.add(fi.path)
            abs_path = os.path.join(self._project_root, fi.path)
            self._known_abs.add(os.path.normpath(abs_path))
        logger.info(
            "JS resolver indexed %d files from project", len(self._known_files)
        )

    # -- Internal: relative resolution --------------------------------------

    def _resolve_relative(self, import_path: str, from_dir: str) -> str | None:
        """Resolve a relative import path from a directory.

        Tries:
        1. Exact path
        2. Path + extensions (.js, .jsx, .mjs, .cjs)
        3. Path as directory with index files
        """
        candidate = os.path.normpath(os.path.join(from_dir, import_path))

        # 1. Exact path
        if self._file_exists(candidate):
            return candidate

        # 2. Try adding extensions
        for ext in _JS_EXTENSIONS:
            with_ext = candidate + ext
            if self._file_exists(with_ext):
                return with_ext

        # 3. Try as directory with index files
        if os.path.isdir(candidate):
            for idx in _INDEX_FILES:
                idx_path = os.path.join(candidate, idx)
                if self._file_exists(idx_path):
                    return idx_path

        return None

    # -- Internal: package resolution ---------------------------------------

    def _resolve_package(
        self, import_path: str, from_file: str,
    ) -> ResolutionResult | None:
        """Resolve a bare package specifier via node_modules."""
        # Split scoped packages: @scope/pkg/path -> package=@scope/pkg, subpath=path
        if import_path.startswith("@"):
            parts = import_path.split("/", 2)
            if len(parts) >= 2:
                package_name = f"{parts[0]}/{parts[1]}"
                subpath = parts[2] if len(parts) > 2 else ""
            else:
                package_name = import_path
                subpath = ""
        else:
            parts = import_path.split("/", 1)
            package_name = parts[0]
            subpath = parts[1] if len(parts) > 1 else ""

        # Walk up directories looking for node_modules
        from_abs = os.path.join(self._project_root, from_file)
        current = os.path.dirname(from_abs)
        while True:
            nm_dir = os.path.join(current, "node_modules", package_name)
            if os.path.isdir(nm_dir):
                if subpath:
                    # Resolve subpath within the package
                    result = self._resolve_relative(f"./{subpath}", nm_dir)
                    if result is not None:
                        return ResolutionResult(
                            resolved_path=result,
                            confidence=0.85,
                            resolution_strategy="node_modules",
                            metadata={"package_name": package_name},
                        )
                else:
                    # Resolve package main entry
                    main = self._read_package_main(nm_dir)
                    if main:
                        result = self._resolve_relative(f"./{main}", nm_dir)
                        if result is not None:
                            return ResolutionResult(
                                resolved_path=result,
                                confidence=0.85,
                                resolution_strategy="node_modules",
                                metadata={"package_name": package_name},
                            )
                    # Try index files
                    for idx in _INDEX_FILES:
                        idx_path = os.path.join(nm_dir, idx)
                        if self._file_exists(idx_path):
                            return ResolutionResult(
                                resolved_path=idx_path,
                                confidence=0.80,
                                resolution_strategy="node_modules",
                                metadata={"package_name": package_name},
                            )

            # Move up one directory
            parent = os.path.dirname(current)
            if parent == current:
                break  # Reached filesystem root
            current = parent

        # Package not found locally — mark as external
        return ResolutionResult(
            resolved_path=None,
            confidence=0.5,
            resolution_strategy="external",
            metadata={"package_name": package_name, "is_external": True},
        )

    # -- Internal: alias resolution -----------------------------------------

    def _try_alias(self, import_path: str) -> str | None:
        """Try to resolve an import path via configured aliases."""
        for prefix, replacement in self._aliases.items():
            if import_path == prefix:
                return replacement
            if import_path.startswith(prefix + "/"):
                rest = import_path[len(prefix) + 1:]
                return os.path.join(replacement, rest)
        return None

    # -- Internal: config loading -------------------------------------------

    def _load_package_json(self) -> None:
        """Load module type from package.json."""
        pkg_path = os.path.join(self._project_root, "package.json")
        if not os.path.isfile(pkg_path):
            return
        try:
            with open(pkg_path, "r") as f:
                data = json.load(f)
            self._module_type = data.get("type", "commonjs")
            logger.info(
                "Detected module type: %s from package.json",
                self._module_type,
            )
        except Exception as exc:
            logger.warning("Failed to load package.json: %s", exc)

    def _load_aliases(self) -> None:
        """Load import aliases from common config files."""
        # Try jsconfig.json / tsconfig.json paths
        for config_name in ("jsconfig.json", "tsconfig.json"):
            config_path = os.path.join(self._project_root, config_name)
            if os.path.isfile(config_path):
                self._load_jsconfig_paths(config_path)
                return

    def _load_jsconfig_paths(self, config_path: str) -> None:
        """Load path aliases from jsconfig.json or tsconfig.json."""
        try:
            with open(config_path, "r") as f:
                raw = f.read()
            # Strip single-line comments (crude but effective)
            import re
            raw = re.sub(r"//.*?$", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
            # Strip trailing commas
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            data = json.loads(raw)

            compiler_opts = data.get("compilerOptions", {})
            base_url = compiler_opts.get("baseUrl", ".")
            base_abs = os.path.normpath(
                os.path.join(os.path.dirname(config_path), base_url)
            )
            paths = compiler_opts.get("paths", {})
            for alias_pattern, targets in paths.items():
                # Handle wildcard patterns: "@/*" -> ["src/*"]
                if alias_pattern.endswith("/*") and targets:
                    prefix = alias_pattern[:-2]  # "@"
                    target = targets[0]
                    if target.endswith("/*"):
                        target = target[:-2]
                    self._aliases[prefix] = os.path.join(base_abs, target)
                elif not alias_pattern.endswith("*") and targets:
                    # Exact alias: "utils" -> ["src/utils"]
                    target = targets[0]
                    if target.endswith("*"):
                        target = target[:-1]
                    self._aliases[alias_pattern] = os.path.join(
                        base_abs, target
                    )
            if self._aliases:
                logger.info(
                    "Loaded %d path aliases from %s",
                    len(self._aliases),
                    config_path,
                )
        except Exception as exc:
            logger.warning("Failed to load %s: %s", config_path, exc)

    def _read_package_main(self, package_dir: str) -> str | None:
        """Read the main entry point from a package's package.json."""
        pkg_json = os.path.join(package_dir, "package.json")
        if not os.path.isfile(pkg_json):
            return None
        try:
            with open(pkg_json, "r") as f:
                data = json.load(f)
            # Prefer "module" field for ESM, fall back to "main"
            return data.get("module") or data.get("main")
        except Exception:
            return None

    def _file_exists(self, path: str) -> bool:
        """Check if a file exists, using the index if available."""
        norm = os.path.normpath(path)
        if self._known_abs:
            return norm in self._known_abs
        return os.path.isfile(norm)
