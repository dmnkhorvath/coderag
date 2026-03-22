"""Targeted tests to boost MCP server coverage from 56% to 95%+.

Covers uncovered lines: 61-62, 72-73, 100, 114-115, 176-184,
211-249, 254-259, 282-316.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: mock SQLiteStore and NetworkXAnalyzer
# ---------------------------------------------------------------------------


def _mock_store():
    store = MagicMock()
    store.initialize.return_value = None
    store.close.return_value = None
    store.get_summary.return_value = MagicMock(project_name="test-project")
    return store


def _mock_analyzer():
    analyzer = MagicMock()
    analyzer.load_from_store.return_value = None
    analyzer.get_statistics.return_value = {"node_count": 10, "edge_count": 20}
    return analyzer


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
_STORE_CLS = "coderag.mcp.server.SQLiteStore"
_ANALYZER_CLS = "coderag.mcp.server.NetworkXAnalyzer"
_REG_TOOLS = "coderag.mcp.server.register_tools"
_REG_RESOURCES = "coderag.mcp.server.register_resources"


# ═══════════════════════════════════════════════════════════════════════
# Tests for GraphContext
# ═══════════════════════════════════════════════════════════════════════


class TestGraphContext:
    """Test GraphContext load, reload, and error paths."""

    def test_basic_load(self, tmp_path):
        """GraphContext loads store and analyzer on init."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with (
            patch(_STORE_CLS, return_value=_mock_store()) as mock_s,
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()) as mock_a,
        ):
            ctx = GraphContext(str(db_file))
            assert ctx._load_count == 1
            mock_s.return_value.initialize.assert_called_once()
            mock_a.return_value.load_from_store.assert_called_once()

    def test_store_close_exception_on_reload(self, tmp_path):
        """Lines 61-62: exception in store.close() during reload is swallowed."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        store1 = _mock_store()
        store1.close.side_effect = RuntimeError("close failed")
        store2 = _mock_store()

        stores = [store1, store2]
        call_count = [0]

        def store_factory(path):
            idx = min(call_count[0], len(stores) - 1)
            call_count[0] += 1
            return stores[idx]

        with patch(_STORE_CLS, side_effect=store_factory), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            assert ctx._load_count == 1
            # Reload triggers close on store1 which raises
            ctx.load()
            assert ctx._load_count == 2

    def test_os_error_getting_mtime(self, tmp_path):
        """Lines 72-73: OSError getting mtime sets _last_mtime to 0.0."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch("os.path.getmtime", side_effect=OSError("no file")),
        ):
            ctx = GraphContext(str(db_file))
            assert ctx._last_mtime == 0.0

    def test_db_path_property(self, tmp_path):
        """Line 100: db_path property returns the path."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            assert ctx.db_path == str(db_file)

    def test_check_and_reload_os_error(self, tmp_path):
        """Lines 114-115: OSError in check_and_reload returns False."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))

        with patch("os.path.getmtime", side_effect=OSError("gone")):
            assert ctx.check_and_reload() is False

    def test_check_and_reload_triggers_reload(self, tmp_path):
        """check_and_reload reloads when mtime increases."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            old_count = ctx._load_count

        # Simulate mtime increase
        with (
            patch("os.path.getmtime", return_value=ctx._last_mtime + 100),
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
        ):
            result = ctx.check_and_reload()
            assert result is True
            assert ctx._load_count == old_count + 1

    def test_check_and_reload_no_change(self, tmp_path):
        """check_and_reload returns False when mtime unchanged."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))

        with patch("os.path.getmtime", return_value=ctx._last_mtime):
            assert ctx.check_and_reload() is False

    def test_close(self, tmp_path):
        """close() closes the store."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()
        mock_s = _mock_store()

        with patch(_STORE_CLS, return_value=mock_s), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            ctx.close()
            mock_s.close.assert_called()
            assert ctx._store is None

    def test_store_property(self, tmp_path):
        """store property returns the store."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()
        mock_s = _mock_store()

        with patch(_STORE_CLS, return_value=mock_s), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            assert ctx.store is mock_s

    def test_analyzer_property(self, tmp_path):
        """analyzer property returns the analyzer."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()
        mock_a = _mock_analyzer()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=mock_a):
            ctx = GraphContext(str(db_file))
            assert ctx.analyzer is mock_a

    # ═══════════════════════════════════════════════════════════════════════

    def test_last_mtime_property(self, tmp_path):
        """Line 104: last_mtime property returns the mtime."""
        from coderag.mcp.server import GraphContext

        db_file = tmp_path / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            # Access the property (not the private attribute)
            mtime = ctx.last_mtime
            assert isinstance(mtime, float)
            assert mtime > 0


# Tests for _StoreProxy and _AnalyzerProxy
# ═══════════════════════════════════════════════════════════════════════


class TestProxies:
    """Test proxy objects delegate to current context."""

    def test_store_proxy_delegates(self, tmp_path):
        from coderag.mcp.server import GraphContext, _StoreProxy

        db_file = tmp_path / "graph.db"
        db_file.touch()
        mock_s = _mock_store()
        mock_s.some_method.return_value = "result"

        with patch(_STORE_CLS, return_value=mock_s), patch(_ANALYZER_CLS, return_value=_mock_analyzer()):
            ctx = GraphContext(str(db_file))
            proxy = _StoreProxy(ctx)
            assert proxy.some_method() == "result"

    def test_analyzer_proxy_delegates(self, tmp_path):
        from coderag.mcp.server import GraphContext, _AnalyzerProxy

        db_file = tmp_path / "graph.db"
        db_file.touch()
        mock_a = _mock_analyzer()
        mock_a.some_method.return_value = 42

        with patch(_STORE_CLS, return_value=_mock_store()), patch(_ANALYZER_CLS, return_value=mock_a):
            ctx = GraphContext(str(db_file))
            proxy = _AnalyzerProxy(ctx)
            assert proxy.some_method() == 42


# ═══════════════════════════════════════════════════════════════════════
# Tests for _find_db_path (lines 176-184)
# ═══════════════════════════════════════════════════════════════════════


class TestFindDbPath:
    """Test _find_db_path function."""

    def test_explicit_db_path_exists(self, tmp_path):
        """Line 176-177: explicit db_path that exists."""
        from coderag.mcp.server import _find_db_path

        db_file = tmp_path / "custom.db"
        db_file.touch()
        result = _find_db_path(str(tmp_path), str(db_file))
        assert result == db_file

    def test_explicit_db_path_missing(self, tmp_path):
        """Lines 181-183: explicit db_path that doesn't exist."""
        from coderag.mcp.server import _find_db_path

        with pytest.raises(FileNotFoundError, match="Graph database not found"):
            _find_db_path(str(tmp_path), str(tmp_path / "nonexistent.db"))

    def test_default_db_path_exists(self, tmp_path):
        """Lines 178-179: default db path."""
        from coderag.mcp.server import _find_db_path

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()
        result = _find_db_path(str(tmp_path))
        assert result == db_file

    def test_default_db_path_missing(self, tmp_path):
        """Lines 181-183: default db path doesn't exist."""
        from coderag.mcp.server import _find_db_path

        with pytest.raises(FileNotFoundError, match="Graph database not found"):
            _find_db_path(str(tmp_path))


