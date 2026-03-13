"""MCP Tools for CodeRAG.

Registers 8 tools on a FastMCP server instance that expose
the knowledge graph to LLMs via the Model Context Protocol.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from enum import StrEnum
from typing import Any

from coderag.core.models import (
    EdgeKind,
    Node,
    NodeKind,
    estimate_tokens,
)

logger = logging.getLogger(__name__)


# ── Enums for tool parameters ─────────────────────────────────


class DetailLevel(StrEnum):
    """Detail level for symbol lookup."""

    signature = "signature"
    summary = "summary"
    detailed = "detailed"
    comprehensive = "comprehensive"


class UsageType(StrEnum):
    """Types of symbol usage to search for."""

    calls = "calls"
    imports = "imports"
    extends = "extends"
    implements = "implements"
    instantiates = "instantiates"
    type_references = "type_references"
    all = "all"


class HttpMethod(StrEnum):
    """HTTP methods for route filtering."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    ANY = "ANY"


class ArchitectureFocus(StrEnum):
    """Focus area for architecture overview."""

    full = "full"
    backend = "backend"
    frontend = "frontend"
    api_layer = "api_layer"
    data_layer = "data_layer"


class DependencyDirection(StrEnum):
    """Direction for dependency graph traversal."""

    dependencies = "dependencies"
    dependents = "dependents"
    both = "both"


# ── Edge kind mapping for usage types ─────────────────────────

_USAGE_TYPE_TO_EDGE_KINDS: dict[str, list[EdgeKind]] = {
    "calls": [EdgeKind.CALLS],
    "imports": [EdgeKind.IMPORTS, EdgeKind.IMPORTS_TYPE, EdgeKind.DYNAMIC_IMPORTS],
    "extends": [EdgeKind.EXTENDS],
    "implements": [EdgeKind.IMPLEMENTS],
    "instantiates": [EdgeKind.INSTANTIATES],
    "type_references": [EdgeKind.HAS_TYPE, EdgeKind.RETURNS_TYPE, EdgeKind.GENERIC_OF],
}


def _truncate_to_budget(text: str, token_budget: int) -> str:
    """Truncate text to fit within token budget."""
    tokens = estimate_tokens(text)
    if tokens <= token_budget:
        return text
    # Rough truncation: ~3.5 chars per token for code
    max_chars = int(token_budget * 3.5)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... (truncated to fit token budget)"


def _resolve_symbol(symbol: str, store: Any) -> tuple[Node | None, list[Node]]:
    """Resolve a symbol name to a node, returning (node, candidates).

    Tries exact qualified name match first, then falls back to search.
    Returns the best match and a list of candidates if no exact match.
    """
    # Try exact qualified name match
    node = store.get_node_by_qualified_name(symbol)
    if node is not None:
        return node, []

    # Try search
    candidates = store.search_nodes(symbol, limit=10)
    if candidates:
        # Check for exact name match in candidates
        for c in candidates:
            if c.name == symbol or c.qualified_name == symbol:
                return c, []
        # Return best match (first result, highest relevance)
        return candidates[0], candidates[1:]

    return None, []


def _format_candidates(candidates: list[Node], symbol: str) -> str:
    """Format a list of candidate nodes as suggestions."""
    lines = [f"Symbol `{symbol}` not found. Did you mean one of these?\n"]
    for c in candidates[:10]:
        kind = c.kind.value if isinstance(c.kind, NodeKind) else c.kind
        lines.append(f"- `{c.qualified_name}` ({kind}, `{c.file_path}:{c.start_line}`)")
    return "\n".join(lines)


def _normalize_file_path(file_path: str, store: Any) -> str | None:
    """Normalize a file path for flexible matching.

    Tries exact match, then strips leading slashes, then searches.
    """
    # Try exact
    nodes = store.find_nodes(file_path=file_path, limit=1)
    if nodes:
        return file_path

    # Strip leading slash
    stripped = file_path.lstrip("/")
    if stripped != file_path:
        nodes = store.find_nodes(file_path=stripped, limit=1)
        if nodes:
            return stripped

    # Try searching with LIKE pattern
    conn = store.connection
    row = conn.execute(
        "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE ? LIMIT 1",
        (f"%{stripped}",),
    ).fetchone()
    if row:
        return row[0]

    return None


