# 🚀 Smart Launcher Guide

The Smart Launcher is CodeRAG's one-command entry point for AI-assisted coding sessions. It detects your project state, parses if needed, builds optimized context, configures your AI tool, and launches the session — all in a single command.

## Overview

The launcher follows a 5-step pipeline:

1. **Detect** — Analyze project state (fresh, stale, or ready)
2. **Parse** — Run the parsing pipeline if needed
3. **Context** — Build token-budgeted context using PageRank + graph analysis
4. **Config** — Write AI tool configuration files
5. **Launch** — Start the MCP server and AI tool

```
coderag launch [PATH] [PROMPT] [OPTIONS]
```

## Project State Detection

The launcher automatically detects your project's state:

| State | Condition | Action |
|-------|-----------|--------|
| **Fresh** | No `.codegraph/graph.db` exists | Full parse triggered |
| **Stale** | Source files newer than database | Incremental re-parse |
| **Ready** | Database is up-to-date | Skip parsing, proceed to context |

State detection compares the modification time of `.codegraph/graph.db` against all source files in the project. If any source file is newer than the database, the project is considered stale.

## Modes of Operation

### `--dry-run` Mode

Preview what the launcher would do without actually launching an AI tool:

```bash
coderag launch . --dry-run
```

This mode:
- Detects project state and parses if needed
- Builds the pre-loaded context
- Generates `CLAUDE.md` project instructions file
- Writes AI tool configuration files
- Displays a summary panel with all details
- **Does NOT** start the MCP server or launch any AI tool

Example output:

```
╭──────────────────────────────────────────────────────────────────────────────╮
│ 🚀 CodeRAG Launch — Dry Run                                                │
│                                                                              │
│ Project state: ready                                                         │
│ Source files: 125                                                            │
│ Context size: 4747 chars (~1186 tokens)                                      │
│ CLAUDE.md: /path/to/project/CLAUDE.md                                        │
│ AI tool: none detected                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Use `--dry-run` the first time to verify everything works before launching.

### `--context-only` Mode

Output the pre-loaded context to stdout and exit:

```bash
coderag launch . --context-only
```

This mode:
- Detects project state and parses if needed
- Builds the pre-loaded context with PageRank-ranked symbols
- Injects session memory (decisions, tasks, facts, hot files)
- Prints the full context to stdout
- **Does NOT** generate CLAUDE.md, write configs, or launch any tool

Useful for:
- Piping context into other tools: `coderag launch . --context-only | pbcopy`
- Inspecting what context the AI tool would receive
- Integrating with custom workflows

### `--token-budget` Option

Control how much context is pre-loaded:

```bash
# Default: 8000 tokens
coderag launch . --dry-run

# Smaller budget for faster models
coderag launch . --dry-run --token-budget 4000

# Larger budget for models with big context windows
coderag launch . --dry-run --token-budget 16000
```

The token budget controls how many symbols and relationships are included in the pre-loaded context. CodeRAG uses PageRank scores to prioritize the most important symbols.

### Full Launch Mode

Launch an AI coding session with full context:

```bash
# Auto-detect AI tool
coderag launch .

# With an initial prompt
coderag launch . "fix the routing bug in UserController"

# Specify AI tool explicitly
coderag launch . --tool claude-code
coderag launch . --tool cursor
coderag launch . --tool codex
```

## AI Tool Configuration

The launcher auto-detects and configures these AI tools:

### Claude Code

- **Config file**: `.claude/settings.local.json`
- **Project file**: `CLAUDE.md` (architecture overview, entry points, MCP tools)
- **MCP server**: Configured in settings with `coderag serve` command

### Cursor

- **Config file**: `.cursor/mcp.json`
- **Rules file**: `.cursor/rules` (project-specific instructions)
- **MCP server**: Configured in mcp.json

### Codex CLI

- **Config file**: `codex.json`
- **MCP server**: Configured in codex.json

### Auto-Detection

With `--tool auto` (the default), the launcher checks for:
1. `.claude/` directory → Claude Code
2. `.cursor/` directory → Cursor
3. `codex.json` file → Codex CLI
4. Falls back to Claude Code if none detected

## CLAUDE.md Generation

The `--dry-run` and full launch modes generate a `CLAUDE.md` file in the project root. This file contains:

- **Architecture Overview**: Module structure, key components, and relationships
- **Entry Points**: Main classes and functions ranked by PageRank importance
- **MCP Tools**: Available tools with descriptions for the AI assistant
- **Cross-Language Connections**: API endpoints, shared constants, and inter-language bridges
- **Framework Information**: Detected frameworks and their patterns

The AI tool reads this file to understand the project before starting work.

## MCP Server Integration

When launching in full mode, the launcher starts the MCP server in the background:

```bash
coderag serve /path/to/project --watch
```

The MCP server provides 8 tools and 3 resources:

**Tools:**
- `coderag_lookup_symbol` — Find symbol definitions
- `coderag_find_usages` — Find all usages of a symbol
- `coderag_impact_analysis` — Analyze blast radius of changes
- `coderag_file_context` — Get context for a specific file
- `coderag_find_routes` — Find API routes/endpoints
- `coderag_search` — Search the knowledge graph
- `coderag_architecture` — Get architecture overview
- `coderag_dependency_graph` — Get dependency graph for a symbol

**Resources:**
- `coderag://summary` — Project summary
- `coderag://architecture` — Architecture overview
- `coderag://file-map` — Complete file map

## Context Building Pipeline

The pre-loaded context is built using a priority-ordered pipeline:

1. **PageRank Top-20**: The 20 most important symbols by PageRank score
2. **Query-Relevant Symbols**: If a prompt is provided, FTS5 search finds relevant symbols
3. **Session Memory**: Injected from the session store:
   - Hot files (most frequently read/edited)
   - Decisions made in previous sessions
   - Open tasks
   - Learned facts
   - Recent activity
4. **Framework Context**: Detected framework patterns and conventions

All context is token-budgeted to fit within the specified limit.

## Examples

### First-Time Setup

```bash
# Parse and preview (recommended first time)
coderag launch /path/to/project --dry-run

# Check the generated CLAUDE.md
cat /path/to/project/CLAUDE.md

# Launch when satisfied
coderag launch /path/to/project
```

### Daily Workflow

```bash
# Quick launch with a task
coderag launch . "add pagination to the user list endpoint"

# Launch with extra context budget
coderag launch . "refactor the authentication module" --token-budget 16000
```

### CI/CD Integration

```bash
# Generate context for automated code review
coderag launch . --context-only > /tmp/project-context.md

# Use in a script
CONTEXT=$(coderag launch . --context-only)
echo "$CONTEXT" | your-review-tool --stdin
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No graph database found" | Run `coderag parse .` first or use `coderag launch .` which auto-parses |
| Context too small | Increase `--token-budget` (default: 8000) |
| Wrong AI tool detected | Use `--tool claude-code\|cursor\|codex` explicitly |
| CLAUDE.md not generated | Use `--dry-run` mode (not `--context-only`) |
| Stale context | Delete `.codegraph/` and re-parse, or the launcher will auto-detect staleness |