# ═══════════════════════════════════════════════════════════════════════
# Tests for create_server (lines 211-249)
# ═══════════════════════════════════════════════════════════════════════


class TestCreateServer:
    """Test create_server function."""

    def test_create_server_basic(self, tmp_path):
        """Lines 211-249: basic server creation."""
        from coderag.mcp.server import create_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS) as mock_rt,
            patch(_REG_RESOURCES) as mock_rr,
        ):
            mcp, ctx = create_server(str(tmp_path))
            assert mcp is not None
            assert ctx is not None
            mock_rt.assert_called_once()
            mock_rr.assert_called_once()
            ctx.close()

    def test_create_server_hot_reload(self, tmp_path):
        """Lines 217-219: hot_reload uses proxy objects."""
        from coderag.mcp.server import _AnalyzerProxy, _StoreProxy, create_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS) as mock_rt,
            patch(_REG_RESOURCES) as mock_rr,
        ):
            mcp, ctx = create_server(str(tmp_path), hot_reload=True)
            # Check that proxies were passed to register_tools/resources
            store_arg = mock_rt.call_args[0][1]
            analyzer_arg = mock_rt.call_args[0][2]
            assert isinstance(store_arg, _StoreProxy)
            assert isinstance(analyzer_arg, _AnalyzerProxy)
            ctx.close()

    def test_create_server_no_hot_reload(self, tmp_path):
        """Lines 220-222: no hot_reload uses direct references."""
        from coderag.mcp.server import _StoreProxy, create_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()
        mock_s = _mock_store()

        with (
            patch(_STORE_CLS, return_value=mock_s),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS) as mock_rt,
            patch(_REG_RESOURCES),
        ):
            mcp, ctx = create_server(str(tmp_path), hot_reload=False)
            store_arg = mock_rt.call_args[0][1]
            assert not isinstance(store_arg, _StoreProxy)
            ctx.close()

    def test_create_server_explicit_db_path(self, tmp_path):
        """create_server with explicit db_path."""
        from coderag.mcp.server import create_server

        db_file = tmp_path / "custom.db"
        db_file.touch()

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS),
            patch(_REG_RESOURCES),
        ):
            mcp, ctx = create_server(str(tmp_path), db_path=str(db_file))
            assert ctx.db_path == str(db_file)
            ctx.close()

    def test_create_server_summary_exception(self, tmp_path):
        """Lines 228-229: exception getting summary falls back to dir name."""
        from coderag.mcp.server import create_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        mock_s = _mock_store()
        mock_s.get_summary.side_effect = RuntimeError("no summary")

        with (
            patch(_STORE_CLS, return_value=mock_s),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS),
            patch(_REG_RESOURCES),
        ):
            mcp, ctx = create_server(str(tmp_path))
            # Should not raise, falls back to dir name
            assert mcp is not None
            ctx.close()


