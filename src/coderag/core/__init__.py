"""
CodeRAG Core Package
====================

Core models, configuration, and plugin registry.
"""

from coderag.core.config import CodeGraphConfig
from coderag.core.models import (
    APICall,
    APIEndpoint,
    ContextResult,
    CrossLanguageMatch,
    DetailLevel,
    Edge,
    EdgeKind,
    ExtractionError,
    ExtractionResult,
    FileInfo,
    FrameworkPattern,
    GraphSummary,
    Language,
    Node,
    NodeKind,
    PipelineSummary,
    ResolutionResult,
    ResolutionStrategy,
    UnresolvedReference,
    compute_content_hash,
    detect_language,
    estimate_tokens,
    generate_node_id,
)
from coderag.core.registry import (
    ASTExtractor,
    FrameworkDetector,
    LanguagePlugin,
    ModuleResolver,
    PluginRegistry,
)

__all__ = [
    # Config
    "CodeGraphConfig",
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
    "ExtractionError",
    "UnresolvedReference",
    "ResolutionResult",
    "FrameworkPattern",
    "CrossLanguageMatch",
    "APIEndpoint",
    "APICall",
    "FileInfo",
    "PipelineSummary",
    "GraphSummary",
    "ContextResult",
    # Plugin System
    "ASTExtractor",
    "ModuleResolver",
    "FrameworkDetector",
    "LanguagePlugin",
    "PluginRegistry",
    # Utility Functions
    "generate_node_id",
    "compute_content_hash",
    "estimate_tokens",
    "detect_language",
]
