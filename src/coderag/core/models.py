"""
CodeRAG Core Models
===================

Enumerations, data models, and utility functions that form the foundation
of the CodeRAG knowledge graph system.

All node types, edge types, and data structures used throughout the
pipeline are defined here. These mirror the interface contracts from
the architecture specification.
"""

from __future__ import annotations

import enum
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# ENUMERATIONS
# =============================================================================


class NodeKind(str, enum.Enum):
    """All recognized node types in the knowledge graph.

    Each node in the graph has exactly one kind. Kinds are organized
    into categories: structural, declarations, scoping, granular,
    and framework-specific.
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
    LISTENER = "listener"
    PROVIDER = "provider"
    CONTROLLER = "controller"


class EdgeKind(str, enum.Enum):
    """All recognized edge types in the knowledge graph.

    Each edge has a source node, target node, kind, and confidence score.
    Edges are directional: source -> target.
    """

    # -- Containment --
    CONTAINS = "contains"
    DEFINED_IN = "defined_in"
    MEMBER_OF = "member_of"

    # -- Inheritance & Type System --
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    USES_TRAIT = "uses_trait"
    HAS_TYPE = "has_type"
    RETURNS_TYPE = "returns_type"
    GENERIC_OF = "generic_of"
    UNION_OF = "union_of"
    INTERSECTION_OF = "intersection_of"

    # -- Dependency --
    IMPORTS = "imports"
    IMPORTS_TYPE = "imports_type"
    EXPORTS = "exports"
    RE_EXPORTS = "re_exports"
    DYNAMIC_IMPORTS = "dynamic_imports"
    DEPENDS_ON = "depends_on"

    # -- Call Graph --
    CALLS = "calls"
    INSTANTIATES = "instantiates"
    DISPATCHES_EVENT = "dispatches_event"
    LISTENS_TO = "listens_to"

    # -- Framework: Routing --
    ROUTES_TO = "routes_to"

    # -- Framework: Components --
    RENDERS = "renders"
    PASSES_PROP = "passes_prop"
    USES_HOOK = "uses_hook"
    PROVIDES_CONTEXT = "provides_context"
    CONSUMES_CONTEXT = "consumes_context"

    # -- Cross-Language --
    API_CALLS = "api_calls"
    API_SERVES = "api_serves"
    SHARES_TYPE_CONTRACT = "shares_type_contract"

    # -- Git-Derived --
    CO_CHANGES_WITH = "co_changes_with"


class Language(str, enum.Enum):
    """Supported programming languages."""
    PHP = "php"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"


class DetailLevel(str, enum.Enum):
    """Level of detail for context assembly output."""
    SIGNATURE = "signature"
    SUMMARY = "summary"
    DETAILED = "detailed"
    COMPREHENSIVE = "comprehensive"


class ResolutionStrategy(str, enum.Enum):
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

    Nodes are immutable value objects. The ``id`` field uniquely identifies
    a node across the entire graph and is deterministically generated
    from the file path, kind, and qualified name.

    Attributes:
        id: Unique identifier (format: "{file_path}:{start_line}:{kind}:{name}")
        kind: The type of code symbol this node represents.
        name: Short, unqualified name (e.g., "UserService").
        qualified_name: Fully-qualified name (e.g., "App\\Services\\UserService").
        file_path: Relative path from project root.
        start_line: 1-based starting line number.
        end_line: 1-based ending line number.
        language: Language identifier string ("php", "javascript", "typescript").
        docblock: PHPDoc / JSDoc / TSDoc content, if present.
        source_text: Raw source text of the symbol (for enrichment).
        content_hash: SHA-256 hash of the source text.
        metadata: Arbitrary key-value metadata (JSON-serializable).
        pagerank: PageRank score computed during enrichment.
        community_id: Community / cluster ID from community detection.
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
        source_id: ID of the source node (FK to Node.id).
        target_id: ID of the target node (FK to Node.id).
        kind: The type of relationship.
        confidence: Confidence score (0.0 = guess, 1.0 = certain).
        line_number: Line where the relationship occurs in source.
        metadata: Arbitrary key-value metadata (JSON-serializable).
    """
    source_id: str
    target_id: str
    kind: EdgeKind
    confidence: float = 1.0
    line_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )


