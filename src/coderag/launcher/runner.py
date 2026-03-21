"""Tool launcher and MCP server management for Smart Launcher.

Handles starting the MCP server and launching AI coding tools
as subprocesses with proper lifecycle management.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Track child processes for cleanup
_child_processes: list[subprocess.Popen] = []


def _cleanup_children() -> None:
    """Terminate all tracked child processes."""
    for proc in _child_processes:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
    _child_processes.clear()


# Register cleanup on exit
atexit.register(_cleanup_children)


def launch_mcp_server(
    project_path: str,
    coderag_bin: str | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Start the CodeRAG MCP server in the background.

    Runs `coderag serve <project_path> --watch` as a subprocess
    with stdout/stderr redirected to devnull (server uses stdio transport).

    Args:
        project_path: Path to the project root.
        coderag_bin: Path to coderag binary (auto-detected if None).
        extra_args: Additional arguments to pass to the serve command.

    Returns:
        The Popen process object.

    Raises:
        FileNotFoundError: If coderag binary is not found.
    """
    if coderag_bin is None:
        coderag_bin = shutil.which("coderag")
        if coderag_bin is None:
            raise FileNotFoundError("coderag binary not found on PATH. Install with: pip install coderag")

    cmd = [coderag_bin, "serve", str(Path(project_path).resolve()), "--watch"]
    if extra_args:
        cmd.extend(extra_args)

    logger.info("Starting MCP server: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    _child_processes.append(proc)

    # Give the server a moment to start
    time.sleep(0.5)

    if proc.poll() is not None:
        stderr_output = ""
        if proc.stderr:
            stderr_output = proc.stderr.read().decode(errors="replace")
        raise RuntimeError(f"MCP server exited immediately with code {proc.returncode}. stderr: {stderr_output[:500]}")

    logger.info("MCP server started (PID: %d)", proc.pid)
    return proc


def launch_tool(
    tool_name: str,
    project_path: str,
    prompt: str | None = None,
) -> subprocess.Popen:
    """Launch an AI coding tool.

    Args:
        tool_name: One of "claude-code", "cursor", "codex".
        project_path: Path to the project root.
        prompt: Optional initial prompt to pass to the tool.

    Returns:
        The Popen process object.

    Raises:
        FileNotFoundError: If the tool binary is not found.
        ValueError: If the tool name is not recognized.
    """
    tool_binaries = {
        "claude-code": "claude",
        "claude": "claude",
        "cursor": "cursor",
        "codex": "codex",
    }

    binary_name = tool_binaries.get(tool_name)
    if binary_name is None:
        raise ValueError(f"Unknown tool: {tool_name}. Supported: {', '.join(tool_binaries.keys())}")

    binary_path = shutil.which(binary_name)
    if binary_path is None:
        raise FileNotFoundError(f"{binary_name} not found on PATH. Please install {tool_name} first.")

    cmd = [binary_path]

    # Tool-specific argument handling
    if tool_name in ("claude-code", "claude"):
        if prompt:
            cmd.extend(["--prompt", prompt])
    elif tool_name == "codex":
        if prompt:
            cmd.extend(["--prompt", prompt])
    elif tool_name == "cursor":
        cmd.append(project_path)

    logger.info("Launching %s: %s", tool_name, " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        cwd=project_path,
        stdin=sys.stdin if sys.stdin.isatty() else None,
        stdout=sys.stdout if sys.stdout.isatty() else None,
        stderr=sys.stderr if sys.stderr.isatty() else None,
    )

    _child_processes.append(proc)
    logger.info("%s started (PID: %d)", tool_name, proc.pid)
    return proc


def stop_process(proc: subprocess.Popen, timeout: int = 10) -> int:
    """Gracefully stop a subprocess.

    Args:
        proc: The process to stop.
        timeout: Seconds to wait before force-killing.

    Returns:
        The process exit code.
    """
    if proc.poll() is not None:
        return proc.returncode

    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Process %d did not terminate, killing...", proc.pid)
        proc.kill()
        proc.wait(timeout=5)

    if proc in _child_processes:
        _child_processes.remove(proc)

    return proc.returncode
