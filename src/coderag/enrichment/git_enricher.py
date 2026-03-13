"""Git metadata enrichment — Phase 7 of the pipeline.

Analyzes git history to enrich the knowledge graph with:
- Change frequency per file (hot files detection)
- Co-change analysis (files that frequently change together)
- Code ownership (who owns what, based on git blame/log)
- Churn metrics (lines added/removed over time)
- Recency scoring (recently changed files are more relevant)
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Data Classes ──────────────────────────────────────────────────


@dataclass
class FileGitMetrics:
    """Git-derived metrics for a single file."""

    file_path: str
    commit_count: int = 0
    unique_authors: int = 0
    primary_author: str = ""
    primary_author_pct: float = 0.0
    last_modified: str = ""  # ISO date of last commit
    first_seen: str = ""  # ISO date of first commit
    age_days: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    churn_ratio: float = 0.0  # deleted / (added + deleted)
    change_frequency: float = 0.0  # commits per month
    recency_score: float = 0.0  # 0.0-1.0, higher = more recent
    is_hot_file: bool = False  # True if in top 10% by commits


@dataclass
class CoChangeEntry:
    """Two files that frequently change together."""

    file_a: str
    file_b: str
    co_change_count: int = 0
    confidence: float = 0.0  # co_changes / min(commits_a, commits_b)
    jaccard_index: float = 0.0  # intersection / union of commit sets


@dataclass
class GitEnrichmentResult:
    """Complete result of git enrichment."""

    file_metrics: dict[str, FileGitMetrics] = field(default_factory=dict)
    co_changes: list[CoChangeEntry] = field(default_factory=list)
    total_commits_analyzed: int = 0
    total_authors: int = 0
    analysis_time_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


# ── Git Enricher ──────────────────────────────────────────────────


class GitEnricher:
    """Analyze git history to produce enrichment metadata.

    Uses raw git commands (subprocess) to extract history data.
    Designed to be fast: uses git log with custom formats to minimize
    the number of subprocess calls.
    """

    # Minimum commits for co-change to be meaningful
    MIN_CO_CHANGE_COUNT = 3
    # Minimum confidence for co-change edge
    MIN_CO_CHANGE_CONFIDENCE = 0.25
    # Top N% of files by commit count are "hot"
    HOT_FILE_PERCENTILE = 0.10
    # Max commits to analyze (0 = unlimited)
    MAX_COMMITS = 0
    # Co-change: max files per commit to consider (skip huge refactors)
    MAX_FILES_PER_COMMIT = 50

    def __init__(
        self,
        repo_root: str,
        *,
        max_commits: int = 0,
        file_filter: set[str] | None = None,
    ) -> None:
        """Initialize GitEnricher.

        Args:
            repo_root: Path to the git repository root.
            max_commits: Limit number of commits to analyze (0 = all).
            file_filter: If provided, only enrich these file paths
                         (relative to repo root).
        """
        self._repo_root = os.path.abspath(repo_root)
        self._max_commits = max_commits or self.MAX_COMMITS
        self._file_filter = file_filter

        # Verify git repo
        if not os.path.isdir(os.path.join(self._repo_root, ".git")):
            raise ValueError(f"Not a git repository: {self._repo_root}")

    # ── Public API ────────────────────────────────────────────

    def enrich(self) -> GitEnrichmentResult:
        """Run full git enrichment analysis.

        Returns:
            GitEnrichmentResult with per-file metrics and co-change data.
        """
        t0 = time.perf_counter()
        result = GitEnrichmentResult()

        try:
            # Step 1: Get commit history
            logger.info("Git enrichment: analyzing commit history...")
            commits = self._get_commit_history()
            result.total_commits_analyzed = len(commits)

            if not commits:
                logger.warning("Git enrichment: no commits found.")
                result.analysis_time_ms = (time.perf_counter() - t0) * 1000
                return result

            # Step 2: Build per-file metrics
            logger.info("Git enrichment: computing per-file metrics...")
            file_metrics = self._compute_file_metrics(commits)
            result.file_metrics = file_metrics

            # Step 3: Compute co-change relationships
            logger.info("Git enrichment: computing co-change relationships...")
            co_changes = self._compute_co_changes(commits, file_metrics)
            result.co_changes = co_changes

            # Step 4: Compute global stats
            all_authors: set[str] = set()
            for commit in commits.values():
                all_authors.add(commit["author"])
            result.total_authors = len(all_authors)

            # Mark hot files
            self._mark_hot_files(file_metrics)

        except Exception as exc:
            logger.error("Git enrichment failed: %s", exc)
            result.errors.append(str(exc))

        result.analysis_time_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Git enrichment complete: %d files, %d co-change pairs, %d commits, %d authors in %.1fms",
            len(result.file_metrics),
            len(result.co_changes),
            result.total_commits_analyzed,
            result.total_authors,
            result.analysis_time_ms,
        )
        return result

    def enrich_to_dicts(self) -> dict[str, Any]:
        """Run enrichment and return serializable dicts.

        Convenience method for pipeline integration.
        Returns dict with keys: file_metrics, co_changes, stats.
        """
        result = self.enrich()
        return {
            "file_metrics": {
                path: {
                    "commit_count": m.commit_count,
                    "unique_authors": m.unique_authors,
                    "primary_author": m.primary_author,
                    "primary_author_pct": m.primary_author_pct,
                    "last_modified": m.last_modified,
                    "first_seen": m.first_seen,
                    "age_days": m.age_days,
                    "lines_added": m.lines_added,
                    "lines_deleted": m.lines_deleted,
                    "churn_ratio": m.churn_ratio,
                    "change_frequency": m.change_frequency,
                    "recency_score": m.recency_score,
                    "is_hot_file": m.is_hot_file,
                }
                for path, m in result.file_metrics.items()
            },
            "co_changes": [
                {
                    "file_a": cc.file_a,
                    "file_b": cc.file_b,
                    "co_change_count": cc.co_change_count,
                    "confidence": cc.confidence,
                    "jaccard_index": cc.jaccard_index,
                }
                for cc in result.co_changes
            ],
            "stats": {
                "total_commits_analyzed": result.total_commits_analyzed,
                "total_authors": result.total_authors,
                "total_files": len(result.file_metrics),
                "total_co_change_pairs": len(result.co_changes),
                "hot_files": sum(1 for m in result.file_metrics.values() if m.is_hot_file),
                "analysis_time_ms": round(result.analysis_time_ms, 1),
            },
            "errors": result.errors,
        }

    # ── Git Data Extraction ───────────────────────────────────

    def _run_git(self, *args: str) -> str:
        """Run a git command and return stdout."""
        cmd = ["git", "-C", self._repo_root] + list(args)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                logger.debug("git command failed: %s\nstderr: %s", cmd, proc.stderr)
                return ""
            return proc.stdout
        except subprocess.TimeoutExpired:
            logger.warning("git command timed out: %s", cmd)
            return ""
        except FileNotFoundError:
            logger.error("git not found in PATH")
            return ""

    def _get_commit_history(self) -> dict[str, dict[str, Any]]:
        """Get commit history with per-commit file changes.

        Returns:
            Dict mapping commit_hash -> {
                hash, author, date, files: [{path, added, deleted}]
            }
        """
        limit_arg = []
        if self._max_commits > 0:
            limit_arg = [f"-n{self._max_commits}"]

        raw = self._run_git(
            "log",
            "--pretty=format:COMMIT|%H|%aN|%aI",
            "--numstat",
            *limit_arg,
        )

        if not raw.strip():
            return {}

        commits: dict[str, dict[str, Any]] = {}
        current_commit: dict[str, Any] | None = None

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("COMMIT|"):
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    commit_hash = parts[1]
                    current_commit = {
                        "hash": commit_hash,
                        "author": parts[2],
                        "date": parts[3],
                        "files": [],
                    }
                    commits[commit_hash] = current_commit
            elif current_commit is not None:
                # numstat line: added\tdeleted\tfilepath
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    added_str, deleted_str, filepath = parts
                    try:
                        added = int(added_str) if added_str != "-" else 0
                        deleted = int(deleted_str) if deleted_str != "-" else 0
                    except ValueError:
                        added, deleted = 0, 0

                    # Apply file filter if set
                    if self._file_filter and filepath not in self._file_filter:
                        continue

                    current_commit["files"].append(
                        {
                            "path": filepath,
                            "added": added,
                            "deleted": deleted,
                        }
                    )

        return commits

    # ── Per-File Metrics ──────────────────────────────────────

    def _compute_file_metrics(
        self,
        commits: dict[str, dict[str, Any]],
    ) -> dict[str, FileGitMetrics]:
        """Compute per-file git metrics from commit history."""
        # Accumulate per-file data
        file_commits: dict[str, list[dict]] = defaultdict(list)
        file_authors: dict[str, Counter] = defaultdict(Counter)
        file_added: dict[str, int] = defaultdict(int)
        file_deleted: dict[str, int] = defaultdict(int)
        file_dates: dict[str, list[str]] = defaultdict(list)

        for commit in commits.values():
            author = commit["author"]
            date = commit["date"]
            for f in commit["files"]:
                path = f["path"]
                file_commits[path].append(commit)
                file_authors[path][author] += 1
                file_added[path] += f["added"]
                file_deleted[path] += f["deleted"]
                file_dates[path].append(date)

        # Compute metrics
        now = datetime.now(UTC)
        metrics: dict[str, FileGitMetrics] = {}

        for path in file_commits:
            dates = sorted(file_dates[path])
            authors = file_authors[path]
            total_commits = len(file_commits[path])
            total_added = file_added[path]
            total_deleted = file_deleted[path]

            # Primary author
            primary_author, primary_count = authors.most_common(1)[0]
            primary_pct = primary_count / total_commits if total_commits > 0 else 0.0

            # Age and frequency
            first_date = dates[0] if dates else ""
            last_date = dates[-1] if dates else ""

            age_days = 0
            change_freq = 0.0
            recency = 0.0

            if first_date and last_date:
                try:
                    first_dt = datetime.fromisoformat(first_date)
                    last_dt = datetime.fromisoformat(last_date)
                    age_days = max(1, (now - first_dt).days)
                    days_since_last = max(0, (now - last_dt).days)

                    # Commits per 30-day month
                    months = max(1.0, age_days / 30.0)
                    change_freq = total_commits / months

                    # Recency: exponential decay, half-life = 90 days
                    half_life = 90.0
                    recency = math.exp(-0.693 * days_since_last / half_life)
                except (ValueError, OverflowError):
                    pass

            # Churn ratio
            total_changes = total_added + total_deleted
            churn_ratio = total_deleted / total_changes if total_changes > 0 else 0.0

            metrics[path] = FileGitMetrics(
                file_path=path,
                commit_count=total_commits,
                unique_authors=len(authors),
                primary_author=primary_author,
                primary_author_pct=round(primary_pct, 3),
                last_modified=last_date,
                first_seen=first_date,
                age_days=age_days,
                lines_added=total_added,
                lines_deleted=total_deleted,
                churn_ratio=round(churn_ratio, 3),
                change_frequency=round(change_freq, 3),
                recency_score=round(recency, 3),
            )

        return metrics

    def _mark_hot_files(self, metrics: dict[str, FileGitMetrics]) -> None:
        """Mark top N% of files by commit count as hot files."""
        if not metrics:
            return

        commit_counts = sorted(
            (m.commit_count for m in metrics.values()),
            reverse=True,
        )
        threshold_idx = max(1, int(len(commit_counts) * self.HOT_FILE_PERCENTILE))
        threshold = commit_counts[min(threshold_idx, len(commit_counts) - 1)]

        for m in metrics.values():
            m.is_hot_file = m.commit_count >= threshold

    # ── Co-Change Analysis ────────────────────────────────────

    def _compute_co_changes(
        self,
        commits: dict[str, dict[str, Any]],
        file_metrics: dict[str, FileGitMetrics],
    ) -> list[CoChangeEntry]:
        """Find files that frequently change together.

        Uses commit-level co-occurrence: if two files appear in the same
        commit, they co-changed. Filters out huge commits (refactors)
        and requires minimum co-change count.
        """
        # Build per-file commit sets for Jaccard
        file_commit_sets: dict[str, set[str]] = defaultdict(set)
        # Count pairwise co-occurrences
        pair_counts: Counter = Counter()

        for commit_hash, commit in commits.items():
            files_in_commit = [f["path"] for f in commit["files"]]

            # Skip huge commits (likely refactors/renames)
            if len(files_in_commit) > self.MAX_FILES_PER_COMMIT:
                continue

            # Only consider files we have metrics for
            relevant = [f for f in files_in_commit if f in file_metrics]

            for f in relevant:
                file_commit_sets[f].add(commit_hash)

            # Count pairs (sorted to avoid duplicates)
            for i, fa in enumerate(relevant):
                for fb in relevant[i + 1 :]:
                    pair = (fa, fb) if fa < fb else (fb, fa)
                    pair_counts[pair] += 1

        # Build co-change entries
        co_changes: list[CoChangeEntry] = []

        for (fa, fb), count in pair_counts.items():
            if count < self.MIN_CO_CHANGE_COUNT:
                continue

            # Confidence: co-changes / min(commits_a, commits_b)
            commits_a = file_metrics[fa].commit_count
            commits_b = file_metrics[fb].commit_count
            min_commits = min(commits_a, commits_b)
            confidence = count / min_commits if min_commits > 0 else 0.0

            if confidence < self.MIN_CO_CHANGE_CONFIDENCE:
                continue

            # Jaccard index
            set_a = file_commit_sets.get(fa, set())
            set_b = file_commit_sets.get(fb, set())
            union = len(set_a | set_b)
            jaccard = len(set_a & set_b) / union if union > 0 else 0.0

            co_changes.append(
                CoChangeEntry(
                    file_a=fa,
                    file_b=fb,
                    co_change_count=count,
                    confidence=round(confidence, 3),
                    jaccard_index=round(jaccard, 3),
                )
            )

        # Sort by confidence descending
        co_changes.sort(key=lambda x: x.confidence, reverse=True)

        logger.info(
            "Co-change analysis: %d pairs from %d file combinations",
            len(co_changes),
            len(pair_counts),
        )
        return co_changes
