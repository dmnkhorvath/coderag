"""Tests for coderag.launcher.runner to push coverage from 19% to 90%+.

Covers: _cleanup_children, launch_mcp_server, launch_tool, stop_process.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from coderag.launcher.runner import (
    _child_processes,
    _cleanup_children,
    launch_mcp_server,
    launch_tool,
    stop_process,
)


@pytest.fixture(autouse=True)
def _clear_children():
    """Ensure _child_processes is clean before/after each test."""
    _child_processes.clear()
    yield
    _child_processes.clear()


# ---------------------------------------------------------------------------
# _cleanup_children
# ---------------------------------------------------------------------------


class TestCleanupChildren:
    def test_cleanup_terminates_running_processes(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None  # still running
        _child_processes.append(proc)
        _cleanup_children()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)
        assert len(_child_processes) == 0

    def test_cleanup_kills_on_timeout(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        _child_processes.append(proc)
        _cleanup_children()
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert len(_child_processes) == 0

    def test_cleanup_handles_oserror_on_terminate(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.terminate.side_effect = OSError("Process gone")
        _child_processes.append(proc)
        _cleanup_children()  # should not raise
        assert len(_child_processes) == 0

    def test_cleanup_handles_oserror_on_kill(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        proc.kill.side_effect = OSError("Already dead")
        _child_processes.append(proc)
        _cleanup_children()  # should not raise
        assert len(_child_processes) == 0

    def test_cleanup_skips_already_exited(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = 0  # already exited
        _child_processes.append(proc)
        _cleanup_children()
        proc.terminate.assert_not_called()
        assert len(_child_processes) == 0

    def test_cleanup_multiple_processes(self):
        procs = []
        for i in range(3):
            p = MagicMock(spec=subprocess.Popen)
            p.poll.return_value = None if i < 2 else 0
            _child_processes.append(p)
            procs.append(p)
        _cleanup_children()
        assert procs[0].terminate.called
        assert procs[1].terminate.called
        assert not procs[2].terminate.called
        assert len(_child_processes) == 0


# ---------------------------------------------------------------------------
# launch_mcp_server
# ---------------------------------------------------------------------------


class TestLaunchMcpServer:
    @patch("coderag.launcher.runner.time.sleep")
    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/coderag")
    def test_launch_auto_detect_binary(self, mock_which, mock_popen, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        result = launch_mcp_server("/tmp/project")
        assert result == mock_proc
        mock_which.assert_called_once_with("coderag")
        assert mock_proc in _child_processes

    @patch("coderag.launcher.runner.time.sleep")
    @patch("coderag.launcher.runner.subprocess.Popen")
    def test_launch_with_explicit_binary(self, mock_popen, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        result = launch_mcp_server("/tmp/project", coderag_bin="/custom/coderag")
        assert result == mock_proc
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/custom/coderag"

    @patch("coderag.launcher.runner.time.sleep")
    @patch("coderag.launcher.runner.subprocess.Popen")
    def test_launch_with_extra_args(self, mock_popen, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        result = launch_mcp_server("/tmp/project", coderag_bin="/usr/bin/coderag", extra_args=["--port", "3001"])
        cmd = mock_popen.call_args[0][0]
        assert "--port" in cmd
        assert "3001" in cmd

    @patch("coderag.launcher.runner.shutil.which", return_value=None)
    def test_launch_binary_not_found(self, mock_which):
        with pytest.raises(FileNotFoundError, match="coderag binary not found"):
            launch_mcp_server("/tmp/project")

    @patch("coderag.launcher.runner.time.sleep")
    @patch("coderag.launcher.runner.subprocess.Popen")
    def test_launch_server_exits_immediately(self, mock_popen, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # exited
        mock_proc.returncode = 1
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"Error: port in use"
        mock_proc.stderr = mock_stderr
        mock_popen.return_value = mock_proc
        with pytest.raises(RuntimeError, match="MCP server exited immediately"):
            launch_mcp_server("/tmp/project", coderag_bin="/usr/bin/coderag")

    @patch("coderag.launcher.runner.time.sleep")
    @patch("coderag.launcher.runner.subprocess.Popen")
    def test_launch_server_exits_no_stderr(self, mock_popen, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mock_proc.stderr = None
        mock_popen.return_value = mock_proc
        with pytest.raises(RuntimeError, match="MCP server exited immediately"):
            launch_mcp_server("/tmp/project", coderag_bin="/usr/bin/coderag")


# ---------------------------------------------------------------------------
# launch_tool
# ---------------------------------------------------------------------------


class TestLaunchTool:
    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/claude")
    def test_launch_claude_code(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        result = launch_tool("claude-code", "/tmp/project")
        assert result == mock_proc
        mock_which.assert_called_once_with("claude")

    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/claude")
    def test_launch_claude_with_prompt(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        launch_tool("claude-code", "/tmp/project", prompt="fix auth")
        cmd = mock_popen.call_args[1].get("args") or mock_popen.call_args[0][0]
        assert "--prompt" in cmd
        assert "fix auth" in cmd

    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/claude")
    def test_launch_claude_alias(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        launch_tool("claude", "/tmp/project", prompt="test")
        cmd = mock_popen.call_args[0][0]
        assert "--prompt" in cmd

    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/codex")
    def test_launch_codex_with_prompt(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        launch_tool("codex", "/tmp/project", prompt="refactor")
        cmd = mock_popen.call_args[0][0]
        assert "--prompt" in cmd
        assert "refactor" in cmd

    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/cursor")
    def test_launch_cursor(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        launch_tool("cursor", "/tmp/project")
        cmd = mock_popen.call_args[0][0]
        assert "/tmp/project" in cmd

    def test_launch_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            launch_tool("unknown-tool", "/tmp/project")

    @patch("coderag.launcher.runner.shutil.which", return_value=None)
    def test_launch_tool_not_found(self, mock_which):
        with pytest.raises(FileNotFoundError, match="not found on PATH"):
            launch_tool("claude-code", "/tmp/project")

    @patch("coderag.launcher.runner.subprocess.Popen")
    @patch("coderag.launcher.runner.shutil.which", return_value="/usr/bin/codex")
    def test_launch_codex_no_prompt(self, mock_which, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_popen.return_value = mock_proc
        launch_tool("codex", "/tmp/project")
        cmd = mock_popen.call_args[0][0]
        assert "--prompt" not in cmd


# ---------------------------------------------------------------------------
# stop_process
# ---------------------------------------------------------------------------


class TestStopProcess:
    def test_stop_already_exited(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = 0
        proc.returncode = 0
        result = stop_process(proc)
        assert result == 0
        proc.terminate.assert_not_called()

    def test_stop_graceful(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.returncode = 0
        _child_processes.append(proc)
        result = stop_process(proc)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=10)
        assert proc not in _child_processes

    def test_stop_force_kill(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.pid = 12345
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="test", timeout=10), None]
        proc.returncode = -9
        _child_processes.append(proc)
        result = stop_process(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert proc not in _child_processes

    def test_stop_custom_timeout(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.returncode = 0
        stop_process(proc, timeout=30)
        proc.wait.assert_called_once_with(timeout=30)

    def test_stop_not_in_child_list(self):
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.returncode = 0
        # proc is NOT in _child_processes
        result = stop_process(proc)
        assert result == 0
