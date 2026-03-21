"""AI tool configuration writers for Smart Launcher.

Detects installed AI coding tools and writes their configuration
files to integrate with CodeRAG's MCP server.
"""

from __future__ import annotations

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)


def detect_ai_tools() -> list[str]:
    """Detect AI coding tools available on PATH.

    Returns:
        List of tool names found (e.g., ["claude", "cursor"]).
    """
    tools: list[str] = []
    tool_binaries = {
        "claude": "claude",
        "cursor": "cursor",
        "codex": "codex",
    }
    for name, binary in tool_binaries.items():
        if shutil.which(binary) is not None:
            tools.append(name)
    return tools


def _find_coderag_bin() -> str:
    """Find the coderag binary path."""
    found = shutil.which("coderag")
    if found:
        return found
    return "coderag"  # Fallback to bare name


def write_claude_config(
    project_path: str,
    coderag_bin: str | None = None,
) -> str:
    """Write .claude/settings.local.json for Claude Code integration.

    Args:
        project_path: Path to the project root.
        coderag_bin: Path to coderag binary (auto-detected if None).

    Returns:
        Path to the written config file.
    """
    if coderag_bin is None:
        coderag_bin = _find_coderag_bin()

    config_dir = os.path.join(project_path, ".claude")
    config_path = os.path.join(config_dir, "settings.local.json")

    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    # Ensure mcpServers section exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["coderag"] = {
        "command": coderag_bin,
        "args": ["serve", project_path, "--watch"],
    }

    os.makedirs(config_dir, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    logger.info("Wrote Claude config: %s", config_path)
    return config_path


def write_cursor_config(
    project_path: str,
    coderag_bin: str | None = None,
) -> str:
    """Write .cursor/mcp.json for Cursor integration.

    Args:
        project_path: Path to the project root.
        coderag_bin: Path to coderag binary (auto-detected if None).

    Returns:
        Path to the written config file.
    """
    if coderag_bin is None:
        coderag_bin = _find_coderag_bin()

    config_dir = os.path.join(project_path, ".cursor")
    config_path = os.path.join(config_dir, "mcp.json")

    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["coderag"] = {
        "command": coderag_bin,
        "args": ["serve", project_path, "--watch"],
    }

    os.makedirs(config_dir, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    logger.info("Wrote Cursor config: %s", config_path)
    return config_path


def write_codex_config(
    project_path: str,
    coderag_bin: str | None = None,
) -> str:
    """Write codex.json for Codex integration.

    Args:
        project_path: Path to the project root.
        coderag_bin: Path to coderag binary (auto-detected if None).

    Returns:
        Path to the written config file.
    """
    if coderag_bin is None:
        coderag_bin = _find_coderag_bin()

    config_path = os.path.join(project_path, "codex.json")

    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["coderag"] = {
        "command": coderag_bin,
        "args": ["serve", project_path, "--watch"],
    }

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    logger.info("Wrote Codex config: %s", config_path)
    return config_path


def write_tool_config(
    tool_name: str,
    project_path: str,
    coderag_bin: str | None = None,
) -> str | None:
    """Write config for a specific AI tool.

    Args:
        tool_name: One of "claude", "cursor", "codex".
        project_path: Path to the project root.
        coderag_bin: Path to coderag binary.

    Returns:
        Path to the written config file, or None if tool unknown.
    """
    writers = {
        "claude": write_claude_config,
        "cursor": write_cursor_config,
        "codex": write_codex_config,
    }
    writer = writers.get(tool_name)
    if writer is None:
        logger.warning("Unknown AI tool: %s", tool_name)
        return None
    return writer(project_path, coderag_bin)
