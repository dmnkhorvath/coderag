# CodeGraph — Master Project Plan

> **Project:** Custom Repository Parsing Solution for LLM Codebase Understanding
> **Created:** 2026-03-10
> **Status:** Planning Phase Complete ✅
> **Languages:** PHP, JavaScript, TypeScript (modular — extensible to others)

---

## 1. Vision & Goals

### What is CodeGraph?
CodeGraph is a **self-built, modular repository parsing solution** that analyzes codebases and builds a **knowledge graph** representing the code's structure, relationships, and patterns. This graph enables LLMs to deeply understand a codebase for feature development, refactoring, and code review.

### Why Build Our Own?
After researching 110+ existing tools (see market research below), we identified critical gaps:
- **No single tool handles PHP + JS + TS equally well** — PHP always needs a dedicated parser
- **Dynamic language challenges** — magic methods, facades, dynamic imports are invisible to most tools
- **Cross-language blindness** — no tool tracks PHP backend → JS frontend connections
- **Framework-specific patterns** — Laravel, React, Vue, Next.js patterns are poorly understood
- **Lack of modularity** — existing tools are monolithic, hard to extend

### Core Principles
1. **Modular by design** — each language is a plugin, new languages added via well-defined interfaces
2. **AST-first** — Tree-sitter for fast, incremental, error-tolerant parsing
3. **Graph-native** — relationships are first-class citizens, not afterthoughts
4. **LLM-optimized output** — context formatted for maximum LLM comprehension
5. **Incremental** — only re-parse what changed (content-hash based)
6. **Cross-language aware** — PHP→JS API matching, shared types, template bridges

---

## 2. Architecture Overview

### Technology Stack
| Component | Technology | Justification |
|-----------|-----------|---------------|
| **Language** | Python 3.12+ | Rich ecosystem, Tree-sitter bindings, ML/AI integration |
| **Primary Parser** | Tree-sitter (py-tree-sitter) | Fast, incremental, error-tolerant, 100+ languages |
| **PHP Deep Parser** | nikic/PHP-Parser (via subprocess) | Most complete PHP AST, used by PHPStan/Psalm |
| **Graph Storage** | SQLite + NetworkX hybrid | Portable (single file), graph algorithms, no external DB |
| **Full-Text Search** | SQLite FTS5 | Built-in, fast, no dependencies |
| **CLI Framework** | Click | Mature, composable, well-documented |
| **MCP Server** | mcp-python-sdk | Official SDK for Model Context Protocol |
| **Testing** | pytest + pytest-cov | Standard Python testing |
| **Packaging** | pyproject.toml + hatchling | Modern Python packaging |

### Processing Pipeline (8 Phases)
```
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌────────────┐
│ 1. Discovery │───▶│ 2. Hash  │───▶│ 3. Extract │───▶│ 4. Resolve │
│ Find files   │    │ Diff     │    │ AST→Nodes  │    │ Imports    │
└─────────────┘    └──────────┘    └────────────┘    └────────────┘
       │                                                    │
       ▼                                                    ▼
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌────────────┐
│ 8. Persist   │◀──│ 7. Enrich│◀──│ 6. X-Lang  │◀──│ 5. Framewk │
│ SQLite+NX    │    │ Git/Docs │    │ PHP↔JS     │    │ Detect     │
└─────────────┘    └──────────┘    └────────────┘    └────────────┘
```

