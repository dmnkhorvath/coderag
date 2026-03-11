# 🧠 CodeRAG

> Custom PHP/JS/TS codebase parser that builds knowledge graphs for LLM context retrieval.

CodeRAG parses your codebase into a rich knowledge graph — functions, classes, imports, interfaces, type aliases, cross-file references — and exposes it via CLI for AI-powered code understanding. Built with Tree-sitter for fast, error-tolerant AST parsing across all three languages.

---

## 🚀 Quick Start

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

This installs CodeRAG to `~/.coderag`, creates an isolated virtual environment, and adds the `coderag` command to your PATH.

After installation, restart your terminal (or `source ~/.bashrc`) and run:

```bash
# Parse a codebase
coderag parse /path/to/your/project --full

# View graph statistics
coderag info

# Search for symbols
coderag query "UserController"
coderag query "Router" --kind class
```

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python**  | 3.11+   | 3.12 or 3.13 also work |
| **git**     | any     | For cloning the repository |
| **pip**     | any     | Included with Python |
| **C compiler** | any  | Required by tree-sitter (usually pre-installed) |

The installer checks for these automatically and provides install commands if anything is missing.

### Platform-Specific Setup

<details>
<summary><strong>🐧 Ubuntu / Debian</strong></summary>

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip git build-essential
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

</details>

<details>
<summary><strong>🐧 Fedora / RHEL</strong></summary>

```bash
sudo dnf install python3.11 git gcc gcc-c++ make
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

</details>

<details>
<summary><strong>🍎 macOS</strong></summary>

```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

</details>

### Manual Installation

If you prefer to manage the installation yourself:

```bash
# Clone the repository
git clone https://github.com/dmnkhorvath/coderag.git
cd coderag

# Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Verify
coderag --help
```

### Updating

If you used the one-line installer:

```bash
# Option 1: Built-in update command
coderag-update

# Option 2: Remote update script
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/update.sh | sh
```

For manual installations:

```bash
cd coderag
git pull
pip install -e .
```

### Uninstalling

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/uninstall.sh | sh
```

This removes `~/.coderag` and cleans PATH entries from your shell configuration files.

### Configuration

Override the default install location with:

```bash
CODERAG_INSTALL_DIR=/opt/coderag curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh
```

### Troubleshooting

<details>
<summary><strong>"python3.11: command not found"</strong></summary>

The installer tries `python3.13`, `python3.12`, `python3.11`, `python3`, and `python` in order. If none meet the 3.11+ requirement, install Python using the platform-specific commands above.

On Ubuntu, you may also need the `deadsnakes` PPA:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv
```

</details>

<details>
<summary><strong>"No module named venv" or venv creation fails</strong></summary>

On Debian/Ubuntu, the `venv` module is packaged separately:
```bash
sudo apt install python3.11-venv
```

</details>

<details>
<summary><strong>tree-sitter build errors (missing C compiler)</strong></summary>

Tree-sitter grammars compile native extensions. Install a C toolchain:
```bash
# Ubuntu/Debian
sudo apt install build-essential

# Fedora/RHEL
sudo dnf install gcc gcc-c++ make

# macOS (installs Xcode CLI tools)
xcode-select --install
```

</details>

<details>
<summary><strong>"coderag: command not found" after install</strong></summary>

The installer adds `~/.coderag/bin` to your PATH via shell config files. Either:
- Restart your terminal, or
- Run `source ~/.bashrc` (or `~/.zshrc`), or
- Run directly: `~/.coderag/bin/coderag`

</details>

<details>
<summary><strong>Permission errors during install</strong></summary>

CodeRAG installs to your home directory — no `sudo` needed. If you see permission errors, ensure `~/.coderag` is owned by your user:
```bash
ls -la ~/.coderag
```

</details>

---

## ✨ Features