def register_tools(mcp: Any, store: Any, analyzer: Any) -> None:
    """Register all 8 CodeRAG tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance.
        store: Initialized SQLiteStore.
        analyzer: Loaded NetworkXAnalyzer.
    """
    from coderag.output.context import ContextAssembler
    from coderag.output.markdown import MarkdownFormatter

    assembler = ContextAssembler()
    formatter = MarkdownFormatter()

    # ── Tool 1: coderag_lookup_symbol ─────────────────────────

    @mcp.tool(
        name="coderag_lookup_symbol",
        description=(
            "Look up a code symbol (class, function, method, etc.) and return "
            "its definition, relationships, and context from the knowledge graph. "
            "Use this to understand what a symbol is, where it's defined, and "
            "how it relates to other code."
        ),
    )
    def coderag_lookup_symbol(
        symbol: str,
        detail_level: DetailLevel = DetailLevel.summary,
        token_budget: int = 4000,
    ) -> str:
        """Look up a symbol in the knowledge graph.

        Args:
            symbol: Symbol name or qualified name to look up.
            detail_level: How much detail to include (signature/summary/detailed/comprehensive).
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)
            result = assembler.assemble_for_symbol(
                qualified_name=symbol,
                store=store,
                analyzer=analyzer,
                token_budget=token_budget,
            )
            return _truncate_to_budget(result.text, token_budget)
        except Exception as exc:
            logger.exception("Error in coderag_lookup_symbol")
            return f"Error looking up symbol `{symbol}`: {exc}"

    # ── Tool 2: coderag_find_usages ───────────────────────────

    @mcp.tool(
        name="coderag_find_usages",
        description=(
            "Find all usages of a symbol — where it's called, imported, extended, "
            "implemented, or instantiated. Useful for understanding how widely "
            "a symbol is used and by whom."
        ),
    )
    def coderag_find_usages(
        symbol: str,
        usage_types: list[UsageType] | None = None,
        max_depth: int = 1,
        token_budget: int = 4000,
    ) -> str:
        """Find all usages of a symbol.

        Args:
            symbol: Symbol name to find usages of.
            usage_types: Types of usage to search for. Default: all.
            max_depth: How many hops to traverse (1=direct, 2+=transitive).
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)
            max_depth = min(max(max_depth, 1), 5)

            node, candidates = _resolve_symbol(symbol, store)
            if node is None:
                return (
                    _format_candidates(candidates, symbol)
                    if candidates
                    else (f"Symbol `{symbol}` not found in the knowledge graph.")
                )

            # Determine which edge kinds to filter
            if usage_types is None or any(u.value == "all" for u in usage_types):
                edge_kind_filter = None  # No filter = all types
            else:
                edge_kind_filter: list[EdgeKind] = []
                for ut in usage_types:
                    edge_kind_filter.extend(_USAGE_TYPE_TO_EDGE_KINDS.get(ut.value, []))

            # Get incoming edges (usages OF this symbol)
            neighbors = store.get_neighbors(
                node_id=node.id,
                direction="incoming",
                edge_kinds=edge_kind_filter,
                max_depth=max_depth,
            )

            if not neighbors:
                kind = node.kind.value if isinstance(node.kind, NodeKind) else node.kind
                return (
                    f"No usages found for `{node.qualified_name}` ({kind}).\n\n"
                    f"This symbol is defined at `{node.file_path}:{node.start_line}` "
                    f"but has no incoming references in the knowledge graph."
                )

            # Format results
            lines = [
                f"## Usages of `{node.qualified_name}`\n",
                f"**Kind**: {node.kind.value if isinstance(node.kind, NodeKind) else node.kind}  ",
                f"**Defined at**: `{node.file_path}:{node.start_line}`  ",
                f"**Total usages found**: {len(neighbors)}\n",
            ]

            # Group by depth
            by_depth: dict[int, list[tuple]] = {}
            for n, edge, depth in neighbors:
                by_depth.setdefault(depth, []).append((n, edge))

            for depth in sorted(by_depth.keys()):
                items = by_depth[depth]
                lines.append(f"### Depth {depth} ({len(items)} usages)\n")

                # Group by edge kind
                by_kind: dict[str, list] = {}
                for n, edge in items:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    by_kind.setdefault(ek, []).append(n)

                for ek, nodes_list in sorted(by_kind.items()):
                    lines.append(f"**{ek}** ({len(nodes_list)}):\n")
                    for n in nodes_list:
                        nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                        lines.append(f"- `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)")
                    lines.append("")

            text = "\n".join(lines)
            return _truncate_to_budget(text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_find_usages")
            return f"Error finding usages of `{symbol}`: {exc}"

    # ── Tool 3: coderag_impact_analysis ───────────────────────

    @mcp.tool(
        name="coderag_impact_analysis",
        description=(
            "Analyze the blast radius of changing a symbol. Shows all code "
            "that would be affected by a change, organized by depth level. "
            "Essential before refactoring or modifying shared code."
        ),
    )
    def coderag_impact_analysis(
        symbol: str,
        max_depth: int = 3,
        token_budget: int = 4000,
    ) -> str:
        """Analyze the impact of changing a symbol.

        Args:
            symbol: Symbol name to analyze impact for.
            max_depth: How many levels of dependencies to trace (1-5).
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)
            max_depth = min(max(max_depth, 1), 5)

            result = assembler.assemble_impact_analysis(
                qualified_name=symbol,
                store=store,
                analyzer=analyzer,
                token_budget=token_budget,
            )
            return _truncate_to_budget(result.text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_impact_analysis")
            return f"Error analyzing impact of `{symbol}`: {exc}"

    # ── Tool 4: coderag_file_context ──────────────────────────

    @mcp.tool(
        name="coderag_file_context",
        description=(
            "Get context for a specific file — all symbols defined in it, "
            "their relationships, and importance scores. Useful for understanding "
            "what a file contains and how it fits into the codebase."
        ),
    )
    def coderag_file_context(
        file_path: str,
        include_source: bool = True,
        token_budget: int = 4000,
    ) -> str:
        """Get context for a file.

        Args:
            file_path: Path to the file (relative or absolute, flexible matching).
            include_source: Whether to include source code snippets.
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)

            # Normalize file path
            resolved = _normalize_file_path(file_path, store)
            if resolved is None:
                # Try to find similar files
                conn = store.connection
                basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
                rows = conn.execute(
                    "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE ? LIMIT 10",
                    (f"%{basename}%",),
                ).fetchall()
                if rows:
                    suggestions = "\n".join(f"- `{r[0]}`" for r in rows)
                    return f"File `{file_path}` not found. Similar files:\n\n{suggestions}"
                return f"File `{file_path}` not found in the knowledge graph."

            result = assembler.assemble_for_file(
                file_path=resolved,
                store=store,
                analyzer=analyzer,
                token_budget=token_budget,
            )
            return _truncate_to_budget(result.text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_file_context")
            return f"Error getting context for `{file_path}`: {exc}"

    # ── Tool 5: coderag_find_routes ───────────────────────────

    @mcp.tool(
        name="coderag_find_routes",
        description=(
            "Find API routes/endpoints matching a URL pattern. Shows route "
            "definitions and optionally frontend code that calls them. "
            "Supports glob patterns like /api/users/*."
        ),
    )
    def coderag_find_routes(
        pattern: str,
        http_method: HttpMethod | None = None,
        include_frontend: bool = True,
        token_budget: int = 4000,
    ) -> str:
        """Find routes matching a pattern.

        Args:
            pattern: URL pattern to match (supports glob: /api/users/*).
            http_method: Filter by HTTP method (GET, POST, etc.).
            include_frontend: Include frontend API calls to matched routes.
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)

            # Get all ROUTE nodes
            route_nodes = store.find_nodes(kind=NodeKind.ROUTE, limit=1000)

            if not route_nodes:
                return "No routes found in the knowledge graph. The codebase may not have been parsed with framework detection enabled."

            # Filter by pattern (glob matching)
            matched: list[Node] = []
            for node in route_nodes:
                route_url = node.metadata.get("url", node.name)
                if fnmatch.fnmatch(route_url, pattern) or pattern in route_url:
                    # Filter by HTTP method if specified
                    if http_method and http_method != HttpMethod.ANY:
                        node_method = node.metadata.get("http_method", "").upper()
                        if node_method != http_method.value:
                            continue
                    matched.append(node)

            if not matched:
                return (
                    f"No routes matching `{pattern}` found.\n\n"
                    f"Total routes in graph: {len(route_nodes)}.\n"
                    f"Try a broader pattern or check available routes with "
                    f'`coderag_search` using node_types=["route"].'
                )

            lines = [
                f"## Routes matching `{pattern}`\n",
                f"**Matched**: {len(matched)} routes\n",
            ]

            for node in matched:
                method = node.metadata.get("http_method", "ANY")
                url = node.metadata.get("url", node.name)
                controller = node.metadata.get("controller", "")
                action = node.metadata.get("action", "")

                lines.append(f"### {method} `{url}`")
                lines.append(f"- **File**: `{node.file_path}:{node.start_line}`")
                if controller:
                    lines.append(f"- **Controller**: `{controller}`")
                if action:
                    lines.append(f"- **Action**: `{action}`")

                # Find connected edges (routes_to, api_calls)
                outgoing = store.get_edges(source_id=node.id)
                incoming = store.get_edges(target_id=node.id)

                # Show what the route connects to
                for edge in outgoing:
                    ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                    target = store.get_node(edge.target_id)
                    if target:
                        lines.append(
                            f"- **{ek}** → `{target.qualified_name}` (`{target.file_path}:{target.start_line}`)"
                        )

                # Show frontend callers if requested
                if include_frontend:
                    api_callers = [
                        e
                        for e in incoming
                        if (e.kind == EdgeKind.API_CALLS or (isinstance(e.kind, str) and e.kind == "api_calls"))
                    ]
                    if api_callers:
                        lines.append(f"\n  **Frontend callers** ({len(api_callers)}):")
                        for edge in api_callers:
                            source = store.get_node(edge.source_id)
                            if source:
                                call_url = edge.metadata.get("call_url", "")
                                lines.append(
                                    f"  - `{source.qualified_name}` "
                                    f"(`{source.file_path}:{source.start_line}`)"
                                    + (f" via `{call_url}`" if call_url else "")
                                )

                lines.append("")

            text = "\n".join(lines)
            return _truncate_to_budget(text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_find_routes")
            return f"Error finding routes matching `{pattern}`: {exc}"

    # ── Tool 6: coderag_search ────────────────────────────────

    @mcp.tool(
        name="coderag_search",
        description=(
            "Full-text search across the knowledge graph. Search for symbols "
            "by name, qualified name, or docblock content. Optionally filter "
            "by node type and language."
        ),
    )
    def coderag_search(
        query: str,
        node_types: list[str] | None = None,
        language: str | None = None,
        mode: str = "auto",
        limit: int = 20,
        token_budget: int = 4000,
    ) -> str:
        """Search the knowledge graph.

        Args:
            query: Search query (matches names, qualified names, docblocks).
            node_types: Filter by node types (e.g. ["class", "function", "route"]).
            language: Filter by language (e.g. "php", "javascript", "typescript").
            mode: Search mode — "fts" (keyword), "semantic" (vector), "hybrid" (both), or "auto" (hybrid if available, else fts).
            limit: Maximum number of results (1-100).
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)
            limit = min(max(limit, 1), 100)

            # Determine effective search mode
            effective_mode = mode.lower() if mode else "auto"
            use_semantic = False
            vector_dir = os.path.dirname(store._db_path)

            if effective_mode in ("semantic", "hybrid", "auto"):
                try:
                    from coderag.search import SEMANTIC_AVAILABLE

                    if SEMANTIC_AVAILABLE:
                        from coderag.search.vector_store import VectorStore

                        if VectorStore.exists(vector_dir):
                            use_semantic = True
                except ImportError:
                    pass

            if use_semantic and effective_mode != "fts":
                from coderag.search.embedder import CodeEmbedder
                from coderag.search.hybrid import HybridSearcher
                from coderag.search.vector_store import VectorStore

                embedder = CodeEmbedder("all-MiniLM-L6-v2")
                vs = VectorStore.load(vector_dir)
                searcher = HybridSearcher(store, vs, embedder)

                kind_filter = node_types[0] if node_types and len(node_types) == 1 else None
                if effective_mode == "semantic":
                    search_results = searcher.search_semantic(query, k=limit, kind=kind_filter)
                else:
                    search_results = searcher.search(query, k=limit, alpha=0.5, kind=kind_filter)

                # Filter by language if specified
                if language:
                    lang_lower = language.lower()
                    search_results = [sr for sr in search_results if sr.language.lower() == lang_lower]

                if not search_results:
                    return (
                        f"No results found for `{query}`"
                        + (f" (types: {node_types})" if node_types else "")
                        + (f" (language: {language})" if language else "")
                        + f" (mode: {effective_mode})"
                        + ".\n\nTry a broader search or different terms."
                    )

                mode_label = effective_mode if effective_mode != "auto" else "hybrid"
                lines = [
                    f"## Search results for `{query}` (mode: {mode_label})\n",
                    f"**Found**: {len(search_results)} results\n",
                ]

                for i, sr in enumerate(search_results, 1):
                    lines.append(
                        f"{i}. **`{sr.qualified_name or sr.name}`** ({sr.kind}, {sr.language})  "
                        f"  `{sr.file_path}` — score: {sr.score:.4f} [{sr.match_type}]"
                    )
                    if sr.vector_similarity > 0:
                        lines.append(f"   > Semantic similarity: {sr.vector_similarity:.4f}")
                    lines.append("")

                text = "\n".join(lines)
                return _truncate_to_budget(text, token_budget)

            # FTS5 fallback
            results: list[Node] = []
            if node_types:
                for nt in node_types:
                    kind_results = store.search_nodes(query, limit=limit, kind=nt)
                    results.extend(kind_results)
                # Deduplicate by id
                seen = set()
                unique = []
                for n in results:
                    if n.id not in seen:
                        seen.add(n.id)
                        unique.append(n)
                results = unique[:limit]
            else:
                results = store.search_nodes(query, limit=limit)

            # Filter by language if specified
            if language:
                lang_lower = language.lower()
                results = [n for n in results if n.language.lower() == lang_lower]

            if not results:
                return (
                    f"No results found for `{query}`"
                    + (f" (types: {node_types})" if node_types else "")
                    + (f" (language: {language})" if language else "")
                    + ".\n\nTry a broader search or different terms."
                )

            lines = [
                f"## Search results for `{query}`\n",
                f"**Found**: {len(results)} results\n",
            ]

            for i, node in enumerate(results, 1):
                kind = node.kind.value if isinstance(node.kind, NodeKind) else node.kind
                lines.append(
                    f"{i}. **`{node.qualified_name}`** ({kind}, {node.language})  "
                    f"  `{node.file_path}:{node.start_line}`"
                )
                if node.docblock:
                    # Show first line of docblock
                    first_line = node.docblock.strip().split("\n")[0][:120]
                    lines.append(f"   > {first_line}")
                lines.append("")

            text = "\n".join(lines)
            return _truncate_to_budget(text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_search")
            return f"Error searching for `{query}`: {exc}"

    # ── Tool 7: coderag_architecture ──────────────────────────

    @mcp.tool(
        name="coderag_architecture",
        description=(
            "Get a high-level architecture overview of the codebase. Shows "
            "communities/modules, important nodes (by PageRank), and entry "
            "points. Can focus on specific layers (backend, frontend, API, data)."
        ),
    )
    def coderag_architecture(
        focus: ArchitectureFocus = ArchitectureFocus.full,
        token_budget: int = 8000,
    ) -> str:
        """Get architecture overview.

        Args:
            focus: Which part of the architecture to focus on.
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 1000), 32000)

            # Compute analyses
            communities_raw = analyzer.community_detection()
            analyzer.pagerank()

            # Determine kind/language filters based on focus
            language_filter = None
            kind_filter = None
            if focus == ArchitectureFocus.backend:
                language_filter = "php"
            elif focus == ArchitectureFocus.frontend:
                language_filter = None  # JS + TS
            elif focus == ArchitectureFocus.api_layer:
                kind_filter = "route"
            elif focus == ArchitectureFocus.data_layer:
                kind_filter = "model"

            # Get top nodes
            if kind_filter:
                top_nodes_raw = analyzer.get_top_nodes("pagerank", limit=20, kind_filter=kind_filter)
            else:
                top_nodes_raw = analyzer.get_top_nodes("pagerank", limit=20)

            # Get entry points
            entry_point_ids = analyzer.get_entry_points(limit=15)

            # Resolve node objects
            def _get_node(nid: str) -> Node | None:
                return store.get_node(nid)

            # Build communities with Node objects, applying filters
            communities: list[tuple[int, list[Node]]] = []
            for idx, community_ids in enumerate(communities_raw[:15]):
                nodes_in_community: list[Node] = []
                for nid in list(community_ids)[:50]:  # Cap per community
                    n = _get_node(nid)
                    if n is None:
                        continue
                    if language_filter and n.language.lower() != language_filter:
                        continue
                    if focus == ArchitectureFocus.frontend and n.language.lower() not in ("javascript", "typescript"):
                        continue
                    nodes_in_community.append(n)
                if nodes_in_community:
                    communities.append((idx, nodes_in_community))

            # Build important nodes list
            important_nodes: list[tuple[Node, float]] = []
            for nid, score in top_nodes_raw:
                n = _get_node(nid)
                if n is None:
                    continue
                if language_filter and n.language.lower() != language_filter:
                    continue
                if focus == ArchitectureFocus.frontend and n.language.lower() not in ("javascript", "typescript"):
                    continue
                important_nodes.append((n, score))

            # Build entry points list
            entry_points: list[Node] = []
            for nid in entry_point_ids:
                n = _get_node(nid)
                if n is None:
                    continue
                if language_filter and n.language.lower() != language_filter:
                    continue
                if focus == ArchitectureFocus.frontend and n.language.lower() not in ("javascript", "typescript"):
                    continue
                entry_points.append(n)

            # Format
            text = formatter.format_architecture_overview(
                communities=communities,
                important_nodes=important_nodes,
                entry_points=entry_points,
            )

            if focus != ArchitectureFocus.full:
                text = f"*Focus: {focus.value}*\n\n" + text

            return _truncate_to_budget(text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_architecture")
            return f"Error generating architecture overview: {exc}"

    # ── Tool 8: coderag_dependency_graph ──────────────────────

    @mcp.tool(
        name="coderag_dependency_graph",
        description=(
            "Show the dependency graph for a symbol or file. Visualizes what "
            "depends on what, including transitive dependencies. Useful for "
            "understanding coupling and planning refactors."
        ),
    )
    def coderag_dependency_graph(
        target: str,
        direction: DependencyDirection = DependencyDirection.both,
        max_depth: int = 2,
        token_budget: int = 4000,
    ) -> str:
        """Show dependency graph for a symbol.

        Args:
            target: Symbol name or file path to analyze.
            direction: Show dependencies, dependents, or both.
            max_depth: How many levels deep to traverse (1-5).
            token_budget: Maximum tokens for the response.
        """
        try:
            token_budget = min(max(token_budget, 500), 16000)
            max_depth = min(max(max_depth, 1), 5)

            # Try to resolve as symbol first, then as file
            node, candidates = _resolve_symbol(target, store)

            if node is None:
                # Try as file path
                resolved_path = _normalize_file_path(target, store)
                if resolved_path:
                    # Get the FILE node or first node in file
                    file_nodes = store.find_nodes(file_path=resolved_path, limit=1)
                    if file_nodes:
                        node = file_nodes[0]

            if node is None:
                if candidates:
                    return _format_candidates(candidates, target)
                return f"Target `{target}` not found in the knowledge graph."

            lines = [
                f"## Dependency Graph: `{node.qualified_name}`\n",
                f"**Kind**: {node.kind.value if isinstance(node.kind, NodeKind) else node.kind}  ",
                f"**File**: `{node.file_path}:{node.start_line}`  ",
                f"**Direction**: {direction.value} | **Max depth**: {max_depth}\n",
            ]

            # Get dependencies (outgoing edges = what this depends on)
            if direction in (DependencyDirection.dependencies, DependencyDirection.both):
                deps = store.get_neighbors(
                    node_id=node.id,
                    direction="outgoing",
                    max_depth=max_depth,
                )
                lines.append(f"### Dependencies ({len(deps)} nodes)\n")
                if deps:
                    lines.append(f"What `{node.name}` depends on:\n")
                    by_depth: dict[int, list] = {}
                    for n, edge, depth in deps:
                        by_depth.setdefault(depth, []).append((n, edge))
                    for d in sorted(by_depth.keys()):
                        indent = "  " * (d - 1)
                        for n, edge in by_depth[d]:
                            ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                            nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                            lines.append(
                                f"{indent}- **{ek}** → `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)"
                            )
                else:
                    lines.append("No dependencies found.\n")
                lines.append("")

            # Get dependents (incoming edges = what depends on this)
            if direction in (DependencyDirection.dependents, DependencyDirection.both):
                dependents = store.get_neighbors(
                    node_id=node.id,
                    direction="incoming",
                    max_depth=max_depth,
                )
                lines.append(f"### Dependents ({len(dependents)} nodes)\n")
                if dependents:
                    lines.append(f"What depends on `{node.name}`:\n")
                    by_depth = {}
                    for n, edge, depth in dependents:
                        by_depth.setdefault(depth, []).append((n, edge))
                    for d in sorted(by_depth.keys()):
                        indent = "  " * (d - 1)
                        for n, edge in by_depth[d]:
                            ek = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                            nk = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                            lines.append(
                                f"{indent}- **{ek}** ← `{n.qualified_name}` ({nk}, `{n.file_path}:{n.start_line}`)"
                            )
                else:
                    lines.append("No dependents found.\n")

            text = "\n".join(lines)
            return _truncate_to_budget(text, token_budget)

        except Exception as exc:
            logger.exception("Error in coderag_dependency_graph")
            return f"Error building dependency graph for `{target}`: {exc}"
