"""Project prompt generator for Smart Launcher.

Generates CLAUDE.md / .cursorrules content with project overview,
architecture summary, and MCP tool descriptions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coderag.core.config import CodeGraphConfig
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# MCP tools with brief descriptions
_MCP_TOOLS: list[tuple[str, str]] = [
    ("coderag_lookup_symbol", "Look up a symbol by name with context and relationships"),
    ("coderag_find_usages", "Find all usages of a symbol across the codebase"),
    ("coderag_impact_analysis", "Analyze blast radius of changing a symbol"),
    ("coderag_file_context", "Get full context for a file including symbols and relationships"),
    ("coderag_find_routes", "Find API routes matching a URL pattern"),
    ("coderag_search", "Full-text search across the knowledge graph"),
    ("coderag_architecture", "Get architecture overview with communities and key nodes"),
    ("coderag_dependency_graph", "Show dependency graph for a symbol or file"),
]


def _get_languages_summary(store: SQLiteStore) -> str:
    """Get a summary of languages in the project."""
    try:
        summary = store.get_summary()
        if summary.files_by_language:
            parts = []
            for lang, count in sorted(summary.files_by_language.items(), key=lambda x: -x[1]):
                parts.append(f"{lang} ({count} files)")
            return ", ".join(parts)
    except Exception:
        pass
    return "Unknown"


def _get_frameworks_summary(store: SQLiteStore) -> str:
    """Get a summary of detected frameworks."""
    try:
        summary = store.get_summary()
        if summary.frameworks:
            return ", ".join(summary.frameworks)
    except Exception:
        pass
    return "None detected"


def _get_top_modules(store: SQLiteStore, limit: int = 10) -> list[tuple[str, str, float]]:
    """Get top modules by PageRank.

    Returns:
        List of (name, qualified_name, pagerank) tuples.
    """
    try:
        summary = store.get_summary()
        return summary.top_nodes_by_pagerank[:limit]
    except Exception:
        return []


def _get_cross_language_summary(store: SQLiteStore) -> str:
    """Get a summary of cross-language connections."""
    try:
        store.get_stats()  # verify store is accessible
        edges_by_kind = {}
        conn = store.connection
        rows = conn.execute(
            "SELECT kind, COUNT(*) FROM edges WHERE kind IN ('api_calls', 'api_serves', 'shares_type_contract') GROUP BY kind"
        ).fetchall()
        for kind, count in rows:
            edges_by_kind[kind] = count

        if edges_by_kind:
            parts = [f"{kind}: {count}" for kind, count in edges_by_kind.items()]
            return ", ".join(parts)
    except Exception:
        pass
    return "None detected"


def generate_project_prompt(
    store: SQLiteStore,
    config: CodeGraphConfig,
) -> str:
    """Generate a project prompt for CLAUDE.md / .cursorrules.

    Generates markdown with:
    - Project name, languages detected, framework summary
    - Architecture overview (top modules by PageRank)
    - Key entry points
    - MCP tools available with brief descriptions
    - Cross-language connections summary

    Args:
        store: Initialized SQLiteStore with graph data.
        config: Project configuration.

    Returns:
        Markdown string suitable for CLAUDE.md.
    """
    parts: list[str] = []
    project_name = config.project_name or Path(config.project_root).name or "Project"

    # Header
    parts.append(f"# {project_name}\n")
    parts.append("This project has been analyzed by CodeRAG. Use the MCP tools below")
    parts.append("to explore the codebase structure and relationships.\n")

    # Project info
    parts.append("## Project Info\n")
    languages = _get_languages_summary(store)
    frameworks = _get_frameworks_summary(store)
    parts.append(f"- **Languages:** {languages}")
    parts.append(f"- **Frameworks:** {frameworks}")

    try:
        summary = store.get_summary()
        parts.append(f"- **Total Symbols:** {summary.total_nodes:,}")
        parts.append(f"- **Total Relationships:** {summary.total_edges:,}")
        parts.append(f"- **Communities:** {summary.communities}")
    except Exception:
        pass
    parts.append("")

    # Architecture overview
    parts.append("## Architecture Overview\n")
    parts.append("Top modules by importance (PageRank):\n")
    top_modules = _get_top_modules(store)
    if top_modules:
        for name, qname, score in top_modules:
            parts.append(f"- `{qname}` (score: {score:.4f})")
    else:
        parts.append("_Run `coderag analyze` to compute architecture metrics._")
    parts.append("")

    # Cross-language connections
    xl_summary = _get_cross_language_summary(store)
    if xl_summary != "None detected":
        parts.append("## Cross-Language Connections\n")
        parts.append(f"- {xl_summary}")
        parts.append("")

    # MCP tools
    parts.append("## Available MCP Tools\n")
    parts.append("Use these tools to explore the codebase:\n")
    for tool_name, description in _MCP_TOOLS:
        parts.append(f"- **{tool_name}**: {description}")
    parts.append("")

    # Tips
    parts.append("## Tips\n")
    parts.append("- Use `coderag_lookup_symbol` to understand any symbol in depth")
    parts.append("- Use `coderag_architecture` to get a high-level overview")
    parts.append("- Use `coderag_impact_analysis` before making changes to understand blast radius")
    parts.append("- Use `coderag_find_routes` to explore API endpoints")
    parts.append("")

    return "\n".join(parts)


def write_project_prompt(
    project_path: str,
    content: str,
    filename: str = "CLAUDE.md",
) -> str:
    """Write the project prompt to a file.

    Args:
        project_path: Path to the project root.
        content: Markdown content to write.
        filename: Output filename (default: CLAUDE.md).

    Returns:
        Path to the written file.
    """
    output_path = os.path.join(project_path, filename)
    with open(output_path, "w") as f:
        f.write(content)
    logger.info("Wrote project prompt: %s", output_path)
    return output_path