### Plugin Architecture
```
codegraph/
├── core/           # Language-agnostic engine
│   ├── pipeline.py     # Orchestrates 8-phase pipeline
│   ├── models.py       # Node, Edge, ExtractionResult dataclasses
│   ├── registry.py     # Plugin discovery & registration
│   └── config.py       # Configuration loading
├── plugins/        # Language-specific plugins
│   ├── php/            # PHP plugin (Tree-sitter + nikic/PHP-Parser)
│   │   ├── extractor.py
│   │   ├── resolver.py
│   │   └── frameworks/
│   │       └── laravel.py
│   ├── javascript/     # JavaScript plugin
│   │   ├── extractor.py
│   │   ├── resolver.py
│   │   └── frameworks/
│   │       ├── react.py
│   │       ├── vue.py
│   │       └── express.py
│   └── typescript/     # TypeScript plugin (extends JS)
│       ├── extractor.py
│       ├── resolver.py
│       └── frameworks/
│           ├── nextjs.py
│           ├── angular.py
│           └── nestjs.py
├── storage/        # Graph persistence
│   ├── sqlite_store.py
│   └── networkx_store.py
├── output/         # LLM output formatters
│   ├── markdown.py
│   ├── json_formatter.py
│   └── context_assembler.py
├── mcp/            # MCP server
│   ├── server.py
│   ├── tools.py
│   └── resources.py
└── cli/            # Command-line interface
    └── main.py
```

### Graph Schema Summary
- **25 Node Types:** File, Package, Namespace, Class, Interface, Trait, Enum, Function, Method, Property, Variable, Constant, Route, Component, Hook, Model, Migration, Middleware, Guard, Pipe, Decorator, TypeAlias, GenericParam, Module, Config
- **30 Edge Types:** extends, implements, uses_trait, calls, imports, exports, contains, instantiates, renders, passes_prop, uses_hook, provides_context, consumes_context, injects, decorated_by, has_route, guards, api_endpoint_serves, api_calls, api_matches, shares_type_contract, co_changes_with, depends_on, type_of, returns_type, parameter_type, overrides, overloads, lazy_loads, references
- **Confidence Scoring:** Every edge has a confidence score (0.0-1.0)
  - High (0.85-1.0): Static imports, explicit extends/implements
  - Medium (0.50-0.84): Framework pattern matches, API endpoint matching
  - Low (0.10-0.49): Dynamic dispatch, heuristic matches

---

## 3. Key Interfaces

The complete interface definitions are in `interfaces.py` (2,101 lines, 68KB). Key abstractions:

```python
class LanguagePlugin(ABC):
    """Every language must implement this."""
    @abstractmethod
    def get_language_id(self) -> Language: ...
    @abstractmethod
    def get_file_extensions(self) -> list[str]: ...
    @abstractmethod
    def create_extractor(self) -> ASTExtractor: ...
    @abstractmethod
    def create_resolver(self) -> ModuleResolver: ...
    @abstractmethod
    def get_framework_detectors(self) -> list[FrameworkDetector]: ...

class ASTExtractor(ABC):
    """Extracts nodes and edges from AST."""
    @abstractmethod
    def extract(self, file_path: Path, source: bytes) -> ExtractionResult: ...

class GraphStore(ABC):
    """Storage backend abstraction."""
    @abstractmethod
    def upsert_nodes(self, nodes: list[Node]) -> None: ...
    @abstractmethod
    def upsert_edges(self, edges: list[Edge]) -> None: ...
    @abstractmethod
    def query_neighbors(self, node_id: str, depth: int) -> SubGraph: ...
```

---

## 4. Implementation Roadmap

### P0 — MVP (Days 1-5)
**Goal:** Parse a PHP+JS project, build basic graph, query it
- [ ] Project scaffolding (pyproject.toml, package structure)
- [ ] Core models (Node, Edge, ExtractionResult dataclasses)
- [ ] Plugin registry with auto-discovery
- [ ] PHP plugin: Tree-sitter extractor (classes, functions, methods, imports)
- [ ] SQLite storage backend with schema
- [ ] Basic CLI: `codegraph parse /path/to/repo`
- [ ] Basic CLI: `codegraph query "show class X"`
- [ ] Markdown output formatter

### P1 — Usable (Days 6-10)
**Goal:** Full language support, module resolution, framework detection
- [ ] JavaScript plugin: Tree-sitter extractor
- [ ] TypeScript plugin: extends JS with type constructs
- [ ] Module resolver for JS/TS (ESM, CJS, TS paths, aliases)
- [ ] PHP module resolver (namespaces, autoloading)
- [ ] Laravel framework detector
- [ ] React framework detector
- [ ] Content-hash incremental updates
- [ ] Progress reporting

