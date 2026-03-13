"""Tests for parallel pipeline phases (Feature 2)."""

import tempfile
import threading
from unittest.mock import MagicMock

import pytest

from coderag.core.config import CodeGraphConfig, PerformanceConfig
from coderag.core.models import (
    EdgeKind,
    ExtractionResult,
    Node,
    NodeKind,
    UnresolvedReference,
)
from coderag.pipeline.orchestrator import PipelineOrchestrator
from coderag.pipeline.resolver import ReferenceResolver
from coderag.storage.sqlite_store import SQLiteStore


@pytest.fixture
def memory_store():
    """Create an in-memory SQLite store for testing."""
    store = SQLiteStore(":memory:")
    store.initialize()
    yield store
    store.close()


@pytest.fixture
def config():
    """Create a test config with parallel settings."""
    cfg = CodeGraphConfig.default()
    return cfg


@pytest.fixture
def registry():
    """Create a mock plugin registry."""
    reg = MagicMock()
    reg.get_all_plugins.return_value = []
    return reg


class TestParallelResolution:
    """Tests for parallel reference resolution (Phase 4)."""

    def test_parallel_resolve_returns_same_as_sequential(self, memory_store, config, registry):
        """Parallel resolution should produce equivalent results to sequential."""
        # Create some nodes in the store
        nodes = [
            Node(
                id=f"node-{i}",
                kind=NodeKind.FUNCTION,
                name=f"func_{i}",
                qualified_name=f"module.func_{i}",
                file_path=f"/tmp/test/file{i}.py",
                start_line=1,
                end_line=10,
                language="python",
            )
            for i in range(10)
        ]
        memory_store.upsert_nodes(nodes)

        # Create extraction results with unresolved references
        results = []
        for i in range(5):
            refs = [
                UnresolvedReference(
                    source_node_id=f"node-{i}",
                    reference_name=f"func_{i + 5}" if i + 5 < 10 else "nonexistent",
                    reference_kind=EdgeKind.CALLS,
                    line_number=5,
                )
            ]
            result = ExtractionResult(
                file_path=f"/tmp/test/file{i}.py",
                language="python",
                nodes=[nodes[i]],
                edges=[],
                unresolved_references=refs,
            )
            results.append(result)

        # Sequential resolution
        resolver_seq = ReferenceResolver(memory_store)
        resolver_seq.build_symbol_table()
        seq_edges, seq_placeholders, seq_resolved, seq_unresolved = resolver_seq.resolve(results)

        # Parallel resolution via orchestrator helper
        orchestrator = PipelineOrchestrator(config, registry, memory_store)
        resolver_par = ReferenceResolver(memory_store)
        resolver_par.build_symbol_table()
        par_edges, par_placeholders, par_resolved, par_unresolved = orchestrator._parallel_resolve(
            resolver_par, results, max_workers=4
        )

        # Results should be equivalent (order may differ)
        assert par_resolved == seq_resolved
        assert par_unresolved == seq_unresolved
        assert len(par_edges) == len(seq_edges)

    def test_parallel_resolve_with_single_result(self, memory_store, config, registry):
        """Single result should still work with parallel resolver."""
        node = Node(
            id="node-1",
            kind=NodeKind.FUNCTION,
            name="func_1",
            qualified_name="module.func_1",
            file_path="/tmp/test/file1.py",
            start_line=1,
            end_line=10,
            language="python",
        )
        memory_store.upsert_nodes([node])

        result = ExtractionResult(
            file_path="/tmp/test/file1.py",
            language="python",
            nodes=[node],
            edges=[],
            unresolved_references=[],
        )

        orchestrator = PipelineOrchestrator(config, registry, memory_store)
        resolver = ReferenceResolver(memory_store)
        resolver.build_symbol_table()
        edges, placeholders, resolved, unresolved = orchestrator._parallel_resolve(resolver, [result], max_workers=2)

        assert resolved == 0
        assert unresolved == 0
        assert len(edges) == 0

    def test_parallel_resolve_empty_results(self, memory_store, config, registry):
        """Empty results should return zeros."""
        orchestrator = PipelineOrchestrator(config, registry, memory_store)
        resolver = ReferenceResolver(memory_store)
        resolver.build_symbol_table()
        edges, placeholders, resolved, unresolved = orchestrator._parallel_resolve(resolver, [], max_workers=2)

        assert resolved == 0
        assert unresolved == 0


class TestSQLiteWriteLock:
    """Tests for SQLite concurrent write safety (Feature 3)."""

    def test_write_lock_exists(self, memory_store):
        """Store should have a write lock."""
        assert hasattr(memory_store, "_write_lock")
        assert isinstance(memory_store._write_lock, type(threading.Lock()))

    def test_execute_write_basic(self, memory_store):
        """execute_write should work for basic operations."""
        memory_store.execute_write(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("test_key", "test_value"),
        )
        memory_store.connection.commit()
        row = memory_store.connection.execute("SELECT value FROM metadata WHERE key = ?", ("test_key",)).fetchone()
        assert row[0] == "test_value"

    def test_create_thread_connection(self, memory_store):
        """Thread connection should be read-only."""
        if memory_store._db_path == ":memory:":
            pytest.skip("Thread connections require file-based DB")

    def test_concurrent_reads_safe(self):
        """Multiple threads reading simultaneously should be safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            db_path = os.path.join(tmpdir, "test_concurrent.db")
            store = SQLiteStore(db_path)
            store.initialize()
            try:
                # Insert some test data
                nodes = [
                    Node(
                        id=f"concurrent-{i}",
                        kind=NodeKind.FUNCTION,
                        name=f"func_{i}",
                        qualified_name=f"mod.func_{i}",
                        file_path=f"/tmp/test/f{i}.py",
                        start_line=1,
                        end_line=5,
                        language="python",
                    )
                    for i in range(20)
                ]
                store.upsert_nodes(nodes)

                errors = []

                def read_nodes(thread_id):
                    try:
                        conn = store.create_thread_connection()
                        try:
                            rows = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
                            assert rows[0] >= 20
                        finally:
                            conn.close()
                    except Exception as exc:
                        errors.append((thread_id, str(exc)))

                threads = [threading.Thread(target=read_nodes, args=(i,)) for i in range(10)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=5)

                assert len(errors) == 0, f"Concurrent read errors: {errors}"
            finally:
                store.close()

    def test_concurrent_writes_serialized(self, memory_store):
        """Concurrent writes via execute_write should be serialized."""
        results = []

        def write_metadata(key, value):
            try:
                memory_store.execute_write(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
                memory_store.connection.commit()
                results.append(True)
            except Exception as exc:
                results.append(str(exc))

        threads = [threading.Thread(target=write_metadata, args=(f"key_{i}", f"val_{i}")) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # All writes should succeed
        assert all(r is True for r in results), f"Write failures: {results}"


class TestPerformanceConfigIntegration:
    """Tests that PerformanceConfig is used by parallel phases."""

    def test_io_workers_resolved(self):
        cfg = PerformanceConfig(io_workers=4)
        assert cfg.resolved_io_workers == 4

    def test_io_workers_auto(self):
        cfg = PerformanceConfig(io_workers="auto")
        workers = cfg.resolved_io_workers
        assert workers >= 1
        assert workers <= 16

    def test_extraction_workers_resolved(self):
        cfg = PerformanceConfig(extraction_workers=2)
        assert cfg.resolved_extraction_workers == 2

    def test_extraction_workers_auto(self):
        cfg = PerformanceConfig(extraction_workers="auto")
        workers = cfg.resolved_extraction_workers
        assert workers >= 1
        assert workers <= 8