# ═══════════════════════════════════════════════════════════════════════
# Tests for _hot_reload_watcher (lines 254-259)
# ═══════════════════════════════════════════════════════════════════════


class TestHotReloadWatcher:
    """Test _hot_reload_watcher async function."""

    def test_watcher_calls_check_and_reload(self, tmp_path):
        """Lines 254-259: watcher polls check_and_reload."""
        from coderag.mcp.server import _hot_reload_watcher

        mock_ctx = MagicMock()
        mock_ctx.check_and_reload.return_value = False

        iteration = [0]
        original_sleep = asyncio.sleep

        async def fake_sleep(interval):
            iteration[0] += 1
            if iteration[0] >= 2:
                raise asyncio.CancelledError()
            await original_sleep(0)  # yield control

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                try:
                    await _hot_reload_watcher(mock_ctx, 0.01)
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        assert mock_ctx.check_and_reload.call_count >= 1

    def test_watcher_handles_exception(self, tmp_path):
        """Lines 258-259: exception during reload is caught."""
        from coderag.mcp.server import _hot_reload_watcher

        mock_ctx = MagicMock()
        mock_ctx.check_and_reload.side_effect = RuntimeError("reload failed")

        iteration = [0]

        async def fake_sleep(interval):
            iteration[0] += 1
            if iteration[0] >= 2:
                raise asyncio.CancelledError()

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                try:
                    await _hot_reload_watcher(mock_ctx, 0.01)
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())
        # Should not raise, exception is caught
        assert mock_ctx.check_and_reload.call_count >= 1


# ═══════════════════════════════════════════════════════════════════════
# Tests for run_stdio_server (lines 282-316)
# ═══════════════════════════════════════════════════════════════════════


class TestRunStdioServer:
    """Test run_stdio_server function."""

    def test_run_stdio_server_file_not_found(self, tmp_path, capsys):
        """Lines 289-291: FileNotFoundError exits with code 1."""
        from coderag.mcp.server import run_stdio_server

        with pytest.raises(SystemExit) as exc_info:
            run_stdio_server(str(tmp_path))
        assert exc_info.value.code == 1

    def test_run_stdio_server_generic_exception(self, tmp_path):
        """Lines 292-294: generic exception exits with code 1."""
        from coderag.mcp.server import run_stdio_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        with patch(_STORE_CLS, side_effect=RuntimeError("init failed")), pytest.raises(SystemExit) as exc_info:
            run_stdio_server(str(tmp_path))
        assert exc_info.value.code == 1

    def test_run_stdio_server_success_no_hot_reload(self, tmp_path):
        """Lines 282-316: successful run without hot_reload."""
        from coderag.mcp.server import run_stdio_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        mock_mcp = MagicMock()

        async def _fake_run():
            pass

        mock_mcp.run_stdio_async = _fake_run

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS),
            patch(_REG_RESOURCES),
            patch("coderag.mcp.server.FastMCP", return_value=mock_mcp),
        ):
            run_stdio_server(str(tmp_path), hot_reload=False)

    def test_run_stdio_server_with_hot_reload(self, tmp_path):
        """Lines 301-310: run with hot_reload enabled."""
        from coderag.mcp.server import run_stdio_server

        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        db_file = db_dir / "graph.db"
        db_file.touch()

        mock_mcp = MagicMock()

        async def fake_run_stdio():
            pass

        mock_mcp.run_stdio_async = fake_run_stdio

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS),
            patch(_REG_RESOURCES),
            patch("coderag.mcp.server.FastMCP", return_value=mock_mcp),
        ):
            run_stdio_server(str(tmp_path), hot_reload=True)

    def test_run_stdio_server_with_explicit_db_path(self, tmp_path):
        """Lines 284-285: explicit db_path printed to stderr."""
        from coderag.mcp.server import run_stdio_server

        db_file = tmp_path / "custom.db"
        db_file.touch()

        mock_mcp = MagicMock()

        async def fake_run_stdio():
            pass

        mock_mcp.run_stdio_async = fake_run_stdio

        with (
            patch(_STORE_CLS, return_value=_mock_store()),
            patch(_ANALYZER_CLS, return_value=_mock_analyzer()),
            patch(_REG_TOOLS),
            patch(_REG_RESOURCES),
            patch("coderag.mcp.server.FastMCP", return_value=mock_mcp),
        ):
            run_stdio_server(str(tmp_path), db_path=str(db_file), hot_reload=False)