### P2 — Powerful (Days 11-16)
**Goal:** Cross-language intelligence, MCP server, advanced queries
- [ ] Cross-language API matching (PHP routes ↔ JS fetch calls)
- [ ] Template bridge detection (Blade, Inertia.js)
- [ ] MCP server with 8 tools and 4 resources
- [ ] Graph analysis (PageRank, blast radius, circular deps)
- [ ] Context assembler with token budgeting
- [ ] Vue/Angular/Next.js framework detectors

### P3 — Complete (Days 17-22)
**Goal:** Production polish, git enrichment, optimization
- [ ] Git metadata enrichment (change frequency, co-change, ownership)
- [ ] PHPStan type enrichment (via subprocess)
- [ ] Parallel file extraction
- [ ] Batch SQLite operations
- [ ] Comprehensive test suite
- [ ] Documentation
- [ ] `codegraph serve` with hot-reload
- [ ] `codegraph export` with multiple formats

### Performance Targets
| Codebase Size | Initial Parse | Incremental Update |
|--------------|--------------|--------------------|
| Small (<100 files) | <5s | <0.5s |
| Medium (100-1000 files) | 15-60s | <2s |
| Large (1000-10000 files) | 60-300s | <5s |
| Very Large (10000+ files) | 5-15min | <10s |

---

## 5. CLI Interface

```
Usage: codegraph [OPTIONS] COMMAND [ARGS]...

  CodeGraph — Build knowledge graphs from your codebase.

Commands:
  init      Initialize codegraph.yaml in current directory
  parse     Parse codebase and build/update knowledge graph
  query     Query the knowledge graph
  export    Export graph data for LLM consumption
  serve     Start MCP server for AI agent integration
  info      Show graph statistics and health
  validate  Validate configuration and plugin setup
```

### Key Commands
```bash
# Initialize project
codegraph init --languages php,javascript,typescript

# Parse codebase
codegraph parse /path/to/repo --incremental --parallel

# Query the graph
codegraph query "What classes extend BaseController?"
codegraph query --node UserService --depth 2 --format markdown
codegraph query --blast-radius src/Models/User.php

# Export for LLM
codegraph export --format markdown --max-tokens 8000 --focus src/Controllers/

# Start MCP server
codegraph serve --port 3000
```

---

## 6. MCP Server Tools

| Tool | Description |
|------|-------------|
| `codegraph_query` | Natural language query against the knowledge graph |
| `codegraph_get_context` | Get LLM-optimized context for a file/symbol |
| `codegraph_blast_radius` | Show impact of changing a file/symbol |
| `codegraph_find_references` | Find all references to a symbol |
| `codegraph_get_dependencies` | Get dependency tree for a file/symbol |
| `codegraph_search` | Full-text search across the codebase |
| `codegraph_get_structure` | Get high-level codebase structure overview |
| `codegraph_cross_language` | Find cross-language connections |

---

## 7. Configuration (codegraph.yaml)

```yaml
project:
  name: my-project
  root: .

languages:
  php:
    enabled: true
    extensions: [".php"]
    deep_parser: true  # Use nikic/PHP-Parser for enrichment
    frameworks:
      - laravel
  javascript:
    enabled: true
    extensions: [".js", ".jsx", ".mjs", ".cjs"]
    frameworks:
      - react
      - express
  typescript:
    enabled: true
    extensions: [".ts", ".tsx"]
    frameworks:
      - nextjs
      - nestjs

storage:
  backend: sqlite
  path: .codegraph/graph.db

output:
  default_format: markdown
  max_tokens: 8000
  detail_level: standard  # minimal | standard | detailed

ignore:
  - node_modules/
  - vendor/
  - .git/
  - "*.min.js"
  - dist/
  - build/

cross_language:
  enabled: true
  api_matching: true
  template_bridges: true
  shared_types: true

mcp:
  port: 3000
  host: localhost
```

