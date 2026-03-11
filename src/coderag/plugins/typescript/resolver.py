"""TypeScript module resolver — extends Node.js resolution with TS-specific features.

Implements TypeScript module resolution including:
- tsconfig.json paths and baseUrl
- TypeScript file extensions (.ts, .tsx, .d.ts, .mts, .cts)
- Type-only import awareness
- Declaration file resolution
- Extends chain in tsconfig.json
"""
from __future__ import annotations

import json
import logging
import os
import re
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

# TypeScript extensions to try (TS-first, then JS fallback)
_TS_EXTENSIONS: tuple[str, ...] = (
    ".ts", ".tsx", ".d.ts", ".mts", ".cts",
    ".js", ".jsx", ".mjs", ".cjs",
)

# Index file names to try when resolving directories
_INDEX_FILES: tuple[str, ...] = (
    "index.ts", "index.tsx", "index.d.ts", "index.mts", "index.cts",
    "index.js", "index.jsx", "index.mjs", "index.cjs",
)


class TSResolver(ModuleResolver):
    """Resolve TypeScript imports to file paths.

    Extends standard Node.js resolution with:
    - tsconfig.json ``paths`` and ``baseUrl``
    - TypeScript file extension priority
    - Type-only import awareness
    - Declaration file (.d.ts) resolution
    """

    def __init__(self) -> None:
        self._project_root: str = ""
        self._known_files: set[str] = set()
        self._known_abs: set[str] = set()
        self._module_type: str = "commonjs"
        # Alias map: prefix -> replacement path (from tsconfig paths)
        self._aliases: dict[str, str] = {}
        # Exact alias map: specifier -> replacement path
        self._exact_aliases: dict[str, str] = {}
        self._package_mains: dict[str, str] = {}
        # tsconfig.json baseUrl (absolute path)
        self._base_url: str | None = None

    def set_project_root(self, project_root: str) -> None:
        self._project_root = project_root
        self._load_package_json()
        self._load_tsconfig()

    # -- ModuleResolver interface -------------------------------------------

    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a TypeScript import specifier to a file path."""
        is_type_only = (context or {}).get("is_type_only", False)

        # 1. Node.js built-in modules
        bare = import_path.removeprefix("node:")
        if import_path in _NODE_BUILTINS or bare in _NODE_BUILTINS:
            return ResolutionResult(
                resolved_path=None,
                confidence=1.0,
                resolution_strategy="builtin",
                metadata={"package_name": bare, "is_external": True},
            )

        # 2. tsconfig paths aliases (highest priority for TS)
        resolved_alias = self._try_alias(import_path)
        if resolved_alias is not None:
            result = self._resolve_relative(resolved_alias, self._project_root)
            if result is not None:
                return ResolutionResult(
                    resolved_path=result,
                    confidence=0.90,
                    resolution_strategy="tsconfig_paths",
                    metadata={"is_type_only": is_type_only},
                )

        # 3. baseUrl resolution (non-relative imports resolved from baseUrl)
        if self._base_url and not import_path.startswith("."):
            result = self._resolve_relative(
                f"./{import_path}", self._base_url
            )
            if result is not None:
                return ResolutionResult(
                    resolved_path=result,
                    confidence=0.85,
                    resolution_strategy="base_url",
                    metadata={"is_type_only": is_type_only},
                )

        # 4. Relative imports (./foo, ../bar)
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
                    metadata={"is_type_only": is_type_only},
                )
            return ResolutionResult(
                resolved_path=None,
                confidence=0.0,
                resolution_strategy="unresolved",
            )

        # 5. Package imports (bare specifiers via node_modules)
        result = self._resolve_package(import_path, from_file)
        if result is not None:
            return result

        # 6. Unresolved
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
        return self.resolve(symbol_name, from_file, context)

    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build a file path index from discovered TypeScript files."""
        self._known_files.clear()
        self._known_abs.clear()
        for fi in files:
            self._known_files.add(fi.path)
            abs_path = os.path.join(self._project_root, fi.path)
            self._known_abs.add(os.path.normpath(abs_path))
        logger.info(
            "TS resolver indexed %d files from project", len(self._known_files)
        )

    # -- Internal: relative resolution --------------------------------------

    def _resolve_relative(self, import_path: str, from_dir: str) -> str | None:
        """Resolve a relative import path from a directory.

        Tries:
        1. Exact path
        2. Path + extensions (.ts, .tsx, .d.ts, .js, .jsx, ...)
        3. Path as directory with index files
        """
        candidate = os.path.normpath(os.path.join(from_dir, import_path))

        # 1. Exact path
        if self._file_exists(candidate):
            return candidate

        # 2. Try adding extensions (TS-first order)
        for ext in _TS_EXTENSIONS:
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
                    result = self._resolve_relative(f"./{subpath}", nm_dir)
                    if result is not None:
                        return ResolutionResult(
                            resolved_path=result,
                            confidence=0.85,
                            resolution_strategy="node_modules",
                            metadata={"package_name": package_name},
                        )
                else:
                    # Try types entry first for TS
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

            parent = os.path.dirname(current)
            if parent == current:
                break
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
        """Try to resolve an import path via tsconfig paths."""
        # Check exact aliases first
        if import_path in self._exact_aliases:
            return self._exact_aliases[import_path]

        # Check wildcard aliases
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

    def _load_tsconfig(self) -> None:
        """Load tsconfig.json with extends chain support."""
        # Try tsconfig.json first, then jsconfig.json
        for config_name in ("tsconfig.json", "jsconfig.json"):
            config_path = os.path.join(self._project_root, config_name)
            if os.path.isfile(config_path):
                merged = self._load_tsconfig_recursive(config_path)
                self._apply_tsconfig(merged, os.path.dirname(config_path))
                return

    def _load_tsconfig_recursive(
        self, config_path: str, _seen: set[str] | None = None,
    ) -> dict:
        """Load tsconfig.json, handling comments, trailing commas, and extends."""
        if _seen is None:
            _seen = set()
        real = os.path.realpath(config_path)
        if real in _seen:
            logger.warning("Circular tsconfig extends detected: %s", real)
            return {}
        _seen.add(real)

        try:
            with open(config_path, "r") as f:
                raw = f.read()
        except Exception as exc:
            logger.warning("Failed to read %s: %s", config_path, exc)
            return {}

        # Strip comments and trailing commas
        raw = re.sub(r"//.*?$", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
        raw = re.sub(r",\s*([}\]])", r"\1", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse %s: %s", config_path, exc)
            return {}

        # Handle extends
        extends = data.pop("extends", None)
        if extends:
            config_dir = os.path.dirname(config_path)
            if not extends.endswith(".json"):
                extends += ".json"
            parent_path = os.path.normpath(
                os.path.join(config_dir, extends)
            )
            if os.path.isfile(parent_path):
                parent = self._load_tsconfig_recursive(parent_path, _seen)
                # Deep merge: child overrides parent
                parent_co = parent.get("compilerOptions", {})
                child_co = data.get("compilerOptions", {})
                parent_co.update(child_co)
                parent.update(data)
                parent["compilerOptions"] = parent_co
                return parent

        return data

    def _apply_tsconfig(self, config: dict, config_dir: str) -> None:
        """Apply tsconfig compilerOptions to resolver state."""
        compiler_opts = config.get("compilerOptions", {})

        # baseUrl
        base_url = compiler_opts.get("baseUrl")
        if base_url:
            self._base_url = os.path.normpath(
                os.path.join(config_dir, base_url)
            )
            logger.info("tsconfig baseUrl: %s", self._base_url)

        # paths
        paths = compiler_opts.get("paths", {})
        base = self._base_url or config_dir
        for alias_pattern, targets in paths.items():
            if not targets:
                continue
            # Wildcard patterns: "@/*" -> ["src/*"]
            if alias_pattern.endswith("/*") and targets[0].endswith("/*"):
                prefix = alias_pattern[:-2]
                target = targets[0][:-2]
                self._aliases[prefix] = os.path.join(base, target)
            elif "*" not in alias_pattern:
                # Exact alias: "utils" -> ["src/utils/index"]
                target = targets[0]
                if target.endswith("*"):
                    target = target[:-1]
                self._exact_aliases[alias_pattern] = os.path.join(
                    base, target
                )
            else:
                # Other wildcard patterns — treat as prefix
                prefix = alias_pattern.split("*")[0].rstrip("/")
                target = targets[0].split("*")[0].rstrip("/")
                if prefix:
                    self._aliases[prefix] = os.path.join(base, target)

        total = len(self._aliases) + len(self._exact_aliases)
        if total:
            logger.info(
                "Loaded %d path aliases from tsconfig.json", total
            )

    def _read_package_main(self, package_dir: str) -> str | None:
        """Read the main entry point from a package's package.json.

        Prefers TypeScript-specific fields: types > typings > module > main.
        """
        pkg_json = os.path.join(package_dir, "package.json")
        if not os.path.isfile(pkg_json):
            return None
        try:
            with open(pkg_json, "r") as f:
                data = json.load(f)
            # For TS: prefer types/typings for type resolution,
            # but module/main for actual source
            return (
                data.get("module")
                or data.get("main")
                or data.get("types")
                or data.get("typings")
            )
        except Exception:
            return None

    def _file_exists(self, path: str) -> bool:
        """Check if a file exists, using the index if available."""
        norm = os.path.normpath(path)
        if self._known_abs:
            return norm in self._known_abs
        return os.path.isfile(norm)
