"""Smart Launcher CLI command for CodeRAG.

Provides the `coderag launch` command that detects project state,
builds context, configures AI tools, and launches coding sessions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


def _load_config_for_launch(project_path: str, config_path: str | None = None):
    """Load config for the launch command."""
    from coderag.core.config import CodeGraphConfig

    if config_path and os.path.isfile(config_path):
        cfg = CodeGraphConfig.from_yaml(config_path)
        cfg.project_root = str(Path(project_path).resolve())
        return cfg

    # Try common locations
    for name in ("codegraph.yaml", "codegraph.yml", ".codegraph.yaml"):
        candidate = os.path.join(project_path, name)
        if os.path.isfile(candidate):
            cfg = CodeGraphConfig.from_yaml(candidate)
            cfg.project_root = str(Path(project_path).resolve())
            return cfg

    # Fall back to defaults
    cfg = CodeGraphConfig.default()
    cfg.project_root = str(Path(project_path).resolve())
    cfg.project_name = Path(project_path).name
    return cfg


def _open_store_for_launch(config):
    """Open an existing SQLite store."""
    from coderag.storage.sqlite_store import SQLiteStore

    db_path = config.db_path_absolute
    if not os.path.isfile(db_path):
        return None
    store = SQLiteStore(db_path)
    store.initialize()
    return store


def _run_parse(project_path: str, config_path: str | None = None) -> bool:
    """Run coderag parse on the project."""
    import shutil
    import subprocess

    coderag_bin = shutil.which("coderag")
    if coderag_bin is None:
        # Try running as module
        cmd = [sys.executable, "-m", "coderag.cli.main", "parse", project_path]
    else:
        cmd = [coderag_bin, "parse", project_path]

    if config_path:
        cmd.extend(["--config", config_path])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        console.print(f"[red]Parse failed:[/red] {exc}")
        return False


def _detect_best_tool() -> str | None:
    """Auto-detect the best available AI tool."""
    from coderag.launcher.tool_config import detect_ai_tools

    tools = detect_ai_tools()
    # Preference order
    for preferred in ["claude", "cursor", "codex"]:
        if preferred in tools:
            return preferred
    return None


def _check_for_updates_on_launch() -> None:
    """Non-blocking update check on launch."""
    try:
        from coderag.updater.checker import UpdateChecker
        from coderag.updater.config import UpdateConfig

        config = UpdateConfig.load()
        if not config.auto_check:
            return

        checker = UpdateChecker(config)
        info = checker.check()  # Uses cache, fast

        if info and info.update_available:
            from rich.console import Console as _Console

            _console = _Console(stderr=True)
            _console.print(
                f"[yellow]⬆ CodeRAG v{info.latest} available "
                f"(current: v{info.current}). "
                f"Run: coderag update install[/yellow]"
            )

            if config.auto_install:
                from coderag.updater.installer import UpdateInstaller

                installer = UpdateInstaller()
                result = installer.install()
                if result.success:
                    _console.print(f"[green]✅ Auto-updated to v{result.new_version}[/green]")
    except Exception:  # noqa: BLE001
        pass  # Never block launch


@click.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.argument("prompt", required=False)
@click.option(
    "--tool",
    type=click.Choice(["claude-code", "cursor", "codex", "auto"]),
    default="auto",
    help="AI tool to launch (default: auto-detect).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would happen without launching.",
)
@click.option(
    "--context-only",
    is_flag=True,
    help="Output pre-loaded context to stdout and exit.",
)
@click.option(
    "--token-budget",
    default=8000,
    type=int,
    help="Token budget for context pre-loading.",
)
@click.pass_context
def launch(
    ctx: click.Context,
    path: str,
    prompt: str | None,
    tool: str,
    dry_run: bool,
    context_only: bool,
    token_budget: int,
) -> None:
    """Launch an AI coding session with CodeRAG context.

    Detects project state, parses if needed, builds context,
    configures AI tools, and launches the coding session.

    PATH is the project root directory (default: current directory).
    PROMPT is an optional initial prompt for the AI tool.
    """
    from coderag.launcher.detector import ProjectState, detect_project_state
    from coderag.launcher.preloader import build_preload_context
    from coderag.launcher.prompt_gen import generate_project_prompt, write_project_prompt
    from coderag.launcher.tool_config import write_tool_config

    project_path = str(Path(path).resolve())
    config_path = ctx.obj.get("config_path") if ctx.obj else None

    # Step 1: Detect project state
    console.print("[bold cyan]CodeRAG Smart Launcher[/bold cyan]\n")
    _check_for_updates_on_launch()
    console.print(f"Project: [bold]{project_path}[/bold]")

    state_info = detect_project_state(project_path)
    console.print(f"State: [bold]{state_info.state.value}[/bold] ({state_info.source_file_count} source files)")

    # Step 2: Parse if needed
    if state_info.state in (ProjectState.FRESH, ProjectState.STALE):
        if state_info.state == ProjectState.FRESH:
            console.print("\n[yellow]No knowledge graph found. Parsing project...[/yellow]")
        else:
            stale_count = len(state_info.stale_files)
            console.print(f"\n[yellow]Graph is stale ({stale_count} files changed). Re-parsing...[/yellow]")

        if not dry_run:
            with console.status("[bold cyan]Parsing project..."):
                success = _run_parse(project_path, config_path)
            if success:
                console.print("[green]\u2713[/green] Parse complete")
            else:
                console.print("[red]\u2717[/red] Parse failed. Run 'coderag parse' manually.")
                if not context_only:
                    raise SystemExit(1)
        else:
            console.print("  [dim](dry-run: would parse project)[/dim]")

    # Step 3: Load config and store
    config = _load_config_for_launch(project_path, config_path)
    store = _open_store_for_launch(config)

    if store is None:
        if context_only or dry_run:
            console.print("[yellow]No database found. Context unavailable.[/yellow]")
            if context_only:
                click.echo("# No CodeRAG database found\n\nRun `coderag parse` first.")
            return
        console.print("[red]No database found after parse attempt.[/red]")
        raise SystemExit(1)

    try:
        # Step 4: Build context pre-load
        with console.status("[bold cyan]Building context..."):
            context = build_preload_context(store, config, query=prompt, token_budget=token_budget)

        if context_only:
            click.echo(context)
            return

        console.print(f"[green]\u2713[/green] Context built ({len(context)} chars, ~{len(context) // 4} tokens)")

        # Step 5: Generate CLAUDE.md
        with console.status("[bold cyan]Generating project prompt..."):
            prompt_content = generate_project_prompt(store, config)
            prompt_path = write_project_prompt(project_path, prompt_content)
        console.print(f"[green]\u2713[/green] Wrote {os.path.basename(prompt_path)}")

        # Step 6: Write AI tool config
        selected_tool = tool
        if selected_tool == "auto":
            detected = _detect_best_tool()
            if detected:
                selected_tool = detected
                console.print(f"[green]\u2713[/green] Detected AI tool: [bold]{selected_tool}[/bold]")
            else:
                console.print("[yellow]No AI tool detected on PATH[/yellow]")
                selected_tool = None

        if selected_tool:
            tool_for_config = "claude" if selected_tool == "claude-code" else selected_tool
            config_written = write_tool_config(tool_for_config, project_path)
            if config_written:
                console.print(
                    f"[green]\u2713[/green] Wrote tool config: {os.path.relpath(config_written, project_path)}"
                )

        # Step 7: Dry run summary
        if dry_run:
            console.print()
            summary_lines = [
                f"Project: {project_path}",
                f"State: {state_info.state.value}",
                f"Source files: {state_info.source_file_count}",
                f"Context size: {len(context)} chars (~{len(context) // 4} tokens)",
                f"CLAUDE.md: {prompt_path}",
                f"AI tool: {selected_tool or 'none detected'}",
            ]
            if prompt:
                summary_lines.append(f"Prompt: {prompt}")
            console.print(
                Panel(
                    "\n".join(summary_lines),
                    title="[bold]Dry Run Summary[/bold]",
                    border_style="cyan",
                )
            )
            return

        # Step 8: Launch MCP server + AI tool
        if selected_tool:
            from coderag.launcher.runner import launch_mcp_server, launch_tool, stop_process

            console.print("\n[bold cyan]Launching...[/bold cyan]")

            try:
                mcp_proc = launch_mcp_server(project_path)
                console.print(f"[green]\u2713[/green] MCP server started (PID: {mcp_proc.pid})")
            except (FileNotFoundError, RuntimeError) as exc:
                console.print(f"[yellow]MCP server: {exc}[/yellow]")
                mcp_proc = None

            tool_name = selected_tool if selected_tool != "claude" else "claude-code"
            try:
                tool_proc = launch_tool(tool_name, project_path, prompt=prompt)
                console.print(f"[green]\u2713[/green] {selected_tool} launched (PID: {tool_proc.pid})")
                console.print("\n[dim]Waiting for AI tool to exit...[/dim]")
                tool_proc.wait()
            except (FileNotFoundError, ValueError) as exc:
                console.print(f"[red]Could not launch {selected_tool}: {exc}[/red]")
            finally:
                if mcp_proc is not None:
                    stop_process(mcp_proc)
                    console.print("[dim]MCP server stopped.[/dim]")
        else:
            console.print("\n[green]\u2713[/green] Project is ready for AI coding!")
            console.print("  Run your AI tool manually in this directory.")

    finally:
        store.close()