---

## 8. Document Index

All planning documents are in `/a0/usr/projects/codebase_knowledgebuilder/`:

### Master Documents
| Document | Size | Description |
|----------|------|-------------|
| **PLAN.md** (this file) | — | Master project plan, single entry point |
| **architecture-design.md** | 172KB | Complete architecture with all design decisions |
| **interfaces.py** | 68KB | All Python interfaces, dataclasses, enums (valid Python) |

### Research Documents
| Document | Size | Description |
|----------|------|-------------|
| **research-ast-parsing.md** | 74KB | Synthesis of all AST research, architecture decisions |
| **research-treesitter-deep-dive.md** | 61KB | Tree-sitter capabilities, node types, queries |
| **research-php-parsing.md** | 75KB | PHP parsing: Tree-sitter vs nikic vs glayzzle |
| **research-js-ts-parsing.md** | 142KB | JS/TS: ESM/CJS, JSX, TypeScript, frameworks |
| **research-graph-schema.md** | 64KB | Graph schema design, storage backends, queries |
| **research-cross-language.md** | 276KB | Cross-language patterns, API matching, bridges |

### Market Research
| Document | Size | Description |
|----------|------|-------------|
| **codebase-mapping-research.md** | 39KB | 110+ repos evaluated, top 5 recommendations |
| **discovered-repos.md** | 13KB | All discovered repositories categorized |
| **repo-metrics-all.json** | 28KB | Raw GitHub metrics for 49 repositories |

### Raw Data
| File | Location | Description |
|------|----------|-------------|
| php-node-types.json | research-data/ | 305 PHP Tree-sitter node types |
| js-node-types.json | research-data/ | 226 JS Tree-sitter node types |
| ts-node-types.json | research-data/ | 324 TS Tree-sitter node types |
| tsx-node-types.json | research-data/ | TSX Tree-sitter node types |

### Total Knowledge Base: ~1MB across 13 documents

---

## 9. Key Design Decisions

| # | Decision | Rationale |
|---|----------|----------|
| 1 | Tree-sitter as primary parser | Fast (100K+ lines/sec), incremental, error-tolerant, 100+ languages |
| 2 | Multi-parser for PHP | Tree-sitter for speed + nikic/PHP-Parser for depth + PHPStan for types |
| 3 | SQLite over Neo4j | Zero infrastructure, portable single file, good enough for most codebases |
| 4 | NetworkX for graph algorithms | PageRank, shortest path, community detection without external DB |
| 5 | Plugin architecture | New languages = new plugin implementing LanguagePlugin interface |
| 6 | Content-hash incremental | SHA-256 per file, skip unchanged files, <2s for no-change re-parse |
| 7 | Confidence scoring on edges | Not all relationships are equally certain, LLMs need to know |
| 8 | MCP as primary integration | Industry standard, works with Claude Code, Cursor, Goose, Agent Zero |
| 9 | Python 3.12+ | Modern type hints, dataclasses, async support, rich ecosystem |
| 10 | Click for CLI | Composable commands, auto-help, well-tested |

---

## 10. What Makes This Different

Compared to the 110+ existing tools we researched:

1. **True PHP depth** — Multi-parser strategy handles magic methods, facades, service containers
2. **Cross-language intelligence** — PHP routes matched to JS fetch calls automatically
3. **Framework-aware** — Laravel, React, Vue, Next.js, Angular, NestJS patterns detected
4. **Modular** — add a new language by implementing one interface
5. **Zero infrastructure** — SQLite, no Neo4j/Docker/external services needed
6. **Confidence-scored** — every relationship has a reliability score
7. **LLM-optimized output** — token-budgeted context with detail levels
8. **Incremental** — sub-second updates for unchanged codebases

---

*Planning phase complete. Ready for implementation.*
