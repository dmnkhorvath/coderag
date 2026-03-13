<div align="center">

# 🧠 CodeRAG

**Build knowledge graphs from your codebase for LLM context retrieval**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests: 1,308 passing](https://img.shields.io/badge/tests-1%2C308%20passing-brightgreen.svg)](#-testing)
[![Lines: 32K+](https://img.shields.io/badge/lines-32K%2B-informational.svg)](#-codebase-stats)
[![CI](https://github.com/dmnkhorvath/coderag/actions/workflows/ci.yml/badge.svg)](https://github.com/dmnkhorvath/coderag/actions/workflows/ci.yml)

*Parse PHP, JavaScript, TypeScript, Python, CSS, and SCSS codebases into rich knowledge graphs with framework detection, cross-language analysis, and MCP server integration for AI-powered code understanding.*

</div>

---

## 📋 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [CLI Reference](#-cli-reference)
- [TUI Monitor](#-tui-monitor)
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

## 🖥️ TUI Monitor

CodeRAG includes a real-time terminal dashboard for monitoring the parsing pipeline.

### Dashboard Wireframe

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🧠 CodeRAG Monitor   ▶ Parsing   Phase: Extraction   ⏱ 00:12   [1][2][3] │
├──────────┬──────────┬──────────┬──────────┬──────────────────────────────────┤
│  Files   │  Nodes   │  Edges   │  Errors  │  Throughput                     │
│   142    │  3,847   │  8,291   │    2     │  ▁▃▅▇▆▄▃▅▇█▇▅▃▂               │
├──────────┴──────────┴──────────┴──────────┴──────────────────────────────────┤
│  Pipeline Progress                                                          │
│  ✓ Discovery  ✓ Hashing  ▶ Extraction  ○ Resolution  ○ Frameworks  ...     │
│  ████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░  42%                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  Log Output                                                     [filtered] │
│  20:15:03 INFO  Parsing src/php/UserController.php                         │
│  20:15:03 INFO  Found 3 classes, 8 methods                                 │
│  20:15:04 WARN  Unresolved import: App\Services\Cache                      │
│  20:15:04 INFO  Parsing src/js/api.js                                      │
│  20:15:04 INFO  Found 3 functions, 2 imports                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  CPU ████████░░ 42%    MEM ██████░░░░ 31%                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  1:Dashboard  2:Logs  3:Details  4:Graph  ?:Help  q:Quit  gg/G:Top/Bot    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Installation

```bash
pip install coderag[tui]
```

### Usage

```bash
# Monitor a project's parsing pipeline in real-time
coderag monitor /path/to/project

# Monitor with verbose output
coderag monitor /path/to/project --verbose
```

### Screens

| Key | Screen | Description |
|-----|--------|-------------|
| `1` | **Dashboard** | Main overview with metrics, progress, logs, and resource usage |
| `2` | **Logs** | Full-screen log viewer with regex search and level filtering |
| `3` | **Details** | File metadata with nodes and edges in sortable tables |
| `4` | **Graph** | SQLite graph statistics by language, node kind, and edge kind |
| `?` | **Help** | Modal overlay with complete keybinding reference |

### Keybinding Reference

| Key | Action |
|-----|--------|
| `j` / `k` | Scroll down / up |
| `G` | Jump to bottom |
| `gg` | Jump to top (two-key vim sequence) |
| `Ctrl+d` / `Ctrl+u` | Half-page down / up |
| `Ctrl+f` / `Ctrl+b` | Full-page down / up |
| `f` | Toggle auto-follow in logs |
| `d` / `i` / `w` / `e` | Filter: Debug / Info / Warning / Error |
| `a` | Show all log levels |
| `/` | Search logs (regex) |
| `n` / `N` | Next / previous search match |
| `s` | Save logs to file |
| `y` | Yank (copy) logs |
| `r` | Refresh graph statistics |
| `h` / `l` | Switch tabs in Details screen |
| `:` | Enter command mode |
| `q` | Quit |

### Command Mode

Press `:` to enter command mode (vim-style):

| Command | Action |
|---------|--------|
| `:q` | Quit the application |
| `:w` | Save current logs to file |
| `:filter <level>` | Set log filter (DEBUG, INFO, WARNING, ERROR) |
| `:set wrap` | Enable line wrapping |
| `:set nowrap` | Disable line wrapping |
| `Escape` | Cancel command mode |

### Features

- **Real-time metrics** — Files parsed, nodes/edges created, error count, throughput sparkline
- **9-phase pipeline progress** — Visual indicators (✓ complete, ▶ active, ○ pending) with progress bar
- **Filterable logs** — Level-based filtering, regex search, auto-follow, save/copy
- **Resource monitoring** — Live CPU and memory usage bars via psutil
- **Post-parse summary** — Modal overlay showing total parse time, files, nodes, edges, languages detected
- **Vim keybindings** — Full vim-style navigation including `gg`, `G`, `j/k`, `Ctrl+d/u`
- **Command mode** — Vim `:` command input for quit, save, filter, and settings
- **Responsive layout** — Adapts to terminal sizes from 80×24 to 200×60+
- **Dark theme** — Custom emerald/cyan accent color scheme optimized for terminals

### ⚡ Performance & Developer Experience

- 🔄 **Live file watching** with auto-reparse (`coderag watch`)
- ⚡ **Parallel pipeline** — phases 3-5 and 7 run in parallel
- 🔍 **Full CLI parity** — all 8 MCP tools available as CLI commands

---

## 🤖 MCP Server Integration
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
coderag query --name "App\\Models\\User" --depth 2 .    # Traverse neighbors
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

### `coderag find-usages`

Find all usages of a symbol across the codebase.

```bash
coderag find-usages UserService                          # Find all usages
coderag find-usages UserService --types calls,imports     # Filter by type
coderag find-usages UserService --depth 2 --format json   # Transitive, JSON output
```

| Option | Description |
|--------|-------------|
| `--types` | Comma-separated usage types: calls, imports, extends, implements, instantiates, type_references, all |
| `--depth` | Transitive traversal depth (default: 1) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

### `coderag impact`

Analyze the blast radius of changing a symbol.

```bash
coderag impact UserService                    # Blast radius analysis
coderag impact UserService --depth 3          # Deeper analysis
coderag impact UserService --format json      # JSON output
```

| Option | Description |
|--------|-------------|
| `--depth` | Impact analysis depth, 1-5 (default: 3) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

### `coderag file-context`

Get LLM-optimized context for a specific file.

```bash
coderag file-context app/Services/UserService.php           # File overview
coderag file-context app/Services/UserService.php --no-source  # Without source code
```

| Option | Description |
|--------|-------------|
| `--no-source` | Exclude source code snippets |
| `--budget` | Token budget (default: 4000) |

### `coderag routes`

Find API routes by pattern with optional filtering.

```bash
coderag routes "/api/users/*"                  # Find routes by pattern
coderag routes "/api/*" --method GET           # Filter by HTTP method
coderag routes "/api/*" --no-frontend          # Exclude frontend callers
```

| Option | Description |
|--------|-------------|
| `--method` | Filter by HTTP method: GET, POST, PUT, PATCH, DELETE, ANY |
| `--no-frontend` | Exclude frontend API callers |
| `-f, --format` | Output format: markdown, json (default: markdown) |

### `coderag deps`

Show the dependency graph for a symbol.

```bash
coderag deps UserService                       # Show dependency graph
coderag deps UserService --direction dependents # Only show dependents
coderag deps UserService --depth 3             # Deeper traversal
```

| Option | Description |
|--------|-------------|
| `--direction` | dependencies, dependents, or both (default: both) |
| `--depth` | Traversal depth, 1-5 (default: 2) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

### `coderag watch`

Watch the filesystem for changes and auto-reparse.

```bash
coderag watch .                                # Watch current directory
coderag watch /path/to/project --debounce 2.0  # Custom debounce
coderag watch . --no-incremental               # Full reparse on changes
```

| Option | Description |
|--------|-------------|
| `--debounce` | Debounce delay in seconds (default: 1.0) |
| `--no-incremental` | Full reparse instead of incremental |


---

## 🤖 MCP Server

CodeRAG includes a full [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the knowledge graph to AI agents.

### Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `coderag_lookup_symbol` | Look up a symbol\'s definition, relationships, and context | `symbol`, `detail_level`, `token_budget` |
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

CodeRAG automatically detects and enriches framework-specific patterns across **11 framework detectors**:

### Laravel (PHP)
- Route definitions (`Route::get`, `Route::resource`, etc.)
- Eloquent models and relationships
- Middleware registration
- Event/listener patterns
- Blade template references

### Symfony (PHP)
- Route definitions (PHP 8 attributes, YAML, XML config)
- Service container and dependency injection
- Doctrine ORM entity mapping
- Twig template references
- Event dispatcher patterns

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
- Server and client components (`\'use server\'`, `\'use client\'`)
- API routes
- Middleware
- Dynamic routes and route groups

### Vue (JavaScript/TypeScript)
- Single-file components (`.vue`)
- Composition API (`ref`, `computed`, `watch`)
- Pinia store detection
- Component registration

### Angular (TypeScript)
- Component, Module, Injectable decorators
- Dependency injection via constructors
- Routing module configuration
- Standalone components and signals

### Django (Python)
- URL patterns and path definitions
- Model classes and field relationships
- View functions and class-based views
- Template tag detection

### Flask (Python)
- Route decorators and blueprints
- Extension detection
- Application factory patterns

### FastAPI (Python)
- Path operation decorators
- Dependency injection with `Depends()`
- Pydantic model integration
- Router mounting

### Tailwind CSS
- **v3**: `tailwind.config.js/ts/cjs/mjs` parsing, `@tailwind` directives, `content` path scanning
- **v4**: CSS-first configuration with `@import \'tailwindcss\'`, `@theme` blocks, `@source`, `@utility`, `@custom-variant`
- Theme token extraction and `@apply` edge detection
- Cross-language Tailwind class→theme token matching

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
  python:
    enabled: true
    extensions: [".py"]
  css:
    enabled: true
    extensions: [".css"]
  scss:
    enabled: true
    extensions: [".scss"]

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
│  parse │ info │ query │ analyze │ find-usages │ impact     │
│  file-context │ routes │ deps │ architecture │ frameworks  │
│  cross-language │ export │ enrich │ embed │ serve │ watch   │
│  monitor │ init                                             │
├─────────────────────────────────────────────────────────────┤
│                    Pipeline Orchestrator                      │
│  Phase 1: Discovery    → File scanning with ignore patterns  │
│  Phase 2: Hashing      → Content-hash for incremental mode   │
│  Phase 3: Extraction   → Tree-sitter AST parsing (parallel)  │
│  Phase 4: Resolution   → Cross-file reference resolution (parallel)     │
│  Phase 5: Frameworks   → Framework pattern detection (parallel)         │
│  Phase 6: Cross-lang   → PHP route ↔ JS API call matching    │
│  Phase 6b: Style edges → Component ↔ stylesheet matching     │
│  Phase 7: Enrichment   → Git metadata + PHPStan types (parallel)        │
│  Phase 8: Persistence  → SQLite batch upsert                 │
├─────────────────────────────────────────────────────────────┤
│                    Plugin System                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐         │
│  │   PHP    │  │  JavaScript  │  │   TypeScript   │         │
│  │ Extractor│  │  Extractor   │  │   Extractor    │         │
│  │ Resolver │  │  Resolver    │  │   Resolver     │         │
│  │ Laravel  │  │  React       │  │   Angular      │         │
│  │ Symfony  │  │  Express     │  │                │         │
│  │          │  │  Next.js     │  │                │         │
│  │          │  │  Vue         │  │                │         │
│  ├──────────┤  ├──────────────┤  ├────────────────┤         │
│  │  Python  │  │     CSS      │  │     SCSS       │         │
│  │ Extractor│  │  Extractor   │  │   Extractor    │         │
│  │ Resolver │  │  Resolver    │  │   Resolver     │         │
│  │ Django   │  │  Tailwind    │  │                │         │
│  │ Flask    │  │              │  │                │         │
│  │ FastAPI  │  │              │  │                │         │
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
| `core/models.py` | 41 node types, 50 edge types, data models | ~500 |
| `core/config.py` | YAML configuration system | ~350 |
| `core/registry.py` | Plugin ABCs and registry | ~200 |
| `plugins/php/` | PHP extractor, resolver, Laravel & Symfony detectors | ~1,500 |
| `plugins/javascript/` | JS extractor, resolver, React/Express/Next.js/Vue | ~2,500 |
| `plugins/typescript/` | TS extractor with interfaces, generics, Angular detector | ~2,800 |
| `plugins/python/` | Python extractor, resolver, Django/Flask/FastAPI detectors | ~2,000 |
| `plugins/css/` | CSS extractor, resolver, Tailwind detector | ~1,500 |
| `plugins/scss/` | SCSS extractor, resolver (variables, mixins, functions) | ~1,900 |
| `pipeline/` | 8-phase orchestrator, scanner, resolver, style edge matcher | ~2,100 |
| `storage/sqlite_store.py` | SQLite backend with FTS5 and WAL mode | ~800 |
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
| Python | 10 | 5,968 | 206,563 | 448,830 | ~13s |

### Mixed-Language Repositories

| Repository | Files | Nodes | Edges | Languages | Frameworks |
|------------|-------|-------|-------|-----------|------------|
| koel | 1,536 | 30,474 | 62,097 | PHP, JS, TS | Laravel |
| monica | 2,847 | 15,333 | 30,925 | PHP, JS | Laravel |
| flarum | 1,982 | 18,204 | 45,178 | PHP, JS, TS | — |
| bagisto | 1,847 | 17,167 | 47,171 | PHP, JS | Laravel |

### CSS / SCSS / Tailwind Repositories

| Project | Type | Files | Nodes | Edges | Time (s) | Queries |
|---------|------|-------|-------|-------|----------|---------|
| normalize.css | CSS | 1 | 1 | 0 | 0.4 | 0/3 |
| animate.css | CSS | 117 | 1,424 | 1,933 | 1.6 | 3/3 |
| pure-css | CSS | 57 | 1,171 | 2,368 | 1.1 | 3/3 |
| Bootstrap | SCSS | 281 | 20,854 | 35,094 | 27.3 | 3/3 |
| Bulma | SCSS | 236 | 11,267 | 15,503 | 21.4 | 3/3 |
| Foundation | SCSS | 301 | 18,040 | 33,519 | 11.6 | 3/3 |
| Tailwind Landing | Tailwind | 26 | 195 | 313 | 0.6 | 3/3 |
| Flowbite | Tailwind | 77 | 3,108 | 4,481 | 2.0 | 3/3 |
| DaisyUI | Tailwind | 246 | 2,615 | 5,201 | 3.5 | 3/3 |
| Excalidraw | Mixed | 714 | 8,379 | 24,931 | 10.9 | 3/3 |
| Cal.com | Mixed | 7,488 | 53,762 | 165,642 | 180.1 | 3/3 |
| Shadcn/ui | Mixed | 4,552 | 21,571 | 117,744 | 111.0 | 3/3 |
| **Totals** | | **14,096** | **142,387** | **406,729** | **384.2** | **33/36** |

> 17 distinct style-specific edge types detected across all styling benchmarks. Full report: [docs/benchmark-styling.md](docs/benchmark-styling.md)

### Combined Totals

| Metric | Value |
|--------|-------|
| **Repositories benchmarked** | 51 |
| **Total files parsed** | 111,809 |
| **Total nodes extracted** | ~1,298,797 |
| **Total edges created** | ~3,162,150 |
| **Query accuracy** | 91.7–100% |
| **Cross-language edges** | Detected in all mixed repos |
| **Style-specific edge types** | 17 |

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

**Test suite:** 1,308 tests across 10 test files covering models, config, storage, pipeline, export, hot-reload, framework detection, PHPStan enrichment, and CSS/SCSS parsing.

---

## 📊 Codebase Stats

| Metric | Value |
|--------|-------|
| **Total lines of code** | 32,200+ |
| **Python source files** | 75+ |
| **Test files** | 10 |
| **Tests passing** | 1,308 |
| **Language plugins** | 6 (PHP, JS, TS, Python, CSS, SCSS) |
| **Framework detectors** | 11 (Laravel, Symfony, React, Express, Next.js, Vue, Angular, Django, Flask, FastAPI, Tailwind CSS) |
| **MCP tools** | 8 |
| **MCP resources** | 3 |
| **Node types** | 41 |
| **Edge types** | 50 |

---

## 🤝 Contributing

Contributions are welcome! Here\'s how to get started:

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
- 🏗️ Additional framework detectors (NestJS, Svelte, Nuxt)
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
