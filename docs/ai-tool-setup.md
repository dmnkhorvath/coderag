# 🤖 AI Tool Setup Guide

CodeRAG integrates with Claude Code, Cursor, and Codex CLI to provide graph-powered context to your AI coding assistant. This guide covers automatic and manual setup for each tool.

## Overview

CodeRAG works with AI tools in two ways:

1. **Pre-loaded context** — The Smart Launcher builds a context document with the most important symbols, relationships, and session memory, then passes it to the AI tool at startup.
2. **MCP server** — A persistent server that exposes 8 tools and 3 resources the AI can call on-demand to query the knowledge graph.

Both methods can be used together for maximum effectiveness.

## Claude Code

Claude Code is the primary supported AI tool with the deepest integration.

### Automatic Setup (Recommended)

```bash
# One-command setup: parse, configure, and launch
coderag launch /path/to/project --tool claude-code

# Or preview first
coderag launch /path/to/project --tool claude-code --dry-run
```

This automatically:
- Parses the codebase (if needed)
- Generates `CLAUDE.md` with architecture overview and MCP tool descriptions
- Creates `.claude/settings.local.json` with MCP server configuration
- Starts the MCP server and launches Claude Code

### Manual Setup

#### Step 1: Generate CLAUDE.md

```bash
coderag launch /path/to/project --dry-run
```

This creates `CLAUDE.md` in the project root containing:
- Architecture overview with module structure
- Entry points ranked by PageRank importance
- Available MCP tools with descriptions
- Cross-language connections
- Framework information

#### Step 2: Configure MCP Server

Create `.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/project", "--watch"]
    }
  }
}
```

Or use the install script which auto-detects the `coderag` binary path:

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install-coderag.sh | bash
```

#### Step 3: Start Claude Code

Open the project in Claude Code. It will automatically:
- Read `CLAUDE.md` for project context
- Start the MCP server using the configuration
- Make all 8 CodeRAG tools available

### CLAUDE.md File

The `CLAUDE.md` file serves as the project's "briefing document" for Claude Code. It contains:

```markdown
# Project: MyApp

## Architecture Overview
- 125 source files, 1,883 symbols, 7,998 relationships
- Primary language: PHP

## Key Entry Points (by PageRank)
1. App (class) — PageRank: 0.0234
2. Router (class) — PageRank: 0.0189
...

## Available MCP Tools
- coderag_lookup_symbol: Find symbol definitions
- coderag_find_usages: Find all usages of a symbol
...
```

## Cursor

Cursor supports MCP servers through its configuration system.

### Automatic Setup

```bash
coderag launch /path/to/project --tool cursor --dry-run
```

This creates:
- `.cursor/mcp.json` — MCP server configuration
- `.cursor/rules` — Project-specific instructions for Cursor

### Manual Setup

#### Step 1: Configure MCP Server

Create `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/project", "--watch"]
    }
  }
}
```

#### Step 2: Add Rules File (Optional)

Create `.cursor/rules` with project-specific instructions:

```
This project uses CodeRAG for code intelligence.
Use the coderag_* MCP tools to understand code structure.
Always check coderag_file_context before modifying a file.
Use coderag_find_usages before renaming or removing symbols.
Use coderag_impact_analysis before making architectural changes.
```

#### Step 3: Open in Cursor

Open the project in Cursor. The MCP server starts automatically.

## Codex CLI

OpenAI's Codex CLI supports MCP server integration.

### Automatic Setup

```bash
coderag launch /path/to/project --tool codex --dry-run
```

This creates `codex.json` with MCP server configuration.

### Manual Setup

Create `codex.json` in the project root:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/project", "--watch"]
    }
  }
}
```

Then launch Codex CLI from the project directory.

## MCP Server Standalone

You can run the MCP server independently for use with any MCP-compatible tool.

### Starting the Server

```bash
# Basic: start MCP server
coderag serve /path/to/project

# With file watching (auto-reparse on changes)
coderag serve /path/to/project --watch

# With custom database path
coderag serve --db /path/to/graph.db

# Disable hot-reload
coderag serve /path/to/project --no-reload

# Custom debounce interval for file watcher
coderag serve /path/to/project --watch --debounce 5.0
```

The server uses **stdio transport** (standard for Claude Code, Cursor, etc.). Diagnostic messages go to stderr.

### Available Tools

The MCP server exposes 8 tools for code intelligence:

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `coderag_lookup_symbol` | Find symbol definitions by name | `symbol` (string) |
| `coderag_find_usages` | Find all usages of a symbol | `symbol` (string) |
| `coderag_impact_analysis` | Analyze blast radius of changes | `symbol` (string) |
| `coderag_file_context` | Get context for a specific file | `file_path` (string) |
| `coderag_find_routes` | Find API routes/endpoints | `pattern` (string) |
| `coderag_search` | Search the knowledge graph | `query` (string) |
| `coderag_architecture` | Get architecture overview | — |
| `coderag_dependency_graph` | Get dependency graph for a symbol | `symbol` (string) |

Plus 8 session memory tools:

| Tool | Description |
|------|-------------|
| `session_log_read` | Log a file read event |
| `session_log_edit` | Log a file edit event |
| `session_log_decision` | Record an architectural decision |
| `session_log_task` | Create or update a task |
| `session_log_fact` | Record a learned fact |
| `session_get_history` | Get recent session events |
| `session_get_hot_files` | Get most frequently accessed files |
| `session_get_context` | Get persisted context |

### Available Resources

The MCP server exposes 3 resources:

| Resource URI | Description |
|-------------|-------------|
| `coderag://summary` | Project summary with statistics |
| `coderag://architecture` | Architecture overview with modules and relationships |
| `coderag://file-map` | Complete file map of the project |

### Server Features

- **Hot-reload**: Automatically reloads when the database file changes (e.g., after a re-parse)
- **File watching**: With `--watch`, monitors source files and auto-reparses on changes
- **Debounce**: Configurable debounce interval prevents excessive re-parsing during rapid edits
- **Stdio transport**: Compatible with all MCP-aware AI tools

## Choosing Your Setup

| Scenario | Recommended Approach |
|----------|---------------------|
| First time with Claude Code | `coderag launch . --tool claude-code --dry-run` |
| Daily development with Claude Code | `coderag launch . "your task"` |
| Using Cursor | `coderag launch . --tool cursor --dry-run` then open in Cursor |
| Using Codex CLI | `coderag launch . --tool codex --dry-run` then run codex |
| Custom MCP integration | `coderag serve . --watch` |
| CI/CD context generation | `coderag launch . --context-only > context.md` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| MCP tools not available | Check that `coderag serve` is running and config file path is correct |
| Stale data from MCP | Re-parse with `coderag parse .` — the server auto-reloads |
| Server crashes on startup | Ensure `.codegraph/graph.db` exists — run `coderag parse .` first |
| Wrong tool auto-detected | Use `--tool claude-code\|cursor\|codex` explicitly |
| Config file not created | Use `--dry-run` mode which writes config files |
| File watching not working | Ensure `--watch` flag is passed to `coderag serve` |