@dataclass(frozen=True, slots=True)
class UnresolvedReference:
    """A reference that could not be resolved to a target node.

    Collected during extraction and resolved in the resolution phase.
    If still unresolved after resolution, low-confidence edges are created.

    Attributes:
        source_node_id: ID of the node containing the reference.
        reference_name: The unresolved name/path as written in source.
        reference_kind: Expected edge kind if resolved.
        line_number: Line where the reference occurs.
        context: Additional context for resolution.
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
        file_path: File where the error occurred.
        line_number: Line number of the error (if known).
        message: Human-readable error description.
        severity: ``"error"`` or ``"warning"``.
        node_type: Tree-sitter node type that caused the error.
    """
    file_path: str
    line_number: int | None
    message: str
    severity: str = "warning"
    node_type: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    """Result of extracting nodes and edges from a single source file.

    Returned by ``ASTExtractor.extract()``. Contains all discovered nodes,
    edges, and any errors encountered during extraction.

    Attributes:
        file_path: Relative path of the parsed file.
        language: Detected language of the file.
        nodes: List of extracted nodes.
        edges: List of extracted edges.
        unresolved_references: Names that could not be resolved to nodes.
        errors: Parse errors or extraction warnings.
        parse_time_ms: Time spent parsing the file in milliseconds.
    """
    file_path: str
    language: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = field(default_factory=list)
    errors: list[ExtractionError] = field(default_factory=list)
    parse_time_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Result of resolving an import/reference path.

    Returned by ``ModuleResolver.resolve()``. Contains the resolved
    file path, confidence, and resolution strategy used.

    Attributes:
        resolved_path: Absolute or project-relative path to the resolved file.
        confidence: How confident we are in this resolution (0.0-1.0).
        resolution_strategy: Which strategy successfully resolved the path.
        is_external: Whether this resolves to an external package.
        package_name: Name of the external package (if is_external).
        exported_symbols: Specific symbols imported (if known).
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

    Returned by ``FrameworkDetector.detect()``. Contains additional
    nodes and edges that represent framework-level abstractions.

    Attributes:
        framework_name: Name of the detected framework (e.g., "laravel", "react").
        framework_version: Detected version (if determinable).
        pattern_type: Type of pattern (e.g., "route", "component", "model").
        nodes: Additional framework-specific nodes to add to the graph.
        edges: Additional framework-specific edges to add to the graph.
        metadata: Framework-specific metadata.
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
        source_node_id: ID of the source node (e.g., JS fetch call).
        target_node_id: ID of the target node (e.g., PHP route).
        edge_kind: Type of cross-language relationship.
        confidence: Confidence in the match (0.0-1.0).
        match_strategy: How the match was determined.
        evidence: Evidence supporting the match.
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
        node_id: ID of the route node in the graph.
        http_method: HTTP method (GET, POST, PUT, PATCH, DELETE).
        url_pattern: URL pattern with parameter placeholders.
        url_regex: Compiled regex for matching against API calls.
        controller: Qualified name of the handler.
        middleware: List of middleware applied.
        parameters: List of URL parameter names.
        response_type: Expected response type/resource (if known).
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
        node_id: ID of the calling node in the graph.
        http_method: HTTP method (if determinable).
        url_pattern: URL pattern or template.
        url_source: How the URL is constructed (static, template, variable).
        file_path: File containing the API call.
        line_number: Line number of the call.
        confidence: Confidence in URL extraction.
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
        path: Absolute path to the file.
        relative_path: Path relative to project root.
        language: Detected language.
        plugin_name: Name of the plugin that will process this file.
        content_hash: SHA-256 hash of file contents.
        size_bytes: File size in bytes.
        is_changed: Whether the file has changed since last parse.
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
        total_files: Total files discovered.
        files_parsed: Files actually parsed (excludes unchanged).
        files_skipped: Files skipped (unchanged).
        files_errored: Files with parse errors.
        total_nodes: Total nodes in the graph after this run.
        total_edges: Total edges in the graph after this run.
        nodes_added: New nodes added in this run.
        nodes_updated: Existing nodes updated in this run.
        nodes_removed: Stale nodes removed in this run.
        edges_added: New edges added in this run.
        files_by_language: File count per language.
        nodes_by_kind: Node count per kind.
        edges_by_kind: Edge count per kind.
        frameworks_detected: List of detected frameworks.
        cross_language_edges: Number of cross-language edges.
        parse_errors: Total parse errors.
        resolution_rate: Percentage of imports successfully resolved.
        avg_confidence: Average edge confidence score.
        total_parse_time_ms: Total time spent parsing files.
        total_pipeline_time_ms: Total pipeline execution time.
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


@dataclass(slots=True)
class ContextResult:
    """Result of context assembly.

    Attributes:
        text: The assembled context text (Markdown formatted).
        tokens_used: Estimated token count of the text.
        token_budget: The budget that was requested.
        nodes_included: Number of nodes included in the context.
        nodes_available: Total nodes that matched the query.
        nodes_truncated: Number of nodes excluded due to budget.
        target_nodes: IDs of the primary target nodes.
        included_files: Set of files represented in the context.
        metadata: Additional metadata about the assembly.
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
# UTILITY FUNCTIONS
# =============================================================================


def generate_node_id(
    file_path: str,
    start_line: int,
    kind: NodeKind,
    name: str,
) -> str:
    """Generate a deterministic, unique node ID.

    Format: ``"{file_path}:{start_line}:{kind.value}:{name}"``

    Args:
        file_path: Relative path from project root.
        start_line: 1-based starting line number.
        kind: Node kind.
        name: Unqualified symbol name.

    Returns:
        Deterministic node ID string.
    """
    return f"{file_path}:{start_line}:{kind.value}:{name}"


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content.

    Args:
        content: Raw file bytes.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(content).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estimate the number of LLM tokens in a text string.

    Uses a simple heuristic: ~4 characters per token for English text,
    ~3.5 characters per token for code (more symbols/short identifiers).

    Args:
        text: The text to estimate.

    Returns:
        Estimated token count.
    """
    return max(1, len(text) // 4)


def detect_language(file_path: str) -> str | None:
    """Detect the programming language from a file path.

    Args:
        file_path: File path (extension is used for detection).

    Returns:
        Language string ("php", "javascript", "typescript") or ``None``.
    """
    # Handle compound extensions first
    if file_path.endswith(".blade.php"):
        return "php"
    if file_path.endswith(".d.ts"):
        return "typescript"

    ext = os.path.splitext(file_path)[1].lower()
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
    # Utility Functions
    "generate_node_id",
    "compute_content_hash",
    "estimate_tokens",
    "detect_language",
]
