<div align="center">

# 🧠 CodeRAG

**Build knowledge graphs from your codebase for LLM context retrieval**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests: 165 passing](https://img.shields.io/badge/tests-165%20passing-brightgreen.svg)](#-testing)
[![Lines: 19K+](https://img.shields.io/badge/lines-19K%2B-informational.svg)](#-codebase-stats)

*Parse PHP, JavaScript, and TypeScript codebases into rich knowledge graphs with framework detection, cross-language analysis, and MCP server integration for AI-powered code understanding.*

</div>

---

## 📋 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [CLI Reference](#-cli-reference)
- [MCP Server](#-mcp-server)
- [Framework Detection](#-framework-detection)
- [Export Formats](#-export-formats)
- [Configuration](#%EF%B8%8F-configuration)
- [Architecture](#-architecture)
- [Plugin Development](#-plugin-development)
- [Performance Benchmarks](#-performance-benchmarks)
- [Testing](#-testing)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

### 🌐 Multi-Language Parsing
- **PHP** — Classes, interfaces, traits, enums, functions, methods, properties, constants, namespaces
- **JavaScript** — ES modules, CommonJS, JSX, classes, functions, arrow functions, React components
- **TypeScript** — Interfaces, type aliases, enums, generics, decorators, TSX, ambient declarations

### 🔍 Deep Code Analysis
- **25 node types** and **30 edge types** for comprehensive code modeling
- **Cross-file reference resolution** with multi-strategy matching (exact → suffix → short name)
- **Cross-language API matching** — PHP routes ↔ JavaScript fetch calls
- **Graph algorithms** — PageRank, community detection, blast radius, circular dependency detection
- **Git metadata enrichment** — Change frequency, co-change analysis, code ownership
- **PHPStan type enrichment** — Static analysis integration for richer type information

### 🏗️ Framework Detection
- **Laravel** — Routes, models, middleware, events, Blade templates
- **React** — Components, hooks, context providers/consumers
- **Express.js** — Routes, middleware chains, error handlers
- **Next.js** — File-based routing, server/client components, API routes
- **Vue** — Single-file components, Composition API, Pinia stores

### 🤖 MCP Server Integration
- **8 tools** for AI agents to query the knowledge graph
- **3 resources** providing passive context (summary, architecture, file map)
- **Hot-reload** — Automatically detects database changes
- **Token budgeting** — Responses sized to fit LLM context windows

### 📦 Export & Output
- **3 formats** — Markdown, JSON, Tree
- **4 scopes** — Full graph, architecture overview, file context, symbol context
- **Rich CLI** — Colored terminal output with progress indicators
- **Token-budgeted** — Control output size for LLM consumption

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11 or higher
- pip package manager

### Installation

```bash
# Clone and install
git clone https://github.com/dmnkhorvath/coderag.git
cd coderag
pip install -e .

# Verify installation
coderag --help
```

**One-line install:**
```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

### Parse Your First Project

```bash
# 1. Initialize configuration
cd /path/to/your/project
coderag init

# 2. Parse the codebase
coderag parse .

# 3. Explore the knowledge graph
coderag info .
coderag query --name "UserController" .

# 4. Start MCP server for AI integration
coderag serve .
```

### Example Output

```
$ coderag info /path/to/laravel-app

📊 Knowledge Graph Summary
├── Project: laravel-app
├── Files: 1,536 (PHP: 1,200 | JS: 236 | TS: 100)
├── Nodes: 30,474
├── Edges: 62,097
├── Communities: 45
├── Frameworks: Laravel, React
└── Parse time: 14.2s
```

---

## 💻 CLI Reference

### `coderag init`

Initialize a `codegraph.yaml` configuration file.

```bash
coderag init                                    # Interactive setup
coderag init --languages php,typescript         # Specify languages
coderag init --name "my-project"                # Set project name
```

### `coderag parse`

Parse a codebase and build the knowledge graph.

```bash
coderag parse .                                 # Parse current directory
coderag parse /path/to/project                  # Parse specific project
coderag parse . --incremental                   # Only re-parse changed files
coderag parse . --parallel                      # Use parallel extraction
```

### `coderag info`

Display knowledge graph statistics.

```bash
coderag info .                                  # Show graph summary
coderag info . --db custom/path/graph.db        # Use custom database path
```

### `coderag query`

Query the knowledge graph for symbols and relationships.

```bash
coderag query --name "User" .                   # Search by name
coderag query --name "UserController" --kind class .  # Filter by kind
coderag query --name "App\Models\User" --depth 2 .    # Traverse neighbors
```

### `coderag export`

Export knowledge graph data in various formats.

```bash
coderag export                                  # Architecture overview (markdown)
coderag export -f json -s full                  # Full graph as JSON
coderag export -s symbol --symbol User          # Symbol context
coderag export -s file --file app/User.php      # File context
coderag export -f tree -s full                  # Repository map tree view
coderag export --tokens 16000 -o out.md         # Custom token budget, save to file
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `-f, --format` | `markdown`, `json`, `tree` | `markdown` | Output format |
| `-s, --scope` | `full`, `architecture`, `file`, `symbol` | `architecture` | Export scope |
| `--symbol` | string | — | Symbol name (for symbol scope) |
| `--file` | path | — | File path (for file scope) |
| `--tokens` | int | `8000` | Token budget |
| `--top` | int | `20` | Top N items for architecture |
| `--depth` | int | `2` | Traversal depth for symbol scope |
| `-o, --output` | path | stdout | Output file path |

### `coderag analyze`

Run graph analysis algorithms.

```bash
coderag analyze .                               # Full analysis
coderag analyze . --top 20                      # Show top 20 results
```

### `coderag architecture`

Generate architecture overview with community detection.

```bash
coderag architecture .                          # Architecture report
```

### `coderag frameworks`

Detect and report framework usage.

```bash
coderag frameworks .                            # Detect all frameworks
```

### `coderag cross-language`

Analyze cross-language connections (PHP routes ↔ JS API calls).

```bash
coderag cross-language .                        # Find cross-language matches
```

### `coderag enrich`

Enrich the knowledge graph with additional metadata.

```bash
coderag enrich --phpstan                        # Run PHPStan enrichment
coderag enrich --phpstan --level 8              # Custom analysis level (0-9)
coderag enrich --phpstan --phpstan-path vendor/bin/phpstan  # Custom binary
```

### `coderag serve`

Start the MCP server for AI agent integration.

```bash
coderag serve .                                 # Start with stdio transport
coderag serve . --db custom/graph.db            # Custom database path
coderag serve . --no-reload                     # Disable hot-reload
```

---

## 🤖 MCP Server

CodeRAG includes a full [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the knowledge graph to AI agents.

### Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `coderag_lookup_symbol` | Look up a symbol's definition, relationships, and context | `symbol`, `detail_level`, `token_budget` |
| `coderag_find_usages` | Find all usages of a symbol (calls, imports, extends, etc.) | `symbol`, `usage_types`, `max_depth` |
| `coderag_impact_analysis` | Analyze blast radius of changing a symbol | `symbol`, `max_depth`, `token_budget` |
| `coderag_file_context` | Get all symbols and relationships in a file | `file_path`, `token_budget` |
| `coderag_find_routes` | Find API routes with optional HTTP method filtering | `pattern`, `http_method` |
| `coderag_search` | Full-text search across the knowledge graph | `query`, `kind_filter`, `limit` |
| `coderag_architecture` | Get architecture overview with configurable focus | `focus`, `token_budget` |
| `coderag_dependency_graph` | Get dependency graph for a symbol | `symbol`, `direction`, `max_depth` |

### Resources

| URI | Description |
|-----|-------------|
| `coderag://summary` | Knowledge graph statistics and project overview |
| `coderag://architecture` | High-level architecture with communities and important nodes |
| `coderag://file-map` | Annotated file tree showing symbols per file |

### Usage with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

---

## 🏗️ Framework Detection

CodeRAG automatically detects and enriches framework-specific patterns:

### Laravel (PHP)
- Route definitions (`Route::get`, `Route::resource`, etc.)
- Eloquent models and relationships
- Middleware registration
- Event/listener patterns
- Blade template references

### React (JavaScript/TypeScript)
- Functional and class components
- Hook usage (`useState`, `useEffect`, custom hooks)
- Context providers and consumers
- Component prop passing

### Express.js (JavaScript)
- Route handlers (`app.get`, `router.post`, etc.)
- Middleware chains
- Error handlers
- Router mounting

### Next.js (JavaScript/TypeScript)
- File-based routing (pages and app directory)
- Server and client components (`'use server'`, `'use client'`)
- API routes
- Middleware
- Dynamic routes and route groups

### Vue (JavaScript/TypeScript)
- Single-file components (`.vue`)
- Composition API (`ref`, `computed`, `watch`)
- Pinia store detection
- Component registration

---

## 📤 Export Formats

### Markdown
Structured markdown optimized for LLM consumption with headers, code blocks, and relationship tables.

### JSON
Complete graph data as structured JSON — ideal for programmatic consumption and custom tooling.

### Tree
Repository map showing file structure annotated with symbol counts — great for orientation.

---

## ⚙️ Configuration

CodeRAG uses a `codegraph.yaml` file in your project root:

```yaml
# codegraph.yaml
project:
  name: my-project
  root: .

languages:
  php:
    enabled: true
    extensions: [".php"]
  javascript:
    enabled: true
    extensions: [".js", ".jsx", ".mjs", ".cjs"]
  typescript:
    enabled: true
    extensions: [".ts", ".tsx"]

storage:
  backend: sqlite
  path: .codegraph/graph.db

output:
  default_format: markdown
  max_tokens: 8000

ignore:
  - node_modules/
  - vendor/
  - .git/
  - "*.min.js"
  - dist/
  - build/
```

Generate a default config with `coderag init`.

---

## 🏛️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                             │
│   parse │ query │ info │ export │ serve │ enrich │ init     │
├─────────────────────────────────────────────────────────────┤
│                    Pipeline Orchestrator                      │
│  Phase 1: Discovery    → File scanning with ignore patterns  │
│  Phase 2: Hashing      → Content-hash for incremental mode   │
│  Phase 3: Extraction   → Tree-sitter AST parsing (parallel)  │
│  Phase 4: Resolution   → Cross-file reference resolution     │
│  Phase 5: Frameworks   → Framework pattern detection         │
│  Phase 6: Cross-lang   → PHP route ↔ JS API call matching    │
│  Phase 7: Enrichment   → Git metadata + PHPStan types        │
│  Phase 8: Persistence  → SQLite batch upsert                 │
├─────────────────────────────────────────────────────────────┤
│                    Plugin System                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐         │
│  │   PHP    │  │  JavaScript  │  │   TypeScript   │         │
│  │ Extractor│  │  Extractor   │  │   Extractor    │         │
│  │ Resolver │  │  Resolver    │  │   Resolver     │         │
│  │ Laravel  │  │  React       │  │                │         │
│  │          │  │  Express     │  │                │         │
│  │          │  │  Next.js     │  │                │         │
│  │          │  │  Vue         │  │                │         │
│  └──────────┘  └──────────────┘  └────────────────┘         │
├─────────────────────────────────────────────────────────────┤
│                    Storage & Analysis                         │
│  SQLite + FTS5 + WAL  │  NetworkX Graph  │  Context Assembly │
├─────────────────────────────────────────────────────────────┤
│                    MCP Server (FastMCP)                       │
│  8 Tools  │  3 Resources  │  Hot-reload  │  Token Budgeting  │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Description | Lines |
|-----------|-------------|-------|
| `core/models.py` | 25 node types, 30 edge types, data models | ~500 |
| `core/config.py` | YAML configuration system | ~350 |
| `core/registry.py` | Plugin ABCs and registry | ~200 |
| `plugins/php/` | PHP extractor, resolver, Laravel detector | ~1,500 |
| `plugins/javascript/` | JS extractor, resolver, React/Express/Next.js/Vue | ~2,500 |
| `plugins/typescript/` | TS extractor with interfaces, generics, decorators | ~2,800 |
| `storage/sqlite_store.py` | SQLite backend with FTS5 and WAL mode | ~800 |
| `pipeline/` | 8-phase orchestrator, scanner, resolver | ~1,500 |
| `analysis/` | NetworkX graph algorithms | ~500 |
| `mcp/` | MCP server, tools, resources | ~1,200 |
| `export/` | Multi-format graph exporter | ~600 |
| `enrichment/` | Git metadata, PHPStan integration | ~700 |
| `cli/` | Click-based CLI with Rich output | ~1,000 |

---

## 🔌 Plugin Development

CodeRAG uses a plugin architecture for language support. Each plugin implements:

```python
from coderag.core.registry import LanguagePlugin, ASTExtractor, ModuleResolver

class MyPlugin(LanguagePlugin):
    def get_language_id(self) -> Language:
        return Language.MY_LANG

    def get_file_extensions(self) -> list[str]:
        return [".ext"]

    def create_extractor(self) -> ASTExtractor:
        return MyExtractor()

    def create_resolver(self) -> ModuleResolver:
        return MyResolver()

    def get_framework_detectors(self) -> list[FrameworkDetector]:
        return [MyFrameworkDetector()]
```

The extractor receives file content and returns an `ExtractionResult` with nodes and edges:

```python
class MyExtractor(ASTExtractor):
    def extract(self, file_path: Path, source: bytes) -> ExtractionResult:
        # Parse AST, create Node and Edge objects
        nodes = [...]  
        edges = [...]
        return ExtractionResult(nodes=nodes, edges=edges)
```

---

## 📊 Performance Benchmarks

### Single-Language Repositories

| Language | Repos | Files | Nodes | Edges | Avg Parse Time |
|----------|-------|-------|-------|-------|----------------|
| PHP | 10 | 34,891 | 516,478 | 1,058,929 | ~45s |
| JavaScript | 8 | 24,321 | 176,095 | 531,145 | ~30s |
| TypeScript | 7 | 24,321 | 176,096 | 531,146 | ~35s |

### Mixed-Language Repositories

| Repository | Files | Nodes | Edges | Languages | Frameworks |
|------------|-------|-------|-------|-----------|------------|
| koel | 1,536 | 30,474 | 62,097 | PHP, JS, TS | Laravel |
| monica | 2,847 | 15,333 | 30,925 | PHP, JS | Laravel |
| flarum | 1,982 | 18,204 | 45,178 | PHP, JS, TS | — |
| bagisto | 1,847 | 17,167 | 47,171 | PHP, JS | Laravel |

### Combined Totals

| Metric | Value |
|--------|-------|
| **Repositories benchmarked** | 29 |
| **Total files parsed** | 91,745 |
| **Total nodes extracted** | 949,847 |
| **Total edges created** | 2,306,591 |
| **Query accuracy** | 97–100% |
| **Cross-language edges** | Detected in all mixed repos |

### Performance Targets

| Codebase Size | Initial Parse | Incremental Update |
|---------------|---------------|--------------------|
| Small (<100 files) | <5s | <0.5s |
| Medium (100–1,000 files) | 15–60s | <2s |
| Large (1,000–10,000 files) | 60–300s | <5s |
| Very Large (10,000+ files) | 5–15min | <10s |

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=coderag --cov-report=term-missing

# Run specific test file
python -m pytest tests/test_enrichment.py -v
```

**Test suite:** 165 tests across 8 test files covering models, config, storage, pipeline, export, hot-reload, framework detection, and PHPStan enrichment.

---

## 📊 Codebase Stats

| Metric | Value |
|--------|-------|
| **Total lines of code** | 19,300+ |
| **Python source files** | 50+ |
| **Test files** | 8 |
| **Tests passing** | 165 |
| **Language plugins** | 3 (PHP, JS, TS) |
| **Framework detectors** | 5 (Laravel, React, Express, Next.js, Vue) |
| **MCP tools** | 8 |
| **MCP resources** | 3 |
| **Node types** | 25 |
| **Edge types** | 30 |

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

```bash
# Clone and set up development environment
git clone https://github.com/dmnkhorvath/coderag.git
cd coderag
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run linter
ruff check src/

# Run type checker
mypy src/coderag/
```

### Areas for Contribution
- 🌐 New language plugins (Go, Rust, Java, C#)
- 🏗️ Additional framework detectors (Django, Spring, Angular, Svelte)
- 📊 New graph analysis algorithms
- 🧪 Additional test coverage
- 📖 Documentation improvements

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with ❤️ using [Tree-sitter](https://tree-sitter.github.io/tree-sitter/), [NetworkX](https://networkx.org/), and [FastMCP](https://github.com/jlowin/fastmcp)**

</div>
