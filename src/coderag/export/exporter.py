"""CodeRAG export module — multi-format graph export for LLM consumption.

Supports markdown, JSON, and tree formats with configurable scopes
and token budgeting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from coderag.core.models import EdgeKind, Node, NodeKind
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Rough token estimation: ~4 chars per token
CHARS_PER_TOKEN = 4


@dataclass
class ExportOptions:
    """Configuration for graph export."""

    format: str = "markdown"  # markdown, json, tree
    scope: str = "architecture"  # full, architecture, file, symbol
    symbol: str | None = None  # symbol name (for symbol scope)
    file_path: str | None = None  # file path (for file scope)
    max_tokens: int = 8000  # token budget
    include_source: bool = False  # include source snippets
    include_git: bool = True  # include git metadata
    depth: int = 2  # traversal depth for symbol/file scope
    top_n: int = 20  # top N items for architecture scope


def _pluralize(kind: str) -> str:
    """Simple pluralization for node kind names."""
    if kind.endswith("s"):
        return kind + "es"
    if kind.endswith("y"):
        return kind[:-1] + "ies"
    return kind + "s"


class GraphExporter:
    """Export knowledge graph data in multiple formats."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def export(self, options: ExportOptions) -> str:
        """Export graph data according to options."""
        scope_fn = {
            "full": self._export_full,
            "architecture": self._export_architecture,
            "file": self._export_file,
            "symbol": self._export_symbol,
        }
        fn = scope_fn.get(options.scope)
        if fn is None:
            raise ValueError(f"Unknown scope: {options.scope}. Valid: {list(scope_fn.keys())}")
        data = fn(options)
        return self._format(data, options)

    # ── Scope Handlers ────────────────────────────────────────

    def _export_full(self, options: ExportOptions) -> dict:
        """Export full graph data."""
        stats = self._store.get_stats()
        all_nodes = self._store.find_nodes(limit=100000)

        by_kind: dict[str, int] = {}
        by_file: dict[str, int] = {}
        by_lang: dict[str, int] = {}

        for node in all_nodes:
            kind = node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if node.file_path:
                by_file[node.file_path] = by_file.get(node.file_path, 0) + 1
            lang = node.language or "unknown"
            by_lang[lang] = by_lang.get(lang, 0) + 1

        return {
            "scope": "full",
            "stats": stats,
            "by_kind": by_kind,
            "by_language": by_lang,
            "by_file": by_file,
            "nodes": all_nodes,
            "node_count": len(all_nodes),
            "file_count": len(by_file),
        }

    def _export_architecture(self, options: ExportOptions) -> dict:
        """Export architecture overview."""
        stats = self._store.get_stats()
        top_n = options.top_n
        all_nodes = self._store.find_nodes(limit=100000)
        sorted_nodes = sorted(all_nodes, key=lambda n: n.pagerank or 0, reverse=True)

        top_classes = [n for n in sorted_nodes if n.kind in (NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.TRAIT)][
            :top_n
        ]
        top_functions = [n for n in sorted_nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)][:top_n]

        by_file: dict[str, list[Node]] = {}
        for node in all_nodes:
            if node.file_path:
                by_file.setdefault(node.file_path, []).append(node)
        top_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)[:top_n]

        by_lang: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for node in all_nodes:
            lang = node.language or "unknown"
            by_lang[lang] = by_lang.get(lang, 0) + 1
            kind = node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
            by_kind[kind] = by_kind.get(kind, 0) + 1

        # Get frameworks from store metadata
        frameworks = []
        try:
            import json as _json

            fw_raw = self._store.get_metadata("frameworks")
            if fw_raw:
                fw_list = _json.loads(fw_raw) if isinstance(fw_raw, str) else fw_raw
                for fw_name in fw_list:
                    frameworks.append({"name": fw_name, "language": "unknown", "metadata": {}})
        except Exception:
            pass

        hot_files = []
        seen_paths = set()
        for node in all_nodes:
            git = node.metadata.get("git", {})
            path = node.file_path or node.name
            if git.get("is_hot_file") and path not in seen_paths:
                seen_paths.add(path)
                hot_files.append(
                    {
                        "path": path,
                        "commits": git.get("commit_count", 0),
                        "authors": git.get("unique_authors", 0),
                        "churn": git.get("churn_ratio", 0),
                    }
                )
        hot_files.sort(key=lambda x: x["commits"], reverse=True)

        return {
            "scope": "architecture",
            "stats": stats,
            "by_language": by_lang,
            "by_kind": by_kind,
            "top_classes": top_classes,
            "top_functions": top_functions,
            "top_files": [(p, len(ns)) for p, ns in top_files],
            "frameworks": frameworks,
            "hot_files": hot_files[:top_n],
        }

    def _export_file(self, options: ExportOptions) -> dict:
        """Export file-scoped context."""
        if not options.file_path:
            raise ValueError("--file is required for file scope")

        file_nodes = self._store.find_nodes(file_path=options.file_path, limit=10000)
        if not file_nodes:
            all_nodes = self._store.find_nodes(limit=100000)
            file_nodes = [n for n in all_nodes if n.file_path and options.file_path in n.file_path]

        if not file_nodes:
            return {
                "scope": "file",
                "file_path": options.file_path,
                "error": f"No nodes found for file: {options.file_path}",
                "nodes": [],
            }

        node_ids = {n.id for n in file_nodes}
        edges = []
        for node in file_nodes:
            neighbor_tuples = self._store.get_neighbors(node.id, max_depth=1)
            for n, edge, depth in neighbor_tuples:
                if n.id not in node_ids:
                    edge_kind = edge.kind.value if hasattr(edge.kind, "value") else str(edge.kind)
                    edges.append({"from": node.name, "to": n.name, "kind": edge_kind})

        file_nodes.sort(key=lambda n: n.start_line or 0)

        return {
            "scope": "file",
            "file_path": options.file_path,
            "nodes": file_nodes,
            "external_refs": edges[:50],
            "node_count": len(file_nodes),
        }

    def _export_symbol(self, options: ExportOptions) -> dict:
        """Export symbol-scoped context."""
        if not options.symbol:
            raise ValueError("--symbol is required for symbol scope")

        results = self._store.search_nodes(options.symbol, limit=5)
        if not results:
            return {
                "scope": "symbol",
                "symbol": options.symbol,
                "error": f"Symbol not found: {options.symbol}",
                "nodes": [],
            }

        primary = results[0]
        neighbor_tuples = self._store.get_neighbors(primary.id, max_depth=options.depth)
        neighbors = [n for n, edge, depth in neighbor_tuples]

        return {
            "scope": "symbol",
            "symbol": options.symbol,
            "primary": primary,
            "neighbors": neighbors,
            "neighbor_count": len(neighbors),
        }

    # ── Formatters ────────────────────────────────────────────

    def _format(self, data: dict, options: ExportOptions) -> str:
        """Format data according to output format."""
        fmt_fn = {
            "markdown": self._format_markdown,
            "json": self._format_json,
            "tree": self._format_tree,
        }
        fn = fmt_fn.get(options.format)
        if fn is None:
            raise ValueError(f"Unknown format: {options.format}. Valid: {list(fmt_fn.keys())}")
        result = fn(data, options)
        return self._apply_token_budget(result, options.max_tokens)

    def _format_json(self, data: dict, options: ExportOptions) -> str:
        """Format as JSON."""

        def _serialize(obj: Any) -> Any:
            if isinstance(obj, Node):
                d = {
                    "id": obj.id,
                    "kind": obj.kind.value if isinstance(obj.kind, NodeKind) else str(obj.kind),
                    "name": obj.name,
                    "qualified_name": obj.qualified_name,
                    "file_path": obj.file_path,
                    "language": obj.language,
                    "start_line": obj.start_line,
                    "end_line": obj.end_line,
                }
                if obj.pagerank:
                    d["pagerank"] = round(obj.pagerank, 6)
                if obj.metadata:
                    d["metadata"] = obj.metadata
                return d
            if isinstance(obj, NodeKind):
                return obj.value
            if isinstance(obj, EdgeKind):
                return obj.value
            return str(obj)

        return json.dumps(data, default=_serialize, indent=2, ensure_ascii=False)

    def _format_markdown(self, data: dict, options: ExportOptions) -> str:
        """Format as Markdown."""
        scope = data.get("scope", "unknown")
        lines: list[str] = []

        if scope == "architecture":
            lines.extend(self._md_architecture(data, options))
        elif scope == "full":
            lines.extend(self._md_full(data, options))
        elif scope == "file":
            lines.extend(self._md_file(data, options))
        elif scope == "symbol":
            lines.extend(self._md_symbol(data, options))
        else:
            lines.append(f"# Export ({scope})\n")
            lines.append(json.dumps(data, indent=2, default=str))

        return "\n".join(lines)

    def _format_tree(self, data: dict, options: ExportOptions) -> str:
        """Format as tree view (like aider's repo map)."""
        scope = data.get("scope", "unknown")
        lines: list[str] = []

        if scope in ("full", "architecture"):
            lines.extend(self._tree_full(data, options))
        elif scope == "file":
            lines.extend(self._tree_file(data, options))
        elif scope == "symbol":
            lines.extend(self._tree_symbol(data, options))

        return "\n".join(lines)

    # ── Markdown Helpers ──────────────────────────────────────

    def _md_architecture(self, data: dict, options: ExportOptions) -> list[str]:
        """Markdown architecture overview."""
        lines = ["# Architecture Overview\n"]

        stats = data.get("stats", {})
        lines.append("## Summary\n")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for key, val in sorted(stats.items()):
            lines.append(f"| {key} | {val} |")
        lines.append("")

        by_lang = data.get("by_language", {})
        if by_lang:
            lines.append("## Languages\n")
            lines.append("| Language | Nodes |")
            lines.append("|----------|-------|")
            for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
                lines.append(f"| {lang} | {count} |")
            lines.append("")

        by_kind = data.get("by_kind", {})
        if by_kind:
            lines.append("## Node Types\n")
            lines.append("| Kind | Count |")
            lines.append("|------|-------|")
            for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
                lines.append(f"| {kind} | {count} |")
            lines.append("")

        frameworks = data.get("frameworks", [])
        if frameworks:
            lines.append("## Frameworks Detected\n")
            for fw in frameworks:
                lines.append(f"- **{fw['name']}** ({fw.get('language', 'unknown')})")
            lines.append("")

        top_classes = data.get("top_classes", [])
        if top_classes:
            lines.append("## Key Classes (by PageRank)\n")
            lines.append("| Class | File | Language | PageRank |")
            lines.append("|-------|------|----------|----------|")
            for node in top_classes:
                pr = f"{node.pagerank:.4f}" if node.pagerank else "—"
                fp = node.file_path or "—"
                lines.append(f"| `{node.qualified_name or node.name}` | {fp} | {node.language or '—'} | {pr} |")
            lines.append("")

        top_fns = data.get("top_functions", [])
        if top_fns:
            lines.append("## Key Functions/Methods (by PageRank)\n")
            lines.append("| Function | File | Language | PageRank |")
            lines.append("|----------|------|----------|----------|")
            for node in top_fns[: options.top_n]:
                pr = f"{node.pagerank:.4f}" if node.pagerank else "—"
                fp = node.file_path or "—"
                lines.append(f"| `{node.qualified_name or node.name}` | {fp} | {node.language or '—'} | {pr} |")
            lines.append("")

        top_files = data.get("top_files", [])
        if top_files:
            lines.append("## Largest Files (by node count)\n")
            lines.append("| File | Nodes |")
            lines.append("|------|-------|")
            for fp, count in top_files:
                lines.append(f"| `{fp}` | {count} |")
            lines.append("")

        hot_files = data.get("hot_files", [])
        if hot_files:
            lines.append("## Hot Files (most changed)\n")
            lines.append("| File | Commits | Authors | Churn |")
            lines.append("|------|---------|---------|-------|")
            for hf in hot_files:
                lines.append(f"| `{hf['path']}` | {hf['commits']} | {hf['authors']} | {hf['churn']:.2f} |")
            lines.append("")

        return lines

    def _md_full(self, data: dict, options: ExportOptions) -> list[str]:
        """Markdown full export."""
        lines = ["# Full Graph Export\n"]
        lines.append(f"**Nodes:** {data.get('node_count', 0)} | **Files:** {data.get('file_count', 0)}\n")

        by_kind = data.get("by_kind", {})
        if by_kind:
            lines.append("## Node Distribution\n")
            lines.append("| Kind | Count |")
            lines.append("|------|-------|")
            for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
                lines.append(f"| {kind} | {count} |")
            lines.append("")

        by_lang = data.get("by_language", {})
        if by_lang:
            lines.append("## Language Distribution\n")
            for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
                lines.append(f"- **{lang}**: {count} nodes")
            lines.append("")

        by_file = data.get("by_file", {})
        if by_file:
            lines.append("## Files\n")
            for fp, count in sorted(by_file.items()):
                lines.append(f"- `{fp}` ({count} nodes)")
            lines.append("")

        return lines

    def _md_file(self, data: dict, options: ExportOptions) -> list[str]:
        """Markdown file export."""
        fp = data.get("file_path", "unknown")
        lines = [f"# File: `{fp}`\n"]

        if data.get("error"):
            lines.append(f"**Error:** {data['error']}\n")
            return lines

        nodes = data.get("nodes", [])
        lines.append(f"**Nodes:** {len(nodes)}\n")

        by_kind: dict[str, list[Node]] = {}
        for node in nodes:
            kind = node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
            by_kind.setdefault(kind, []).append(node)

        for kind, kind_nodes in sorted(by_kind.items()):
            lines.append(f"## {_pluralize(kind)}\n")
            for node in kind_nodes:
                loc = ""
                if node.start_line:
                    loc = f" (L{node.start_line}"
                    loc += f"-{node.end_line})" if node.end_line else ")"
                lines.append(f"- `{node.qualified_name or node.name}`{loc}")
                if node.metadata.get("docstring"):
                    doc = node.metadata["docstring"][:100]
                    lines.append(f"  > {doc}")
            lines.append("")

        ext_refs = data.get("external_refs", [])
        if ext_refs:
            lines.append("## External References\n")
            for ref in ext_refs:
                lines.append(f"- `{ref['from']}` -> `{ref['to']}`")
            lines.append("")

        return lines

    def _md_symbol(self, data: dict, options: ExportOptions) -> list[str]:
        """Markdown symbol export."""
        symbol = data.get("symbol", "unknown")
        lines = [f"# Symbol: `{symbol}`\n"]

        if data.get("error"):
            lines.append(f"**Error:** {data['error']}\n")
            return lines

        primary = data.get("primary")
        if primary:
            kind = primary.kind.value if isinstance(primary.kind, NodeKind) else str(primary.kind)
            lines.append(f"**Kind:** {kind}")
            lines.append(f"**Qualified Name:** `{primary.qualified_name or primary.name}`")
            if primary.file_path:
                lines.append(f"**File:** `{primary.file_path}`")
            if primary.start_line:
                lines.append(f"**Lines:** {primary.start_line}-{primary.end_line or '?'}")
            if primary.language:
                lines.append(f"**Language:** {primary.language}")
            pr = f"{primary.pagerank:.6f}" if primary.pagerank else "—"
            lines.append(f"**PageRank:** {pr}")
            if primary.metadata.get("docstring"):
                lines.append(f"\n> {primary.metadata['docstring']}")
            lines.append("")

        neighbors = data.get("neighbors", [])
        if neighbors:
            lines.append(f"## Related Symbols ({len(neighbors)})\n")
            by_kind: dict[str, list[Node]] = {}
            for n in neighbors:
                kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
                by_kind.setdefault(kind, []).append(n)

            for kind, kind_nodes in sorted(by_kind.items()):
                lines.append(f"### {_pluralize(kind)}")
                for n in kind_nodes:
                    lines.append(f"- `{n.qualified_name or n.name}` ({n.file_path or '—'})")
                lines.append("")

        return lines

    # ── Tree Helpers ──────────────────────────────────────────

    def _tree_full(self, data: dict, options: ExportOptions) -> list[str]:
        """Tree view of full graph (repo map style)."""
        lines = []
        nodes = data.get("nodes", [])
        if not nodes and data.get("top_classes"):
            nodes = data.get("top_classes", []) + data.get("top_functions", [])

        by_file: dict[str, list[Node]] = {}
        for node in nodes:
            fp = node.file_path or "(no file)"
            by_file.setdefault(fp, []).append(node)

        for fp in sorted(by_file.keys()):
            lines.append(fp)
            file_nodes = sorted(by_file[fp], key=lambda n: n.start_line or 0)
            for i, node in enumerate(file_nodes):
                kind = node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
                prefix = "  └── " if i == len(file_nodes) - 1 else "  ├── "
                loc = f":{node.start_line}" if node.start_line else ""
                lines.append(f"{prefix}{kind} {node.name}{loc}")

        return lines

    def _tree_file(self, data: dict, options: ExportOptions) -> list[str]:
        """Tree view of a single file."""
        fp = data.get("file_path", "unknown")
        lines = [fp]
        nodes = data.get("nodes", [])
        nodes.sort(key=lambda n: n.start_line or 0)

        for i, node in enumerate(nodes):
            kind = node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
            prefix = "  └── " if i == len(nodes) - 1 else "  ├── "
            loc = f":{node.start_line}" if node.start_line else ""
            lines.append(f"{prefix}{kind} {node.name}{loc}")

        return lines

    def _tree_symbol(self, data: dict, options: ExportOptions) -> list[str]:
        """Tree view of a symbol and its neighbors."""
        primary = data.get("primary")
        if not primary:
            return [f"Symbol not found: {data.get('symbol', '?')}"]

        kind = primary.kind.value if isinstance(primary.kind, NodeKind) else str(primary.kind)
        lines = [f"{kind} {primary.qualified_name or primary.name}"]

        neighbors = data.get("neighbors", [])
        for i, n in enumerate(neighbors):
            nk = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
            prefix = "  └── " if i == len(neighbors) - 1 else "  ├── "
            lines.append(f"{prefix}{nk} {n.qualified_name or n.name}")

        return lines

    # ── Token Budget ──────────────────────────────────────────

    def _apply_token_budget(self, text: str, max_tokens: int) -> str:
        """Truncate output to fit within token budget."""
        max_chars = max_tokens * CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text

        truncated = text[: max_chars - 200]
        last_nl = truncated.rfind("\n")
        if last_nl > 0:
            truncated = truncated[:last_nl]

        truncated += f"\n\n---\n*Output truncated to ~{max_tokens} tokens. "
        truncated += "Use --tokens to increase budget or narrow --scope.*\n"
        return truncated
