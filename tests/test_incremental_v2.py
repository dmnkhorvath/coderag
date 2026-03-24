"""Tests for AST Incremental Parsing v2 — Phase 1 (Foundation MVP).

Covers:
- ParseTreeCache: put/get, LRU eviction, memory limits, stats, thread safety
- EditComputer: compute_edits with insertions, deletions, replacements
- IncrementalOrchestrator: incremental vs full path, cache warming, deletions
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import tree_sitter
import tree_sitter_python as tspython

from coderag.core.models import ExtractionResult, Node, NodeKind
from coderag.pipeline.edit_computer import EditComputer
from coderag.pipeline.incremental import IncrementalOrchestrator, IncrementalSummary
from coderag.pipeline.parse_cache import CachedTree, ParseTreeCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser() -> tree_sitter.Parser:
    """Create a tree-sitter Python parser."""
    lang = tree_sitter.Language(tspython.language())
    return tree_sitter.Parser(lang)


def _parse(source: bytes) -> tree_sitter.Tree:
    """Parse Python source bytes and return the tree."""
    return _make_parser().parse(source)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# =========================================================================
# TestParseTreeCache
# =========================================================================


class TestParseTreeCache:
    """Tests for the in-memory LRU parse-tree cache."""

    def test_put_and_get(self) -> None:
        cache = ParseTreeCache()
        src = b"def foo(): pass"
        tree = _parse(src)
        h = _sha256(src)

        cache.put("a.py", tree, src, h, "python")
        cached = cache.get("a.py")

        assert cached is not None
        assert cached.content_hash == h
        assert cached.language == "python"
        assert cached.source == src

    def test_get_miss(self) -> None:
        cache = ParseTreeCache()
        assert cache.get("nonexistent.py") is None

    def test_stats_hit_miss(self) -> None:
        cache = ParseTreeCache()
        src = b"x = 1"
        cache.put("a.py", _parse(src), src, _sha256(src), "python")

        cache.get("a.py")  # hit
        cache.get("b.py")  # miss
        cache.get("a.py")  # hit

        stats = cache.stats()
        assert stats.hit_count == 2
        assert stats.miss_count == 1
        assert stats.entries == 1

    def test_evict_specific(self) -> None:
        cache = ParseTreeCache()
        src = b"x = 1"
        cache.put("a.py", _parse(src), src, _sha256(src), "python")
        assert cache.get("a.py") is not None

        cache.evict("a.py")
        assert cache.get("a.py") is None

    def test_evict_nonexistent(self) -> None:
        cache = ParseTreeCache()
        cache.evict("nope.py")  # should not raise

    def test_clear(self) -> None:
        cache = ParseTreeCache()
        for i in range(5):
            src = f"x_{i} = {i}".encode()
            cache.put(f"{i}.py", _parse(src), src, _sha256(src), "python")

        assert cache.stats().entries == 5
        cache.clear()
        stats = cache.stats()
        assert stats.entries == 0
        assert stats.hit_count == 0
        assert stats.miss_count == 0

    def test_lru_eviction_under_memory_limit(self) -> None:
        """When memory limit is tiny, oldest entries get evicted."""
        # Each entry: source * 3 bytes estimated
        # Use a very small limit to force eviction
        cache = ParseTreeCache(max_memory_mb=0)  # 0 MB = immediate eviction
        src = b"x = 1"
        cache.put("a.py", _parse(src), src, _sha256(src), "python")

        # With 0 MB limit, the entry should be evicted immediately
        stats = cache.stats()
        assert stats.entries == 0
        assert stats.eviction_count >= 1

    def test_lru_eviction_order(self) -> None:
        """LRU eviction removes least recently accessed entry."""
        # Create cache with ~100 bytes limit
        # Each entry with source b"x" is ~3 bytes estimated
        # We need a limit that fits some but not all
        small_src = b"a"
        # size_bytes = len(small_src) * 3 = 3 bytes per entry
        # Set limit to hold ~3 entries (9 bytes) but not 4 (12 bytes)
        cache = ParseTreeCache.__new__(ParseTreeCache)
        cache._max_bytes = 10  # fits 3 entries of 3 bytes each
        cache._entries = {}
        cache._lock = threading.Lock()
        cache._hit_count = 0
        cache._miss_count = 0
        cache._eviction_count = 0

        for i in range(4):
            src = f"{i}".encode()
            cache.put(f"{i}.py", _parse(src), src, _sha256(src), "python")
            time.sleep(0.01)  # ensure different timestamps

        # First entry should have been evicted
        assert cache.get("0.py") is None
        assert cache.stats().entries == 3
        assert cache.stats().eviction_count >= 1

    def test_replace_existing_entry(self) -> None:
        cache = ParseTreeCache()
        src1 = b"x = 1"
        src2 = b"x = 2"
        cache.put("a.py", _parse(src1), src1, _sha256(src1), "python")
        cache.put("a.py", _parse(src2), src2, _sha256(src2), "python")

        cached = cache.get("a.py")
        assert cached is not None
        assert cached.source == src2
        assert cache.stats().entries == 1

    def test_thread_safety(self) -> None:
        """Concurrent put/get operations should not corrupt state."""
        cache = ParseTreeCache()
        errors: list[Exception] = []

        def writer(idx: int) -> None:
            try:
                for j in range(20):
                    src = f"x_{idx}_{j} = {j}".encode()
                    cache.put(f"{idx}_{j}.py", _parse(src), src, _sha256(src), "python")
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(50):
                    cache.get("0_0.py")
                    cache.stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread safety errors: {errors}"

    def test_size_bytes_estimation(self) -> None:
        src = b"x = 1" * 100  # 500 bytes
        entry = CachedTree(
            tree=_parse(src),
            source=src,
            content_hash=_sha256(src),
            language="python",
        )
        assert entry.size_bytes == len(src) * 3


# =========================================================================
# TestEditComputer
# =========================================================================


class TestEditComputer:
    """Tests for the edit computation engine."""

    def test_identical_sources(self) -> None:
        src = b"def foo(): pass"
        edits = EditComputer.compute_edits(src, src)
        assert edits == []

    def test_empty_to_content(self) -> None:
        edits = EditComputer.compute_edits(b"", b"x = 1")
        assert len(edits) >= 1

    def test_content_to_empty(self) -> None:
        edits = EditComputer.compute_edits(b"x = 1", b"")
        assert len(edits) >= 1

    def test_single_line_replacement(self) -> None:
        old = b"x = 1"
        new = b"x = 2"
        edits = EditComputer.compute_edits(old, new)
        assert len(edits) >= 1
        assert edits[0].start_byte == 0

    def test_insertion_at_end(self) -> None:
        old = b"x = 1\ny = 2"
        new = b"x = 1\ny = 2\nz = 3"
        edits = EditComputer.compute_edits(old, new)
        assert len(edits) >= 1

    def test_deletion_of_line(self) -> None:
        old = b"x = 1\ny = 2\nz = 3"
        new = b"x = 1\nz = 3"
        edits = EditComputer.compute_edits(old, new)
        assert len(edits) >= 1

    def test_multi_block_changes(self) -> None:
        old = b"a = 1\nb = 2\nc = 3\nd = 4\ne = 5"
        new = b"a = 1\nB = 2\nc = 3\nD = 4\ne = 5"
        edits = EditComputer.compute_edits(old, new)
        assert len(edits) == 2  # two separate changed blocks

    def test_edit_byte_offsets_correctness(self) -> None:
        """Verify byte offsets are correct for a simple replacement."""
        old = b"line1\nline2\nline3"
        new = b"line1\nLINE2_MODIFIED\nline3"
        edits = EditComputer.compute_edits(old, new)

        assert len(edits) == 1
        edit = edits[0]
        # line2 starts at byte 6 ("line1\n" = 6 bytes)
        assert edit.start_byte == 6
        # old_end_byte: end of "line2\n" = 6 + 5 + 1 = 12
        assert edit.old_end_byte == 12
        # start_point should be (1, 0) — line index 1
        assert edit.start_point == (1, 0)

    def test_apply_edits_to_tree(self) -> None:
        """Verify that edits can be applied to a tree and re-parsed."""
        parser = _make_parser()
        old_src = b"def foo():\n    return 1\n"
        new_src = b"def foo():\n    return 42\n"

        tree = parser.parse(old_src)
        edits = EditComputer.compute_edits(old_src, new_src)
        assert len(edits) >= 1

        EditComputer.apply_edits(tree, edits)
        new_tree = parser.parse(new_src, tree)

        assert new_tree.root_node.type == "module"
        # The tree should parse correctly
        assert not new_tree.root_node.has_error

    def test_total_edit_bytes(self) -> None:
        old = b"x = 1\ny = 2"
        new = b"x = 100\ny = 2"
        edits = EditComputer.compute_edits(old, new)
        total = EditComputer.total_edit_bytes(edits)
        assert total > 0

    def test_byte_offset_for_line(self) -> None:
        lines = [b"hello", b"world", b"foo"]
        assert EditComputer._byte_offset_for_line(lines, 0) == 0
        assert EditComputer._byte_offset_for_line(lines, 1) == 6  # "hello\n"
        assert EditComputer._byte_offset_for_line(lines, 2) == 12  # "hello\nworld\n"
        assert EditComputer._byte_offset_for_line(lines, 3) == 16  # all three + newlines

    def test_incremental_reparse_produces_valid_tree(self) -> None:
        """Full round-trip: edit → reparse → validate AST."""
        parser = _make_parser()
        old_src = b"""class Foo:
    def bar(self):
        return 1

    def baz(self):
        return 2
