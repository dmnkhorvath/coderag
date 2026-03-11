# 🧠 CodeRAG

> Custom PHP/JS/TS codebase parser that builds knowledge graphs for LLM context retrieval.

CodeRAG parses your codebase into a rich knowledge graph — functions, classes, imports, API routes, cross-language bridges — and exposes it via an MCP server for AI-powered code understanding.

---

## ✨ Features

- **Multi-language**: PHP, JavaScript, TypeScript (plugin architecture for more)
- **Deep AST parsing**: Tree-sitter primary + nikic/PHP-Parser for PHP depth
- **Knowledge graph**: 25 node types, 30 edge types with confidence scoring
- **Cross-language detection**: PHP backend ↔ JS frontend API matching
- **Framework-aware**: Laravel, React, Vue, Express, Next.js patterns
- **MCP integration**: 8 tools for Claude Code / Cursor / Agent Zero
- **Zero infrastructure**: SQLite + NetworkX (no Neo4j required)
- **Incremental**: Content-hash based, <2s for unchanged codebases

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
1. Discovery → 2. Hashing → 3. AST Extraction → 4. Symbol Resolution
5. Framework Detection → 6. Cross-Language Matching → 7. Enrichment → 8. Persistence

---

## 📑 Documentation

### Master Documents

| Document | Description |
|----------|-------------|
| [📋 Master Plan](docs/plan/PLAN.md) | Implementation roadmap, priorities, timeline (~22 days) |
| [🏗️ Architecture Design](docs/architecture/architecture-design.md) | Complete system architecture, pipeline, plugin system, MCP integration |
| [🔌 Python Interfaces](docs/architecture/interfaces.py) | All ABCs, dataclasses, enums (25 node types, 30 edge types) |

### Research Documents

| Document | Description |
|----------|-------------|
| [🔬 AST Parsing Synthesis](docs/research/research-ast-parsing.md) | Master synthesis of all AST research and architecture decisions |
| [🌳 Tree-sitter Deep Dive](docs/research/research-treesitter-deep-dive.md) | Capabilities, node types, queries for PHP/JS/TS |
| [🐘 PHP Parsing](docs/research/research-php-parsing.md) | Tree-sitter vs nikic vs glayzzle, Laravel patterns |
| [⚡ JS/TS Parsing](docs/research/research-js-ts-parsing.md) | ESM/CJS, JSX, frameworks, module resolution |
| [🕸️ Graph Schema Design](docs/research/research-graph-schema.md) | Node types, edge types, storage backends, queries |
| [🌐 Cross-Language Patterns](docs/research/research-cross-language.md) | PHP↔JS API matching, template bridges, shared types |

### Market Research

| Document | Description |
|----------|-------------|
| [📊 Market Research](docs/market-research/codebase-mapping-research.md) | 110+ repositories evaluated, top 5 recommendations |
| [📚 Discovered Repositories](docs/market-research/discovered-repos.md) | All discovered and categorized repositories |

---

## 🗺️ Implementation Roadmap

| Phase | Duration | Focus | Status |
|-------|----------|-------|--------|
| **P0 — MVP** | 5 days | Core pipeline + PHP plugin + SQLite + basic CLI | 🔲 Not started |
| **P1 — Usable** | 5 days | JS/TS plugins + module resolution + framework detection | 🔲 Not started |
| **P2 — Powerful** | 6 days | MCP server + cross-language matching + advanced queries | 🔲 Not started |
| **P3 — Complete** | 6 days | Git enrichment + optimization + documentation | 🔲 Not started |

---

## 🔑 Key Design Decisions

| # | Decision | Rationale |
|---|----------|----------|
| 1 | Tree-sitter as primary parser | Fast, incremental, error-tolerant, 100+ languages |
| 2 | Multi-parser for PHP | Tree-sitter for speed + nikic for depth + PHPStan for types |
| 3 | SQLite over Neo4j | Zero infrastructure, portable, sufficient for most codebases |
| 4 | Plugin architecture | New languages = new plugin implementing one interface |
| 5 | Content-hash incremental | SHA-256 per file, <2s for no-change re-parse |
| 6 | Confidence scoring | Not all relationships are equally certain |
| 7 | MCP as primary integration | Industry standard for AI tool integration |

---

## 🛠️ Tech Stack

- **Parser**: [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter) + [nikic/PHP-Parser](https://github.com/nikic/PHP-Parser)
- **Storage**: SQLite (FTS5) + NetworkX
- **CLI**: Click
- **MCP**: mcp-python-sdk
- **Languages**: Python 3.11+

---

## 📦 Project Structure

```
coderag/
├── docs/                    # All documentation
│   ├── plan/               # Master plan & roadmap
│   ├── architecture/       # Architecture & interfaces
│   ├── research/           # Deep research documents
│   └── market-research/    # Market analysis
├── src/coderag/            # Source code
│   ├── plugins/            # Language plugins (PHP, JS, TS)
│   ├── storage/            # SQLite + NetworkX backends
│   ├── pipeline/           # 8-phase processing pipeline
│   ├── mcp/               # MCP server implementation
│   └── cli/               # CLI commands
├── tests/                  # Test suite
├── pyproject.toml          # Project configuration
└── README.md               # This file
```

---

## 📊 Research Scope

- **110+ repositories** evaluated in market research
- **49 repositories** with full metrics (stars, forks, activity, language support)
- **6 deep research documents** (~680 KB) covering AST parsing, graph schemas, cross-language patterns
- **~1 MB total** knowledge base across 14 documents

---

*Built with [Agent Zero](https://github.com/frdel/agent-zero)*