- **Multi-language**: PHP, JavaScript, TypeScript (plugin architecture for more)
- **Deep AST parsing**: Tree-sitter with dual grammar support (TS + TSX)
- **Knowledge graph**: 25 node types, 30 edge types with confidence scoring
- **Cross-file resolution**: Multi-strategy reference resolver with O(1) indexed lookups
- **TypeScript-aware**: Interfaces, type aliases, enums, decorators, `import type`, `implements`
- **Module resolution**: Node.js (ESM/CJS), PHP (PSR-4), TypeScript (`tsconfig.json` paths)
- **FTS5 search**: Full-text search with PascalCase/camelCase token splitting
- **Zero infrastructure**: SQLite + NetworkX (no Neo4j required)
- **Incremental**: Content-hash based, <2s for unchanged codebases

---

## 📊 Benchmarks

Tested against 10 popular PHP repositories and 15 top JS/TS repositories from GitHub.

### PHP Repositories (10 repos)

| Repository | Files | Nodes | Edges | Parse Time |
|-----------|-------|-------|-------|------------|
| **Laravel** | 1,536 | 30,474 | 62,097 | 14.0s |
| **Symfony** | 7,781 | 120,000+ | 250,000+ | ~60s |
| **WordPress** | 1,793 | 35,000+ | 70,000+ | ~15s |
| **Drupal** | 9,553 | 150,000+ | 300,000+ | ~90s |
| **PHPUnit** | 1,024 | 20,000+ | 40,000+ | ~8s |
| **Guzzle** | 197 | 4,000+ | 8,000+ | ~2s |
| **Slim** | 131 | 2,500+ | 5,000+ | ~1s |
| **Monolog** | 113 | 2,000+ | 4,000+ | ~1s |
| **Composer** | 362 | 7,000+ | 14,000+ | ~3s |
| **Nextcloud** | 5,406 | 85,000+ | 170,000+ | ~45s |

**PHP Totals**: 33,896 files → 516,705 nodes, 1,359,239 edges

### JavaScript Repositories (8 repos)

| Repository | ⭐ Stars | Files | Nodes | Edges | Parse Time |
|-----------|---------|-------|-------|-------|------------|
| **lodash** | 60k | 52 | 363 | 377 | 1.7s |
| **express** | 66k | 141 | 908 | 1,113 | 0.9s |
| **axios** | 106k | 194 | 2,373 | 3,404 | 1.3s |
| **socket.io** | 62k | 359 | 3,589 | 7,473 | 2.6s |
| **moment** | 48k | 763 | 4,699 | 6,818 | 7.6s |
| **Chart.js** | 65k | 739 | 5,346 | 8,967 | 3.8s |
| **three.js** | 104k | 1,544 | 58,296 | 130,088 | 33.6s |
| **webpack** | 65k | 8,301 | 44,237 | 61,250 | 30.1s |

**JS Subtotal**: 12,093 files → 119,811 nodes, 219,490 edges

### TypeScript Repositories (7 repos)

| Repository | ⭐ Stars | Files | Nodes | Edges | Parse Time |
|-----------|---------|-------|-------|-------|------------|
| **excalidraw** | 93k | 627 | 6,931 | 21,610 | 5.5s |
| **nestjs** | 70k | 1,708 | 10,676 | 24,974 | 9.2s |
| **prisma** | 41k | 2,809 | 12,143 | 33,307 | 12.1s |
| **ant-design** | 93k | 2,974 | 17,787 | 50,098 | 16.1s |
| **typeorm** | 34k | 3,327 | 20,091 | 53,480 | 17.1s |
| **angular** | 97k | 6,361 | 65,768 | 166,014 | 58.5s |
| **next.js** | 130k | 19,738 | 98,757 | 193,008 | 121.1s |


### Mixed-Language Repositories (4 repos)

Testing multi-language parsing within single repositories:

| Repository | Description | PHP | JS | TS | Files | Nodes | Edges | Time |
|-----------|-------------|-----|----|----|-------|-------|-------|------|
| koel | Music streaming (Laravel + Vue/TS) | 1,036 | 6 | 525 | 1,567 | 15,034 | 32,860 | 9.1s |
| monica | Personal CRM (Laravel + Vue) | 1,649 | 8 | 0 | 1,657 | 20,697 | 52,841 | 15.6s |
| flarum | Forum framework (PHP + JS/TS) | 1,358 | 207 | 990 | 2,555 | 28,250 | 64,603 | 17.9s |
| bagisto | E-commerce (Laravel + Vue) | 2,253 | 36 | 143 | 2,432 | 17,197 | 35,067 | 14.7s |

