"""
CodeGraph - Core Interfaces & Data Models
==========================================

This module defines all abstract base classes, protocols, and data models
that form the contract between CodeGraph's core engine and its plugins.

All language plugins, storage backends, and output formatters must implement
the interfaces defined here.

Usage:
    from codegraph.interfaces import (
        LanguagePlugin, ASTExtractor, FrameworkDetector,
        ModuleResolver, GraphStore, GraphAnalyzer,
        OutputFormatter, ContextAssembler, CrossLanguageMatcher,
        Node, Edge, NodeKind, EdgeKind, ExtractionResult,
    )
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# ENUMERATIONS
# =============================================================================


class NodeKind(enum.StrEnum):
    """All recognized node types in the knowledge graph.

    Each node in the graph has exactly one kind. Kinds are organized
    into categories: structural, type-system, module-system, and
    framework-specific.
    """

    # -- Structural --
    FILE = "file"
    DIRECTORY = "directory"
    PACKAGE = "package"

    # -- Declarations --
    CLASS = "class"
    INTERFACE = "interface"
    TRAIT = "trait"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    CONSTANT = "constant"
    ENUM = "enum"
    TYPE_ALIAS = "type_alias"
    VARIABLE = "variable"

    # -- Scoping --
    NAMESPACE = "namespace"
    MODULE = "module"

    # -- Granular --
    PARAMETER = "parameter"
    IMPORT = "import"
    EXPORT = "export"
    DECORATOR = "decorator"

    # -- Framework-Specific --
    ROUTE = "route"
    COMPONENT = "component"
    HOOK = "hook"
    MODEL = "model"
    EVENT = "event"
    MIDDLEWARE = "middleware"


class EdgeKind(enum.StrEnum):
    """All recognized edge types in the knowledge graph.

    Each edge has a source node, target node, kind, and confidence score.
    Edges are directional: source -> target.
    """

    # -- Containment --
    CONTAINS = "contains"
    DEFINED_IN = "defined_in"
    MEMBER_OF = "member_of"

    # -- Inheritance & Implementation --
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    USES_TRAIT = "uses_trait"

    # -- Type System --
    HAS_TYPE = "has_type"
    RETURNS_TYPE = "returns_type"
    GENERIC_OF = "generic_of"
    UNION_OF = "union_of"
    INTERSECTION_OF = "intersection_of"

    # -- Module System --
    IMPORTS = "imports"
    IMPORTS_TYPE = "imports_type"
    EXPORTS = "exports"
    RE_EXPORTS = "re_exports"
    DYNAMIC_IMPORTS = "dynamic_imports"
    DEPENDS_ON = "depends_on"

    # -- Call Graph --
    CALLS = "calls"
    INSTANTIATES = "instantiates"

    # -- Event System --
    DISPATCHES_EVENT = "dispatches_event"
    LISTENS_TO = "listens_to"

    # -- Framework: Routing --
    ROUTES_TO = "routes_to"

    # -- Framework: Components --
    RENDERS = "renders"
    PASSES_PROP = "passes_prop"
    USES_HOOK = "uses_hook"
    PROVIDES_CONTEXT = "provides_context"

    # -- Cross-Language --
    API_CALLS = "api_calls"
    API_SERVES = "api_serves"
    SHARES_TYPE_CONTRACT = "shares_type_contract"

    # -- Git-Derived --
    CO_CHANGES_WITH = "co_changes_with"


class Language(enum.StrEnum):
    """Supported programming languages."""

    PHP = "php"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"


class DetailLevel(enum.StrEnum):
    """Level of detail for context assembly output."""

    SIGNATURE = "signature"
    SUMMARY = "summary"
    DETAILED = "detailed"
    COMPREHENSIVE = "comprehensive"


class ResolutionStrategy(enum.StrEnum):
    """How an import was resolved."""

    EXACT = "exact"
    EXTENSION = "extension"
    INDEX = "index"
    ALIAS = "alias"
    TSCONFIG_PATH = "tsconfig_path"
    NODE_MODULES = "node_modules"
    PSR4 = "psr4"
    HEURISTIC = "heuristic"
    UNRESOLVED = "unresolved"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(frozen=True, slots=True)
class Node:
    """A node in the knowledge graph representing a code symbol.

    Nodes are immutable value objects. The `id` field uniquely identifies
    a node across the entire graph and is deterministically generated
    from the file path, kind, and qualified name.

    Attributes:
        id: Unique identifier (format: "{file_path}:{start_line}:{kind}:{name}")
        kind: The type of code symbol this node represents
        name: Short, unqualified name (e.g., "UserService")
        qualified_name: Fully-qualified name (e.g., "App\\Services\\UserService")
        file_path: Relative path from project root
        start_line: 1-based starting line number
        end_line: 1-based ending line number (inclusive)
        language: Programming language of the source file
        docblock: PHPDoc/JSDoc/TSDoc content, if present
        source_text: Source code of the symbol, if captured
        content_hash: SHA-256 hash of the source text for change detection
        metadata: Arbitrary key-value metadata (JSON-serializable)
        pagerank: Computed PageRank score (0.0-1.0, set during enrichment)
        community_id: Detected community/cluster ID (set during enrichment)
    """

    id: str
    kind: NodeKind
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    docblock: str | None = None
    source_text: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    pagerank: float = 0.0
    community_id: int | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed edge in the knowledge graph representing a relationship.

    Edges connect two nodes with a typed relationship and a confidence
    score indicating how certain we are about the relationship.

    Attributes:
        source_id: ID of the source node (FK to Node.id)
        target_id: ID of the target node (FK to Node.id)
        kind: The type of relationship
        confidence: Confidence score (0.0 = guess, 1.0 = certain)
        line_number: Line where the relationship occurs in source
        metadata: Arbitrary key-value metadata (JSON-serializable)
    """

    source_id: str
    target_id: str
    kind: EdgeKind
    confidence: float = 1.0
    line_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")


