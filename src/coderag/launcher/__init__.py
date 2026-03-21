"""Smart Launcher for CodeRAG.

Provides one-command entry point to scan a project and prepare it
for AI coding sessions.
"""

from coderag.launcher.detector import ProjectState, detect_project_state
from coderag.launcher.preloader import build_preload_context
from coderag.launcher.prompt_gen import generate_project_prompt, write_project_prompt
from coderag.launcher.runner import launch_mcp_server, launch_tool
from coderag.launcher.tool_config import detect_ai_tools, write_claude_config, write_codex_config, write_cursor_config

__all__ = [
    "ProjectState",
    "build_preload_context",
    "detect_ai_tools",
    "detect_project_state",
    "generate_project_prompt",
    "launch_mcp_server",
    "launch_tool",
    "write_claude_config",
    "write_codex_config",
    "write_cursor_config",
    "write_project_prompt",
]
