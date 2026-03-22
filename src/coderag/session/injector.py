"""Context injection markdown generator.

Builds token-budgeted markdown context from session history
for pre-loading into AI coding sessions.
"""

from __future__ import annotations

import logging

from coderag.session.store import SessionStore

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate token count: ~4 chars per token."""
    return max(1, len(text) // 4)


class ContextInjector:
    """Generate markdown context from session history.

    Produces a markdown document summarizing session activity,
    hot files, decisions, tasks, and facts for AI pre-loading.

    Sections are ordered by priority:
    1. Hot files (most accessed)
    2. Decisions
    3. Open tasks
    4. Facts
    5. Recent activity

    Args:
        store: An initialized SessionStore instance.
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def generate_context(self, token_budget: int = 4000) -> str:
        """Generate markdown context within token budget.

        Args:
            token_budget: Maximum estimated tokens for the output.

        Returns:
            Markdown string with session context.
        """
        sections: list[tuple[str, str]] = []  # (name, content)
        tokens_used = 0

        # Header
        header = "## Session Context (from previous sessions)\n"
        tokens_used += _estimate_tokens(header)

        # Priority 1: Hot files
        hot_files_section = self._build_hot_files_section()
        if hot_files_section:
            sections.append(("hot_files", hot_files_section))

        # Priority 2: Decisions
        decisions_section = self._build_decisions_section()
        if decisions_section:
            sections.append(("decisions", decisions_section))

        # Priority 3: Open tasks
        tasks_section = self._build_tasks_section()
        if tasks_section:
            sections.append(("tasks", tasks_section))

        # Priority 4: Facts
        facts_section = self._build_facts_section()
        if facts_section:
            sections.append(("facts", facts_section))

        # Priority 5: Recent activity
        activity_section = self._build_recent_activity_section()
        if activity_section:
            sections.append(("activity", activity_section))

        # Assemble within budget
        parts: list[str] = [header]
        for _name, content in sections:
            section_tokens = _estimate_tokens(content)
            if tokens_used + section_tokens <= token_budget:
                parts.append(content)
                tokens_used += section_tokens
            else:
                # Try to fit a truncated version
                remaining_chars = (token_budget - tokens_used) * 4
                if remaining_chars > 100:
                    truncated = content[:remaining_chars].rsplit("\n", 1)[0]
                    truncated += "\n\n_[Section truncated to fit token budget]_\n"
                    parts.append(truncated)
                    tokens_used = token_budget
                break

        result = "\n".join(parts)

        # Safety net
        max_chars = token_budget * 4
        if len(result) > max_chars:
            result = result[:max_chars] + "\n\n_[Context truncated to fit token budget]_\n"

        return result

    def _build_hot_files_section(self, limit: int = 10) -> str:
        """Build hot files section."""
        hot_files = self._store.get_hot_files(limit=limit)
        if not hot_files:
            return ""

        lines = ["### Hot Files (most accessed)\n"]

        # Get per-file read/edit breakdown
        for i, (file_path, total_count) in enumerate(hot_files, 1):
            # Count reads and edits separately
            reads = self._store.get_events(event_type="read", target=file_path, limit=10000)
            edits = self._store.get_events(event_type="edit", target=file_path, limit=10000)
            read_count = len(reads)
            edit_count = len(edits)
            lines.append(f"{i}. `{file_path}` \u2014 {read_count} reads, {edit_count} edits")

        lines.append("")
        return "\n".join(lines)

    def _build_decisions_section(self, limit: int = 10) -> str:
        """Build decisions section."""
        decisions = self._store.get_context(category="decision", active_only=True, limit=limit)
        if not decisions:
            return ""

        lines = ["### Decisions\n"]
        for d in decisions:
            created = d["created_at"][:10]  # date only
            lines.append(f"- [{created}] {d['content']}")

        lines.append("")
        return "\n".join(lines)

    def _build_tasks_section(self, limit: int = 10) -> str:
        """Build open tasks section."""
        tasks = self._store.get_context(category="task", active_only=True, limit=limit)
        if not tasks:
            return ""

        lines = ["### Open Tasks\n"]
        for t in tasks:
            lines.append(f"- [ ] {t['content']}")

        lines.append("")
        return "\n".join(lines)

    def _build_facts_section(self, limit: int = 10) -> str:
        """Build facts section."""
        facts = self._store.get_context(category="fact", active_only=True, limit=limit)
        if not facts:
            return ""

        lines = ["### Facts\n"]
        for f in facts:
            lines.append(f"- {f['content']}")

        lines.append("")
        return "\n".join(lines)

    def _build_recent_activity_section(self, limit: int = 3) -> str:
        """Build recent activity section from recent sessions."""
        sessions = self._store.get_recent_sessions(limit=limit)
        if not sessions:
            return ""

        lines = ["### Recent Activity\n"]
        for s in sessions:
            tool = s["tool"] or "unknown"
            started = s["started_at"][:10] if s["started_at"] else "?"
            event_count = s["event_count"] or 0
            prompt_preview = ""
            if s["prompt"]:
                prompt_preview = f' \u2014 "{s["prompt"][:60]}"'
            lines.append(f"- [{started}] {tool}: {event_count} events{prompt_preview}")

        # Also show recent edits and queries
        recent_edits = self._store.get_events(event_type="edit", limit=5)
        if recent_edits:
            lines.append("")
            lines.append("**Recent edits:**")
            seen: set[str] = set()
            for ev in recent_edits:
                if ev.target not in seen:
                    seen.add(ev.target)
                    lines.append(f"- `{ev.target}` ({ev.timestamp.strftime('%Y-%m-%d')})")

        recent_queries = self._store.get_events(event_type="query", limit=5)
        if recent_queries:
            lines.append("")
            lines.append("**Recent queries:**")
            for ev in recent_queries:
                lines.append(f'- "{ev.target}" ({ev.timestamp.strftime("%Y-%m-%d")})')

        lines.append("")
        return "\n".join(lines)
