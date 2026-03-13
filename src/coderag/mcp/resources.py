"""MCP Resources for CodeRAG.

Registers 3 resources on a FastMCP server instance that provide
passive context about the knowledge graph to LLMs.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from coderag.core.models import (
    Node,
)

logger = logging.getLogger(__name__)


def register_resources(mcp: Any, store: Any, analyzer: Any) -> None:
    """Register all 3 CodeRAG resources on the FastMCP server.

    Args:
        mcp: FastMCP server instance.
        store: Initialized SQLiteStore.
        analyzer: Loaded NetworkXAnalyzer.
    """
    from coderag.output.markdown import MarkdownFormatter

    formatter = MarkdownFormatter()

    # ── Resource 1: coderag://summary ─────────────────────────

    @mcp.resource(
        "coderag://summary",
        name="CodeRAG Summary",
        description="Knowledge graph statistics and project overview",
        mime_type="text/markdown",
    )
    def get_summary() -> str:
        """Return graph summary statistics as markdown."""
        try:
            summary = store.get_summary()

            proj_name = summary.project_name or "(unnamed)"
            lines = [
                "# CodeRAG Knowledge Graph Summary\n",
                f"**Project**: {proj_name}  ",
                f"**Root**: `{summary.project_root}`  ",
                f"**Database**: `{summary.db_path}` ({summary.db_size_bytes / 1024 / 1024:.1f} MB)  ",
                f"**Last parsed**: {summary.last_parsed or 'never'}\n",
                "## Statistics\n",
                f"- **Total nodes**: {summary.total_nodes:,}",
                f"- **Total edges**: {summary.total_edges:,}",
                f"- **Communities**: {summary.communities}",
                f"- **Avg edge confidence**: {summary.avg_confidence:.2f}\n",
            ]

            # Languages
            if summary.files_by_language:
                lines.append("## Languages\n")
                total_files = sum(summary.files_by_language.values())
                for lang, count in sorted(
                    summary.files_by_language.items(),
                    key=lambda x: -x[1],
                ):
                    pct = (count / total_files * 100) if total_files > 0 else 0
                    lines.append(f"- **{lang}**: {count:,} files ({pct:.1f}%)")
                lines.append("")

            # Node types
            if summary.nodes_by_kind:
                lines.append("## Node Types\n")
                for kind, count in sorted(
                    summary.nodes_by_kind.items(),
                    key=lambda x: -x[1],
                ):
                    lines.append(f"- **{kind}**: {count:,}")
                lines.append("")

            # Edge types
            if summary.edges_by_kind:
                lines.append("## Edge Types\n")
                for kind, count in sorted(
                    summary.edges_by_kind.items(),
                    key=lambda x: -x[1],
                ):
                    lines.append(f"- **{kind}**: {count:,}")
                lines.append("")

            # Frameworks
            if summary.frameworks:
                lines.append("## Frameworks Detected\n")
                for fw in summary.frameworks:
                    lines.append(f"- {fw}")
                lines.append("")

            # Top nodes
            if summary.top_nodes_by_pagerank:
                lines.append("## Most Important Nodes (by PageRank)\n")
                for i, (name, qn, score) in enumerate(summary.top_nodes_by_pagerank[:10], 1):
                    lines.append(f"{i}. `{qn}` (score: {score:.4f})")
                lines.append("")

            return "\n".join(lines)

        except Exception as exc:
            logger.exception("Error generating summary resource")
            return f"Error generating summary: {exc}"

    # ── Resource 2: coderag://architecture ─────────────────────

    @mcp.resource(
        "coderag://architecture",
        name="Architecture Overview",
        description="High-level codebase architecture with communities, important nodes, and entry points",
        mime_type="text/markdown",
    )
    def get_architecture() -> str:
        """Return high-level architecture overview."""
        try:
            # Compute analyses
            communities_raw = analyzer.community_detection()
            top_nodes_raw = analyzer.get_top_nodes("pagerank", limit=20)
            entry_point_ids = analyzer.get_entry_points(limit=15)

            # Resolve node objects for communities
            communities: list[tuple[int, list[Node]]] = []
            for idx, community_ids in enumerate(communities_raw[:15]):
                nodes_in_community: list[Node] = []
                for nid in list(community_ids)[:50]:
                    n = store.get_node(nid)
                    if n is not None:
                        nodes_in_community.append(n)
                if nodes_in_community:
                    communities.append((idx, nodes_in_community))

            # Resolve important nodes
            important_nodes: list[tuple[Node, float]] = []
            for nid, score in top_nodes_raw:
                n = store.get_node(nid)
                if n is not None:
                    important_nodes.append((n, score))

            # Resolve entry points
            entry_points: list[Node] = []
            for nid in entry_point_ids:
                n = store.get_node(nid)
                if n is not None:
                    entry_points.append(n)

            text = formatter.format_architecture_overview(
                communities=communities,
                important_nodes=important_nodes,
                entry_points=entry_points,
            )

            # Add statistics header
            stats = analyzer.get_statistics()
            is_dag = "Yes" if stats.get("is_dag", False) else "No (has cycles)"
            header_lines = [
                "# Architecture Overview\n",
                f"- **Nodes**: {stats.get('node_count', 0):,}",
                f"- **Edges**: {stats.get('edge_count', 0):,}",
                f"- **DAG**: {is_dag}",
                f"- **Weakly connected components**: {stats.get('weakly_connected_components', 0)}",
                f"- **Strongly connected components**: {stats.get('strongly_connected_components', 0)}",
                f"- **Isolated nodes**: {stats.get('isolate_count', 0)}\n",
            ]

            return "\n".join(header_lines) + "\n" + text

        except Exception as exc:
            logger.exception("Error generating architecture resource")
            return f"Error generating architecture overview: {exc}"

    # ── Resource 3: coderag://file-map ─────────────────────────

    @mcp.resource(
        "coderag://file-map",
        name="File Map",
        description="Annotated file tree showing symbols per file",
        mime_type="text/markdown",
    )
    def get_file_map() -> str:
        """Return annotated file tree showing symbols per file."""
        try:
            conn = store.connection

            # Get all files with their symbol counts
            rows = conn.execute(
                """SELECT file_path, language, COUNT(*) as symbol_count,
                          GROUP_CONCAT(DISTINCT kind) as kinds
                   FROM nodes
                   WHERE kind != 'file'
                   GROUP BY file_path
                   ORDER BY file_path"""
            ).fetchall()

            if not rows:
                return "# File Map\n\nNo files found in the knowledge graph."

            lines = [
                "# File Map\n",
                f"**Total files**: {len(rows)}\n",
                "```",
            ]

            # Build tree structure
            tree: dict[str, Any] = {}
            file_info: dict[str, dict] = {}

            for row in rows:
                fp = row[0]
                file_info[fp] = {
                    "language": row[1],
                    "count": row[2],
                    "kinds": row[3].split(",") if row[3] else [],
                }
                parts = fp.split("/")
                current = tree
                for part in parts[:-1]:
                    current = current.setdefault(part, {})
                current[parts[-1]] = None  # Leaf file

            def _render_tree(node: dict, prefix: str = "", path_parts: list[str] | None = None) -> None:
                if path_parts is None:
                    path_parts = []
                items = sorted(node.items(), key=lambda x: (x[1] is None, x[0]))
                for i, (name, subtree) in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    extension = "    " if is_last else "│   "

                    current_path = "/".join(path_parts + [name])

                    if subtree is None:  # File
                        info = file_info.get(current_path, {})
                        count = info.get("count", 0)
                        kinds = info.get("kinds", [])
                        # Summarize kinds
                        kind_summary = ", ".join(sorted(set(k for k in kinds if k not in ("file", "import", "export"))))
                        annotation = f"  ({count} symbols"
                        if kind_summary:
                            annotation += f": {kind_summary}"
                        annotation += ")"
                        lines.append(f"{prefix}{connector}{name}{annotation}")
                    else:  # Directory
                        # Count total symbols in directory
                        dir_prefix = current_path + "/"
                        dir_count = sum(
                            info.get("count", 0) for fp, info in file_info.items() if fp.startswith(dir_prefix)
                        )
                        dir_annotation = f"  [{dir_count} symbols]" if dir_count > 0 else ""
                        lines.append(f"{prefix}{connector}{name}/{dir_annotation}")
                        _render_tree(
                            subtree,
                            prefix + extension,
                            path_parts + [name],
                        )

            _render_tree(tree)
            lines.append("```")

            # Add language breakdown
            lang_counts: dict[str, int] = defaultdict(int)
            for info in file_info.values():
                lang_counts[info.get("language", "unknown")] += 1

            lines.append("\n## Language Breakdown\n")
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{lang}**: {count} files")

            return "\n".join(lines)

        except Exception as exc:
            logger.exception("Error generating file map resource")
            return f"Error generating file map: {exc}"
