"""
CodeRAG Plugin Registry
=======================

Abstract base classes for language plugins and a concrete plugin
registry that discovers, loads, and manages them.

Plugins are discovered via Python entry points (group: ``codegraph.plugins``)
or registered explicitly at runtime.
"""

from __future__ import annotations

import importlib
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from coderag.core.models import (
    Edge,
    EdgeKind,
    ExtractionResult,
    FileInfo,
    FrameworkPattern,
    Language,
    Node,
    NodeKind,
    ResolutionResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ABSTRACT BASE CLASSES
# =============================================================================


class ASTExtractor(ABC):
    """Interface for extracting nodes and edges from source file ASTs.

    Each language plugin provides an ``ASTExtractor`` that knows how to
    parse source files using tree-sitter and extract structural
    information into :class:`Node` and :class:`Edge` objects.

    The extractor should:

    - Parse the source file using tree-sitter.
    - Walk the AST to find declarations (classes, functions, etc.).
    - Create :class:`Node` objects for each declaration.
    - Create :class:`Edge` objects for relationships visible in the AST.
    - Collect unresolved references for later resolution.
    - Handle parse errors gracefully (partial extraction).
    """

    @abstractmethod
    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Extract nodes and edges from a source file.

        Args:
            file_path: Relative path from project root.
            source: Raw source file contents as bytes.

        Returns:
            :class:`ExtractionResult` containing all discovered nodes,
            edges, unresolved references, and any errors.

        Note:
            This method must be safe to call from multiple threads.
            Tree-sitter parsers are thread-safe for parsing, but
            the extractor should not share mutable state.
        """
        ...

    @abstractmethod
    def supported_node_kinds(self) -> frozenset[NodeKind]:
        """Return the set of :class:`NodeKind` values this extractor can produce."""
        ...

    @abstractmethod
    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        """Return the set of :class:`EdgeKind` values this extractor can produce."""
        ...


class ModuleResolver(ABC):
    """Interface for resolving import paths and symbol references.

    Each language has its own module resolution algorithm:

    - **PHP**: PSR-4 autoloading, namespace resolution.
    - **JavaScript**: Node.js resolution (relative, node_modules, aliases).
    - **TypeScript**: tsconfig paths, Node.js resolution.

    The resolver is called during the resolution phase (Phase 4)
    to convert unresolved references into concrete edges.
    """

    @abstractmethod
    def resolve(
        self,
        import_path: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve an import path to a concrete file.

        Args:
            import_path: The import specifier as written in source code.
            from_file: Relative path of the file containing the import.
            context: Additional context for resolution:
                - ``'is_type_only'``: bool — TypeScript type-only import.
                - ``'specifiers'``: list[str] — Named imports.
                - ``'is_dynamic'``: bool — Dynamic ``import()``.

        Returns:
            :class:`ResolutionResult` with the resolved path and confidence.
            If resolution fails, ``resolved_path`` is ``None`` and
            ``confidence`` is ``0.0``.
        """
        ...

    @abstractmethod
    def resolve_symbol(
        self,
        symbol_name: str,
        from_file: str,
        context: dict[str, Any] | None = None,
    ) -> ResolutionResult:
        """Resolve a symbol reference to its definition.

        Used for resolving type references, function calls, and
        class instantiations that are not explicit imports.

        Args:
            symbol_name: The symbol name as used in source code.
            from_file: Relative path of the file containing the reference.
            context: Additional context (e.g., namespace, use statements).

        Returns:
            :class:`ResolutionResult` with the resolved file path and confidence.
        """
        ...

    @abstractmethod
    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build the resolution index from discovered files.

        Called once before resolution begins. The resolver should
        build any indexes needed for efficient resolution (e.g.,
        PSR-4 namespace map, export map, barrel file index).

        Args:
            files: All discovered source files for this language.
        """
        ...


class FrameworkDetector(ABC):
    """Interface for detecting framework-specific patterns.

    Framework detectors run after structural extraction and resolution.
    They analyze the extracted nodes and edges to identify higher-level
    patterns specific to a framework (e.g., Laravel routes, React
    components, Express middleware chains).

    Each detector focuses on a single framework and produces additional
    nodes and edges that represent framework-level abstractions.
    """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """Name of the framework this detector handles (e.g., ``'laravel'``, ``'react'``)."""
        ...

    @abstractmethod
    def detect_framework(self, project_root: str) -> bool:
        """Check if this framework is used in the project.

        Called during project discovery to determine which detectors
        to activate. Should be fast (check config files, not parse code).

        Args:
            project_root: Absolute path to the project root.

        Returns:
            ``True`` if the framework is detected in the project.
        """
        ...

    @abstractmethod
    def detect(
        self,
        file_path: str,
        tree: Any,  # tree_sitter.Tree
        source: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> list[FrameworkPattern]:
        """Detect framework patterns in a parsed file.

        Called for each file after structural extraction. The detector
        receives the tree-sitter AST and the already-extracted nodes
        and edges, and returns additional framework-specific patterns.

        Args:
            file_path: Relative path of the file.
            tree: Tree-sitter parse tree.
            source: Raw source bytes.
            nodes: Nodes already extracted from this file.
            edges: Edges already extracted from this file.

        Returns:
            List of :class:`FrameworkPattern` objects with additional
            nodes/edges. May be empty if no patterns are found.
        """
        ...

    @abstractmethod
    def detect_global_patterns(
        self,
        store: Any,  # GraphStore — forward reference to avoid circular import
    ) -> list[FrameworkPattern]:
        """Detect framework patterns that span multiple files.

        Called once after all files have been processed. Used for
        patterns that require a global view (e.g., event listeners
        registered in a service provider, route groups).

        Args:
            store: The graph store with all extracted nodes/edges.

        Returns:
            List of :class:`FrameworkPattern` objects with additional
            nodes/edges.
        """
        ...


class LanguagePlugin(ABC):
    """Interface for language-specific plugins.

    Each supported language (PHP, JavaScript, TypeScript) implements this
    interface. The plugin is responsible for:

    - Declaring which file extensions it handles.
    - Providing an AST extractor for structural extraction.
    - Providing a module resolver for import resolution.
    - Providing framework detectors for framework-specific patterns.

    Plugins are discovered via Python entry points::

        [project.entry-points."codegraph.plugins"]
        php = "codegraph.plugins.php:PHPPlugin"

    Lifecycle:

    1. ``__init__()`` — Plugin is instantiated.
    2. ``initialize(config)`` — Plugin receives configuration.
    3. ``get_extractor()`` — Called once per pipeline run.
    4. ``get_resolver()`` — Called once per pipeline run.
    5. ``get_framework_detectors()`` — Called once per pipeline run.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (e.g., ``'php'``, ``'javascript'``, ``'typescript'``)."""
        ...

    @property
    @abstractmethod
    def language(self) -> Language:
        """The language this plugin handles."""
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> frozenset[str]:
        """File extensions this plugin handles.

        Extensions include the leading dot
        (e.g., ``frozenset({'.php', '.blade.php'})``).
        """
        ...

    @abstractmethod
    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the plugin with project-specific configuration.

        Called once before any extraction begins. The plugin should:

        - Parse language-specific config files (composer.json, tsconfig.json, etc.).
        - Initialize tree-sitter parser with the appropriate grammar.
        - Set up any caches or state needed for extraction.

        Args:
            config: Language-specific configuration from ``codegraph.yaml``.
            project_root: Absolute path to the project root directory.
        """
        ...

    @abstractmethod
    def get_extractor(self) -> ASTExtractor:
        """Return the AST extractor for this language.

        Returns:
            An initialized :class:`ASTExtractor` instance.
        """
        ...

    @abstractmethod
    def get_resolver(self) -> ModuleResolver:
        """Return the module/name resolver for this language.

        Returns:
            An initialized :class:`ModuleResolver` instance.
        """
        ...

    @abstractmethod
    def get_framework_detectors(self) -> list[FrameworkDetector]:
        """Return framework detectors for this language.

        Each detector identifies patterns specific to a framework
        (e.g., Laravel routes, React components).

        Returns:
            List of initialized :class:`FrameworkDetector` instances.
            May be empty if no frameworks are detected/configured.
        """
        ...

    def cleanup(self) -> None:
        """Release any resources held by the plugin.

        Called after the pipeline run completes. Override to clean up
        subprocess handles, temporary files, etc.
        """


# =============================================================================
# CONCRETE PLUGIN REGISTRY
# =============================================================================


class PluginRegistry:
    """Discovers, loads, and manages language plugins.

    Plugins can be registered explicitly via :meth:`register_plugin` or
    discovered automatically from Python entry points in the
    ``codegraph.plugins`` group.

    Example::

        registry = PluginRegistry()
        registry.discover_plugins()
        plugin = registry.get_plugin("php")
    """

    ENTRY_POINT_GROUP = "codegraph.plugins"

    def __init__(self) -> None:
        self._plugins: dict[str, LanguagePlugin] = {}
        self._extension_map: dict[str, str] = {}  # ext -> plugin name

    # ── Registration ──────────────────────────────────────────

    def register_plugin(self, plugin: LanguagePlugin) -> None:
        """Explicitly register a plugin instance.

        Args:
            plugin: The plugin to register.

        Raises:
            ValueError: If a plugin with the same name is already registered.
        """
        name = plugin.name
        if name in self._plugins:
            raise ValueError(
                f"Plugin '{name}' is already registered. "
                f"Existing: {self._plugins[name].__class__.__name__}, "
                f"New: {plugin.__class__.__name__}"
            )

        self._plugins[name] = plugin

        # Build extension -> plugin name mapping
        for ext in plugin.file_extensions:
            if ext in self._extension_map:
                existing = self._extension_map[ext]
                logger.warning(
                    "Extension '%s' already claimed by plugin '%s', overriding with '%s'",
                    ext,
                    existing,
                    name,
                )
            self._extension_map[ext] = name

        logger.info(
            "Registered plugin '%s' for extensions: %s",
            name,
            ", ".join(sorted(plugin.file_extensions)),
        )

    def discover_plugins(self) -> list[str]:
        """Discover available plugins via entry points.

        Scans the ``codegraph.plugins`` entry point group and
        instantiates each discovered plugin class.

        Returns:
            List of discovered plugin names.
        """
        discovered: list[str] = []

        try:
            from importlib.metadata import entry_points
        except ImportError:
            from importlib_metadata import entry_points  # type: ignore[no-redef]

        eps = entry_points()

        # Python 3.12+ returns a SelectableGroups or dict-like
        if hasattr(eps, "select"):
            plugin_eps = eps.select(group=self.ENTRY_POINT_GROUP)
        elif isinstance(eps, dict):
            plugin_eps = eps.get(self.ENTRY_POINT_GROUP, [])
        else:
            plugin_eps = [ep for ep in eps if getattr(ep, "group", None) == self.ENTRY_POINT_GROUP]

        for ep in plugin_eps:
            try:
                plugin_cls = ep.load()
                plugin = plugin_cls()
                self.register_plugin(plugin)
                discovered.append(plugin.name)
                logger.info("Discovered plugin '%s' from entry point", plugin.name)
            except Exception:
                logger.exception("Failed to load plugin from entry point '%s'", ep.name)

        return discovered

    def discover_builtin_plugins(self) -> list[str]:
        """Discover built-in plugins from the ``coderag.plugins`` package.

        Attempts to import known plugin modules and register them.

        Returns:
            List of discovered plugin names.
        """
        discovered: list[str] = []
        builtin_modules = [
            "coderag.plugins.php",
            "coderag.plugins.javascript",
            "coderag.plugins.typescript",
            "coderag.plugins.python",
            "coderag.plugins.css",
            "coderag.plugins.scss",
            "coderag.plugins.go",
        ]

        for module_path in builtin_modules:
            try:
                module = importlib.import_module(module_path)
                # Convention: each plugin module exposes a `Plugin` class
                # or a `create_plugin()` factory function
                plugin_cls = getattr(module, "Plugin", None)
                if plugin_cls is None:
                    factory = getattr(module, "create_plugin", None)
                    if factory is not None:
                        plugin = factory()
                    else:
                        logger.debug(
                            "Module '%s' has no Plugin class or create_plugin factory",
                            module_path,
                        )
                        continue
                else:
                    plugin = plugin_cls()

                if plugin.name not in self._plugins:
                    self.register_plugin(plugin)
                    discovered.append(plugin.name)
            except ImportError:
                logger.debug("Built-in plugin module '%s' not found", module_path)
            except Exception:
                logger.exception("Failed to load built-in plugin from '%s'", module_path)

        return discovered

    # ── Lookup ────────────────────────────────────────────────

    def get_plugin(self, name: str) -> LanguagePlugin | None:
        """Get a registered plugin by name.

        Args:
            name: Plugin name (e.g., ``"php"``, ``"javascript"``).

        Returns:
            The plugin, or ``None`` if not registered.
        """
        return self._plugins.get(name)

    def get_plugin_for_file(self, file_path: str) -> LanguagePlugin | None:
        """Get the plugin that handles a given file extension.

        Checks compound extensions first (e.g., ``.blade.php``),
        then falls back to the simple extension.

        Args:
            file_path: File path (extension is used for matching).

        Returns:
            The plugin, or ``None`` if no plugin handles this extension.
        """
        basename = os.path.basename(file_path)

        # Check compound extensions (longest match first)
        for ext in sorted(self._extension_map.keys(), key=len, reverse=True):
            if basename.endswith(ext):
                plugin_name = self._extension_map[ext]
                return self._plugins.get(plugin_name)

        return None

    def get_all_plugins(self) -> list[LanguagePlugin]:
        """Get all registered plugins.

        Returns:
            List of all registered plugin instances.
        """
        return list(self._plugins.values())

    def get_all_extensions(self) -> dict[str, str]:
        """Get a mapping of file extensions to plugin names.

        Returns:
            Dict mapping extension (e.g., ``".php"``) to plugin name
            (e.g., ``"php"``).
        """
        return dict(self._extension_map)

    # ── Utilities ─────────────────────────────────────────────

    def initialize_all(
        self,
        configs: dict[str, dict[str, Any]],
        project_root: str,
    ) -> None:
        """Initialize all registered plugins with their configuration.

        Args:
            configs: Language-specific configs keyed by plugin name.
            project_root: Absolute path to the project root.
        """
        for name, plugin in self._plugins.items():
            config = configs.get(name, {})
            try:
                plugin.initialize(config, project_root)
                logger.info("Initialized plugin '%s'", name)
            except Exception:
                logger.exception("Failed to initialize plugin '%s'", name)
                raise

    def cleanup_all(self) -> None:
        """Call cleanup on all registered plugins."""
        for name, plugin in self._plugins.items():
            try:
                plugin.cleanup()
            except Exception:
                logger.exception("Error during cleanup of plugin '%s'", name)

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def __repr__(self) -> str:
        plugins = ", ".join(sorted(self._plugins.keys()))
        return f"PluginRegistry([{plugins}])"


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "ASTExtractor",
    "ModuleResolver",
    "FrameworkDetector",
    "LanguagePlugin",
    "PluginRegistry",
]