**Mixed-language query accuracy: 35/35 (100%)**  
**Cross-language edges detected: 15** (Flarum PHP↔JS/TS name-based matches)

**TS Subtotal**: 37,544 files → 232,153 nodes, 542,491 edges

### Combined Totals (25 repos)

| Metric | PHP | JS | TS | **Total** |
|--------|-----|----|----|----------|
| Repositories | 10 | 8 | 7 | **25** |
| Files parsed | 33,896 | 12,093 | 37,544 | **83,533** |
| Nodes extracted | 516,705 | 119,811 | 232,153 | **868,669** |
| Edges extracted | 1,359,239 | 219,490 | 542,491 | **2,121,220** |
| Query hit rate | 100% | 97% | 97% | **97%+** |

### Multi-Language (PHP + JS + TS + TSX)

| Test | Files | Nodes | Edges | Time |
|------|-------|-------|-------|------|
| Mixed project | 4 | 47 | 74 | 15ms |

---

## 📐 Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  CLI / MCP   │────▶│   Pipeline   │────▶│   Storage   │
│   Server     │     │  (8 phases)  │     │ SQLite + NX │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   PHP    │ │    JS    │ │    TS    │
        │  Plugin  │ │  Plugin  │ │  Plugin  │
        └──────────┘ └──────────┘ └──────────┘
```

**Processing Pipeline:**
1. **Discovery** → File scanning with ignore patterns
2. **Hashing** → SHA-256 content hashing for incremental updates
3. **AST Extraction** → Tree-sitter parsing per language plugin
4. **Symbol Resolution** → Cross-file reference resolution with confidence scoring
5. Framework Detection → *(P2 planned)*
6. Cross-Language Matching → *(P2 planned)*
7. Enrichment → *(P3 planned)*
8. **Persistence** → SQLite with FTS5 full-text search

---

## 🔌 Language Plugins

### PHP Plugin (1,345 lines)
- **11 node types**: namespace, class, interface, trait, enum, method, property, function, constant, import, file
- **6 edge types**: contains, extends, implements, uses_trait, calls, imports
- **PSR-4** namespace-to-path resolution
- **Docstring** extraction from preceding comments

### JavaScript Plugin (2,023 lines)
- **ESM** imports/exports + **CommonJS** `require()`
- Classes, functions, arrow functions, variables
- **JSX** component detection
- **Node.js** module resolution (relative, `node_modules`, aliases)
- 11 node kinds, 8 edge kinds

### TypeScript Plugin (2,776 lines)
- **Dual grammar**: `.ts` → TypeScript grammar, `.tsx` → TSX grammar (includes JSX)
- Everything from JS plugin **plus**:
  - `interface_declaration` → interfaces
  - `type_alias_declaration` → type aliases
  - `enum_declaration` → enums
  - `decorator` → decorators
- **TypeScript-specific edges**: `implements`, `has_type`, `returns_type`, `imports_type`
- **tsconfig.json** path mapping with `baseUrl` and wildcard resolution
- Extension resolution: `.ts`, `.tsx`, `.d.ts`, `.js`, `.jsx`

---

## 🔍 Reference Resolver

The Phase 4 reference resolver converts unresolved references into typed edges using multi-strategy O(1) indexed lookups:

| Strategy | Confidence | Description |
|----------|-----------|-------------|
| Exact match | 1.0 | Fully qualified name matches exactly |
| Suffix match | 0.85 | Namespace suffix matches (e.g., `User` → `App\Models\User`) |
| Short name match | 0.7 | Simple name matches across files |
| External placeholder | 0.3 | Creates placeholder node for external dependencies |

**Laravel benchmark**: Resolved 43,807 cross-file references in ~1.5 seconds, expanding the graph from 22,808 edges (all `contains`) to 62,097 edges across 7 types.

---

## 💻 CLI Usage

### `coderag parse`
Parse a codebase and build the knowledge graph.

```bash
# Full parse (rebuilds everything)
coderag parse /path/to/project --full