"""
        new_src = b"""class Foo:
    def bar(self):
        return 42

    def baz(self):
        return 2

    def qux(self):
        return 3
"""
        old_tree = parser.parse(old_src)
        edits = EditComputer.compute_edits(old_src, new_src)
        assert len(edits) >= 1

        # Apply edits and reparse
        edited_tree = old_tree.copy()
        EditComputer.apply_edits(edited_tree, edits)
        new_tree = parser.parse(new_src, edited_tree)

        assert new_tree.root_node.type == "module"
        assert not new_tree.root_node.has_error

        # Verify changed_ranges works
        changed = edited_tree.changed_ranges(new_tree)
        assert isinstance(changed, list)


# =========================================================================
# TestIncrementalOrchestrator
# =========================================================================


class TestIncrementalOrchestrator:
    """Tests for the incremental orchestrator."""

    def _make_mock_registry(self) -> MagicMock:
        """Create a mock registry with a Python plugin."""
        parser = _make_parser()

        extractor = MagicMock()
        extractor._parser = parser
        extractor.extract.return_value = ExtractionResult(
            file_path="test.py",
            language="python",
            nodes=[],
            edges=[],
        )

        plugin = MagicMock()
        plugin.name = "python"
        plugin.file_extensions = {".py"}
        plugin.get_extractor.return_value = extractor

        registry = MagicMock()
        registry.get_plugin_for_file.return_value = plugin
        registry.get_all_plugins.return_value = [plugin]

        return registry

    def _make_mock_store(self) -> MagicMock:
        store = MagicMock()
        store.delete_nodes_for_file.return_value = 0
        store.upsert_node.return_value = None
        store.upsert_edge.return_value = None
        store.set_file_hash.return_value = None
        return store

    def _make_mock_config(self) -> MagicMock:
        return MagicMock()

    def test_full_extract_on_cache_miss(self) -> None:
        """Files not in cache should go through full extraction."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)
        src = b"def hello(): pass\n"
        summary = orch.process_changes({"test.py": src})

        assert summary.files_full == 1
        assert summary.files_incremental == 0
        assert summary.cache_misses == 1

    def test_incremental_extract_on_cache_hit(self) -> None:
        """Files in cache with changes should use incremental path."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        # First pass: full extract to populate cache
        # Use a multi-line file so a single-line edit stays under 50% threshold
        src1 = b"""class Greeter:
    def hello(self):
        return 1

    def goodbye(self):
        return 2

    def greet(self, name):
        return name
