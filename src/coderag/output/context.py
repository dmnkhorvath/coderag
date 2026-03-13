"""Context Assembler for CodeRAG.

Assembles token-budgeted context from the knowledge graph for LLM consumption.
Uses progressive detail levels to maximize information within token limits.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from coderag.core.models import (
    ContextResult,
    DetailLevel,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    estimate_tokens,
)
from coderag.output.markdown import MarkdownFormatter

if TYPE_CHECKING:
    from coderag.analysis.networkx_analyzer import NetworkXAnalyzer
    from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Edge kinds grouped by relationship category
_RELATIONSHIP_EDGES = {
    EdgeKind.CALLS,
    EdgeKind.EXTENDS,
    EdgeKind.IMPLEMENTS,
    EdgeKind.USES_TRAIT,
    EdgeKind.INSTANTIATES,
    EdgeKind.IMPORTS,
}
_CONTAINMENT_EDGES = {
    EdgeKind.CONTAINS,
    EdgeKind.DEFINED_IN,
    EdgeKind.MEMBER_OF,
}


class ContextAssembler:
    """Assembles token-budgeted context from the knowledge graph.

    Uses progressive detail levels to fit maximum useful information
    within a given token budget. Leverages the NetworkXAnalyzer for
    relevance scoring and the MarkdownFormatter for output.

    Example::

        assembler = ContextAssembler()
        result = assembler.assemble_for_symbol(
            "App\\Models\\User", store, analyzer, token_budget=4000
        )
        print(result.text)
    """

    def __init__(self) -> None:
        self._formatter = MarkdownFormatter()

    # ── Symbol Context ────────────────────────────────────────

    def assemble_for_symbol(
        self,
        qualified_name: str,
        store: SQLiteStore,
        analyzer: NetworkXAnalyzer,
        token_budget: int = 4000,
    ) -> ContextResult:
        """Assemble context for a specific symbol.

        Progressive detail levels:
        1. Always: symbol definition, file path, kind
        2. If budget allows: direct relationships (calls, extends, implements)
        3. If budget allows: callers/callees (1 hop)
        4. If budget allows: 2-hop relationships

        Args:
            qualified_name: Fully-qualified name of the symbol.
            store: Initialized SQLiteStore.
            analyzer: Loaded NetworkXAnalyzer.
            token_budget: Maximum tokens for the output.

        Returns:
            ContextResult with assembled markdown text.
        """
        # Find the target node
        node = store.get_node_by_qualified_name(qualified_name)
        if node is None:
            # Try search as fallback
            results = store.search_nodes(qualified_name, limit=1)
            node = results[0] if results else None

        if node is None:
            return ContextResult(
                text=f"Symbol `{qualified_name}` not found in the knowledge graph.",
                tokens_used=estimate_tokens(f"Symbol `{qualified_name}` not found."),
                token_budget=token_budget,
                nodes_included=0,
                nodes_available=0,
                nodes_truncated=0,
                target_nodes=[],
            )

        lines: list[str] = []
        tokens_used = 0
        nodes_included = 1
        included_files: set[str] = {node.file_path}
        all_related: list[tuple[Node, Edge, int]] = []

        # Level 1: Symbol definition (always included)
        header = f"# Context for `{node.qualified_name}`\n"
        node_text = MarkdownFormatter.format_node(node, DetailLevel.DETAILED)
        level1 = header + node_text
        level1_tokens = estimate_tokens(level1)

        if level1_tokens > token_budget:
            # Even basic info exceeds budget — use signature level
            node_text = MarkdownFormatter.format_node(node, DetailLevel.SIGNATURE)
            level1 = header + node_text
            level1_tokens = estimate_tokens(level1)

        lines.append(level1)
        tokens_used = level1_tokens

        # Level 2: Direct relationships
        if tokens_used < token_budget * 0.9:
            outgoing = store.get_edges(source_id=node.id)
            incoming = store.get_edges(target_id=node.id)

            # Score and sort related nodes
            scored_relations: list[tuple[Node, Edge, str, float]] = []

            for edge in outgoing:
                if edge.kind in _CONTAINMENT_EDGES:
                    continue
                related = store.get_node(edge.target_id)
                if related:
                    score = analyzer.relevance_score(related.id, qualified_name)
                    scored_relations.append((related, edge, "outgoing", score))
                    all_related.append((related, edge, 1))

            for edge in incoming:
                if edge.kind in _CONTAINMENT_EDGES:
                    continue
                related = store.get_node(edge.source_id)
                if related:
                    score = analyzer.relevance_score(related.id, qualified_name)
                    scored_relations.append((related, edge, "incoming", score))
                    all_related.append((related, edge, 1))

            scored_relations.sort(key=lambda x: -x[3])

            if scored_relations:
                section = "\n\n## Direct Relationships\n"
                section_tokens = estimate_tokens(section)

                if tokens_used + section_tokens < token_budget:
                    lines.append(section)
                    tokens_used += section_tokens

                    for related, edge, direction, score in scored_relations:
                        if tokens_used >= token_budget * 0.85:
                            break

                        arrow = "→" if direction == "outgoing" else "←"
                        kind_str = edge.kind.value if isinstance(edge.kind, EdgeKind) else edge.kind
                        entry = (
                            f"- {arrow} **{kind_str}** "
                            f"`{related.qualified_name}` "
                            f"({related.kind.value if isinstance(related.kind, NodeKind) else related.kind}, "
                            f"{related.file_path}:{related.start_line})\n"
                        )
                        entry_tokens = estimate_tokens(entry)

                        if tokens_used + entry_tokens < token_budget:
                            lines.append(entry)
                            tokens_used += entry_tokens
                            nodes_included += 1
                            included_files.add(related.file_path)

        # Level 3: 1-hop neighbors (callers/callees)
        new_neighbors: list[tuple[Node, Edge, int]] = []
        if tokens_used < token_budget * 0.7:
            neighbors = store.get_neighbors(node.id, max_depth=1)
            seen_ids = {node.id} | {r.id for r, _, _ in all_related}

            new_neighbors = [
                (n, e, d)
                for n, e, d in neighbors
                if n.id not in seen_ids
                and (
                    e.kind not in _CONTAINMENT_EDGES
                    if isinstance(e.kind, EdgeKind)
                    else e.kind not in {ek.value for ek in _CONTAINMENT_EDGES}
                )
            ]

            if new_neighbors:
                section = "\n\n## Extended Neighborhood (1-hop)\n"
                section_tokens = estimate_tokens(section)

                if tokens_used + section_tokens < token_budget:
                    lines.append(section)
                    tokens_used += section_tokens

                    # Score and sort
                    scored = [(n, e, d, analyzer.relevance_score(n.id, qualified_name)) for n, e, d in new_neighbors]
                    scored.sort(key=lambda x: -x[3])

                    for n, e, d, score in scored:
                        if tokens_used >= token_budget * 0.9:
                            break

                        kind_str = e.kind.value if isinstance(e.kind, EdgeKind) else e.kind
                        entry = (
                            f"- **{kind_str}** `{n.qualified_name}` "
                            f"({n.kind.value if isinstance(n.kind, NodeKind) else n.kind})\n"
                        )
                        entry_tokens = estimate_tokens(entry)

                        if tokens_used + entry_tokens < token_budget:
                            lines.append(entry)
                            tokens_used += entry_tokens
                            nodes_included += 1
                            included_files.add(n.file_path)

        # Level 4: 2-hop relationships (if budget remains)
        if tokens_used < token_budget * 0.6:
            neighbors_2 = store.get_neighbors(node.id, max_depth=2)
            seen_ids = {node.id} | {r.id for r, _, _ in all_related}
            seen_ids |= {n.id for n, _, _ in new_neighbors}

            hop2 = [(n, e, d) for n, e, d in neighbors_2 if n.id not in seen_ids and d == 2]

            if hop2:
                section = "\n\n## 2-Hop Relationships\n"
                section_tokens = estimate_tokens(section)

                if tokens_used + section_tokens < token_budget:
                    lines.append(section)
                    tokens_used += section_tokens

                    for n, e, d in hop2[:20]:  # Cap at 20
                        if tokens_used >= token_budget * 0.95:
                            break

                        kind_str = e.kind.value if isinstance(e.kind, EdgeKind) else e.kind
                        entry = f"- `{n.qualified_name}` ({kind_str})\n"
                        entry_tokens = estimate_tokens(entry)

                        if tokens_used + entry_tokens < token_budget:
                            lines.append(entry)
                            tokens_used += entry_tokens
                            nodes_included += 1

        text = "".join(lines)
        return ContextResult(
            text=text,
            tokens_used=estimate_tokens(text),
            token_budget=token_budget,
            nodes_included=nodes_included,
            nodes_available=len(all_related),
            nodes_truncated=max(0, len(all_related) - nodes_included + 1),
            target_nodes=[node.id],
            included_files=included_files,
        )

    # ── File Context ──────────────────────────────────────────

    def assemble_for_file(
        self,
        file_path: str,
        store: SQLiteStore,
        analyzer: NetworkXAnalyzer,
        token_budget: int = 4000,
    ) -> ContextResult:
        """Assemble context for a specific file.

        Shows all symbols in the file, scored by importance (PageRank).
        Progressive detail: signatures → summaries → full details.

        Args:
            file_path: Relative file path.
            store: Initialized SQLiteStore.
            analyzer: Loaded NetworkXAnalyzer.
            token_budget: Maximum tokens for the output.

        Returns:
            ContextResult with assembled markdown text.
        """
        # Find all nodes in this file
        conn = store.connection
        rows = conn.execute(
            "SELECT * FROM nodes WHERE file_path = ? ORDER BY start_line",
            (file_path,),
        ).fetchall()

        if not rows:
            return ContextResult(
                text=f"No symbols found in `{file_path}`.",
                tokens_used=estimate_tokens(f"No symbols found in `{file_path}`."),
                token_budget=token_budget,
                nodes_included=0,
                nodes_available=0,
                nodes_truncated=0,
                target_nodes=[],
            )

        # Convert rows to nodes using store\' s internal method
        nodes: list[Node] = []
        for row in rows:
            node = store._row_to_node(row)
            nodes.append(node)

        # Score by PageRank
        pr_scores = analyzer.pagerank()
        scored_nodes = [(n, pr_scores.get(n.id, 0.0)) for n in nodes]
        scored_nodes.sort(key=lambda x: -x[1])

        lines: list[str] = []
        tokens_used = 0
        nodes_included = 0

        # File header
        header = f"# File: `{file_path}`\n\n"
        header += f"**Symbols**: {len(nodes)} | "

        # Count by kind
        kind_counts: dict[str, int] = defaultdict(int)
        for n in nodes:
            k = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
            kind_counts[k] += 1
        header += ", ".join(f"{count} {kind}" for kind, count in sorted(kind_counts.items()))
        header += "\n"

        lines.append(header)
        tokens_used = estimate_tokens(header)

        # Progressive detail: try SUMMARY first, fall back to SIGNATURE
        detail = DetailLevel.SUMMARY
        total_summary_estimate = sum(
            estimate_tokens(MarkdownFormatter.format_node(n, DetailLevel.SUMMARY)) for n, _ in scored_nodes
        )

        if total_summary_estimate > token_budget * 0.8:
            detail = DetailLevel.SIGNATURE

        # Add nodes
        for node, score in scored_nodes:
            if tokens_used >= token_budget * 0.95:
                break

            node_text = MarkdownFormatter.format_node(node, detail)
            node_tokens = estimate_tokens(node_text)

            if tokens_used + node_tokens < token_budget:
                lines.append("\n" + node_text + "\n")
                tokens_used += node_tokens
                nodes_included += 1
            elif detail == DetailLevel.SUMMARY:
                # Try signature level
                sig_text = MarkdownFormatter.format_node(node, DetailLevel.SIGNATURE)
                sig_tokens = estimate_tokens(sig_text)
                if tokens_used + sig_tokens < token_budget:
                    lines.append("\n" + sig_text + "\n")
                    tokens_used += sig_tokens
                    nodes_included += 1

        text = "".join(lines)
        return ContextResult(
            text=text,
            tokens_used=estimate_tokens(text),
            token_budget=token_budget,
            nodes_included=nodes_included,
            nodes_available=len(nodes),
            nodes_truncated=max(0, len(nodes) - nodes_included),
            target_nodes=[n.id for n in nodes],
            included_files={file_path},
        )

    # ── Impact Analysis ───────────────────────────────────────

    def assemble_impact_analysis(
        self,
        qualified_name: str,
        store: SQLiteStore,
        analyzer: NetworkXAnalyzer,
        token_budget: int = 4000,
    ) -> ContextResult:
        """Assemble impact analysis for a symbol change.

        Computes blast radius and formats impact at each depth level,
        including affected files summary.

        Args:
            qualified_name: Fully-qualified name of the symbol.
            store: Initialized SQLiteStore.
            analyzer: Loaded NetworkXAnalyzer.
            token_budget: Maximum tokens for the output.

        Returns:
            ContextResult with impact analysis markdown.
        """
        # Find the target node
        node = store.get_node_by_qualified_name(qualified_name)
        if node is None:
            results = store.search_nodes(qualified_name, limit=1)
            node = results[0] if results else None

        if node is None:
            return ContextResult(
                text=f"Symbol `{qualified_name}` not found.",
                tokens_used=estimate_tokens(f"Symbol `{qualified_name}` not found."),
                token_budget=token_budget,
                nodes_included=0,
                nodes_available=0,
                nodes_truncated=0,
                target_nodes=[],
            )

        # Compute blast radius
        blast = analyzer.blast_radius(node.id, max_depth=3)

        lines: list[str] = []
        tokens_used = 0
        nodes_included = 1
        included_files: set[str] = {node.file_path}
        total_affected = sum(len(ids) for ids in blast.values())

        # Header
        header = (
            f"# Impact Analysis: `{node.qualified_name}`\n\n"
            f"**Kind**: {node.kind.value if isinstance(node.kind, NodeKind) else node.kind} | "
            f"**File**: `{node.file_path}` | "
            f"**Total Affected**: {total_affected} nodes\n"
        )
        lines.append(header)
        tokens_used = estimate_tokens(header)

        if not blast:
            lines.append("\n*No downstream dependencies found. This symbol is a leaf node.*\n")
        else:
            # Format each depth level
            for depth in sorted(blast.keys()):
                if tokens_used >= token_budget * 0.95:
                    break

                node_ids = blast[depth]
                section_header = (
                    f"\n## Depth {depth} — {len(node_ids)} affected node{'s' if len(node_ids) != 1 else ''}\n\n"
                )
                section_tokens = estimate_tokens(section_header)

                if tokens_used + section_tokens >= token_budget:
                    break

                lines.append(section_header)
                tokens_used += section_tokens

                # Get node details and sort by relevance
                depth_nodes: list[tuple[Node, float]] = []
                for nid in node_ids:
                    n = store.get_node(nid)
                    if n:
                        score = analyzer.relevance_score(nid)
                        depth_nodes.append((n, score))

                depth_nodes.sort(key=lambda x: -x[1])

                for n, score in depth_nodes:
                    if tokens_used >= token_budget * 0.9:
                        remaining = len(depth_nodes) - nodes_included
                        if remaining > 0:
                            lines.append(f"\n*... and {remaining} more nodes*\n")
                        break

                    kind_str = n.kind.value if isinstance(n.kind, NodeKind) else n.kind
                    entry = f"- **{kind_str}** `{n.qualified_name}` (`{n.file_path}:{n.start_line}`)\n"
                    entry_tokens = estimate_tokens(entry)

                    if tokens_used + entry_tokens < token_budget:
                        lines.append(entry)
                        tokens_used += entry_tokens
                        nodes_included += 1
                        included_files.add(n.file_path)

        # Affected files summary
        if tokens_used < token_budget * 0.9 and len(included_files) > 1:
            files_section = f"\n## Affected Files ({len(included_files)})\n\n"
            for fp in sorted(included_files):
                files_section += f"- `{fp}`\n"

            files_tokens = estimate_tokens(files_section)
            if tokens_used + files_tokens < token_budget:
                lines.append(files_section)
                tokens_used += files_tokens

        text = "".join(lines)
        return ContextResult(
            text=text,
            tokens_used=estimate_tokens(text),
            token_budget=token_budget,
            nodes_included=nodes_included,
            nodes_available=total_affected,
            nodes_truncated=max(0, total_affected - nodes_included + 1),
            target_nodes=[node.id],
            included_files=included_files,
        )