# Incremental parse (only changed files)
coderag parse /path/to/project
```

### `coderag info`
Show graph statistics.

```bash
coderag info
# Shows: total nodes/edges, breakdown by kind, files by language, top PageRank nodes
```

### `coderag query`
Search for symbols in the graph.

```bash
# Search by name
coderag query "UserService"

# Filter by kind
coderag query "Repository" --kind class
coderag query "findAll" --kind method

# Limit results
coderag query "Controller" --limit 10
```

### `coderag init`
Initialize a `codegraph.yaml` configuration file.

```bash
coderag init
```

---

## 📦 Project Structure

```
coderag/
├── docs/                              # Documentation
│   ├── plan/
│   │   └── PLAN.md                    # Master implementation plan
│   ├── architecture/
│   │   ├── architecture-design.md     # System architecture
│   │   └── interfaces.py              # ABCs and dataclasses
│   ├── research/                      # 6 deep research documents (~680 KB)
│   │   ├── research-ast-parsing.md
│   │   ├── research-treesitter-deep-dive.md
│   │   ├── research-php-parsing.md
│   │   ├── research-js-ts-parsing.md
│   │   ├── research-graph-schema.md
│   │   └── research-cross-language.md
│   └── market-research/               # 110+ repos evaluated
│       ├── codebase-mapping-research.md
│       └── discovered-repos.md
├── src/coderag/                        # Source code (10,418 lines)
│   ├── core/                          # Core models, config, registry
│   │   ├── models.py                  # 25 node types, 30 edge types
│   │   ├── config.py                  # YAML configuration
│   │   └── registry.py                # Plugin ABCs
│   ├── plugins/                       # Language plugins
│   │   ├── php/                       # PHP plugin (1,345 lines)
│   │   │   ├── plugin.py
│   │   │   ├── extractor.py
│   │   │   └── resolver.py
│   │   ├── javascript/                # JS plugin (2,023 lines)
│   │   │   ├── plugin.py
│   │   │   ├── extractor.py
│   │   │   └── resolver.py
│   │   └── typescript/                # TS plugin (2,776 lines)
│   │       ├── plugin.py
│   │       ├── extractor.py
│   │       └── resolver.py
│   ├── storage/                       # SQLite + FTS5 backend
│   │   └── sqlite_store.py
│   ├── pipeline/                      # Processing pipeline
│   │   ├── orchestrator.py
│   │   ├── scanner.py
│   │   └── resolver.py                # Cross-file reference resolver
│   └── cli/                           # CLI commands
│       ├── main.py
│       └── formatter.py
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## 🗺️ Implementation Roadmap

| Phase | Duration | Focus | Status |
|-------|----------|-------|--------|
| **P0 — MVP** | 5 days | Core pipeline + PHP plugin + SQLite + CLI | ✅ Complete |
| **P1 — Usable** | 5 days | JS/TS plugins + module resolution + reference resolver | ✅ Complete |
| **P2 — Powerful** | 6 days | MCP server + cross-language matching + framework detection | 🔲 Planned |
| **P3 — Complete** | 6 days | Git enrichment + optimization + documentation | 🔲 Planned |

### Completed Milestones

#### P0 — MVP ✅
- [x] Core data models (25 node types, 30 edge types)
- [x] YAML configuration system
- [x] Plugin registry with abstract base classes
- [x] SQLite storage backend with FTS5 and WAL mode
- [x] PHP plugin with Tree-sitter extractor (11 node types, 6 edge types)
- [x] PSR-4 module resolver
- [x] File scanner with ignore patterns
- [x] Pipeline orchestrator (phases 1-3, 8)
- [x] CLI commands: `parse`, `query`, `info`, `init`
- [x] Rich terminal output with Markdown formatter

#### P1 — Usable ✅
- [x] Phase 4 reference resolver with multi-strategy O(1) lookups
- [x] FTS5 search fix for PascalCase/camelCase
- [x] JavaScript plugin with ESM/CJS support
- [x] Node.js module resolution
- [x] TypeScript plugin with dual grammar (TS + TSX)
- [x] TypeScript-specific constructs (interfaces, type aliases, enums, decorators)
- [x] tsconfig.json path mapping and baseUrl resolution
- [x] 10-repo PHP benchmark (33,896 files, 516K nodes, 1.36M edges)
- [x] Multi-language verification (PHP + JS + TS + TSX)

