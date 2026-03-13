"""Live file watcher with auto-reparse — ``coderag watch`` support.

Monitors a project directory for file changes using the ``watchdog`` library
and triggers incremental pipeline runs on changed files.

Features:

- Respects the same ignore patterns as :class:`FileScanner`.
- Debounces rapid changes (configurable, default 2 s).
- Handles create / modify / delete events.
- Emits pipeline events so the MCP server can detect changes.
- Cleans up deleted-file nodes and edges from the store.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import signal
import threading
from collections.abc import Callable
from typing import Any

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from coderag.core.config import CodeGraphConfig
from coderag.core.registry import PluginRegistry
from coderag.pipeline.events import (
    EventEmitter,
    PhaseCompleted,
    PhaseStarted,
    PipelinePhase,
    PipelineStarted,
)
from coderag.pipeline.events import (
    PipelineCompleted as PipelineCompletedEvent,
)
from coderag.storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Debounced change collector
# ---------------------------------------------------------------------------


class _ChangeCollector:
    """Collect file-system events and flush them after a debounce window.

    Thread-safe: watchdog callbacks run on the observer thread while the
    flush timer fires on its own thread.
    """

    def __init__(
        self,
        debounce_seconds: float = 2.0,
        on_flush: Callable[[set[str], set[str]], None] | None = None,
    ) -> None:
        self._debounce = debounce_seconds
        self._on_flush = on_flush
        self._lock = threading.Lock()
        self._changed: set[str] = set()  # created / modified
        self._deleted: set[str] = set()
        self._timer: threading.Timer | None = None

    # -- public API ----------------------------------------------------------

    def add_change(self, path: str) -> None:
        """Record a created or modified file."""
        with self._lock:
            self._changed.add(path)
            self._deleted.discard(path)
            self._reset_timer()

    def add_deletion(self, path: str) -> None:
        """Record a deleted file."""
        with self._lock:
            self._deleted.add(path)
            self._changed.discard(path)
            self._reset_timer()

    def flush_now(self) -> tuple[set[str], set[str]]:
        """Immediately flush pending changes (for testing / shutdown)."""
        with self._lock:
            self._cancel_timer()
            changed = set(self._changed)
            deleted = set(self._deleted)
            self._changed.clear()
            self._deleted.clear()
        if self._on_flush and (changed or deleted):
            self._on_flush(changed, deleted)
        return changed, deleted

    def stop(self) -> None:
        """Cancel any pending timer."""
        with self._lock:
            self._cancel_timer()

    # -- internals -----------------------------------------------------------

    def _reset_timer(self) -> None:
        self._cancel_timer()
        self._timer = threading.Timer(self._debounce, self._on_timer)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_timer(self) -> None:
        self.flush_now()


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------


class _ProjectEventHandler(FileSystemEventHandler):
    """Filter events through ignore patterns and forward to collector."""

    def __init__(
        self,
        project_root: str,
        extensions: set[str],
        ignore_patterns: list[str],
        collector: _ChangeCollector,
    ) -> None:
        super().__init__()
        self._root = os.path.abspath(project_root)
        self._extensions = extensions
        self._ignore = ignore_patterns
        self._collector = collector

    # -- watchdog callbacks --------------------------------------------------

    def on_created(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            path = str(event.src_path)
            if self._accept(path):
                self._collector.add_change(path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            path = str(event.src_path)
            if self._accept(path):
                self._collector.add_change(path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileDeletedEvent) and not event.is_directory:
            path = str(event.src_path)
            if self._accept(path):
                self._collector.add_deletion(path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            src = str(event.src_path)
            dest = str(event.dest_path)
            if self._accept(src):
                self._collector.add_deletion(src)
            if self._accept(dest):
                self._collector.add_change(dest)

    # -- filtering -----------------------------------------------------------

    def _accept(self, abs_path: str) -> bool:
        """Return *True* if the file should be watched."""
        _, ext = os.path.splitext(abs_path)
        if self._extensions and ext not in self._extensions:
            return False
        rel = os.path.relpath(abs_path, self._root)
        return not self._is_ignored(rel)

    def _is_ignored(self, rel_path: str) -> bool:
        """Mirror :meth:`FileScanner._is_ignored`."""
        norm = rel_path.replace(os.sep, "/")
        if norm.startswith("./"):
            norm = norm[2:]
        for pattern in self._ignore:
            if fnmatch.fnmatch(norm, pattern):
                return True
            if fnmatch.fnmatch(os.path.basename(norm), pattern):
                return True
            parts = norm.split("/")
            for part in parts:
                if fnmatch.fnmatch(part + "/", pattern):
                    return True
                if fnmatch.fnmatch(part, pattern.rstrip("/").rstrip("/*")):
                    return True
        return False


# ---------------------------------------------------------------------------
# Public API — FileWatcher
# ---------------------------------------------------------------------------


class FileWatcher:
    """Watch a project directory and trigger incremental pipeline runs.

    Usage::

        watcher = FileWatcher(config, registry, store, emitter)
        watcher.start("/path/to/project")
        # … blocks until Ctrl-C or watcher.stop() from another thread …

    The watcher reuses the same :class:`PipelineOrchestrator` for each
    incremental run so that plugin registries and store connections are
    shared.
    """

    def __init__(
        self,
        config: CodeGraphConfig,
        registry: PluginRegistry,
        store: SQLiteStore,
        emitter: EventEmitter | None = None,
        *,
        debounce_seconds: float = 2.0,
        on_reparse: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._store = store
        self._emitter = emitter
        self._debounce = debounce_seconds
        self._on_reparse = on_reparse

        self._observer: Any = None  # watchdog Observer
        self._collector: _ChangeCollector | None = None
        self._project_root: str = ""
        self._running = False
        self._reparse_count = 0
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------

    @property
    def reparse_count(self) -> int:
        """Number of incremental re-parses triggered so far."""
        return self._reparse_count

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, project_root: str, *, blocking: bool = True) -> None:
        """Start watching *project_root*.

        Args:
            project_root: Absolute or relative path to the project.
            blocking: If *True* (default), block until interrupted.
        """
        self._project_root = os.path.abspath(project_root)
        logger.info("FileWatcher starting on %s", self._project_root)

        # Collect extensions from registered plugins
        all_extensions: set[str] = set()
        for plugin in self._registry.get_all_plugins():
            all_extensions.update(plugin.file_extensions)

        ignore = self._config.ignore_patterns

        self._collector = _ChangeCollector(
            debounce_seconds=self._debounce,
            on_flush=self._handle_changes,
        )

        handler = _ProjectEventHandler(
            project_root=self._project_root,
            extensions=all_extensions,
            ignore_patterns=ignore,
            collector=self._collector,
        )

        self._observer = Observer()
        self._observer.schedule(handler, self._project_root, recursive=True)
        self._observer.start()
        self._running = True

        logger.info(
            "FileWatcher active — monitoring %d extension(s), debounce=%.1fs",
            len(all_extensions),
            self._debounce,
        )

        if blocking:
            self._block_until_stopped()

    def stop(self) -> None:
        """Stop the watcher gracefully."""
        logger.info("FileWatcher stopping…")
        self._running = False
        if self._collector:
            # Flush any pending changes before stopping
            self._collector.flush_now()
            self._collector.stop()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        logger.info(
            "FileWatcher stopped after %d reparse(s).",
            self._reparse_count,
        )

    # -- internals -----------------------------------------------------------

    def _block_until_stopped(self) -> None:
        """Block the calling thread; honour SIGINT / SIGTERM."""
        stop_event = threading.Event()

        def _signal_handler(signum: int, frame: Any) -> None:
            logger.info("Received signal %d, stopping watcher…", signum)
            stop_event.set()

        prev_int = signal.signal(signal.SIGINT, _signal_handler)
        prev_term = signal.signal(signal.SIGTERM, _signal_handler)
        try:
            while self._running and not stop_event.is_set():
                stop_event.wait(timeout=0.5)
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
            self.stop()

    def _handle_changes(
        self,
        changed: set[str],
        deleted: set[str],
    ) -> None:
        """Process a batch of debounced file-system changes."""
        if not changed and not deleted:
            return

        logger.info(
            "FileWatcher: %d changed, %d deleted — triggering reparse",
            len(changed),
            len(deleted),
        )

        with self._lock:
            try:
                self._emit(PipelineStarted(project_root=self._project_root))

                # Handle deletions first
                if deleted:
                    self._handle_deletions(deleted)

                # Run incremental pipeline on changed files
                stats: dict[str, Any] = {}
                if changed:
                    stats = self._run_incremental(changed)

                self._reparse_count += 1

                self._emit(
                    PipelineCompletedEvent(
                        project_root=self._project_root,
                        summary=stats,
                    )
                )

                if self._on_reparse:
                    self._on_reparse(stats)

                logger.info(
                    "FileWatcher: reparse #%d complete — %s",
                    self._reparse_count,
                    stats,
                )

            except Exception:
                logger.exception("FileWatcher: reparse failed")

    def _handle_deletions(self, deleted: set[str]) -> None:
        """Remove nodes and edges for deleted files from the store."""
        self._emit(PhaseStarted(phase=PipelinePhase.PERSISTENCE))
        for file_path in deleted:
            try:
                count = self._store.delete_nodes_for_file(file_path)
                # Also remove the file hash entry
                self._store.connection.execute(
                    "DELETE FROM file_hashes WHERE file_path = ?",
                    (file_path,),
                )
                self._store.connection.commit()
                logger.info(
                    "Deleted %d nodes for removed file: %s",
                    count,
                    file_path,
                )
            except Exception:
                logger.exception("Failed to clean up deleted file: %s", file_path)
        self._emit(
            PhaseCompleted(
                phase=PipelinePhase.PERSISTENCE,
                summary={"deleted_files": len(deleted)},
            )
        )

    def _run_incremental(self, changed: set[str]) -> dict[str, Any]:
        """Run the pipeline on a specific set of changed files."""
        # Lazy import to avoid circular dependency
        from coderag.pipeline.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator(
            config=self._config,
            registry=self._registry,
            store=self._store,
            emitter=self._emitter,
        )
        summary = orchestrator.run(
            project_root=self._project_root,
            incremental=True,
        )
        return {
            "files_parsed": summary.files_parsed,
            "files_skipped": summary.files_skipped,
            "files_errored": summary.files_errored,
            "total_nodes": summary.total_nodes,
            "total_edges": summary.total_edges,
        }

    def _emit(self, event: Any) -> None:
        if self._emitter is not None:
            self._emitter.emit(event)
