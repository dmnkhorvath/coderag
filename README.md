# 🧠 CodeRAG

**Build knowledge graphs from your codebase for smarter AI coding assistants**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/dmnkhorvath/coderag-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/dmnkhorvath/coderag-cli/actions/workflows/ci.yml)

CodeRAG parses your codebase using tree-sitter AST analysis, builds a rich knowledge graph of symbols and relationships, and serves that intelligence to AI coding assistants via an MCP server. It understands classes, functions, routes, components, cross-language connections, and framework patterns — giving your AI tools deep structural awareness instead of naive file reading.

---

## ✨ Key Features

- 🌐 **7 Languages** — PHP, JavaScript, TypeScript, Python, CSS, SCSS + Vue SFC
- 🏗️ **11 Framework Detectors** — Laravel, Symfony, React, Express, Next.js, Vue, Angular, Django, Flask, FastAPI, Tailwind CSS
- 🤖 **MCP Server** — 16 tools for Claude Code, Cursor, and Codex CLI integration
- 📊 **Graph Analysis** — PageRank, community detection, blast radius, dependency graphs
- 🔍 **Hybrid Search** — FTS5 full-text + FAISS vector semantic search
- 🔗 **Cross-Language** — Matches PHP routes to JS fetch calls, Python APIs to TS clients
- 💰 **86% Token Savings** — Proven cost reduction in AI coding sessions
- 🧠 **Session Memory** — Cross-session context persistence
- 🐳 **Docker Ready** — One-command deployment
- 📈 **Battle-Tested** — 7 dogfood sessions, 17 bugs found & fixed, 255K+ nodes parsed

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
# Clone and install
git clone https://github.com/dmnkhorvath/coderag-cli.git
cd coderag
pip install -e '.[all]'
```

Or use the automated installer:

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install-coderag.sh | sh
```

### Parse a Codebase

```bash
# Parse your project
coderag parse /path/to/project

# Explore the graph
coderag info
coderag query MyClass
coderag find-usages UserController
coderag architecture
```

### Launch with AI

```bash
# One command — parse, configure MCP, launch AI tool
coderag launch /path/to/project --tool claude-code

# Or start the MCP server standalone
coderag serve /path/to/project --watch
```

---

## 🔬 How It Works

1. **Parse** — Tree-sitter AST extracts symbols (classes, functions, routes, components) across 7 languages
2. **Resolve** — Cross-file references resolved with 4-strategy matching (exact, suffix, short name, placeholder)
3. **Serve** — MCP server provides graph intelligence to AI coding tools with 16 specialized tools

```
Your Codebase          CodeRAG                    AI Tool
┌──────────┐    ┌─────────────────┐    ┌──────────────────┐
│ .php     │    │ Tree-sitter AST │    │ Claude Code      │
│ .ts/.js  │───▶│ Knowledge Graph │───▶│ Cursor           │
│ .py      │    │ MCP Server      │    │ Codex CLI        │
│ .css     │    └─────────────────┘    └──────────────────┘
└──────────┘
```

---

## 🌐 Supported Languages & Frameworks

| Language | Extensions | Node Types | Framework Detectors |
|----------|-----------|------------|--------------------|
| PHP | `.php`, `.blade.php` | class, function, method, trait, interface, enum, constant | Laravel, Symfony |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | class, function, arrow_function, component, export | Express, React |
| TypeScript | `.ts`, `.tsx`, `.mts`, `.cts`, `.vue` | class, function, interface, type_alias, enum, component | Next.js, Vue, Angular |
| Python | `.py` | class, function, method, decorator | Django, Flask, FastAPI |
| CSS | `.css` | selector, variable, keyframes, media_query, layer | Tailwind CSS |
| SCSS | `.scss` | selector, variable, mixin, function, placeholder | — |

---

## 📋 CLI Reference

| Command | Description |
|---------|-------------|
| `coderag parse <path>` | Parse codebase and build knowledge graph |
| `coderag query <symbol>` | Search for symbols by name |
| `coderag info [path]` | Show graph statistics |
| `coderag find-usages <symbol>` | Find all usages of a symbol |
| `coderag deps <symbol>` | Show dependency graph |
| `coderag analyze <symbol>` | Deep analysis with PageRank and centrality |
| `coderag architecture` | Show architecture overview |
| `coderag frameworks` | Show detected frameworks |
| `coderag cross-language` | Show cross-language connections |
| `coderag routes` | List all detected routes |
| `coderag impact <symbol>` | Blast radius analysis |
| `coderag file-context <file>` | Get context for a specific file |
| `coderag export` | Export graph in markdown/json/tree format |
| `coderag enrich` | Enrich graph with git history |
| `coderag watch <path>` | Watch for file changes and auto-reparse |
| `coderag serve` | Start MCP server for AI tools |
| `coderag launch <path>` | Smart launcher — parse, configure, launch AI tool |
| `coderag visualize <path>` | Generate interactive D3.js graph visualization |
| `coderag benchmark <path>` | Token cost benchmarking |
| `coderag session list` | List coding sessions |
| `coderag session show <id>` | Show session details |
| `coderag session context` | Show session context |
| `coderag update check` | Check for updates |
| `coderag update install` | Install latest version |
| `coderag init` | Initialize configuration |

---

## 🤖 MCP Server

CodeRAG includes a Model Context Protocol (MCP) server that exposes the knowledge graph to AI coding assistants. Start it with `coderag serve` or automatically via `coderag launch`.

### Code Intelligence Tools (8)