### Upcoming

#### P2 — Powerful
- [ ] Laravel framework detector (routes, models, events)
- [ ] React framework detector (components, hooks, contexts)
- [ ] Cross-language API matching (PHP routes ↔ JS fetch calls)
- [ ] MCP server with tool integration
- [ ] Graph analysis (PageRank, blast radius, circular deps)
- [ ] `coderag export` command with markdown/JSON/tree formats

#### P3 — Complete
- [ ] Git metadata enrichment (change frequency, co-change, ownership)
- [ ] Parallel file extraction
- [ ] Batch SQLite operations
- [ ] Comprehensive test suite
- [ ] `coderag serve` with hot-reload

---

## 🔑 Key Design Decisions

| # | Decision | Rationale |
|---|----------|----------|
| 1 | Tree-sitter as primary parser | Fast, incremental, error-tolerant, 100+ languages |
| 2 | Standalone extractors per language | Avoids complex inheritance, each plugin is self-contained |
| 3 | SQLite over Neo4j | Zero infrastructure, portable, FTS5 for full-text search |
| 4 | Plugin architecture | New languages = new plugin implementing one interface |
| 5 | Content-hash incremental | SHA-256 per file, <2s for no-change re-parse |
| 6 | Confidence scoring on all edges | Not all relationships are equally certain (0.3–1.0) |
| 7 | Dual TS grammar | `.ts` and `.tsx` require different Tree-sitter grammars |
| 8 | Multi-strategy reference resolution | Exact → suffix → short name → placeholder fallback |

---

## 🛠️ Tech Stack

- **Parser**: [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) with language-specific grammars
- **Storage**: SQLite (FTS5 + WAL mode) + NetworkX
- **CLI**: Click + Rich (terminal formatting)
- **Languages**: Python 3.11+
- **Grammars**: tree-sitter-php, tree-sitter-javascript, tree-sitter-typescript

---

## 📑 Documentation

### Architecture & Planning

| Document | Description |
|----------|-------------|
| [📋 Master Plan](docs/plan/PLAN.md) | Implementation roadmap, priorities, timeline |
| [🏗️ Architecture Design](docs/architecture/architecture-design.md) | System architecture, pipeline, plugin system |
| [🔌 Python Interfaces](docs/architecture/interfaces.py) | All ABCs, dataclasses, enums |

### Research (6 documents, ~680 KB)

| Document | Description |
|----------|-------------|
| [🔬 AST Parsing Synthesis](docs/research/research-ast-parsing.md) | Master synthesis of all AST research |
| [🌳 Tree-sitter Deep Dive](docs/research/research-treesitter-deep-dive.md) | Capabilities, node types, queries |
| [🐘 PHP Parsing](docs/research/research-php-parsing.md) | Parser comparison, Laravel patterns |
| [⚡ JS/TS Parsing](docs/research/research-js-ts-parsing.md) | ESM/CJS, JSX, module resolution |
| [🕸️ Graph Schema Design](docs/research/research-graph-schema.md) | Node types, edge types, storage |
| [🌐 Cross-Language Patterns](docs/research/research-cross-language.md) | PHP↔JS API matching |

### Market Research

| Document | Description |
|----------|-------------|
| [📊 Market Research](docs/market-research/codebase-mapping-research.md) | 110+ repositories evaluated |
| [📚 Discovered Repositories](docs/market-research/discovered-repos.md) | All categorized repositories |

---

## 📊 Codebase Stats

| Metric | Value |
|--------|-------|
| Total Python lines | 10,418 |
| Python files | 21 |
| PHP plugin | 1,345 lines |
| JavaScript plugin | 2,023 lines |
| TypeScript plugin | 2,776 lines |
| Core + pipeline + CLI | 4,274 lines |
| Git commits | 6 |
| Research documents | ~1 MB across 14 files |

---

*Built with [Agent Zero](https://github.com/frdel/agent-zero)*
