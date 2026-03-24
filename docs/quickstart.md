# 🚀 CodeRAG Quick Start Guide

Get up and running with CodeRAG in under 5 minutes. This guide walks you through installation, parsing your first project, querying the knowledge graph, and launching an AI coding session.

## Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **Git** (for cloning repositories)
- **pip** (Python package manager)

## Installation

### From Source (Recommended)

```bash
# Clone the repository
git clone https://github.com/dmnkhorvath/coderag-cli.git
cd coderag

# Install with all dependencies
pip install -e '.[all]'

# Verify installation
coderag --version
```

### Using the Install Script

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install-coderag.sh | bash
```

The install script auto-generates `.mcp.json` and `CLAUDE.md` for Claude Code integration.

## Step 1: Parse Your First Project

CodeRAG builds a knowledge graph from your codebase using AST parsing. Point it at any project directory:

```bash
# Parse a project
coderag parse /path/to/your/project
```

Example output:

```
╭─────────────────────────────────────╮
│ CodeRAG — Parsing /path/to/project  │
╰─────────────────────────────────────╯
  Database: /path/to/project/.codegraph/graph.db
  Mode:     incremental

      Parse Results
┏━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Metric        ┃  Value ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Files Found   │    125 │
│ Files Parsed  │    125 │
│ Total Nodes   │  1,883 │
│ Total Edges   │  7,998 │
│ Pipeline Time │ 1673ms │
└───────────────┴────────┘

✓ Parse completed in 1.67s
```

CodeRAG supports **PHP**, **JavaScript**, **TypeScript**, **Python**, **CSS**, **SCSS**, and **Vue** files.

## Step 2: Explore the Knowledge Graph

```bash
cd /path/to/your/project

# View graph statistics
coderag info

# Search for symbols (classes, functions, methods)
coderag query App

# Find all usages of a symbol
coderag find-usages Router

# Analyze a symbol's blast radius
coderag analyze App

# View architecture overview
coderag architecture

# Detect frameworks
coderag frameworks
```

## Step 3: Get File Context

Get rich context for any file — its symbols, relationships, and dependencies:

```bash
coderag file-context src/App.php
```

This is what AI tools use to understand your code without reading every file.

## Step 4: Launch an AI Coding Session

The Smart Launcher detects your project state, builds optimized context, and configures your AI tool:

```bash
# Preview what would happen (recommended first time)
coderag launch . --dry-run

# Output pre-loaded context to stdout
coderag launch . --context-only

# Launch with a specific prompt
coderag launch . "fix the routing bug in UserController"

# Launch with a specific AI tool
coderag launch . --tool claude-code
```

The `--dry-run` flag generates a `CLAUDE.md` project file and shows a summary without launching any tool.

## Step 5: Start the MCP Server

For continuous AI integration, start the MCP server:

```bash
# Start MCP server with file watching
coderag serve --watch
```

This exposes 8 tools and 3 resources that AI assistants can call to understand your codebase.

## Step 6: Benchmark Cost Savings

See how much CodeRAG saves on AI token costs:

```bash
coderag benchmark .
```

Typical result: **86.4% token savings** compared to manual file searching.

## What's Next?

- **[Launcher Guide](launcher.md)** — Deep dive into the Smart Launcher
- **[Session Memory](session-memory.md)** — Cross-session context persistence
- **[Cost Savings](cost-savings.md)** — Token cost benchmarking methodology
- **[AI Tool Setup](ai-tool-setup.md)** — Configure Claude Code, Cursor, or Codex
- **[CLI Reference](wiki/CLI-Reference.md)** — Full command documentation

## Common Commands Cheat Sheet

| Command | Description |
|---------|-------------|
| `coderag parse <path>` | Parse a codebase and build the knowledge graph |
| `coderag info` | Show graph statistics |
| `coderag query <search>` | Search for symbols |
| `coderag find-usages <symbol>` | Find all usages of a symbol |
| `coderag analyze <symbol>` | Analyze blast radius |
| `coderag architecture` | Architecture overview |
| `coderag frameworks` | Detect frameworks |
| `coderag deps <target>` | Show dependency graph |
| `coderag file-context <file>` | Get context for a file |
| `coderag launch . --dry-run` | Preview AI session launch |
| `coderag serve --watch` | Start MCP server with file watching |
| `coderag benchmark .` | Run cost benchmark |
| `coderag session list` | List recent sessions |
| `coderag update check` | Check for updates |
