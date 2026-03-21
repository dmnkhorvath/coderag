"""Context pre-loading for Smart Launcher.

Builds token-budgeted markdown context from the knowledge graph
for pre-loading into AI coding sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
    from coderag.core.config import CodeGraphConfig
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _build_project_overview(store: SQLiteStore, config: CodeGraphConfig) -> str:
    """Build a project overview section."""
    parts: list[str] = []
    parts.append("# Project Overview\n")

    name = config.project_name or "Unknown Project"
    parts.append(f"**Project:** {name}\n")

    try:
        summary = store.get_summary()
        parts.append(f"**Total Nodes:** {summary.total_nodes:,}")
        parts.append(f"**Total Edges:** {summary.total_edges:,}")

        if summary.files_by_language:
            lang_parts = [f"{lang}: {count}" for lang, count in sorted(summary.files_by_language.items())]
            joined_langs = ", ".join(lang_parts)
            parts.append(f"**Languages:** {joined_langs}")

        if summary.frameworks:
            joined_fw = ", ".join(summary.frameworks)
            parts.append(f"**Frameworks:** {joined_fw}")

        if summary.nodes_by_kind:
            kind_parts = [
                f"{kind}: {count}" for kind, count in sorted(summary.nodes_by_kind.items(), key=lambda x: -x[1])[:10]
            ]
            joined_kinds = ", ".join(kind_parts)
            parts.append(f"**Node Types:** {joined_kinds}")

        parts.append("")
    except Exception as exc:
        logger.debug("Could not get summary: %s", exc)
        parts.append("")

    return "\n".join(parts)


def _build_key_files_section(
    store: SQLiteStore,
    analyzer: NetworkXAnalyzer,
    limit: int = 20,
) -> str:
    """Build a section listing the most important files/symbols by PageRank."""
    parts: list[str] = []
    parts.append("## Key Files & Symbols\n")

    try:
        analyzer.pagerank()
        top_nodes = analyzer.get_top_nodes("pagerank", limit=limit)

        if not top_nodes:
            parts.append("_No nodes found in graph._\n")
            return "\n".join(parts)

        for node_id, score in top_nodes:
            node = store.get_node(node_id)
            if node is None:
                continue
            kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
            parts.append(
                f"- **`{node.qualified_name}`** ({kind}) in `{node.file_path}:{node.start_line}` [PR: {score:.4f}]"
            )

        parts.append("")
    except Exception as exc:
        logger.debug("Could not compute PageRank: %s", exc)
        parts.append("_Could not compute importance ranking._\n")

    return "\n".join(parts)


def _build_search_results_section(
    store: SQLiteStore,
    query: str,
    limit: int = 15,
) -> str:
    """Build a section with FTS5 search results for a query."""
    parts: list[str] = []
    parts.append(f"## Relevant Symbols for: '{query}'\n")

    try:
        results = store.search_nodes(query, limit=limit)

        if not results:
            parts.append("_No matching symbols found._\n")
            return "\n".join(parts)

        for node in results:
            kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
            doc_preview = ""
            if node.docblock:
                doc_preview = node.docblock[:100].replace("\n", " ").strip()
                doc_preview = f" — {doc_preview}"
            parts.append(f"- **`{node.qualified_name}`** ({kind}) in `{node.file_path}:{node.start_line}`{doc_preview}")

        parts.append("")
    except Exception as exc:
        logger.debug("Search failed: %s", exc)
        parts.append("_Search unavailable._\n")

    return "\n".join(parts)


def _build_entry_points_section(
    store: SQLiteStore,
    analyzer: NetworkXAnalyzer,
    limit: int = 10,
) -> str:
    """Build a section listing likely entry points."""
    parts: list[str] = []
    parts.append("## Entry Points\n")

    try:
        entry_ids = analyzer.get_entry_points(limit=limit)

        if not entry_ids:
            parts.append("_No entry points detected._\n")
            return "\n".join(parts)

        for node_id in entry_ids:
            node = store.get_node(node_id)
            if node is None:
                continue
            kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
            parts.append(f"- **`{node.qualified_name}`** ({kind}) in `{node.file_path}:{node.start_line}`")

        parts.append("")
    except Exception as exc:
        logger.debug("Could not find entry points: %s", exc)
        parts.append("_Could not detect entry points._\n")

    return "\n".join(parts)


def _load_analyzer(store: SQLiteStore) -> NetworkXAnalyzer:
    """Load a NetworkXAnalyzer from the store."""
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer

    analyzer = NetworkXAnalyzer()
    analyzer.load_from_store(store)
    return analyzer


def build_preload_context(
    store: SQLiteStore,
    config: CodeGraphConfig,
    query: str | None = None,
    token_budget: int = 8000,
) -> str:
    """Build token-budgeted markdown context for AI pre-loading.

    Runs PageRank on the graph to identify the most important files
    and symbols. If a query is provided, also runs FTS5 search for
    relevant symbols.

    Args:
        store: Initialized SQLiteStore with graph data.
        config: Project configuration.
        query: Optional search query for relevant symbols.
        token_budget: Maximum token budget for the output.

    Returns:
        Markdown string with project context.
    """
    sections: list[str] = []
    tokens_used = 0

    # 1. Project overview (always included)
    overview = _build_project_overview(store, config)
    overview_tokens = _estimate_tokens(overview)
    sections.append(overview)
    tokens_used += overview_tokens

    # 2. Load analyzer for graph-based sections
    try:
        analyzer = _load_analyzer(store)
    except Exception as exc:
        logger.debug("Could not load analyzer: %s", exc)
        sections.append("\n_Graph analysis unavailable._\n")
        return "\n".join(sections)

    remaining = token_budget - tokens_used

    # 3. Key files by PageRank (allocate ~40% of remaining budget)
    key_files_budget = int(remaining * 0.4)
    key_files_limit = max(5, key_files_budget // 80)
    key_files = _build_key_files_section(store, analyzer, limit=min(key_files_limit, 30))
    key_files_tokens = _estimate_tokens(key_files)
    if tokens_used + key_files_tokens <= token_budget:
        sections.append(key_files)
        tokens_used += key_files_tokens

    # 4. Query-specific results (if query provided, ~30% of remaining)
    if query:
        remaining = token_budget - tokens_used
        search_limit = max(5, int(remaining * 0.3) // 80)
        search_results = _build_search_results_section(store, query, limit=min(search_limit, 20))
        search_tokens = _estimate_tokens(search_results)
        if tokens_used + search_tokens <= token_budget:
            sections.append(search_results)
            tokens_used += search_tokens

    # 5. Entry points (remaining budget)
    remaining = token_budget - tokens_used
    if remaining > 200:
        entry_limit = max(3, remaining // 80)
        entry_points = _build_entry_points_section(store, analyzer, limit=min(entry_limit, 15))
        entry_tokens = _estimate_tokens(entry_points)
        if tokens_used + entry_tokens <= token_budget:
            sections.append(entry_points)
            tokens_used += entry_tokens

    result = "\n".join(sections)

    # Final truncation safety net
    max_chars = token_budget * 4
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n_[Context truncated to fit token budget]_\n"

    return result