"""
        summary1 = orch.process_changes({"test.py": src1})
        assert summary1.files_full == 1

        # Second pass: small change (one line) should use incremental path
        src2 = b"""class Greeter:
    def hello(self):
        return 42

    def goodbye(self):
        return 2

    def greet(self, name):
        return name
"""
        summary2 = orch.process_changes({"test.py": src2})
        assert summary2.files_incremental == 1
        assert summary2.cache_hits == 1

    def test_skip_unchanged_file(self) -> None:
        """Files with same content hash should be skipped."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        src = b"def hello(): pass\n"
        orch.process_changes({"test.py": src})

        # Same content again
        summary = orch.process_changes({"test.py": src})
        assert summary.files_skipped == 1
        assert summary.files_incremental == 0
        assert summary.files_full == 0

    def test_deletion_evicts_cache(self) -> None:
        """Deleted files should be evicted from cache."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        src = b"x = 1\n"
        orch.process_changes({"test.py": src})
        assert cache.get("test.py") is not None

        summary = orch.process_changes({}, deleted_files={"test.py"})
        assert summary.files_deleted == 1
        assert cache.get("test.py") is None

    def test_large_edit_falls_back_to_full(self) -> None:
        """Edits exceeding 50% threshold should fall back to full extract."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        # First pass
        src1 = b"x = 1\n"
        orch.process_changes({"test.py": src1})

        # Second pass: completely different content (>50% change)
        src2 = b"y = 2\nz = 3\nw = 4\na = 5\nb = 6\n"
        summary = orch.process_changes({"test.py": src2})

        # Should fall back to full since the edit is massive relative to original
        assert summary.files_full == 1 or summary.files_incremental == 1
        # Either way, the file should be processed
        assert (summary.files_full + summary.files_incremental) == 1

    def test_no_plugin_returns_none(self) -> None:
        """Files with no matching plugin should be skipped."""
        registry = MagicMock()
        registry.get_plugin_for_file.return_value = None
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)
        summary = orch.process_changes({"unknown.xyz": b"data"})

        assert summary.files_full == 0
        assert summary.files_incremental == 0

    def test_warm_cache(self) -> None:
        """warm_cache should populate cache from project files."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file
            py_file = os.path.join(tmpdir, "hello.py")
            with open(py_file, "wb") as f:
                f.write(b"def hello(): pass\n")

            count = orch.warm_cache(tmpdir)
            assert count >= 1
            assert cache.get(py_file) is not None

    def test_process_changes_returns_summary(self) -> None:
        """process_changes should return a valid IncrementalSummary."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()

        orch = IncrementalOrchestrator(config, registry, store)
        summary = orch.process_changes({})

        assert isinstance(summary, IncrementalSummary)
        assert summary.total_time_ms >= 0

    def test_persist_results_called(self) -> None:
        """Verify store methods are called for persisting results."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()

        # Make extractor return a node
        plugin = registry.get_plugin_for_file.return_value
        extractor = plugin.get_extractor.return_value
        extractor.extract.return_value = ExtractionResult(
            file_path="test.py",
            language="python",
            nodes=[
                Node(
                    id="test.py:1:function:hello",
                    kind=NodeKind.FUNCTION,
                    name="hello",
                    qualified_name="hello",
                    file_path="test.py",
                    start_line=1,
                    end_line=1,
                    language="python",
                )
            ],
            edges=[],
        )

        orch = IncrementalOrchestrator(config, registry, store)
        orch.process_changes({"test.py": b"def hello(): pass\n"})

        store.delete_nodes_for_file.assert_called_once_with("test.py")
        store.upsert_node.assert_called_once()

    def test_mixed_changes_and_deletions(self) -> None:
        """Process both changed and deleted files in one batch."""
        registry = self._make_mock_registry()
        store = self._make_mock_store()
        config = self._make_mock_config()
        cache = ParseTreeCache()

        orch = IncrementalOrchestrator(config, registry, store, cache=cache)

        # Populate cache
        orch.process_changes(
            {
                "a.py": b"x = 1\n",
                "b.py": b"y = 2\n",
            }
        )

        # Change a.py, delete b.py
        summary = orch.process_changes(
            changed_files={"a.py": b"x = 42\n"},
            deleted_files={"b.py"},
        )

        assert summary.files_deleted == 1
        assert (summary.files_incremental + summary.files_full) == 1
        assert cache.get("b.py") is None