| Tool | Description |
|------|-------------|
| `coderag_lookup_symbol` | Look up a symbol — definition, relationships, and context |
| `coderag_find_usages` | Find all usages — calls, imports, extensions, implementations |
| `coderag_impact_analysis` | Blast radius analysis for a symbol or file change |
| `coderag_file_context` | Get full context for a file — symbols, relationships, importance |
| `coderag_find_routes` | Find API routes and their frontend callers |
| `coderag_search` | Full-text and semantic search across the knowledge graph |
| `coderag_architecture` | High-level architecture overview with key metrics |
| `coderag_dependency_graph` | Dependency graph for a symbol or file |

### Session Memory Tools (8)

| Tool | Description |
|------|-------------|
| `session_log_read` | Log a file read event |
| `session_log_edit` | Log a file edit event |
| `session_log_decision` | Log an architectural decision |
| `session_log_task` | Log a task completion |
| `session_log_fact` | Log a discovered fact |
| `session_get_history` | Get session history |
| `session_get_hot_files` | Get frequently accessed files |
| `session_get_context` | Get session context for pre-loading |

### Resources (3)

| Resource | Description |
|----------|-------------|
| `coderag://summary` | Project summary with key metrics |
| `coderag://architecture` | Architecture overview |
| `coderag://file-map` | Complete file map of the project |

### AI Tool Configuration

**Claude Code** — auto-configured via `coderag launch --tool claude-code`:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", ".", "--watch"]
    }
  }
}
```

**Cursor** — auto-configured via `coderag launch --tool cursor`:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", ".", "--watch"]
    }
  }
}
```

**Codex CLI** — auto-configured via `coderag launch --tool codex`:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", ".", "--watch"]
    }
  }
}
```

---

## 🐳 Docker

```bash
# Quick start
docker compose up -d
```

### Services

| Service | Description | Port |
|---------|-------------|------|
| `cli` | CodeRAG CLI for parsing and queries | — |
| `mcp` | MCP server for AI tool integration | 3000 |
| `watcher` | File watcher for auto-reparse | — |

See [docs/docker.md](docs/docker.md) for full Docker documentation.

---

## 📊 Performance Benchmarks

### Automated Benchmarks (51 repositories)

| Category | Repos | Files | Nodes | Edges |
|----------|-------|-------|-------|-------|
| PHP | 10 | 33,896 | 516,705 | 1,359,239 |
| JavaScript | 8 | 12,093 | 119,811 | 219,490 |
| TypeScript | 7 | 37,544 | 232,153 | 542,491 |
| Python | 10 | 5,968 | 206,563 | 448,830 |
| Mixed (PHP+JS/TS) | 4 | 8,212 | 81,178 | 185,371 |
| CSS/SCSS/Tailwind | 12 | 14,096 | 142,387 | 406,729 |
| **Total** | **51** | **111,809** | **~1,298,797** | **~3,162,150** |

### Real-World Dogfood Sessions (7 sessions)

| Session | Project | Type | Files | Nodes | Edges | Bugs Fixed |
|---------|---------|------|-------|-------|-------|------------|
| 1 | koel | PHP + Vue | 1,592 | 13,384 | 36,709 | 2 |
| 2 | paperless-ngx | Django + Angular | 807 | 20,580 | 50,517 | 0 |
| 3 | saleor | Django + GraphQL | 4,220 | 111,076 | 260,654 | 3 |
| 4 | NocoDB | TypeScript + Vue | 1,823 | 24,367 | 74,284 | 4 |
| 5 | Cal.com | TS + React + Tailwind | 7,530 | 50,926 | 220,752 | 4 |
| 6 | koel (MCP) | MCP + Claude Code | — | 15,797 | 34,294 | 1 |
| 7 | Mealie | FastAPI + Vue | 1,008 | 18,895 | 53,380 | 2 |
| **Total** | | | **16,980** | **255,025** | **730,590** | **17** |

### Token Cost Savings

| Metric | Without CodeRAG | With CodeRAG | Savings |
|--------|----------------|--------------|--------|
| Avg tokens/task | 17,617 | 2,400 | **86.4%** |
| Monthly cost (Claude Sonnet) | $42.28 | $5.76 | **$36.52** |

---

## 🧪 Testing

- **4,563 tests** passing
- **94% code coverage** on critical modules (67% overall)
- **18 E2E integration tests** (full workflow validation)
- CI/CD via GitHub Actions — Python 3.11, 3.12, 3.13

```bash
# Run tests
python -m pytest tests/ -q

# Run with coverage
python -m pytest tests/ --cov=src/coderag --cov-report=term-missing

# Run E2E tests
bash tests/e2e/test_full_workflow.sh
```

---

## 📈 Codebase Stats

| Metric | Value |
|--------|-------|
| Python source files | 120 |
| Total source lines | 43,312 |
| Test files | 139 |
| Total test lines | 59,235 |
| Tests passing | 4,563 |
| Language plugins | 6 (PHP, JS, TS, Python, CSS, SCSS) + Vue SFC |
| Framework detectors | 11 |
| MCP tools | 16 |
| MCP resources | 3 |
| Node types | 41 |
| Edge types | 50 |
| CLI commands | 25 |

---

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [Quick Start](docs/quickstart.md) | Installation and first steps |
| [Smart Launcher](docs/launcher.md) | One-command AI session setup |
| [Session Memory](docs/session-memory.md) | Cross-session context persistence |
| [Cost Savings](docs/cost-savings.md) | Token cost benchmarking |
| [AI Tool Setup](docs/ai-tool-setup.md) | Claude Code, Cursor, Codex configuration |
| [Docker](docs/docker.md) | Container deployment |
| [Architecture](docs/architecture/) | System design |
| [Research](docs/research/) | Language parsing research |

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`python -m pytest tests/ -q`)
5. Run linting (`ruff check src/ tests/ && ruff format src/ tests/`)
6. Submit a pull request

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.
