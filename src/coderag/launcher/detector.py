"""Project state detection for Smart Launcher.

Detects whether a project's knowledge graph is fresh, stale, or ready.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ProjectState(StrEnum):
    """State of a project's knowledge graph."""

    FRESH = "fresh"  # No graph.db exists
    STALE = "stale"  # Source files newer than db
    READY = "ready"  # Graph is current


@dataclass(slots=True)
class ProjectStateInfo:
    """Detailed information about a project's state."""

    state: ProjectState
    db_path: str
    db_exists: bool
    db_mtime: float | None = None
    source_file_count: int = 0
    newest_source_mtime: float | None = None
    stale_files: list[str] = field(default_factory=list)


# Common source extensions to check
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".php",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".py",
        ".css",
        ".scss",
        ".vue",
    }
)

# Directories to always skip
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "vendor",
        ".git",
        "__pycache__",
        ".codegraph",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "venv",
        ".venv",
        "env",
        ".tox",
    }
)


def _find_source_files(project_path: str) -> list[tuple[str, float]]:
    """Find source files and their mtimes.

    Returns:
        List of (relative_path, mtime) tuples.
    """
    results: list[tuple[str, float]] = []
    root = Path(project_path).resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _SOURCE_EXTENSIONS:
                full_path = os.path.join(dirpath, fname)
                try:
                    mtime = os.path.getmtime(full_path)
                    rel_path = os.path.relpath(full_path, root)
                    results.append((rel_path, mtime))
                except OSError:
                    continue

    return results


def detect_project_state(
    path: str,
    db_relative: str = ".codegraph/graph.db",
) -> ProjectStateInfo:
    """Detect the state of a project's knowledge graph.

    Args:
        path: Path to the project root.
        db_relative: Relative path to the database file.

    Returns:
        ProjectStateInfo with state and diagnostic details.
    """
    project_path = str(Path(path).resolve())
    db_path = os.path.join(project_path, db_relative)
    db_exists = os.path.isfile(db_path)

    if not db_exists:
        # Count source files even for fresh projects
        source_files = _find_source_files(project_path)
        return ProjectStateInfo(
            state=ProjectState.FRESH,
            db_path=db_path,
            db_exists=False,
            source_file_count=len(source_files),
        )

    db_mtime = os.path.getmtime(db_path)
    source_files = _find_source_files(project_path)

    if not source_files:
        return ProjectStateInfo(
            state=ProjectState.READY,
            db_path=db_path,
            db_exists=True,
            db_mtime=db_mtime,
            source_file_count=0,
        )

    # Find files newer than the database
    stale_files = [rel_path for rel_path, mtime in source_files if mtime > db_mtime]
    newest_mtime = max(mtime for _, mtime in source_files)

    if stale_files:
        state = ProjectState.STALE
    else:
        state = ProjectState.READY

    return ProjectStateInfo(
        state=state,
        db_path=db_path,
        db_exists=True,
        db_mtime=db_mtime,
        source_file_count=len(source_files),
        newest_source_mtime=newest_mtime,
        stale_files=stale_files[:50],  # Cap for display
    )