@dataclass(slots=True)
class ExtractionResult:
    """Result of extracting nodes and edges from a single source file.

    Returned by ASTExtractor.extract(). Contains all discovered nodes,
    edges, and any errors encountered during extraction.

    Attributes:
        file_path: Relative path of the parsed file
        language: Detected language of the file
        nodes: List of extracted nodes
        edges: List of extracted edges
        unresolved_references: Names that could not be resolved to nodes
        errors: Parse errors or extraction warnings
        parse_time_ms: Time spent parsing the file in milliseconds
    """

    file_path: str
    language: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = field(default_factory=list)
    errors: list[ExtractionError] = field(default_factory=list)
    parse_time_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class UnresolvedReference:
    """A reference that could not be resolved to a target node.

    These are collected during extraction and resolved in the
    resolution phase. If still unresolved after resolution,
    low-confidence edges are created.

    Attributes:
        source_node_id: ID of the node containing the reference
        reference_name: The unresolved name/path as written in source
        reference_kind: Expected edge kind if resolved
        line_number: Line where the reference occurs
        context: Additional context for resolution
    """

    source_node_id: str
    reference_name: str
    reference_kind: EdgeKind
    line_number: int
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractionError:
    """An error encountered during AST extraction.

    Attributes:
        file_path: File where the error occurred
        line_number: Line number of the error (if known)
        message: Human-readable error description
        severity: "error" or "warning"
        node_type: Tree-sitter node type that caused the error
    """

    file_path: str
    line_number: int | None
    message: str
    severity: str = "warning"
    node_type: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Result of resolving an import/reference path.

    Returned by ModuleResolver.resolve(). Contains the resolved
    file path, confidence, and resolution strategy used.

    Attributes:
        resolved_path: Absolute or project-relative path to the resolved file
        confidence: How confident we are in this resolution (0.0-1.0)
        resolution_strategy: Which strategy successfully resolved the path
        is_external: Whether this resolves to an external package
        package_name: Name of the external package (if is_external)
        exported_symbols: Specific symbols imported (if known)
    """

    resolved_path: str | None
    confidence: float
    resolution_strategy: ResolutionStrategy
    is_external: bool = False
    package_name: str | None = None
    exported_symbols: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FrameworkPattern:
    """A detected framework-specific pattern.

    Returned by FrameworkDetector.detect(). Contains additional
    nodes and edges that represent framework-level abstractions.

    Attributes:
        framework_name: Name of the detected framework (e.g., "laravel", "react")
        framework_version: Detected version (if determinable)
        pattern_type: Type of pattern (e.g., "route", "component", "model")
        nodes: Additional framework-specific nodes to add to the graph
        edges: Additional framework-specific edges to add to the graph
        metadata: Framework-specific metadata
    """

    framework_name: str
    framework_version: str | None = None
    pattern_type: str = ""
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrossLanguageMatch:
    """A detected cross-language connection.

    Represents a connection between code in different languages,
    such as a JavaScript fetch() call to a PHP API endpoint.

    Attributes:
        source_node_id: ID of the source node (e.g., JS fetch call)
        target_node_id: ID of the target node (e.g., PHP route)
        edge_kind: Type of cross-language relationship
        confidence: Confidence in the match (0.0-1.0)
        match_strategy: How the match was determined
        evidence: Evidence supporting the match
    """

    source_node_id: str
    target_node_id: str
    edge_kind: EdgeKind
    confidence: float
    match_strategy: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class APIEndpoint:
    """A detected API endpoint (backend route).

    Intermediate representation used during cross-language matching.

    Attributes:
        node_id: ID of the route node in the graph
        http_method: HTTP method (GET, POST, PUT, PATCH, DELETE)
        url_pattern: URL pattern with parameter placeholders
        url_regex: Compiled regex for matching against API calls
        controller: Qualified name of the handler
        middleware: List of middleware applied
        parameters: List of URL parameter names
        response_type: Expected response type/resource (if known)
    """

    node_id: str
    http_method: str
    url_pattern: str
    url_regex: str
    controller: str
    middleware: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    response_type: str | None = None


@dataclass(frozen=True, slots=True)
class APICall:
    """A detected API call (frontend HTTP request).

    Intermediate representation used during cross-language matching.

    Attributes:
        node_id: ID of the calling node in the graph
        http_method: HTTP method (if determinable)
        url_pattern: URL pattern or template
        url_source: How the URL is constructed (static, template, variable)
        file_path: File containing the API call
        line_number: Line number of the call
        confidence: Confidence in URL extraction
    """

    node_id: str
    http_method: str | None
    url_pattern: str
    url_source: str  # "static" | "template" | "variable" | "computed"
    file_path: str
    line_number: int
    confidence: float = 1.0


@dataclass(slots=True)
class FileInfo:
    """Metadata about a discovered source file.

    Used during the file discovery and hashing phase.

    Attributes:
        path: Absolute path to the file
        relative_path: Path relative to project root
        language: Detected language
        plugin_name: Name of the plugin that will process this file
        content_hash: SHA-256 hash of file contents
        size_bytes: File size in bytes
        is_changed: Whether the file has changed since last parse
    """

    path: str
    relative_path: str
    language: str
    plugin_name: str
    content_hash: str = ""
    size_bytes: int = 0
    is_changed: bool = True


@dataclass(slots=True)
class PipelineSummary:
    """Summary statistics from a pipeline run.

    Attributes:
        total_files: Total files discovered
        files_parsed: Files actually parsed (excludes unchanged)
        files_skipped: Files skipped (unchanged)
        files_errored: Files with parse errors
        total_nodes: Total nodes in the graph after this run
        total_edges: Total edges in the graph after this run
        nodes_added: New nodes added in this run
        nodes_updated: Existing nodes updated in this run
        nodes_removed: Stale nodes removed in this run
        edges_added: New edges added in this run
        files_by_language: File count per language
        nodes_by_kind: Node count per kind
        edges_by_kind: Edge count per kind
        frameworks_detected: List of detected frameworks
        cross_language_edges: Number of cross-language edges
        parse_errors: Total parse errors
        resolution_rate: Percentage of imports successfully resolved
        avg_confidence: Average edge confidence score
        total_parse_time_ms: Total time spent parsing files
        total_pipeline_time_ms: Total pipeline execution time
    """

    total_files: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    nodes_added: int = 0
    nodes_updated: int = 0
    nodes_removed: int = 0
    edges_added: int = 0
    files_by_language: dict[str, int] = field(default_factory=dict)
    nodes_by_kind: dict[str, int] = field(default_factory=dict)
    edges_by_kind: dict[str, int] = field(default_factory=dict)
    frameworks_detected: list[str] = field(default_factory=list)
    cross_language_edges: int = 0
    parse_errors: int = 0
    resolution_rate: float = 0.0
    avg_confidence: float = 0.0
    total_parse_time_ms: float = 0.0
    total_pipeline_time_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class GraphSummary:
    """Summary of the current graph state.

    Used by the info command and MCP summary resource.
    """

    project_name: str
    project_root: str
    db_path: str
    db_size_bytes: int
    last_parsed: str | None
    total_nodes: int
    total_edges: int
    nodes_by_kind: dict[str, int]
    edges_by_kind: dict[str, int]
    files_by_language: dict[str, int]
    frameworks: list[str]
    communities: int
    avg_confidence: float
    top_nodes_by_pagerank: list[tuple[str, str, float]]  # (name, qualified_name, score)


# =============================================================================
# CORE INTERFACES
# =============================================================================


class LanguagePlugin(ABC):
    """Interface for language-specific plugins.

    Each supported language (PHP, JavaScript, TypeScript) implements this
    interface. The plugin is responsible for:
    - Declaring which file extensions it handles
    - Providing an AST extractor for structural extraction
    - Providing a module resolver for import resolution
    - Providing framework detectors for framework-specific patterns

    Plugins are discovered via Python entry points:
        [project.entry-points."codegraph.plugins"]
        php = "codegraph.plugins.php:PHPPlugin"

    Lifecycle:
        1. __init__() -- Plugin is instantiated
        2. initialize(config) -- Plugin receives configuration
        3. get_extractor() -- Called once per pipeline run
        4. get_resolver() -- Called once per pipeline run
        5. get_framework_detectors() -- Called once per pipeline run
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (e.g., 'php', 'javascript', 'typescript')."""
        ...

    @property
    @abstractmethod
    def language(self) -> Language:
        """The language this plugin handles."""
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> frozenset[str]:
        """File extensions this plugin handles (e.g., frozenset({''.php', '.blade.php'})).

        Extensions include the leading dot.
        """
        ...

    @abstractmethod
    def initialize(self, config: dict[str, Any], project_root: str) -> None:
        """Initialize the plugin with project-specific configuration.

        Called once before any extraction begins. The plugin should:
        - Parse language-specific config files (composer.json, tsconfig.json, etc.)
        - Initialize tree-sitter parser with the appropriate grammar
        - Set up any caches or state needed for extraction

        Args:
            config: Language-specific configuration from codegraph.yaml
            project_root: Absolute path to the project root directory
        """
        ...

    @abstractmethod
    def get_extractor(self) -> ASTExtractor:
        """Return the AST extractor for this language.

        The extractor is responsible for parsing source files and
        extracting nodes and edges from the AST.

        Returns:
            An initialized ASTExtractor instance
        """
        ...

    @abstractmethod
    def get_resolver(self) -> ModuleResolver:
        """Return the module/name resolver for this language.

        The resolver is responsible for resolving import paths and
        symbol references to concrete file paths.

        Returns:
            An initialized ModuleResolver instance
        """
        ...

    @abstractmethod
    def get_framework_detectors(self) -> list[FrameworkDetector]:
        """Return framework detectors for this language.

        Each detector identifies patterns specific to a framework
        (e.g., Laravel routes, React components).

        Returns:
            List of initialized FrameworkDetector instances.
            May be empty if no frameworks are detected/configured.
        """
        ...

    def cleanup(self) -> None:
        """Release any resources held by the plugin.

        Called after the pipeline run completes. Override to clean up
        subprocess handles, temporary files, etc.
        """
        pass


class ASTExtractor(ABC):
    """Interface for extracting nodes and edges from source file ASTs.

    Each language plugin provides an ASTExtractor that knows how to
    parse source files using tree-sitter and extract structural
    information into Node and Edge objects.

    The extractor should:
    - Parse the source file using tree-sitter
    - Walk the AST to find declarations (classes, functions, etc.)
    - Create Node objects for each declaration
    - Create Edge objects for relationships visible in the AST
    - Collect unresolved references for later resolution
    - Handle parse errors gracefully (partial extraction)
    """

    @abstractmethod
    def extract(self, file_path: str, source: bytes) -> ExtractionResult:
        """Extract nodes and edges from a source file.

        Args:
            file_path: Relative path from project root
            source: Raw source file contents as bytes

        Returns:
            ExtractionResult containing all discovered nodes, edges,
            unresolved references, and any errors.

        Note:
            This method must be safe to call from multiple threads.
            Tree-sitter parsers are thread-safe for parsing, but
            the extractor should not share mutable state.
        """
        ...

    @abstractmethod
    def supported_node_kinds(self) -> frozenset[NodeKind]:
        """Return the set of NodeKinds this extractor can produce.

        Used for validation and documentation.
        """
        ...

    @abstractmethod
    def supported_edge_kinds(self) -> frozenset[EdgeKind]:
        """Return the set of EdgeKinds this extractor can produce.

        Used for validation and documentation.
        """
        ...


class ModuleResolver(ABC):
    """Interface for resolving import paths and symbol references.

    Each language has its own module resolution algorithm:
    - PHP: PSR-4 autoloading, namespace resolution
    - JavaScript: Node.js resolution (relative, node_modules, aliases)
    - TypeScript: tsconfig paths, Node.js resolution

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
            import_path: The import specifier as written in source code
            from_file: Relative path of the file containing the import
            context: Additional context for resolution:
                     - 'is_type_only': bool -- TypeScript type-only import
                     - 'specifiers': list[str] -- Named imports
                     - 'is_dynamic': bool -- Dynamic import()

        Returns:
            ResolutionResult with the resolved path and confidence.
            If resolution fails, resolved_path is None and confidence is 0.0.
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
            symbol_name: The symbol name as used in source code
            from_file: Relative path of the file containing the reference
            context: Additional context (e.g., namespace, use statements)

        Returns:
            ResolutionResult with the resolved file path and confidence.
        """
        ...

    @abstractmethod
    def build_index(self, files: Sequence[FileInfo]) -> None:
        """Build the resolution index from discovered files.

        Called once before resolution begins. The resolver should
        build any indexes needed for efficient resolution (e.g.,
        PSR-4 namespace map, export map, barrel file index).

        Args:
            files: All discovered source files for this language
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
        """Name of the framework this detector handles (e.g., 'laravel', 'react')."""
        ...

    @abstractmethod
    def detect_framework(self, project_root: str) -> bool:
        """Check if this framework is used in the project.

        Called during project discovery to determine which detectors
        to activate. Should be fast (check config files, not parse code).

        Args:
            project_root: Absolute path to the project root

        Returns:
            True if the framework is detected in the project
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
            file_path: Relative path of the file
            tree: Tree-sitter parse tree
            source: Raw source bytes
            nodes: Nodes already extracted from this file
            edges: Edges already extracted from this file

        Returns:
            List of FrameworkPattern objects with additional nodes/edges.
            May be empty if no patterns are found in this file.
        """
        ...

    @abstractmethod
    def detect_global_patterns(
        self,
        store: GraphStore,
    ) -> list[FrameworkPattern]:
        """Detect framework patterns that span multiple files.

        Called once after all files have been processed. Used for
        patterns that require a global view (e.g., event listeners
        registered in a service provider, route groups).

        Args:
            store: The graph store with all extracted nodes/edges

        Returns:
            List of FrameworkPattern objects with additional nodes/edges.
        """
        ...


class CrossLanguageMatcher(ABC):
    """Interface for detecting cross-language connections.

    Matches connections between code in different languages,
    primarily API endpoints (backend) <-> API calls (frontend)
    and shared type contracts.
    """

    @abstractmethod
    def extract_endpoints(self, store: GraphStore) -> list[APIEndpoint]:
        """Extract all API endpoints from the graph.

        Scans route nodes and their metadata to build a list of
        API endpoints that can be matched against frontend calls.

        Args:
            store: The graph store with all extracted nodes/edges

        Returns:
            List of APIEndpoint objects
        """
        ...

    @abstractmethod
    def extract_api_calls(self, store: GraphStore) -> list[APICall]:
        """Extract all API calls from frontend code.

        Scans function nodes for fetch(), axios, and other HTTP
        client calls to build a list of API calls.

        Args:
            store: The graph store with all extracted nodes/edges

        Returns:
            List of APICall objects
        """
        ...

    @abstractmethod
    def match(
        self,
        endpoints: list[APIEndpoint],
        calls: list[APICall],
    ) -> list[CrossLanguageMatch]:
        """Match API calls to API endpoints.

        Uses multiple strategies (exact URL match, parameterized match,
        prefix match, fuzzy match) with decreasing confidence.

        Args:
            endpoints: Backend API endpoints
            calls: Frontend API calls

        Returns:
            List of CrossLanguageMatch objects with confidence scores
        """
        ...

    @abstractmethod
    def match_type_contracts(
        self,
        store: GraphStore,
    ) -> list[CrossLanguageMatch]:
        """Match shared type contracts across languages.

        Finds TypeScript interfaces that correspond to PHP API
        Resources or response shapes by comparing field names
        and types.

        Args:
            store: The graph store with all extracted nodes/edges

        Returns:
            List of CrossLanguageMatch objects for type contracts
        """
        ...


# =============================================================================
# STORAGE INTERFACES
# =============================================================================


class GraphStore(ABC):
    """Interface for the knowledge graph storage backend.

    The graph store is responsible for persisting nodes and edges,
    providing efficient queries, and supporting incremental updates.

    The default implementation uses SQLite with WAL mode and FTS5
    for full-text search. Alternative implementations could use
    PostgreSQL, Neo4j, or other graph databases.

    Thread Safety:
        The store must support concurrent reads. Write operations
        may be serialized. The SQLite implementation uses WAL mode
        to allow concurrent reads during writes.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the storage backend.

        Create tables, indexes, and any required schema. Safe to
        call multiple times (idempotent).
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the storage backend and release resources."""
        ...

    # -- Node Operations --

    @abstractmethod
    def upsert_node(self, node: Node) -> None:
        """Insert or update a single node.

        If a node with the same ID exists, update it. Otherwise, insert.

        Args:
            node: The node to upsert
        """
        ...

    @abstractmethod
    def upsert_nodes(self, nodes: Sequence[Node]) -> int:
        """Bulk insert or update nodes.

        More efficient than calling upsert_node() in a loop.
        Uses a single transaction.

        Args:
            nodes: Sequence of nodes to upsert

        Returns:
            Number of nodes upserted
        """
        ...

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """Get a node by its ID.

        Args:
            node_id: Unique node identifier

        Returns:
            The node, or None if not found
        """
        ...

    @abstractmethod
    def get_node_by_qualified_name(self, qualified_name: str) -> Node | None:
        """Get a node by its fully-qualified name.

        If multiple nodes share the same qualified name (unlikely but
        possible across languages), returns the one with highest PageRank.

        Args:
            qualified_name: Fully-qualified symbol name

        Returns:
            The node, or None if not found
        """
        ...

    @abstractmethod
    def find_nodes(
        self,
        kind: NodeKind | None = None,
        language: str | None = None,
        file_path: str | None = None,
        name_pattern: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Node]:
        """Find nodes matching filter criteria.

        All filters are AND-combined. None means no filter.

        Args:
            kind: Filter by node kind
            language: Filter by language
            file_path: Filter by file path (exact match)
            name_pattern: Filter by name (supports SQL LIKE wildcards)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of matching nodes, ordered by PageRank descending
        """
        ...

    @abstractmethod
    def search_nodes(self, query: str, limit: int = 20) -> list[Node]:
        """Full-text search across node names, qualified names, and docblocks.

        Uses FTS5 for efficient full-text search with ranking.

        Args:
            query: Search query (supports FTS5 syntax: AND, OR, NOT, prefix*)
            limit: Maximum results to return

        Returns:
            List of matching nodes, ordered by relevance
        """
        ...

    @abstractmethod
    def delete_nodes_for_file(self, file_path: str) -> int:
        """Delete all nodes (and their edges) for a given file.

        Used during incremental updates to remove stale nodes
        before re-extracting from a changed file.

        Args:
            file_path: Relative file path

        Returns:
            Number of nodes deleted
        """
        ...

    # -- Edge Operations --

    @abstractmethod
    def upsert_edge(self, edge: Edge) -> None:
        """Insert or update a single edge.

        Edges are uniquely identified by (source_id, target_id, kind).
        If a matching edge exists, update confidence and metadata.

        Args:
            edge: The edge to upsert
        """
        ...

    @abstractmethod
    def upsert_edges(self, edges: Sequence[Edge]) -> int:
        """Bulk insert or update edges.

        Args:
            edges: Sequence of edges to upsert

        Returns:
            Number of edges upserted
        """
        ...

    @abstractmethod
    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: EdgeKind | None = None,
        min_confidence: float = 0.0,
    ) -> list[Edge]:
        """Get edges matching filter criteria.

        At least one of source_id, target_id, or kind should be specified
        to avoid returning the entire edge set.

        Args:
            source_id: Filter by source node ID
            target_id: Filter by target node ID
            kind: Filter by edge kind
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching edges, ordered by confidence descending
        """
        ...

    @abstractmethod
    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        edge_kinds: Sequence[EdgeKind] | None = None,
        max_depth: int = 1,
        min_confidence: float = 0.0,
    ) -> list[tuple[Node, Edge, int]]:
        """Get neighboring nodes with their connecting edges.

        Supports multi-hop traversal up to max_depth.

        Args:
            node_id: Starting node ID
            direction: Traversal direction ("outgoing", "incoming", or "both")
            edge_kinds: Filter by edge kinds (None = all)
            max_depth: Maximum traversal depth (1 = direct neighbors only)
            min_confidence: Minimum edge confidence

        Returns:
            List of (node, edge, depth) tuples, ordered by depth then PageRank
        """
        ...

    @abstractmethod
    def blast_radius(
        self,
        node_id: str,
        max_depth: int = 3,
        min_confidence: float = 0.3,
    ) -> dict[int, list[Node]]:
        """Compute the blast radius of changing a node.

        Returns all nodes that would be affected by a change,
        organized by distance (depth) from the changed node.

        Args:
            node_id: The node being changed
            max_depth: Maximum depth to traverse
            min_confidence: Minimum edge confidence to follow

        Returns:
            Dict mapping depth to list of affected nodes
        """
        ...

    # -- File Hash Tracking --

    @abstractmethod
    def get_file_hash(self, file_path: str) -> str | None:
        """Get the stored content hash for a file.

        Used for incremental update detection.

        Args:
            file_path: Relative file path

        Returns:
            SHA-256 hash string, or None if file not previously parsed
        """
        ...

    @abstractmethod
    def set_file_hash(
        self,
        file_path: str,
        content_hash: str,
        language: str,
        plugin_name: str,
        node_count: int,
        edge_count: int,
        parse_time_ms: float,
    ) -> None:
        """Store the content hash and metadata for a parsed file.

        Args:
            file_path: Relative file path
            content_hash: SHA-256 hash of file contents
            language: Detected language
            plugin_name: Plugin that processed the file
            node_count: Number of nodes extracted
            edge_count: Number of edges extracted
            parse_time_ms: Time spent parsing
        """
        ...

    @abstractmethod
    def get_stale_files(self, current_files: set[str]) -> set[str]:
        """Find files that were previously parsed but no longer exist.

        Used during incremental updates to detect deleted files.

        Args:
            current_files: Set of currently existing file paths

        Returns:
            Set of file paths that are in the store but not in current_files
        """
        ...

    # -- Graph Metadata --

    @abstractmethod
    def get_summary(self) -> GraphSummary:
        """Get a summary of the current graph state.

        Returns:
            GraphSummary with statistics about the graph
        """
        ...

    @abstractmethod
    def set_metadata(self, key: str, value: str) -> None:
        """Store a metadata key-value pair.

        Used for storing pipeline state (last parse time, schema version, etc.).

        Args:
            key: Metadata key
            value: Metadata value (string)
        """
        ...

    @abstractmethod
    def get_metadata(self, key: str) -> str | None:
        """Retrieve a metadata value.

        Args:
            key: Metadata key

        Returns:
            The value, or None if not found
        """
        ...

    # -- Transactions --

    @abstractmethod
    def begin_transaction(self) -> None:
        """Begin a write transaction.

        All upsert/delete operations between begin_transaction()
        and commit_transaction() are atomic.
        """
        ...

    @abstractmethod
    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        ...

    @abstractmethod
    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        ...


class GraphAnalyzer(ABC):
    """Interface for graph analysis algorithms.

    Provides graph algorithms that operate on the knowledge graph,
    including PageRank, centrality, community detection, and
    path finding.

    The default implementation uses NetworkX for in-memory analysis.
    """

    @abstractmethod
    def load_from_store(self, store: GraphStore) -> None:
        """Load the graph from the store into the analyzer.

        Args:
            store: The graph store to load from
        """
        ...

    @abstractmethod
    def pagerank(
        self,
        personalization: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Compute PageRank scores for all nodes.

        Args:
            personalization: Optional personalization vector
                             (node_id -> weight) for topic-sensitive PageRank

        Returns:
            Dict mapping node_id to PageRank score
        """
        ...

    @abstractmethod
    def betweenness_centrality(self) -> dict[str, float]:
        """Compute betweenness centrality for all nodes.

        Returns:
            Dict mapping node_id to centrality score
        """
        ...

    @abstractmethod
    def community_detection(self) -> list[set[str]]:
        """Detect communities/clusters in the graph.

        Returns:
            List of sets, each set containing node IDs in a community
        """
        ...

    @abstractmethod
    def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str] | None:
        """Find the shortest path between two nodes.

        Args:
            source_id: Starting node ID
            target_id: Target node ID

        Returns:
            List of node IDs forming the path, or None if no path exists
        """
        ...

    @abstractmethod
    def find_cycles(
        self,
        edge_kinds: Sequence[EdgeKind] | None = None,
    ) -> list[list[str]]:
        """Find circular dependencies in the graph.

        Args:
            edge_kinds: Only consider these edge types (None = all)

        Returns:
            List of cycles, each cycle is a list of node IDs
        """
        ...

    @abstractmethod
    def relevance_score(
        self,
        node_id: str,
        query_context: dict[str, Any],
    ) -> float:
        """Compute a multi-factor relevance score for a node.

        Used by the context assembler to rank nodes for inclusion
        in token-budgeted output.

        Args:
            node_id: The node to score
            query_context: Context about the query:
                - 'target_id': str -- Primary query target
                - 'preferred_edge_kinds': list[str] -- Preferred relationships
                - 'query_text': str -- Original query text

        Returns:
            Relevance score (0.0-1.0)
        """
        ...


# =============================================================================
# OUTPUT INTERFACES
# =============================================================================


class OutputFormatter(ABC):
    """Interface for formatting graph data into various output formats.

    Formatters convert graph query results into human-readable or
    machine-readable formats (Markdown, JSON, tree view).
    """

    @abstractmethod
    def format_node(self, node: Node, detail_level: DetailLevel) -> str:
        """Format a single node.

        Args:
            node: The node to format
            detail_level: Level of detail to include

        Returns:
            Formatted string representation
        """
        ...

    @abstractmethod
    def format_node_with_relationships(
        self,
        node: Node,
        incoming_edges: list[tuple[Edge, Node]],
        outgoing_edges: list[tuple[Edge, Node]],
        detail_level: DetailLevel,
    ) -> str:
        """Format a node with its relationships.

        Args:
            node: The central node
            incoming_edges: (edge, source_node) pairs for incoming edges
            outgoing_edges: (edge, target_node) pairs for outgoing edges
            detail_level: Level of detail to include

        Returns:
            Formatted string with node definition and relationships
        """
        ...

    @abstractmethod
    def format_file_overview(
        self,
        file_path: str,
        nodes: list[Node],
        edges: list[Edge],
    ) -> str:
        """Format an overview of all symbols in a file.

        Args:
            file_path: The file path
            nodes: All nodes in the file
            edges: All edges involving nodes in the file

        Returns:
            Formatted file overview
        """
        ...

    @abstractmethod
    def format_graph_summary(self, summary: GraphSummary) -> str:
        """Format the graph summary statistics.

        Args:
            summary: Graph summary data

        Returns:
            Formatted summary string
        """
        ...

    @abstractmethod
    def format_impact_analysis(
        self,
        target_node: Node,
        affected_by_depth: dict[int, list[Node]],
    ) -> str:
        """Format an impact analysis (blast radius) result.

        Args:
            target_node: The node being analyzed
            affected_by_depth: Affected nodes organized by distance

        Returns:
            Formatted impact analysis
        """
        ...

    @abstractmethod
    def format_tree(
        self,
        nodes: list[Node],
        group_by: str = "file",
    ) -> str:
        """Format nodes as a tree view.

        Args:
            nodes: Nodes to include in the tree
            group_by: How to group nodes ("file", "kind", "language", "community")

        Returns:
            Formatted tree string
        """
        ...


class ContextAssembler(ABC):
    """Interface for assembling token-budgeted context for LLMs.

    The context assembler is the key interface for MCP integration.
    It takes a query (symbol name, file path, or natural language)
    and assembles the most relevant context within a token budget.

    The assembly process:
    1. Identify the target node(s) from the query
    2. Expand outward following edges, prioritized by relevance
    3. Format each node at the appropriate detail level
    4. Pack nodes into the token budget using a greedy algorithm
    5. Return the assembled context with metadata
    """

    @abstractmethod
    def assemble(
        self,
        query: str,
        token_budget: int = 8000,
        detail_level: DetailLevel = DetailLevel.SIGNATURES,
        include_source: bool = False,
        edge_kinds: Sequence[EdgeKind] | None = None,
        max_depth: int = 2,
        min_confidence: float = 0.3,
    ) -> ContextResult:
        """Assemble context for a query within a token budget.

        Args:
            query: Symbol name, file path, or natural language query
            token_budget: Maximum tokens to include in the result
            detail_level: Level of detail for node formatting
            include_source: Whether to include source code
            edge_kinds: Only follow these edge types (None = all)
            max_depth: Maximum traversal depth from target node
            min_confidence: Minimum edge confidence to follow

        Returns:
            ContextResult with assembled text and metadata
        """
        ...

    @abstractmethod
    def assemble_multi(
        self,
        queries: list[str],
        token_budget: int = 8000,
        detail_level: DetailLevel = DetailLevel.SIGNATURES,
    ) -> ContextResult:
        """Assemble context for multiple queries within a shared budget.

        Useful for understanding relationships between multiple symbols.

        Args:
            queries: List of symbol names, file paths, or queries
            token_budget: Maximum tokens for the combined result
            detail_level: Level of detail for node formatting

        Returns:
            ContextResult with assembled text and metadata
        """
        ...


@dataclass(slots=True)
class ContextResult:
    """Result of context assembly.

    Attributes:
        text: The assembled context text (Markdown formatted)
        tokens_used: Estimated token count of the text
        token_budget: The budget that was requested
        nodes_included: Number of nodes included in the context
        nodes_available: Total nodes that matched the query
        nodes_truncated: Number of nodes excluded due to budget
        target_nodes: IDs of the primary target nodes
        included_files: Set of files represented in the context
        metadata: Additional metadata about the assembly
    """

    text: str
    tokens_used: int
    token_budget: int
    nodes_included: int
    nodes_available: int
    nodes_truncated: int
    target_nodes: list[str]
    included_files: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# PIPELINE INTERFACES
# =============================================================================


class ProgressReporter(ABC):
    """Interface for reporting pipeline progress.

    Implementations can report to CLI (rich progress bars),
    log files, or MCP progress notifications.
    """

    @abstractmethod
    def start_phase(self, phase_name: str, total_items: int = 0) -> None:
        """Signal the start of a pipeline phase.

        Args:
            phase_name: Human-readable phase name
            total_items: Expected number of items to process (0 = unknown)
        """
        ...

    @abstractmethod
    def advance(self, items: int = 1, message: str = "") -> None:
        """Report progress within the current phase.

        Args:
            items: Number of items completed
            message: Optional status message
        """
        ...

    @abstractmethod
    def finish_phase(self, summary: str = "") -> None:
        """Signal the end of the current phase.

        Args:
            summary: Optional summary message
        """
        ...

    @abstractmethod
    def error(self, message: str, file_path: str | None = None) -> None:
        """Report an error.

        Args:
            message: Error description
            file_path: File where the error occurred (if applicable)
        """
        ...

    @abstractmethod
    def warning(self, message: str, file_path: str | None = None) -> None:
        """Report a warning.

        Args:
            message: Warning description
            file_path: File where the warning occurred (if applicable)
        """
        ...


class PluginRegistry(ABC):
    """Interface for the language plugin registry.

    The registry discovers, loads, and manages language plugins.
    Plugins are discovered via Python entry points or explicit
    registration.

    Entry point group: "codegraph.plugins"
    """

    @abstractmethod
    def discover_plugins(self) -> list[str]:
        """Discover available plugins via entry points.

        Returns:
            List of discovered plugin names
        """
        ...

    @abstractmethod
    def register_plugin(self, plugin: LanguagePlugin) -> None:
        """Explicitly register a plugin instance.

        Args:
            plugin: The plugin to register

        Raises:
            ValueError: If a plugin with the same name is already registered
        """
        ...

    @abstractmethod
    def get_plugin(self, name: str) -> LanguagePlugin | None:
        """Get a registered plugin by name.

        Args:
            name: Plugin name (e.g., "php", "javascript")

        Returns:
            The plugin, or None if not registered
        """
        ...

    @abstractmethod
    def get_plugin_for_file(self, file_path: str) -> LanguagePlugin | None:
        """Get the plugin that handles a given file extension.

        Args:
            file_path: File path (extension is used for matching)

        Returns:
            The plugin, or None if no plugin handles this extension
        """
        ...

    @abstractmethod
    def get_all_plugins(self) -> list[LanguagePlugin]:
        """Get all registered plugins.

        Returns:
            List of all registered plugin instances
        """
        ...

    @abstractmethod
    def get_all_extensions(self) -> dict[str, str]:
        """Get a mapping of file extensions to plugin names.

        Returns:
            Dict mapping extension (e.g., ".php") to plugin name (e.g., "php")
        """
        ...


class Pipeline(ABC):
    """Interface for the main processing pipeline.

    The pipeline orchestrates the 8-phase processing flow:
    1. Project Discovery
    2. File Discovery & Hashing
    3. Structural Extraction
    4. Name & Module Resolution
    5. Framework Pattern Detection
    6. Cross-Language Matching
    7. Enrichment (PageRank, community detection)
    8. Persistence & Indexing
    """

    @abstractmethod
    def run(
        self,
        project_root: str,
        config: dict[str, Any] | None = None,
        progress: ProgressReporter | None = None,
    ) -> PipelineSummary:
        """Run the full pipeline on a project.

        Args:
            project_root: Absolute path to the project root
            config: Optional configuration overrides
            progress: Optional progress reporter

        Returns:
            PipelineSummary with statistics about the run
        """
        ...

    @abstractmethod
    def run_incremental(
        self,
        project_root: str,
        changed_files: Sequence[str] | None = None,
        progress: ProgressReporter | None = None,
    ) -> PipelineSummary:
        """Run an incremental update on a project.

        If changed_files is None, uses content hashing to detect changes.
        If changed_files is provided, only re-processes those files.

        Args:
            project_root: Absolute path to the project root
            changed_files: Optional list of changed file paths
            progress: Optional progress reporter

        Returns:
            PipelineSummary with statistics about the incremental run
        """
        ...

    @abstractmethod
    def run_phase(
        self,
        phase_name: str,
        project_root: str,
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        """Run a single pipeline phase (for debugging/testing).

        Args:
            phase_name: Name of the phase to run
            project_root: Absolute path to the project root
            progress: Optional progress reporter

        Returns:
            Phase-specific result dict
        """
        ...


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(slots=True)
class CodeGraphConfig:
    """Top-level configuration for a CodeGraph project.

    Loaded from codegraph.yaml in the project root.

    Attributes:
        project_name: Human-readable project name
        project_root: Absolute path to the project root
        db_path: Path to the SQLite database file
        languages: Enabled language plugins and their config
        ignore_patterns: Glob patterns for files/dirs to ignore
        framework_detection: Framework detection settings
        cross_language: Cross-language matching settings
        enrichment: Enrichment phase settings
        output: Output formatting settings
        performance: Performance tuning settings
    """

    project_name: str = ""
    project_root: str = ""
    db_path: str = ".codegraph/graph.db"
    languages: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "php": {"enabled": True},
            "javascript": {"enabled": True},
            "typescript": {"enabled": True},
        }
    )
    ignore_patterns: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/vendor/**",
            "**/.git/**",
            "**/dist/**",
            "**/build/**",
            "**/__pycache__/**",
            "**/storage/**",
            "**/*.min.js",
            "**/*.min.css",
            "**/*.map",
        ]
    )
    framework_detection: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": True,
            "auto_detect": True,
            "frameworks": {},
        }
    )
    cross_language: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": True,
            "api_matching": True,
            "type_contracts": True,
            "min_confidence": 0.3,
        }
    )
    enrichment: dict[str, Any] = field(
        default_factory=lambda: {
            "pagerank": True,
            "community_detection": True,
            "git_metadata": False,
        }
    )
    output: dict[str, Any] = field(
        default_factory=lambda: {
            "default_format": "markdown",
            "default_detail_level": "signatures",
            "default_token_budget": 8000,
        }
    )
    performance: dict[str, Any] = field(
        default_factory=lambda: {
            "max_workers": 4,
            "batch_size": 100,
            "max_file_size_bytes": 1_000_000,
        }
    )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> CodeGraphConfig:
        """Load configuration from a YAML file.

        Args:
            yaml_path: Path to codegraph.yaml

        Returns:
            Populated CodeGraphConfig instance

        Raises:
            FileNotFoundError: If the YAML file does not exist
            ValueError: If the YAML is malformed
        """
        raise NotImplementedError

    @classmethod
    def default(cls) -> CodeGraphConfig:
        """Create a default configuration."""
        return cls()


# =============================================================================
# MCP SERVER INTERFACES
# =============================================================================


class MCPToolHandler(ABC):
    """Interface for MCP tool implementations.

    Each MCP tool exposed by the CodeGraph server implements this
    interface. Tools receive structured arguments and return
    formatted results.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name as exposed via MCP (e.g., 'codegraph_lookup_symbol')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable tool description for LLM tool selection."""
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input arguments."""
        ...

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> str:
        """Execute the tool with the given arguments.

        Args:
            arguments: Validated arguments matching input_schema

        Returns:
            Formatted string result (Markdown)
        """
        ...


class MCPResourceHandler(ABC):
    """Interface for MCP resource implementations.

    Resources provide read-only access to graph data via URIs.
    """

    @property
    @abstractmethod
    def uri_template(self) -> str:
        """URI template for this resource (e.g., 'codegraph://files/{path}')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable resource name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable resource description."""
        ...

    @property
    @abstractmethod
    def mime_type(self) -> str:
        """MIME type of the resource content."""
        ...

    @abstractmethod
    async def read(self, uri: str) -> str:
        """Read the resource at the given URI.

        Args:
            uri: The resource URI

        Returns:
            Resource content as a string
        """
        ...


# =============================================================================
# UTILITY FUNCTIONS (type stubs for key helpers)
# =============================================================================


def generate_node_id(
    file_path: str,
    start_line: int,
    kind: NodeKind,
    name: str,
) -> str:
    """Generate a deterministic, unique node ID.

    Format: "{file_path}:{start_line}:{kind.value}:{name}"

    Args:
        file_path: Relative path from project root
        start_line: 1-based starting line number
        kind: Node kind
        name: Unqualified symbol name

    Returns:
        Deterministic node ID string
    """
    return f"{file_path}:{start_line}:{kind.value}:{name}"


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content.

    Args:
        content: Raw file bytes

    Returns:
        Hex-encoded SHA-256 hash string
    """
    import hashlib

    return hashlib.sha256(content).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estimate the number of LLM tokens in a text string.

    Uses a simple heuristic: ~4 characters per token for English text,
    ~3.5 characters per token for code (more symbols/short identifiers).

    Args:
        text: The text to estimate

    Returns:
        Estimated token count
    """
    # Rough heuristic: code averages ~3.5 chars per token
    return max(1, len(text) // 4)


def detect_language(file_path: str) -> str | None:
    """Detect the programming language from a file path.

    Args:
        file_path: File path (extension is used for detection)

    Returns:
        Language string ("php", "javascript", "typescript") or None
    """
    import os

    ext = os.path.splitext(file_path)[1].lower()
    # Handle compound extensions
    if file_path.endswith(".blade.php"):
        return "php"
    if file_path.endswith(".d.ts"):
        return "typescript"
    mapping: dict[str, str] = {
        ".php": "php",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".mts": "typescript",
        ".cts": "typescript",
    }
    return mapping.get(ext)


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Enumerations
    "NodeKind",
    "EdgeKind",
    "Language",
    "DetailLevel",
    "ResolutionStrategy",
    # Data Models
    "Node",
    "Edge",
    "ExtractionResult",
    "UnresolvedReference",
    "ExtractionError",
    "ResolutionResult",
    "FrameworkPattern",
    "CrossLanguageMatch",
    "APIEndpoint",
    "APICall",
    "FileInfo",
    "PipelineSummary",
    "GraphSummary",
    "ContextResult",
    # Core Interfaces
    "LanguagePlugin",
    "ASTExtractor",
    "ModuleResolver",
    "FrameworkDetector",
    "CrossLanguageMatcher",
    # Storage Interfaces
    "GraphStore",
    "GraphAnalyzer",
    # Output Interfaces
    "OutputFormatter",
    "ContextAssembler",
    # Pipeline Interfaces
    "ProgressReporter",
    "PluginRegistry",
    "Pipeline",
    # Configuration
    "CodeGraphConfig",
    # MCP Interfaces
    "MCPToolHandler",
    "MCPResourceHandler",
    # Utility Functions
    "generate_node_id",
    "compute_content_hash",
    "estimate_tokens",
    "detect_language",
]
