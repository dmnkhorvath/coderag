# CodeGraph Architecture Design

> **Version**: 1.0.0  
> **Date**: 2026-03-10  
> **Status**: Design Complete — Ready for Implementation  
> **Author**: Agent Zero Master Developer  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Structure](#2-project-structure)
3. [Plugin / Module System for Language Support](#3-plugin--module-system-for-language-support)
4. [Core Interfaces & Abstractions](#4-core-interfaces--abstractions)
5. [Data Flow Architecture](#5-data-flow-architecture)
6. [Configuration System](#6-configuration-system)
7. [CLI Interface Design](#7-cli-interface-design)
8. [MCP Server Integration](#8-mcp-server-integration)
9. [Storage Architecture](#9-storage-architecture)
10. [Testing Strategy](#10-testing-strategy)
11. [Dependency Management](#11-dependency-management)
12. [Implementation Roadmap](#12-implementation-roadmap)

---

## 1. Executive Summary

### 1.1 What is CodeGraph?

CodeGraph is a **production-ready Python tool** that parses codebases (PHP, JavaScript, TypeScript — with extensible language support) and builds a **knowledge graph** that LLMs can query to understand code structure, relationships, and architecture.

It transforms raw source code into a structured, queryable graph of **25 node types** and **30 edge types**, stored in a portable **SQLite database** with **NetworkX** for graph algorithms. The graph is exposed via an **MCP server** for seamless LLM integration, or via CLI for direct querying.

### 1.2 Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary parser | **Tree-sitter** (py-tree-sitter) | Fast (~5-50ms/file), incremental, error-tolerant, multi-language |
| PHP name resolution | **nikic/PHP-Parser** (subprocess) | De facto standard, built-in NameResolver visitor |
| PHP type enrichment | **PHPStan/Larastan** (subprocess) | Resolves facades, container bindings, Eloquent types |
| JS/TS module resolution | **Custom Python ModuleResolver** | Must handle ESM, CJS, TS paths, aliases, exports field |
| Graph storage | **SQLite** (WAL + FTS5) | Portable, zero-infra, sub-ms queries, single file |
| Graph algorithms | **NetworkX** (in-memory) | PageRank, centrality, shortest path for context ranking |
| Output format | **Structured Markdown** with token budgeting | Optimized for LLM context windows |
| Schema | **25 node types, 30 edge types** | Unified across PHP/JS/TS with language-specific extensions |
| Incremental updates | **Content-hash** based file tracking | Skip unchanged files, re-parse only modified |
| CLI framework | **Click** | Composable, well-documented, supports groups and plugins |
| MCP SDK | **mcp** (official Python SDK) | Standard protocol for LLM tool integration |
| Language support | **Plugin architecture** | Each language is a self-contained plugin implementing defined interfaces |

### 1.3 Performance Targets (5,000-file codebase)

| Phase | Target | Notes |
|-------|--------|-------|
| File discovery | <1s | Filesystem scan + gitignore filtering |
| Tree-sitter parsing | 25-50s | ~5-10ms/file average |
| Name/module resolution | 15-45s | PHP subprocess + JS/TS path resolution |
| Framework detection | 5-10s | Route/model/event extraction |
| Cross-language matching | 2-5s | URL pattern matching |
| Graph construction | 2-5s | SQLite inserts + index building |
| **Total initial build** | **50-120s** | |
| **Incremental update** | **<2s** | Content-hash skip for unchanged files |

### 1.4 Design Principles

1. **Plugin-first**: The core engine is language-agnostic. All language-specific logic lives in plugins.
2. **Portable**: Single SQLite file output. No external services required.
3. **Incremental**: Content-hash tracking ensures only changed files are re-parsed.
4. **LLM-optimized**: Output formats are designed for token efficiency with progressive detail levels.
5. **Confidence-scored**: Every edge carries a confidence score (0.0–1.0) indicating reliability.
6. **Production-grade**: Comprehensive error handling, logging, progress reporting, and graceful degradation.

---

## 2. Project Structure

### 2.1 Directory Layout

```
codegraph/
├── pyproject.toml                  # Project metadata, dependencies, entry points
├── README.md                       # Project documentation
├── LICENSE                         # MIT License
├── codegraph.example.yaml          # Example configuration file
├── .gitignore
│
├── src/
│   └── codegraph/                  # Main package (src layout)
│       ├── __init__.py             # Package init, version
│       ├── __main__.py             # python -m codegraph entry point
│       │
│       ├── cli/                    # CLI layer (Click commands)
│       │   ├── __init__.py
│       │   ├── main.py             # Root CLI group
│       │   ├── init_cmd.py         # codegraph init
│       │   ├── parse_cmd.py        # codegraph parse
│       │   ├── query_cmd.py        # codegraph query
│       │   ├── export_cmd.py       # codegraph export
│       │   └── serve_cmd.py        # codegraph serve (MCP)
│       │
│       ├── core/                   # Core engine (language-agnostic)
│       │   ├── __init__.py
│       │   ├── config.py           # Configuration loading & validation
│       │   ├── pipeline.py         # 8-phase orchestration pipeline
│       │   ├── discovery.py        # Phase 1: Project discovery
│       │   ├── file_scanner.py     # Phase 2: File discovery & hashing
│       │   ├── extractor.py        # Phase 3: Structural extraction coordinator
│       │   ├── resolver.py         # Phase 4: Name/module resolution coordinator
│       │   ├── framework.py        # Phase 5: Framework detection coordinator
│       │   ├── cross_language.py   # Phase 6: Cross-language matching
│       │   ├── enrichment.py       # Phase 7: Enrichment (git, metrics, PageRank)
│       │   ├── progress.py         # Progress reporting (callbacks, events)
│       │   └── errors.py           # Custom exception hierarchy
│       │
│       ├── graph/                  # Graph data model & storage
│       │   ├── __init__.py
│       │   ├── models.py           # Node, Edge, GraphSummary dataclasses
│       │   ├── store.py            # GraphStore abstract + SQLite implementation
│       │   ├── sqlite_store.py     # SQLite + FTS5 + WAL implementation
│       │   ├── networkx_bridge.py  # NetworkX projection for algorithms
│       │   ├── queries.py          # Pre-built query library (CTE traversals)
│       │   └── schema.py           # DDL, migrations, schema version tracking
│       │
│       ├── plugins/                # Language plugin system
│       │   ├── __init__.py         # Plugin registry, auto-discovery
│       │   ├── base.py             # Abstract base classes for plugins
│       │   ├── registry.py         # Plugin registration & lifecycle
│       │   │
│       │   ├── php/                # PHP language plugin
│       │   │   ├── __init__.py     # Plugin registration entry point
│       │   │   ├── plugin.py       # PHPPlugin(LanguagePlugin)
│       │   │   ├── extractor.py    # PHP AST extraction (tree-sitter queries)
│       │   │   ├── resolver.py     # PHP name resolution (nikic/PHP-Parser)
│       │   │   ├── frameworks/     # PHP framework detectors
│       │   │   │   ├── __init__.py
│       │   │   │   ├── laravel.py  # Laravel routes, models, events, etc.
│       │   │   │   └── symfony.py  # Symfony (future)
│       │   │   ├── enrichment.py   # PHPStan/Larastan integration
│       │   │   └── queries.scm     # Tree-sitter query patterns for PHP
│       │   │
│       │   ├── javascript/         # JavaScript language plugin
│       │   │   ├── __init__.py
│       │   │   ├── plugin.py       # JavaScriptPlugin(LanguagePlugin)
│       │   │   ├── extractor.py    # JS AST extraction
│       │   │   ├── resolver.py     # JS module resolution (ESM/CJS)
│       │   │   ├── frameworks/     # JS framework detectors
│       │   │   │   ├── __init__.py
│       │   │   │   ├── react.py    # React components, hooks, context
│       │   │   │   ├── nextjs.py   # Next.js file-based routing, RSC
│       │   │   │   ├── vue.py      # Vue SFC, Composition API
│       │   │   │   ├── angular.py  # Angular decorators, DI
│       │   │   │   ├── express.py  # Express/Fastify routes
│       │   │   │   └── nestjs.py   # NestJS modules, controllers
│       │   │   └── queries.scm     # Tree-sitter query patterns for JS
│       │   │
│       │   └── typescript/         # TypeScript language plugin
│       │       ├── __init__.py
│       │       ├── plugin.py       # TypeScriptPlugin(LanguagePlugin)
│       │       ├── extractor.py    # TS-specific extraction (interfaces, generics, etc.)
│       │       ├── resolver.py     # TS module resolution (paths, baseUrl)
│       │       └── queries.scm     # Tree-sitter query patterns for TS
│       │
│       ├── output/                 # Output formatting for LLM consumption
│       │   ├── __init__.py
│       │   ├── base.py             # OutputFormatter abstract base
│       │   ├── markdown.py         # Structured Markdown formatter
│       │   ├── json_fmt.py         # JSON output formatter
│       │   ├── tree.py             # Aider-style tree format
│       │   ├── context.py          # Token-budgeted context assembly
│       │   └── relevance.py        # Relevance scoring (PageRank + multi-factor)
│       │
│       ├── mcp/                    # MCP server integration
│       │   ├── __init__.py
│       │   ├── server.py           # MCP server setup & lifecycle
│       │   ├── tools.py            # MCP tool definitions
│       │   └── resources.py        # MCP resource definitions
│       │
│       └── utils/                  # Shared utilities
│           ├── __init__.py
│           ├── hashing.py          # Content hashing (SHA-256)
│           ├── gitignore.py        # .gitignore pattern matching
│           ├── treesitter.py       # Tree-sitter helpers (parser pool, query cache)
│           ├── subprocess.py       # Subprocess management (PHP-Parser, PHPStan)
│           ├── logging.py          # Structured logging setup
│           └── tokens.py           # Token counting utilities
│
├── tests/                          # Test suite (mirrors src structure)
│   ├── conftest.py                 # Shared fixtures
│   ├── __init__.py
│   │
│   ├── unit/                       # Unit tests
│   │   ├── __init__.py
│   │   ├── core/
│   │   │   ├── test_config.py
│   │   │   ├── test_pipeline.py
│   │   │   ├── test_discovery.py
│   │   │   ├── test_file_scanner.py
│   │   │   └── test_cross_language.py
│   │   ├── graph/
│   │   │   ├── test_models.py
│   │   │   ├── test_sqlite_store.py
│   │   │   ├── test_networkx_bridge.py
│   │   │   └── test_queries.py
│   │   ├── plugins/
│   │   │   ├── php/
│   │   │   │   ├── test_extractor.py
│   │   │   │   ├── test_resolver.py
│   │   │   │   └── test_laravel.py
│   │   │   ├── javascript/
│   │   │   │   ├── test_extractor.py
│   │   │   │   ├── test_resolver.py
│   │   │   │   └── test_react.py
│   │   │   └── typescript/
│   │   │       ├── test_extractor.py
│   │   │       └── test_resolver.py
│   │   └── output/
│   │       ├── test_markdown.py
│   │       ├── test_context.py
│   │       └── test_relevance.py
│   │
│   ├── integration/                # Integration tests
│   │   ├── __init__.py
│   │   ├── test_full_pipeline.py
│   │   ├── test_mcp_server.py
│   │   └── test_incremental.py
│   │
│   └── fixtures/                   # Test fixtures (real code samples)
│       ├── php/
│       │   ├── laravel-app/         # Minimal Laravel app structure
│       │   │   ├── composer.json
│       │   │   ├── routes/
│       │   │   │   └── api.php
│       │   │   ├── app/
│       │   │   │   ├── Models/
│       │   │   │   │   └── User.php
│       │   │   │   ├── Http/
│       │   │   │   │   └── Controllers/
│       │   │   │   │       └── UserController.php
│       │   │   │   └── Services/
│       │   │   │       └── UserService.php
│       │   │   └── config/
│       │   │       └── app.php
│       │   └── standalone/          # Standalone PHP files
│       │       ├── classes.php
│       │       └── functions.php
│       ├── javascript/
│       │   ├── react-app/           # Minimal React app
│       │   │   ├── package.json
│       │   │   ├── src/
│       │   │   │   ├── App.jsx
│       │   │   │   ├── components/
│       │   │   │   │   └── UserList.jsx
│       │   │   │   └── hooks/
│       │   │   │       └── useUsers.js
│       │   │   └── vite.config.js
│       │   └── express-api/         # Minimal Express API
│       │       ├── package.json
│       │       ├── index.js
│       │       └── routes/
│       │           └── users.js
│       ├── typescript/
│       │   ├── nextjs-app/          # Minimal Next.js app
│       │   │   ├── package.json
│       │   │   ├── tsconfig.json
│       │   │   └── app/
│       │   │       ├── page.tsx
│       │   │       ├── layout.tsx
│       │   │       └── api/
│       │   │           └── users/
│       │   │               └── route.ts
│       │   └── standalone/
│       │       ├── interfaces.ts
│       │       ├── generics.ts
│       │       └── decorators.ts
│       └── mixed/                   # Cross-language fixtures
│           └── laravel-react/       # Laravel + React SPA
│               ├── composer.json
│               ├── package.json
│               ├── routes/
│               │   └── api.php
│               ├── app/
│               │   └── Http/
│               │       └── Controllers/
│               │           └── ApiController.php
│               └── resources/
│                   └── js/
│                       ├── app.jsx
│                       └── api/
│                           └── client.js
│
└── docs/                           # Documentation
    ├── getting-started.md
    ├── configuration.md
    ├── plugins.md                   # How to write a language plugin
    ├── mcp-tools.md                 # MCP tool reference
    ├── query-cookbook.md             # Common query patterns
    └── architecture.md              # This document (symlinked)
```

### 2.2 Design Rationale

**src layout**: Using `src/codegraph/` prevents accidental imports from the project root during development. This is the [recommended layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) for distributable packages.

**Plugin directories**: Each language plugin is a self-contained package under `plugins/`. This allows:
- Independent development and testing
- Optional installation (e.g., skip PHP plugin if not needed)
- Clear ownership boundaries
- Framework detectors nested within their language plugin

**Test mirroring**: The test directory mirrors the source structure exactly, making it trivial to find tests for any module.

**Fixtures as real code**: Test fixtures are minimal but realistic project structures, not synthetic AST fragments. This ensures tests validate real-world parsing behavior.

---

## 3. Plugin / Module System for Language Support

### 3.1 Plugin Architecture Overview

The plugin system is the **most critical architectural component**. It ensures the core engine remains language-agnostic while allowing rich, language-specific behavior.

```
┌─────────────────────────────────────────────────────────────┐
│                     Core Pipeline Engine                      │
│  (discovery → hashing → extraction → resolution → ...)       │
│                                                              │
│  Calls plugin methods via LanguagePlugin interface            │
└──────────────┬──────────────┬──────────────┬────────────────┘
               │              │              │
       ┌───────▼──────┐ ┌────▼─────┐ ┌──────▼───────┐
       │  PHP Plugin   │ │ JS Plugin│ │  TS Plugin   │
       │              │ │          │ │              │
       │ • extractor  │ │ • extractor│ │ • extractor  │
       │ • resolver   │ │ • resolver │ │ • resolver   │
       │ • frameworks │ │ • frameworks│ │ • frameworks │
       │   - laravel  │ │   - react  │ │   (inherits  │
       │   - symfony  │ │   - nextjs │ │    from JS)  │
       │ • enrichment │ │   - vue    │ │              │
       │   - phpstan  │ │   - express│ │              │
       └──────────────┘ └──────────┘ └──────────────┘
```

### 3.2 Plugin Discovery & Registration

Plugins are discovered via **Python entry points** (for installed packages) and **explicit registration** (for built-in plugins).

```python
# pyproject.toml — entry point registration
[project.entry-points."codegraph.plugins"]
php = "codegraph.plugins.php:PHPPlugin"
javascript = "codegraph.plugins.javascript:JavaScriptPlugin"
typescript = "codegraph.plugins.typescript:TypeScriptPlugin"
```

```python
# src/codegraph/plugins/registry.py

from importlib.metadata import entry_points
from typing import Dict, Type
from codegraph.plugins.base import LanguagePlugin

class PluginRegistry:
    """Central registry for language plugins."""

    def __init__(self):
        self._plugins: Dict[str, LanguagePlugin] = {}
        self._plugin_classes: Dict[str, Type[LanguagePlugin]] = {}

    def discover(self) -> None:
        """Auto-discover plugins via entry points."""
        eps = entry_points(group="codegraph.plugins")
        for ep in eps:
            cls = ep.load()
            self._plugin_classes[ep.name] = cls

    def register(self, name: str, plugin_class: Type[LanguagePlugin]) -> None:
        """Explicitly register a plugin class."""
        self._plugin_classes[name] = plugin_class

    def initialize(self, config: "CodeGraphConfig") -> None:
        """Initialize all registered plugins with config."""
        for name, cls in self._plugin_classes.items():
            plugin = cls(config)
            plugin.setup()  # Install grammars, validate dependencies
            self._plugins[name] = plugin

    def get_plugin_for_file(self, file_path: str) -> LanguagePlugin | None:
        """Return the appropriate plugin for a given file."""
        for plugin in self._plugins.values():
            if plugin.can_handle(file_path):
                return plugin
        return None

    def get_plugin(self, name: str) -> LanguagePlugin | None:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def all_plugins(self) -> list[LanguagePlugin]:
        """Return all initialized plugins."""
        return list(self._plugins.values())

    @property
    def supported_extensions(self) -> set[str]:
        """All file extensions supported across all plugins."""
        exts = set()
        for plugin in self._plugins.values():
            exts.update(plugin.file_extensions)
        return exts
```

### 3.3 Plugin Lifecycle

```
1. DISCOVERY    → PluginRegistry.discover() loads entry points
2. REGISTRATION → Plugin classes registered in registry
3. INITIALIZATION → PluginRegistry.initialize(config) creates instances
4. SETUP        → plugin.setup() installs grammars, checks dependencies
5. EXTRACTION   → plugin.extract(file_path, tree) called per file
6. RESOLUTION   → plugin.resolve(nodes, edges) called after extraction
7. FRAMEWORK    → plugin.detect_frameworks(nodes, edges) called after resolution
8. ENRICHMENT   → plugin.enrich(nodes, edges) called optionally
9. TEARDOWN     → plugin.teardown() cleanup resources
```

### 3.4 What Each Plugin Provides

Every language plugin must provide:

| Component | Interface | Purpose |
|-----------|-----------|--------|
| **File matching** | `can_handle(path)`, `file_extensions` | Determine which files this plugin processes |
| **Grammar setup** | `setup()` | Install/configure tree-sitter grammar |
| **AST extraction** | `extract(file_path, tree) → (nodes, edges)` | Extract nodes and edges from parsed AST |
| **Tree-sitter queries** | `get_queries() → dict[str, str]` | Named SCM query patterns for the language |
| **Node type mapping** | `node_type_map() → dict` | Map AST node types to graph node types |
| **Name resolution** | `resolve(nodes, edges) → (nodes, edges)` | Resolve imports, qualified names |
| **Framework detectors** | `framework_detectors() → list[FrameworkDetector]` | Detect framework-specific patterns |
| **Module system** | `detect_module_system(file_path) → ModuleSystem` | Detect ESM/CJS/namespace/etc. |

Optionally:
| Component | Interface | Purpose |
|-----------|-----------|--------|
| **Enrichment** | `enrich(nodes, edges) → (nodes, edges)` | Type enrichment (PHPStan, etc.) |
| **Cross-language** | `get_api_endpoints() → list[Endpoint]` | Expose API endpoints for cross-lang matching |
| **Cross-language** | `get_api_calls() → list[APICall]` | Expose API call sites for cross-lang matching |

### 3.5 TypeScript Plugin Inheritance

The TypeScript plugin **extends** the JavaScript plugin, adding TS-specific constructs:

```python
class TypeScriptPlugin(JavaScriptPlugin):
    """TypeScript plugin — extends JavaScript with type system constructs."""

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def file_extensions(self) -> set[str]:
        return {".ts", ".tsx", ".mts", ".cts"}

    def get_grammar_name(self) -> str:
        return "typescript"  # or "tsx" for .tsx files

    def extract(self, file_path: str, tree: "Tree") -> tuple[list[Node], list[Edge]]:
        # Get base JS extraction
        nodes, edges = super().extract(file_path, tree)
        # Add TS-specific: interfaces, type aliases, enums, generics, decorators
        ts_nodes, ts_edges = self._extract_typescript_constructs(file_path, tree)
        nodes.extend(ts_nodes)
        edges.extend(ts_edges)
        return nodes, edges
```

### 3.6 Adding a New Language

To add support for a new language (e.g., Go, Rust, Python):

1. **Create plugin directory**: `src/codegraph/plugins/go/`
2. **Implement `LanguagePlugin`**: Create `plugin.py` with all required methods
3. **Write tree-sitter queries**: Create `queries.scm` with extraction patterns
4. **Add framework detectors**: Create `frameworks/` directory if needed
5. **Register entry point**: Add to `pyproject.toml` under `[project.entry-points."codegraph.plugins"]`
6. **Add tests**: Create `tests/unit/plugins/go/` with extraction and resolution tests
7. **Add fixtures**: Create `tests/fixtures/go/` with sample Go projects

No changes to the core engine are required.

---

## 4. Core Interfaces & Abstractions

All interfaces are defined as Python `Protocol` classes (structural subtyping) with `ABC` fallbacks for runtime enforcement. Full implementations are in the companion file `interfaces.py`.

### 4.1 Interface Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        Core Interfaces                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  LanguagePlugin          The main plugin contract                │
│    ├── ASTExtractor      Extracts nodes/edges from AST           │
│    ├── ModuleResolver    Resolves import paths to files          │
│    └── FrameworkDetector Detects framework-specific patterns     │
│                                                                  │
│  GraphStore              Storage backend abstraction             │
│    └── SQLiteGraphStore  Concrete SQLite implementation          │
│                                                                  │
│  GraphAnalyzer           Graph algorithm abstraction             │
│    └── NetworkXAnalyzer  Concrete NetworkX implementation        │
│                                                                  │
│  OutputFormatter         Formats graph data for consumption      │
│    ├── MarkdownFormatter Structured Markdown output              │
│    ├── JSONFormatter     JSON output                             │
│    └── TreeFormatter     Aider-style tree format                 │
│                                                                  │
│  CrossLanguageMatcher    Matches cross-language connections       │
│                                                                  │
│  ContextAssembler        Token-budgeted context for LLMs         │
│                                                                  │
│  ProgressReporter        Reports pipeline progress               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Model Classes

These are the core data structures that flow through the pipeline:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class NodeKind(str, Enum):
    """All 25 node types in the graph."""
    # File-level (3)
    FILE = "file"
    DIRECTORY = "directory"
    PACKAGE = "package"
    # Declaration-level (10)
    CLASS = "class"
    INTERFACE = "interface"
    TRAIT = "trait"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    CONSTANT = "constant"
    ENUM = "enum"
    TYPE_ALIAS = "type_alias"
    VARIABLE = "variable"
    # Structural (3)
    NAMESPACE = "namespace"
    MODULE = "module"
    PARAMETER = "parameter"
    # Import/Export (3)
    IMPORT = "import"
    EXPORT = "export"
    DECORATOR = "decorator"
    # Framework-specific (6)
    ROUTE = "route"
    COMPONENT = "component"
    HOOK = "hook"
    MODEL = "model"
    EVENT = "event"
    MIDDLEWARE = "middleware"


class EdgeKind(str, Enum):
    """All 30 edge types in the graph."""
    # Structural (3)
    CONTAINS = "contains"
    DEFINED_IN = "defined_in"
    MEMBER_OF = "member_of"
    # Inheritance & Type System (8)
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    USES_TRAIT = "uses_trait"
    HAS_TYPE = "has_type"
    RETURNS_TYPE = "returns_type"
    GENERIC_OF = "generic_of"
    UNION_OF = "union_of"
    INTERSECTION_OF = "intersection_of"
    # Dependency (6)
    IMPORTS = "imports"
    IMPORTS_TYPE = "imports_type"
    EXPORTS = "exports"
    RE_EXPORTS = "re_exports"
    DYNAMIC_IMPORTS = "dynamic_imports"
    DEPENDS_ON = "depends_on"
    # Call Graph (4)
    CALLS = "calls"
    INSTANTIATES = "instantiates"
    DISPATCHES_EVENT = "dispatches_event"
    LISTENS_TO = "listens_to"
    # Framework (5)
    ROUTES_TO = "routes_to"
    RENDERS = "renders"
    PASSES_PROP = "passes_prop"
    USES_HOOK = "uses_hook"
    PROVIDES_CONTEXT = "provides_context"
    # Cross-Language (4)
    API_CALLS = "api_calls"
    API_SERVES = "api_serves"
    SHARES_TYPE_CONTRACT = "shares_type_contract"
    CO_CHANGES_WITH = "co_changes_with"


@dataclass
class Node:
    """A node in the code knowledge graph."""
    id: str                          # Unique: "file_path:start_line:name" or qualified_name
    kind: NodeKind                   # Node type from registry
    name: str                        # Short name (e.g., "UserService")
    qualified_name: str              # Fully-qualified name (e.g., "App\\Services\\UserService")
    file_path: str                   # Relative to project root
    start_line: int                  # 1-based
    end_line: int                    # 1-based, inclusive
    language: str                    # "php", "javascript", "typescript"
    docblock: Optional[str] = None   # PHPDoc/JSDoc/TSDoc content
    content_hash: Optional[str] = None  # SHA-256 of source text
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata examples by kind:
    # class:    {"is_abstract": bool, "is_final": bool, "visibility": str, "generic_params": list}
    # function: {"is_async": bool, "is_generator": bool, "is_exported": bool, "parameters": list}
    # method:   {"visibility": str, "is_static": bool, "is_abstract": bool}
    # property: {"visibility": str, "is_static": bool, "is_readonly": bool, "default_value": str}
    # route:    {"http_method": str, "middleware": list, "is_api": bool}
    # component:{"framework": str, "is_server": bool, "is_client": bool, "props": list}
    # import:   {"specifiers": list, "is_type_only": bool, "is_dynamic": bool, "module_system": str}


@dataclass
class Edge:
    """An edge (relationship) in the code knowledge graph."""
    source_id: str                   # Node ID of source
    target_id: str                   # Node ID of target
    kind: EdgeKind                   # Edge type from registry
    confidence: float = 1.0          # 0.0-1.0 reliability score
    line_number: Optional[int] = None  # Where the relationship occurs in source
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata examples by kind:
    # calls:       {"is_dynamic": bool, "is_conditional": bool, "argument_count": int}
    # imports:     {"specifiers": list, "is_type_only": bool, "module_system": str}
    # api_calls:   {"strategy": str, "url_pattern": str, "http_method": str}
    # passes_prop: {"prop_name": str, "prop_type": str}
    # co_changes:  {"jaccard_similarity": float, "co_change_count": int}


@dataclass
class ExtractionResult:
    """Result of extracting nodes and edges from a single file."""
    file_path: str
    language: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parse_time_ms: float = 0.0


@dataclass
class GraphSummary:
    """Summary statistics for the knowledge graph."""
    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_kind: dict[str, int] = field(default_factory=dict)
    edges_by_kind: dict[str, int] = field(default_factory=dict)
    files_by_language: dict[str, int] = field(default_factory=dict)
    avg_confidence: float = 0.0
    low_confidence_edges: int = 0  # edges with confidence < 0.5
    parse_errors: int = 0
    total_parse_time_ms: float = 0.0
```

### 4.3 LanguagePlugin Interface

```python
from abc import ABC, abstractmethod
from typing import Optional
import tree_sitter


class LanguagePlugin(ABC):
    """Base interface for all language plugins.

    Every language (PHP, JavaScript, TypeScript, etc.) must implement
    this interface to participate in the CodeGraph pipeline.
    """

    def __init__(self, config: "CodeGraphConfig"):
        self.config = config

    # ── Identity ──────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name (e.g., 'php', 'javascript', 'typescript')."""
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> set[str]:
        """File extensions this plugin handles (e.g., {'.php', '.blade.php'})."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        return self.name.title()

    # ── Lifecycle ─────────────────────────────────────────────

    @abstractmethod
    def setup(self) -> None:
        """Initialize the plugin: install grammars, validate dependencies.

        Called once during PluginRegistry.initialize().
        Raise PluginSetupError if dependencies are missing.
        """
        ...

    def teardown(self) -> None:
        """Cleanup resources. Called when pipeline completes."""
        pass

    # ── File Matching ─────────────────────────────────────────

    def can_handle(self, file_path: str) -> bool:
        """Return True if this plugin should process the given file.

        Default implementation checks file extension.
        Override for more complex logic (e.g., .vue SFC detection).
        """
        from pathlib import Path
        suffix = Path(file_path).suffix
        # Handle compound extensions like .blade.php
        name = Path(file_path).name
        for ext in self.file_extensions:
            if name.endswith(ext):
                return True
        return suffix in self.file_extensions

    # ── Grammar ───────────────────────────────────────────────

    @abstractmethod
    def get_grammar_name(self) -> str:
        """Return the tree-sitter grammar name for this language.

        Used to load the appropriate grammar from tree_sitter_languages
        or a custom-compiled grammar.
        """
        ...

    def get_grammar_for_file(self, file_path: str) -> str:
        """Return grammar name for a specific file.

        Override for languages with multiple grammars
        (e.g., TypeScript uses 'typescript' for .ts, 'tsx' for .tsx).
        """
        return self.get_grammar_name()

    # ── Extraction ────────────────────────────────────────────

    @abstractmethod
    def extract(self, file_path: str, tree: tree_sitter.Tree,
                source_bytes: bytes) -> ExtractionResult:
        """Extract nodes and edges from a parsed AST.

        Args:
            file_path: Relative path to the source file.
            tree: Parsed tree-sitter Tree object.
            source_bytes: Raw file content as bytes.

        Returns:
            ExtractionResult with nodes, edges, and any parse errors.
        """
        ...

    @abstractmethod
    def get_queries(self) -> dict[str, str]:
        """Return named tree-sitter query patterns.

        Keys are query names (e.g., 'classes', 'functions', 'imports').
        Values are S-expression query strings.

        Example:
            {
                'classes': '(class_declaration name: (name) @class.name) @class.def',
                'functions': '(function_definition name: (name) @func.name) @func.def',
            }
        """
        ...

    # ── Resolution ────────────────────────────────────────────

    @abstractmethod
    def create_resolver(self, project_root: str) -> "ModuleResolver":
        """Create a module resolver for this language.

        The resolver handles import path → file path resolution,
        including language-specific rules (PSR-4, node_modules, etc.).
        """
        ...

    # ── Framework Detection ───────────────────────────────────

    @abstractmethod
    def get_framework_detectors(self) -> list["FrameworkDetector"]:
        """Return framework detectors for this language.

        Each detector identifies framework-specific patterns
        (e.g., Laravel routes, React components, Express middleware).
        """
        ...

    # ── Enrichment (Optional) ─────────────────────────────────

    def enrich(self, nodes: list[Node], edges: list[Edge]) -> tuple[list[Node], list[Edge]]:
        """Optional enrichment pass (e.g., PHPStan type resolution).

        Default implementation returns nodes/edges unchanged.
        """
        return nodes, edges

    # ── Cross-Language (Optional) ─────────────────────────────

    def get_api_endpoints(self, nodes: list[Node], edges: list[Edge]) -> list["APIEndpoint"]:
        """Extract API endpoints defined in this language.

        Used for cross-language matching (e.g., PHP routes → JS fetch calls).
        """
        return []

    def get_api_calls(self, nodes: list[Node], edges: list[Edge]) -> list["APICall"]:
        """Extract API call sites in this language.

        Used for cross-language matching (e.g., JS fetch → PHP routes).
        """
        return []

    # ── Module System Detection ───────────────────────────────

    def detect_module_system(self, file_path: str, source_bytes: bytes) -> str:
        """Detect the module system used by a file.

        Returns: 'esm', 'cjs', 'namespace', 'global', or 'unknown'.
        Default returns 'unknown'. Override for JS/TS.
        """
        return "unknown"
```

### 4.4 ASTExtractor Interface

```python
class ASTExtractor(ABC):
    """Extracts structured data from a tree-sitter AST.

    Each language plugin contains one or more extractors that know
    how to interpret language-specific AST node types.
    """

    @abstractmethod
    def extract_declarations(self, tree: tree_sitter.Tree,
                              source_bytes: bytes,
                              file_path: str) -> list[Node]:
        """Extract all declarations (classes, functions, etc.) from the AST."""
        ...

    @abstractmethod
    def extract_references(self, tree: tree_sitter.Tree,
                            source_bytes: bytes,
                            file_path: str,
                            declarations: list[Node]) -> list[Edge]:
        """Extract all references (calls, imports, type usage) from the AST."""
        ...

    @abstractmethod
    def extract_imports(self, tree: tree_sitter.Tree,
                         source_bytes: bytes,
                         file_path: str) -> list[Node]:
        """Extract all import/require statements."""
        ...

    @abstractmethod
    def extract_exports(self, tree: tree_sitter.Tree,
                         source_bytes: bytes,
                         file_path: str) -> list[Node]:
        """Extract all export statements."""
        ...
```

### 4.5 ModuleResolver Interface

```python
@dataclass
class ResolvedImport:
    """Result of resolving an import path."""
    source_file: str          # File containing the import
    import_specifier: str     # Raw import string (e.g., '@/components/Button')
    resolved_path: Optional[str]  # Resolved absolute file path, or None
    is_external: bool = False     # True if resolves to node_modules/vendor
    is_builtin: bool = False      # True if resolves to language built-in
    confidence: float = 1.0       # Resolution confidence
    resolution_strategy: str = ""  # How it was resolved (e.g., 'tsconfig_paths')


class ModuleResolver(ABC):
    """Resolves import paths to file system paths.

    Each language has different module resolution rules:
    - PHP: PSR-4 autoloading, composer classmap
    - JavaScript: Node.js resolution, ESM, CJS
    - TypeScript: tsconfig paths, baseUrl, Node.js resolution
    """

    def __init__(self, project_root: str, config: dict[str, Any] | None = None):
        self.project_root = project_root
        self.config = config or {}

    @abstractmethod
    def resolve(self, import_specifier: str, from_file: str) -> ResolvedImport:
        """Resolve an import specifier to a file path.

        Args:
            import_specifier: The import string (e.g., './utils', 'lodash', 'App\\Models\\User').
            from_file: The file containing the import (for relative resolution).

        Returns:
            ResolvedImport with resolved path and metadata.
        """
        ...

    @abstractmethod
    def resolve_batch(self, imports: list[tuple[str, str]]) -> list[ResolvedImport]:
        """Resolve multiple imports efficiently.

        Args:
            imports: List of (import_specifier, from_file) tuples.

        Returns:
            List of ResolvedImport results in same order.
        """
        ...

    def invalidate_cache(self, file_path: str | None = None) -> None:
        """Invalidate resolution cache for a file or all files."""
        pass
```

### 4.6 FrameworkDetector Interface

```python
@dataclass
class FrameworkPattern:
    """A detected framework-specific pattern."""
    framework: str           # e.g., "laravel", "react", "nextjs"
    pattern_type: str        # e.g., "route", "component", "middleware"
    nodes: list[Node]        # Nodes created from this pattern
    edges: list[Edge]        # Edges created from this pattern
    confidence: float = 1.0  # Detection confidence


class FrameworkDetector(ABC):
    """Detects framework-specific patterns in parsed code.

    Each framework detector knows how to identify patterns specific
    to its framework (e.g., Laravel routes, React components).
    """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """Name of the framework (e.g., 'laravel', 'react')."""
        ...

    @abstractmethod
    def detect(self, file_path: str, tree: tree_sitter.Tree,
               source_bytes: bytes, existing_nodes: list[Node],
               existing_edges: list[Edge]) -> list[FrameworkPattern]:
        """Detect framework patterns in a parsed file.

        Args:
            file_path: Path to the source file.
            tree: Parsed tree-sitter Tree.
            source_bytes: Raw file content.
            existing_nodes: Nodes already extracted from this file.
            existing_edges: Edges already extracted from this file.

        Returns:
            List of detected framework patterns with nodes and edges.
        """
        ...

    def detect_project_level(self, all_nodes: list[Node],
                              all_edges: list[Edge]) -> list[FrameworkPattern]:
        """Detect project-level framework patterns.

        Called once after all files are processed. Used for patterns
        that span multiple files (e.g., route registration, DI container).
        """
        return []

    @abstractmethod
    def is_active(self, project_root: str) -> bool:
        """Check if this framework is present in the project.

        Typically checks for framework-specific files or dependencies
        (e.g., composer.json with laravel/framework, package.json with react).
        """
        ...
```

### 4.7 GraphStore Interface

```python
class GraphStore(ABC):
    """Abstract storage backend for the code knowledge graph.

    The primary implementation is SQLiteGraphStore, but this abstraction
    allows for alternative backends (e.g., Neo4j, DuckDB).
    """

    @abstractmethod
    def initialize(self) -> None:
        """Create schema, indexes, and prepare for writes."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close connections and flush pending writes."""
        ...

    # ── Write Operations ──────────────────────────────────────

    @abstractmethod
    def upsert_node(self, node: Node) -> None:
        """Insert or update a node."""
        ...

    @abstractmethod
    def upsert_nodes(self, nodes: list[Node]) -> int:
        """Bulk insert/update nodes. Returns count of affected rows."""
        ...

    @abstractmethod
    def upsert_edge(self, edge: Edge) -> None:
        """Insert or update an edge."""
        ...

    @abstractmethod
    def upsert_edges(self, edges: list[Edge]) -> int:
        """Bulk insert/update edges. Returns count of affected rows."""
        ...

    @abstractmethod
    def delete_nodes_for_file(self, file_path: str) -> int:
        """Delete all nodes (and their edges) for a given file.

        Used during incremental updates when a file is re-parsed.
        Returns count of deleted nodes.
        """
        ...

    @abstractmethod
    def update_file_hash(self, file_path: str, content_hash: str) -> None:
        """Update the stored content hash for a file."""
        ...

    # ── Read Operations ───────────────────────────────────────

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        ...

    @abstractmethod
    def get_node_by_qualified_name(self, qualified_name: str) -> Node | None:
        """Get a node by fully-qualified name."""
        ...

    @abstractmethod
    def find_nodes(self, kind: NodeKind | None = None,
                   file_path: str | None = None,
                   name_pattern: str | None = None,
                   language: str | None = None,
                   limit: int = 100) -> list[Node]:
        """Find nodes matching criteria."""
        ...

    @abstractmethod
    def search_nodes(self, query: str, limit: int = 20) -> list[Node]:
        """Full-text search across node names and qualified names."""
        ...

    @abstractmethod
    def get_edges(self, source_id: str | None = None,
                  target_id: str | None = None,
                  kind: EdgeKind | None = None,
                  min_confidence: float = 0.0) -> list[Edge]:
        """Get edges matching criteria."""
        ...

    @abstractmethod
    def get_neighbors(self, node_id: str, direction: str = "both",
                      edge_kinds: list[EdgeKind] | None = None,
                      max_depth: int = 1) -> list[tuple[Node, Edge, int]]:
        """Get neighboring nodes with their connecting edges.

        Args:
            node_id: Starting node.
            direction: 'outgoing', 'incoming', or 'both'.
            edge_kinds: Filter by edge types (None = all).
            max_depth: Maximum traversal depth.

        Returns:
            List of (node, edge, depth) tuples.
        """
        ...

    @abstractmethod
    def get_file_hash(self, file_path: str) -> str | None:
        """Get the stored content hash for a file."""
        ...

    @abstractmethod
    def get_summary(self) -> GraphSummary:
        """Get summary statistics for the graph."""
        ...

    # ── Advanced Queries ──────────────────────────────────────

    @abstractmethod
    def find_callers(self, qualified_name: str, max_depth: int = 3) -> list[tuple[Node, int]]:
        """Find all callers of a function/method (transitive)."""
        ...

    @abstractmethod
    def find_callees(self, qualified_name: str, max_depth: int = 3) -> list[tuple[Node, int]]:
        """Find all functions/methods called by a function (transitive)."""
        ...

    @abstractmethod
    def find_implementations(self, interface_name: str) -> list[Node]:
        """Find all classes implementing an interface."""
        ...

    @abstractmethod
    def find_subclasses(self, class_name: str, max_depth: int = 5) -> list[Node]:
        """Find all subclasses (transitive)."""
        ...

    @abstractmethod
    def blast_radius(self, qualified_name: str, max_depth: int = 3) -> dict[str, list[Node]]:
        """Calculate the blast radius of changing a symbol.

        Returns dict keyed by depth level: {'1': [...], '2': [...], '3': [...]}.
        """
        ...

    @abstractmethod
    def find_entry_points(self) -> list[Node]:
        """Find entry points (routes, main functions, CLI commands)."""
        ...

    # ── Context Manager ───────────────────────────────────────

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
```

### 4.8 GraphAnalyzer Interface

```python
class GraphAnalyzer(ABC):
    """Graph algorithm abstraction for analysis operations.

    The primary implementation uses NetworkX for in-memory graph algorithms.
    Loaded from the GraphStore on demand.
    """

    @abstractmethod
    def load_from_store(self, store: GraphStore) -> None:
        """Load graph data from a GraphStore into the analyzer."""
        ...

    @abstractmethod
    def pagerank(self, personalization: dict[str, float] | None = None) -> dict[str, float]:
        """Compute PageRank scores for all nodes.

        Args:
            personalization: Optional bias toward specific nodes.

        Returns:
            Dict mapping node_id → PageRank score.
        """
        ...

    @abstractmethod
    def betweenness_centrality(self) -> dict[str, float]:
        """Compute betweenness centrality for all nodes."""
        ...

    @abstractmethod
    def community_detection(self) -> list[set[str]]:
        """Detect communities/clusters in the graph.

        Returns list of sets, each set containing node IDs in a community.
        """
        ...

    @abstractmethod
    def shortest_path(self, source_id: str, target_id: str) -> list[str] | None:
        """Find shortest path between two nodes."""
        ...

    @abstractmethod
    def find_cycles(self, edge_kinds: list[EdgeKind] | None = None) -> list[list[str]]:
        """Find circular dependencies."""
        ...

    @abstractmethod
    def relevance_score(self, node_id: str, query_context: dict) -> float:
        """Compute multi-factor relevance score for a node.

        Combines PageRank, distance, relationship type, recency, and name similarity.
        """
        ...
```

### 4.9 OutputFormatter Interface

```python
class OutputFormatter(ABC):
    """Formats graph query results for consumption.

    Different formatters optimize for different consumers:
    - MarkdownFormatter: Human-readable, good for LLMs
    - JSONFormatter: Machine-readable, good for APIs
    - TreeFormatter: Compact, good for repository overviews
    """

    @abstractmethod
    def format_node(self, node: Node, edges: list[Edge],
                    related_nodes: list[Node],
                    detail_level: str = "summary") -> str:
        """Format a single node with its relationships.

        Args:
            node: The node to format.
            edges: Edges connected to this node.
            related_nodes: Nodes connected via edges.
            detail_level: 'signature', 'summary', 'detailed', or 'comprehensive'.
        """
        ...

    @abstractmethod
    def format_graph_summary(self, summary: GraphSummary) -> str:
        """Format graph summary statistics."""
        ...

    @abstractmethod
    def format_impact_analysis(self, target: Node,
                                impacted: dict[str, list[Node]]) -> str:
        """Format blast radius / impact analysis results."""
        ...

    @abstractmethod
    def format_file_overview(self, file_path: str, nodes: list[Node],
                              edges: list[Edge]) -> str:
        """Format an overview of a single file's contents."""
        ...

    @abstractmethod
    def format_architecture_overview(self, communities: list[set[str]],
                                      important_nodes: list[tuple[str, float]],
                                      entry_points: list[Node]) -> str:
        """Format a high-level architecture overview."""
        ...
```

### 4.10 CrossLanguageMatcher Interface

```python
@dataclass
class APIEndpoint:
    """An API endpoint defined in backend code."""
    path: str                    # URL path (e.g., "/api/users/{id}")
    http_method: str             # GET, POST, PUT, DELETE, etc.
    handler_node_id: str         # Node ID of the handler function/method
    file_path: str
    middleware: list[str] = field(default_factory=list)
    name: Optional[str] = None   # Named route (e.g., "users.show")


@dataclass
class APICall:
    """An API call site in frontend code."""
    url_pattern: str             # URL pattern (may contain variables)
    http_method: str             # GET, POST, etc. (or "UNKNOWN")
    caller_node_id: str          # Node ID of the calling function
    file_path: str
    is_static: bool = True       # Whether URL is statically determinable
    confidence: float = 1.0


@dataclass
class CrossLanguageMatch:
    """A matched connection between backend and frontend."""
    endpoint: APIEndpoint
    call: APICall
    match_strategy: str          # 'exact', 'parameterized', 'prefix', 'fuzzy'
    confidence: float
    edge: Edge                   # The resulting graph edge


class CrossLanguageMatcher(ABC):
    """Matches cross-language connections.

    Primary use case: matching PHP API routes to JavaScript fetch/axios calls.
    Uses a multi-strategy matching pipeline:
    exact → parameterized → prefix → fuzzy
    """

    @abstractmethod
    def match(self, endpoints: list[APIEndpoint],
              calls: list[APICall]) -> list[CrossLanguageMatch]:
        """Match API endpoints to API call sites.

        Returns list of matches with confidence scores.
        """
        ...
```

### 4.11 ContextAssembler Interface

```python
class ContextAssembler(ABC):
    """Assembles token-budgeted context for LLM consumption.

    Combines graph query results with relevance scoring and
    progressive detail levels to fit within token budgets.
    """

    @abstractmethod
    def assemble(self, query: str, store: GraphStore,
                 analyzer: GraphAnalyzer,
                 token_budget: int = 4000,
                 formatter: OutputFormatter | None = None) -> str:
        """Assemble context for an LLM query.

        Args:
            query: Natural language or structured query.
            store: Graph store to query.
            analyzer: Graph analyzer for relevance scoring.
            token_budget: Maximum tokens in output.
            formatter: Output formatter (default: MarkdownFormatter).

        Returns:
            Formatted context string within token budget.
        """
        ...

    @abstractmethod
    def assemble_for_symbol(self, qualified_name: str, store: GraphStore,
                             analyzer: GraphAnalyzer,
                             token_budget: int = 4000) -> str:
        """Assemble context for a specific symbol."""
        ...

    @abstractmethod
    def assemble_for_file(self, file_path: str, store: GraphStore,
                           analyzer: GraphAnalyzer,
                           token_budget: int = 4000) -> str:
        """Assemble context for a specific file."""
        ...

    @abstractmethod
    def assemble_impact_analysis(self, qualified_name: str, store: GraphStore,
                                  analyzer: GraphAnalyzer,
                                  token_budget: int = 4000) -> str:
        """Assemble impact analysis for a symbol change."""
        ...
```

### 4.12 ProgressReporter Interface

```python
from enum import Enum

class PipelinePhase(str, Enum):
    DISCOVERY = "discovery"
    FILE_SCANNING = "file_scanning"
    EXTRACTION = "extraction"
    RESOLUTION = "resolution"
    FRAMEWORK_DETECTION = "framework_detection"
    CROSS_LANGUAGE = "cross_language"
    ENRICHMENT = "enrichment"
    PERSISTENCE = "persistence"


class ProgressReporter(ABC):
    """Reports pipeline progress to the user."""

    @abstractmethod
    def on_phase_start(self, phase: PipelinePhase, total_items: int = 0) -> None:
        """Called when a pipeline phase begins."""
        ...

    @abstractmethod
    def on_phase_progress(self, phase: PipelinePhase, current: int,
                           total: int, message: str = "") -> None:
        """Called to report progress within a phase."""
        ...

    @abstractmethod
    def on_phase_complete(self, phase: PipelinePhase, summary: dict) -> None:
        """Called when a pipeline phase completes."""
        ...

    @abstractmethod
    def on_error(self, phase: PipelinePhase, error: str,
                  file_path: str | None = None) -> None:
        """Called when an error occurs."""
        ...

    @abstractmethod
    def on_pipeline_complete(self, summary: GraphSummary) -> None:
        """Called when the entire pipeline completes."""
        ...
```

---

## 5. Data Flow Architecture

### 5.1 Pipeline Overview

The CodeGraph pipeline transforms a repository path into an LLM-queryable knowledge graph through **8 sequential phases**. Each phase has well-defined inputs, outputs, and error handling.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        CodeGraph Pipeline                             │
│                                                                      │
│  INPUT: repo_path + codegraph.yaml                                   │
│                                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │ Phase 1  │──▶│ Phase 2  │──▶│ Phase 3  │──▶│ Phase 4  │         │
│  │ Project  │   │ File     │   │ AST      │   │ Name &   │         │
│  │ Discovery│   │ Scanning │   │ Extract  │   │ Module   │         │
│  │          │   │ & Hashing│   │          │   │ Resolve  │         │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘         │
│       │              │              │              │                 │
│       ▼              ▼              ▼              ▼                 │
│  ProjectInfo    FileManifest   RawExtractions  ResolvedGraph        │
│                                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │ Phase 5  │──▶│ Phase 6  │──▶│ Phase 7  │──▶│ Phase 8  │         │
│  │ Framework│   │ Cross-   │   │ Enrich-  │   │ Persist  │         │
│  │ Detect   │   │ Language │   │ ment     │   │ & Index  │         │
│  │          │   │ Match    │   │          │   │          │         │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘         │
│       │              │              │              │                 │
│       ▼              ▼              ▼              ▼                 │
│  FrameworkGraph  XLangEdges    EnrichedGraph   SQLite DB             │
│                                                + NetworkX            │
│                                                                      │
│  OUTPUT: .codegraph/graph.db + summary.json                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 Phase Details

#### Phase 1: Project Discovery

**Purpose**: Detect project type, parse configuration files, build resolver configs.

| Aspect | Detail |
|--------|--------|
| **Input** | `repo_path: str`, `codegraph.yaml` (optional) |
| **Output** | `ProjectInfo` dataclass |
| **Duration** | <1s |
| **Can fail?** | Yes — invalid project structure |

```python
@dataclass
class ProjectInfo:
    root_path: str
    project_type: str                    # "php", "javascript", "typescript", "mixed"
    languages_detected: list[str]        # ["php", "javascript", "typescript"]
    active_plugins: list[str]            # Plugin names to activate
    # PHP-specific
    composer_json: dict | None           # Parsed composer.json
    psr4_map: dict[str, str]             # PSR-4 namespace → directory mapping
    # JS/TS-specific
    package_json: dict | None            # Parsed package.json
    tsconfig: dict | None                # Parsed tsconfig.json (with extends resolved)
    module_system: str                   # "esm", "cjs", "mixed"
    path_aliases: dict[str, str]         # Alias → path mapping (from tsconfig, bundler)
    workspaces: list[str]                # Monorepo workspace paths
    # Framework detection hints
    detected_frameworks: list[str]       # ["laravel", "react", "nextjs"]
    # Build config
    bundler_config: dict | None          # Parsed vite/webpack config
    entry_points: list[str]              # Build entry points
```

**Operations**:
1. Scan for `composer.json` → parse PSR-4 map, detect PHP frameworks from `require`
2. Scan for `package.json` → parse dependencies, detect JS frameworks, workspaces
3. Scan for `tsconfig.json` → resolve `extends` chain, extract `paths`, `baseUrl`
4. Scan for bundler configs → extract aliases, entry points
5. Determine active plugins based on detected languages
6. Merge with `codegraph.yaml` overrides

#### Phase 2: File Discovery & Hashing

**Purpose**: Build a manifest of all source files with content hashes for incremental processing.

| Aspect | Detail |
|--------|--------|
| **Input** | `ProjectInfo` |
| **Output** | `FileManifest` |
| **Duration** | <1s for 5,000 files |
| **Can fail?** | No — gracefully skips unreadable files |

```python
@dataclass
class FileEntry:
    path: str                # Relative to project root
    absolute_path: str       # Absolute path
    language: str            # Detected language
    extension: str           # File extension
    content_hash: str        # SHA-256 of file content
    size_bytes: int
    plugin_name: str         # Which plugin handles this file
    needs_reparse: bool      # True if hash differs from stored hash

@dataclass
class FileManifest:
    files: list[FileEntry]
    total_files: int
    files_to_parse: int      # Only files needing re-parse
    files_unchanged: int     # Skipped (hash match)
    files_by_language: dict[str, int]
    scan_time_ms: float
```

**Operations**:
1. Walk directory tree, respecting `.gitignore` + `codegraph.yaml` ignore patterns
2. Classify each file by language using extension → plugin mapping
3. Compute SHA-256 content hash for each file
4. Compare with stored hashes in existing `.codegraph/graph.db`
5. Mark files as `needs_reparse` if hash differs or no stored hash exists
6. For files that no longer exist, mark their nodes for deletion

**Incremental Logic**:
```python
def should_reparse(file_entry: FileEntry, store: GraphStore) -> bool:
    stored_hash = store.get_file_hash(file_entry.path)
    if stored_hash is None:
        return True  # New file
    return stored_hash != file_entry.content_hash
```

#### Phase 3: Structural Extraction (Tree-sitter)

**Purpose**: Parse each file with tree-sitter and extract nodes and edges via language plugins.

| Aspect | Detail |
|--------|--------|
| **Input** | `FileManifest` (only `needs_reparse` files) |
| **Output** | `dict[str, ExtractionResult]` (keyed by file path) |
| **Duration** | 25-50s for 5,000 files |
| **Can fail?** | Partially — individual files can fail, pipeline continues |

**Operations**:
1. For each file needing re-parse:
   a. Read file content as bytes
   b. Get appropriate plugin via `PluginRegistry.get_plugin_for_file()`
   c. Get grammar name via `plugin.get_grammar_for_file()`
   d. Parse with tree-sitter: `parser.parse(source_bytes)`
   e. Call `plugin.extract(file_path, tree, source_bytes)`
   f. Collect `ExtractionResult` with nodes, edges, errors
2. Report progress per file
3. Collect parse errors (tree-sitter is error-tolerant, so partial results are valid)

**Parallelization**: Files are independent — can use `concurrent.futures.ProcessPoolExecutor` for CPU-bound parsing. Tree-sitter parsers are not thread-safe, so use process pool.

```python
def extract_file(file_entry: FileEntry, plugin: LanguagePlugin) -> ExtractionResult:
    source_bytes = Path(file_entry.absolute_path).read_bytes()
    parser = get_parser(plugin.get_grammar_for_file(file_entry.path))
    tree = parser.parse(source_bytes)
    result = plugin.extract(file_entry.path, tree, source_bytes)
    result.parse_time_ms = timer.elapsed_ms()
    return result
```

#### Phase 4: Name & Module Resolution

**Purpose**: Resolve import paths, qualified names, and cross-file references.

| Aspect | Detail |
|--------|--------|
| **Input** | `dict[str, ExtractionResult]`, `ProjectInfo` |
| **Output** | Updated nodes/edges with resolved references |
| **Duration** | 15-45s (PHP subprocess + JS/TS resolution) |
| **Can fail?** | Partially — unresolved imports get low confidence |

**Operations**:
1. For each plugin, create a `ModuleResolver` via `plugin.create_resolver(project_root)`
2. Collect all import nodes across all files
3. Batch-resolve imports: `resolver.resolve_batch(imports)`
4. For resolved imports:
   a. Create `imports` edges between files
   b. Update import node metadata with resolved path
   c. Set confidence based on resolution strategy
5. For unresolved imports:
   a. Create edge with low confidence (0.1-0.3)
   b. Log warning for debugging
6. PHP-specific: Run nikic/PHP-Parser subprocess for FQCN resolution
7. Resolve call targets: match function/method calls to declarations

**Confidence Scoring for Resolution**:
```python
RESOLUTION_CONFIDENCE = {
    "exact_path": 1.0,
    "extension_added": 0.95,
    "index_file": 0.90,
    "tsconfig_paths": 0.90,
    "bundler_alias": 0.85,
    "package_exports": 0.90,
    "package_main": 0.85,
    "node_modules": 0.80,
    "psr4_autoload": 0.95,
    "classmap": 0.90,
    "heuristic": 0.50,
    "unresolved": 0.10,
}
```

#### Phase 5: Framework Pattern Detection

**Purpose**: Detect framework-specific patterns (routes, models, components, etc.).

| Aspect | Detail |
|--------|--------|
| **Input** | Resolved nodes/edges, `ProjectInfo` |
| **Output** | Additional framework-specific nodes and edges |
| **Duration** | 5-10s |
| **Can fail?** | No — detectors are optional and independent |

**Operations**:
1. For each active plugin, get framework detectors: `plugin.get_framework_detectors()`
2. Filter to active detectors: `detector.is_active(project_root)`
3. For each file, run per-file detection: `detector.detect(file_path, tree, ...)`
4. After all files, run project-level detection: `detector.detect_project_level(all_nodes, all_edges)`
5. Merge framework nodes/edges into the graph

**Framework Detection Examples**:
- **Laravel**: Route definitions → `Route` nodes + `routes_to` edges to controllers
- **React**: JSX components → `Component` nodes + `renders` edges + `passes_prop` edges
- **Next.js**: File-based routes → `Route` nodes + server/client component classification
- **Express**: `app.get('/path', handler)` → `Route` nodes + `routes_to` edges

#### Phase 6: Cross-Language Matching

**Purpose**: Match connections between backend (PHP) and frontend (JS/TS) code.

| Aspect | Detail |
|--------|--------|
| **Input** | All nodes/edges from phases 3-5 |
| **Output** | Cross-language edges (api_calls, shares_type_contract, etc.) |
| **Duration** | 2-5s |
| **Can fail?** | No — produces edges with varying confidence |

**Operations**:
1. Collect API endpoints from backend plugins: `plugin.get_api_endpoints()`
2. Collect API call sites from frontend plugins: `plugin.get_api_calls()`
3. Run `CrossLanguageMatcher.match(endpoints, calls)`
4. Multi-strategy matching pipeline:
   a. **Exact match**: URL paths match exactly → confidence 0.95
   b. **Parameterized match**: After normalizing `{id}`, `$id`, `:id` → confidence 0.85
   c. **Prefix match**: URL prefix matches → confidence 0.60
   d. **Fuzzy match**: Levenshtein distance < threshold → confidence 0.40
5. Create `api_calls` / `api_serves` edges with match metadata
6. Detect shared type contracts (PHP API Resources ↔ TypeScript interfaces)

#### Phase 7: Enrichment (Optional)

**Purpose**: Add metadata from external tools and analysis.

| Aspect | Detail |
|--------|--------|
| **Input** | Complete graph from phases 1-6 |
| **Output** | Enriched nodes/edges with additional metadata |
| **Duration** | 5-30s (depends on enabled enrichments) |
| **Can fail?** | Yes — each enrichment is independent, failures are non-fatal |

**Enrichment Sources**:

| Source | Data Added | Requires |
|--------|-----------|----------|
| **PHPStan/Larastan** | Resolved types for facades, container bindings, Eloquent | PHP, PHPStan installed |
| **Git metadata** | Change frequency, co-change analysis, author ownership | Git repository |
| **Complexity metrics** | Cyclomatic complexity, LOC, coupling metrics | None (computed from AST) |
| **PageRank** | Importance scores for all nodes | NetworkX (computed) |
| **Community detection** | Architectural clusters/modules | NetworkX (computed) |

**Operations**:
1. Run plugin-specific enrichment: `plugin.enrich(nodes, edges)`
2. If git repo: extract change frequency, co-change pairs, author data
3. Compute cyclomatic complexity from AST for functions/methods
4. Build NetworkX projection from current graph
5. Compute PageRank, betweenness centrality, community detection
6. Store computed metrics as node/edge metadata

#### Phase 8: Graph Persistence & Indexing

**Purpose**: Persist the complete graph to SQLite and build search indexes.

| Aspect | Detail |
|--------|--------|
| **Input** | Complete enriched graph |
| **Output** | `.codegraph/graph.db` + `summary.json` |
| **Duration** | 2-5s |
| **Can fail?** | Yes — disk write errors |

**Operations**:
1. Begin SQLite transaction
2. For re-parsed files: delete old nodes/edges, insert new ones
3. For deleted files: remove all associated nodes/edges
4. Upsert all new/updated nodes (batch insert)
5. Upsert all new/updated edges (batch insert)
6. Update file hash tracking table
7. Rebuild FTS5 index for full-text search
8. Commit transaction
9. Write `summary.json` with graph statistics
10. Log completion summary

**Output Structure**:
```
.codegraph/
├── graph.db          # SQLite database (WAL mode)
├── summary.json      # Graph statistics and metadata
└── config.json       # Snapshot of config used for this build
```

### 5.3 Error Handling Strategy

```python
class ErrorStrategy(str, Enum):
    """How to handle errors at each pipeline phase."""
    FAIL_FAST = "fail_fast"      # Stop pipeline on first error
    COLLECT = "collect"          # Collect errors, continue processing
    SKIP = "skip"                # Skip errored items silently

# Default error strategies per phase
DEFAULT_ERROR_STRATEGIES = {
    PipelinePhase.DISCOVERY: ErrorStrategy.FAIL_FAST,       # Can't continue without project info
    PipelinePhase.FILE_SCANNING: ErrorStrategy.COLLECT,     # Skip unreadable files
    PipelinePhase.EXTRACTION: ErrorStrategy.COLLECT,        # Skip unparseable files
    PipelinePhase.RESOLUTION: ErrorStrategy.COLLECT,        # Low-confidence for unresolved
    PipelinePhase.FRAMEWORK_DETECTION: ErrorStrategy.SKIP,  # Framework detection is optional
    PipelinePhase.CROSS_LANGUAGE: ErrorStrategy.SKIP,       # Cross-lang is optional
    PipelinePhase.ENRICHMENT: ErrorStrategy.SKIP,           # Enrichment is optional
    PipelinePhase.PERSISTENCE: ErrorStrategy.FAIL_FAST,     # Must persist successfully
}
```

### 5.4 Pipeline Orchestrator

```python
class Pipeline:
    """Orchestrates the 8-phase CodeGraph pipeline."""

    def __init__(self, config: CodeGraphConfig, store: GraphStore,
                 registry: PluginRegistry, reporter: ProgressReporter):
        self.config = config
        self.store = store
        self.registry = registry
        self.reporter = reporter

    def run(self, repo_path: str) -> GraphSummary:
        """Execute the full pipeline."""
        # Phase 1: Project Discovery
        self.reporter.on_phase_start(PipelinePhase.DISCOVERY)
        project_info = self._discover_project(repo_path)
        self.reporter.on_phase_complete(PipelinePhase.DISCOVERY, {...})

        # Phase 2: File Discovery & Hashing
        self.reporter.on_phase_start(PipelinePhase.FILE_SCANNING)
        manifest = self._scan_files(project_info)
        self.reporter.on_phase_complete(PipelinePhase.FILE_SCANNING, {...})

        # Phase 3: Structural Extraction
        self.reporter.on_phase_start(PipelinePhase.EXTRACTION, manifest.files_to_parse)
        extractions = self._extract_all(manifest)
        self.reporter.on_phase_complete(PipelinePhase.EXTRACTION, {...})

        # Phase 4: Name & Module Resolution
        self.reporter.on_phase_start(PipelinePhase.RESOLUTION)
        resolved = self._resolve_all(extractions, project_info)
        self.reporter.on_phase_complete(PipelinePhase.RESOLUTION, {...})

        # Phase 5: Framework Detection
        self.reporter.on_phase_start(PipelinePhase.FRAMEWORK_DETECTION)
        framework_results = self._detect_frameworks(resolved, project_info)
        self.reporter.on_phase_complete(PipelinePhase.FRAMEWORK_DETECTION, {...})

        # Phase 6: Cross-Language Matching
        self.reporter.on_phase_start(PipelinePhase.CROSS_LANGUAGE)
        xlang_edges = self._match_cross_language(resolved, framework_results)
        self.reporter.on_phase_complete(PipelinePhase.CROSS_LANGUAGE, {...})

        # Phase 7: Enrichment
        self.reporter.on_phase_start(PipelinePhase.ENRICHMENT)
        enriched = self._enrich(resolved, framework_results, xlang_edges)
        self.reporter.on_phase_complete(PipelinePhase.ENRICHMENT, {...})

        # Phase 8: Persistence
        self.reporter.on_phase_start(PipelinePhase.PERSISTENCE)
        summary = self._persist(enriched)
        self.reporter.on_phase_complete(PipelinePhase.PERSISTENCE, {...})

        self.reporter.on_pipeline_complete(summary)
        return summary
```

---

## 6. Configuration System

### 6.1 Configuration Hierarchy

Configuration is loaded from multiple sources with clear precedence:

```
1. CLI flags (highest priority)        --output-dir, --verbose, etc.
2. Environment variables               CODEGRAPH_OUTPUT_DIR, etc.
3. Project config file                 codegraph.yaml in project root
4. User config file                    ~/.config/codegraph/config.yaml
5. Built-in defaults (lowest priority) Hardcoded in config.py
```

### 6.2 Configuration File: `codegraph.yaml`

```yaml
# codegraph.yaml — CodeGraph project configuration
# Place in your project root directory

# ─── General ──────────────────────────────────────────────────────
version: "1"                          # Config schema version
project_name: "my-app"                # Optional project name
output_dir: ".codegraph"              # Where to store the graph database
log_level: "info"                     # debug, info, warning, error

# ─── File Discovery ───────────────────────────────────────────────
include:
  - "src/**"
  - "app/**"
  - "routes/**"
  - "resources/js/**"
  - "resources/views/**"

exclude:
  - "**/node_modules/**"
  - "**/vendor/**"
  - "**/.git/**"
  - "**/dist/**"
  - "**/build/**"
  - "**/storage/**"
  - "**/*.min.js"
  - "**/*.map"
  - "**/tests/**"                     # Exclude tests by default
  - "**/test/**"

# Respect .gitignore patterns (in addition to exclude list)
respect_gitignore: true

# Maximum file size to parse (bytes). Skip larger files.
max_file_size: 1048576                # 1MB

# ─── Language Configuration ───────────────────────────────────────
languages:
  php:
    enabled: true
    extensions:
      - ".php"
      - ".blade.php"
    # PHP name resolution via nikic/PHP-Parser
    name_resolver:
      enabled: true
      php_binary: "php"               # Path to PHP binary
      # Path to PHP-Parser helper script (bundled with CodeGraph)
      # Set to null to skip PHP name resolution
      parser_script: null              # Auto-detected
    # PHPStan enrichment
    phpstan:
      enabled: false                   # Requires PHPStan installed
      binary: "vendor/bin/phpstan"     # Path to PHPStan binary
      config: "phpstan.neon"           # PHPStan config file
      level: 5                         # Analysis level

  javascript:
    enabled: true
    extensions:
      - ".js"
      - ".jsx"
      - ".mjs"
      - ".cjs"
    # Module resolution configuration
    resolution:
      # Additional path aliases (merged with tsconfig/bundler aliases)
      aliases:
        "@": "src"
        "~": "src"
      # Directories to skip during node_modules resolution
      skip_packages: []

  typescript:
    enabled: true
    extensions:
      - ".ts"
      - ".tsx"
      - ".mts"
      - ".cts"
    # TypeScript-specific resolution
    resolution:
      tsconfig: "tsconfig.json"       # Path to tsconfig.json
      # Override tsconfig paths (merged, not replaced)
      additional_paths: {}

# ─── Framework Detection ─────────────────────────────────────────
frameworks:
  # Auto-detect frameworks from package.json/composer.json
  auto_detect: true

  # Explicitly enable/disable specific framework detectors
  laravel:
    enabled: true                     # Auto-detected from composer.json
    route_files:
      - "routes/web.php"
      - "routes/api.php"
    model_directory: "app/Models"

  react:
    enabled: true                     # Auto-detected from package.json
    # Detect custom hooks (functions starting with 'use')
    detect_hooks: true
    # Detect context providers/consumers
    detect_context: true

  nextjs:
    enabled: true
    app_directory: "app"              # App Router directory
    pages_directory: "pages"          # Pages Router directory

  vue:
    enabled: true
    # Parse Single File Components
    parse_sfc: true

  express:
    enabled: true

  nestjs:
    enabled: true

# ─── Cross-Language Matching ──────────────────────────────────────
cross_language:
  enabled: true
  # Minimum confidence for cross-language edges
  min_confidence: 0.3
  # Matching strategies (in order of priority)
  strategies:
    - exact
    - parameterized
    - prefix
    - fuzzy
  # API base URL prefix to strip (e.g., "/api/v1")
  api_prefix: "/api"

# ─── Enrichment ───────────────────────────────────────────────────
enrichment:
  # Git metadata enrichment
  git:
    enabled: true
    # Analyze last N commits for change frequency
    commit_depth: 500
    # Co-change analysis: minimum Jaccard similarity
    co_change_threshold: 0.3

  # Complexity metrics
  complexity:
    enabled: true

  # Graph algorithms (PageRank, centrality)
  graph_algorithms:
    enabled: true

# ─── Output ───────────────────────────────────────────────────────
output:
  # Default output format for CLI export
  default_format: "markdown"          # markdown, json, tree
  # Default token budget for LLM context
  default_token_budget: 4000
  # Include source code in output
  include_source: true
  # Maximum source lines to include per symbol
  max_source_lines: 100

# ─── MCP Server ───────────────────────────────────────────────────
mcp:
  # Server transport
  transport: "stdio"                  # stdio or sse
  # Host/port for SSE transport
  host: "127.0.0.1"
  port: 3333
  # Default token budget for MCP tool responses
  default_token_budget: 8000
  # Maximum token budget (hard limit)
  max_token_budget: 32000

# ─── Performance ──────────────────────────────────────────────────
performance:
  # Number of parallel workers for file parsing
  max_workers: 4                      # 0 = auto (CPU count)
  # SQLite WAL mode (recommended)
  sqlite_wal: true
  # Batch size for SQLite inserts
  batch_size: 500
  # Cache tree-sitter queries (significant speedup)
  cache_queries: true
```

### 6.3 Configuration Dataclass

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
import yaml


@dataclass
class CodeGraphConfig:
    """Complete CodeGraph configuration."""

    # General
    project_name: str = ""
    output_dir: str = ".codegraph"
    log_level: str = "info"

    # File discovery
    include_patterns: list[str] = field(default_factory=lambda: ["**/*"])
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "**/node_modules/**", "**/vendor/**", "**/.git/**",
        "**/dist/**", "**/build/**", "**/*.min.js", "**/*.map",
    ])
    respect_gitignore: bool = True
    max_file_size: int = 1_048_576  # 1MB

    # Language configs
    languages: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Framework configs
    frameworks: dict[str, dict[str, Any]] = field(default_factory=dict)
    auto_detect_frameworks: bool = True

    # Cross-language
    cross_language_enabled: bool = True
    cross_language_min_confidence: float = 0.3
    cross_language_strategies: list[str] = field(
        default_factory=lambda: ["exact", "parameterized", "prefix", "fuzzy"]
    )
    api_prefix: str = "/api"

    # Enrichment
    git_enrichment: bool = True
    git_commit_depth: int = 500
    complexity_metrics: bool = True
    graph_algorithms: bool = True

    # Output
    default_format: str = "markdown"
    default_token_budget: int = 4000
    include_source: bool = True
    max_source_lines: int = 100

    # MCP
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 3333
    mcp_default_token_budget: int = 8000
    mcp_max_token_budget: int = 32000

    # Performance
    max_workers: int = 4
    sqlite_wal: bool = True
    batch_size: int = 500
    cache_queries: bool = True

    @classmethod
    def load(cls, project_root: str, config_path: str | None = None) -> "CodeGraphConfig":
        """Load configuration from file with defaults."""
        config = cls()

        # Try to find config file
        if config_path:
            path = Path(config_path)
        else:
            path = Path(project_root) / "codegraph.yaml"
            if not path.exists():
                path = Path(project_root) / "codegraph.yml"

        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            config._apply_yaml(data)

        # Apply environment variable overrides
        config._apply_env_overrides()

        return config

    def _apply_yaml(self, data: dict) -> None:
        """Apply YAML config data to this config object."""
        # Map YAML structure to flat config fields
        if "output_dir" in data:
            self.output_dir = data["output_dir"]
        if "log_level" in data:
            self.log_level = data["log_level"]
        if "include" in data:
            self.include_patterns = data["include"]
        if "exclude" in data:
            self.exclude_patterns = data["exclude"]
        if "languages" in data:
            self.languages = data["languages"]
        if "frameworks" in data:
            self.frameworks = data["frameworks"]
            self.auto_detect_frameworks = data["frameworks"].get("auto_detect", True)
        # ... (additional fields)

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        import os
        if val := os.environ.get("CODEGRAPH_OUTPUT_DIR"):
            self.output_dir = val
        if val := os.environ.get("CODEGRAPH_LOG_LEVEL"):
            self.log_level = val
        if val := os.environ.get("CODEGRAPH_MAX_WORKERS"):
            self.max_workers = int(val)

    def get_language_config(self, language: str) -> dict[str, Any]:
        """Get language-specific configuration."""
        return self.languages.get(language, {})

    def is_language_enabled(self, language: str) -> bool:
        """Check if a language is enabled."""
        lang_config = self.languages.get(language, {})
        return lang_config.get("enabled", True)  # Enabled by default

    def is_framework_enabled(self, framework: str) -> bool:
        """Check if a framework detector is enabled."""
        fw_config = self.frameworks.get(framework, {})
        return fw_config.get("enabled", self.auto_detect_frameworks)
```

### 6.4 Configuration Validation

```python
def validate_config(config: CodeGraphConfig, project_root: str) -> list[str]:
    """Validate configuration and return list of warnings."""
    warnings = []

    # Check output directory is writable
    output_path = Path(project_root) / config.output_dir
    if output_path.exists() and not os.access(output_path, os.W_OK):
        raise ConfigError(f"Output directory not writable: {output_path}")

    # Check PHP binary if PHP is enabled
    if config.is_language_enabled("php"):
        php_config = config.get_language_config("php")
        php_binary = php_config.get("name_resolver", {}).get("php_binary", "php")
        if not shutil.which(php_binary):
            warnings.append(f"PHP binary not found: {php_binary}. PHP name resolution disabled.")

    # Check for conflicting include/exclude patterns
    if not config.include_patterns:
        warnings.append("No include patterns specified. No files will be scanned.")

    # Validate token budgets
    if config.default_token_budget > config.mcp_max_token_budget:
        warnings.append("default_token_budget exceeds mcp_max_token_budget.")

    return warnings
```

---

## 7. CLI Interface Design

### 7.1 CLI Structure

CodeGraph uses **Click** for its CLI, organized as a command group with subcommands.

```
codegraph
├── init          Initialize a codegraph.yaml config file
├── parse         Parse codebase and build/update the knowledge graph
├── query         Query the knowledge graph
├── export        Export graph data for LLM consumption
├── serve         Start MCP server for LLM integration
├── info          Show graph statistics and project info
└── clean         Remove generated graph data
```

### 7.2 Entry Point Configuration

```toml
# pyproject.toml
[project.scripts]
codegraph = "codegraph.cli.main:cli"
```

### 7.3 Command Specifications

#### `codegraph` (root)

```
$ codegraph --help
Usage: codegraph [OPTIONS] COMMAND [ARGS]...

  CodeGraph — Build knowledge graphs from codebases for LLM consumption.

  Parse PHP, JavaScript, and TypeScript codebases into a queryable
  knowledge graph of classes, functions, routes, components, and their
  relationships.

Options:
  -c, --config PATH    Path to codegraph.yaml config file
  -d, --project-dir PATH  Project root directory [default: .]
  -v, --verbose        Increase verbosity (-v info, -vv debug)
  -q, --quiet          Suppress all output except errors
  --version            Show version and exit
  --help               Show this message and exit.

Commands:
  init    Initialize a new codegraph.yaml configuration file
  parse   Parse codebase and build the knowledge graph
  query   Query the knowledge graph
  export  Export graph data in various formats
  serve   Start MCP server for LLM tool integration
  info    Show graph statistics and project information
  clean   Remove generated .codegraph directory
```

#### `codegraph init`

```
$ codegraph init --help
Usage: codegraph init [OPTIONS]

  Initialize a new codegraph.yaml configuration file.

  Scans the project to auto-detect languages, frameworks, and
  configuration. Generates a codegraph.yaml with sensible defaults.

Options:
  --force          Overwrite existing codegraph.yaml
  --minimal        Generate minimal config (only non-default values)
  --interactive    Interactive mode with prompts [default]
  --help           Show this message and exit.
```

**Behavior**:
1. Scan project root for `composer.json`, `package.json`, `tsconfig.json`
2. Detect languages and frameworks
3. Generate `codegraph.yaml` with detected settings
4. Print summary of detected configuration

**Example output**:
```
$ codegraph init
✓ Detected languages: PHP, JavaScript, TypeScript
✓ Detected frameworks: Laravel 11.x, React 18.x, Next.js 14.x
✓ Found composer.json with PSR-4 autoloading
✓ Found tsconfig.json with path aliases
✓ Found 3,247 source files

Generated codegraph.yaml with:
  • PHP plugin enabled (extensions: .php, .blade.php)
  • JavaScript plugin enabled (extensions: .js, .jsx, .mjs)
  • TypeScript plugin enabled (extensions: .ts, .tsx)
  • Laravel framework detector enabled
  • React framework detector enabled
  • Next.js framework detector enabled
  • Cross-language matching enabled
  • Git enrichment enabled

Run 'codegraph parse' to build the knowledge graph.
```

#### `codegraph parse`

```
$ codegraph parse --help
Usage: codegraph parse [OPTIONS]

  Parse the codebase and build/update the knowledge graph.

  On first run, performs a full parse. On subsequent runs, only
  re-parses files that have changed (incremental update).

Options:
  --full               Force full re-parse (ignore cached hashes)
  --no-resolve         Skip name/module resolution phase
  --no-frameworks      Skip framework detection phase
  --no-cross-language  Skip cross-language matching phase
  --no-enrichment      Skip enrichment phase (git, metrics, PageRank)
  --workers INTEGER    Number of parallel workers [default: 4]
  --dry-run            Show what would be parsed without parsing
  --profile            Enable performance profiling
  --help               Show this message and exit.
```

**Example output**:
```
$ codegraph parse
CodeGraph v1.0.0 — Parsing /home/user/my-app

[1/8] Project Discovery
  ✓ Detected: PHP + JavaScript + TypeScript (mixed project)
  ✓ Frameworks: Laravel 11.x, React 18.x

[2/8] File Scanning
  ✓ Found 3,247 files (1,842 PHP, 987 JS, 418 TS)
  ✓ 127 files changed since last parse
  ✓ 3,120 files unchanged (skipped)

[3/8] Structural Extraction
  ████████████████████████████████████████ 127/127 files  [00:03]
  ✓ Extracted 4,521 nodes, 8,934 edges
  ⚠ 2 files had parse errors (partial extraction)

[4/8] Name & Module Resolution
  ✓ Resolved 2,847/2,901 imports (98.1%)
  ⚠ 54 unresolved imports (low confidence edges created)

[5/8] Framework Detection
  ✓ Laravel: 89 routes, 34 models, 12 events, 8 middleware
  ✓ React: 156 components, 43 hooks, 12 contexts

[6/8] Cross-Language Matching
  ✓ Matched 67 API connections (PHP → JS/TS)
  ✓ 12 shared type contracts detected

[7/8] Enrichment
  ✓ Git metadata: 500 commits analyzed
  ✓ PageRank computed for 4,521 nodes
  ✓ 8 architectural communities detected

[8/8] Persistence
  ✓ Graph saved to .codegraph/graph.db (12.4 MB)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Graph Summary:
  Nodes: 4,521 (1,842 PHP, 987 JS, 418 TS, 1,274 framework)
  Edges: 8,934 (avg confidence: 0.89)
  Parse time: 3.2s (incremental)
  Total time: 8.7s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### `codegraph query`

```
$ codegraph query --help
Usage: codegraph query [OPTIONS] QUERY

  Query the knowledge graph.

  QUERY can be a symbol name, file path, or natural language question.

Options:
  -t, --type TEXT        Filter by node type (class, function, route, etc.)
  -l, --language TEXT    Filter by language (php, javascript, typescript)
  -d, --depth INTEGER    Traversal depth for relationship queries [default: 2]
  --callers              Show callers of the symbol
  --callees              Show callees of the symbol
  --impact               Show blast radius / impact analysis
  --implementations      Show implementations of interface/abstract class
  --dependencies         Show dependency tree
  --dependents           Show reverse dependency tree
  -f, --format TEXT      Output format: markdown, json, tree [default: markdown]
  --tokens INTEGER       Token budget for output [default: 4000]
  --help                 Show this message and exit.
```

**Example queries**:
```bash
# Find a class and show its relationships
$ codegraph query "UserService"

# Show all callers of a method
$ codegraph query "UserService::createUser" --callers --depth 3

# Impact analysis: what breaks if I change this?
$ codegraph query "UserController" --impact

# Find all routes
$ codegraph query --type route

# Find all React components that use a specific hook
$ codegraph query "useAuth" --dependents --type component

# Show file overview
$ codegraph query "app/Services/UserService.php"

# Search by name pattern
$ codegraph query "*Repository" --type class
```

#### `codegraph export`

```
$ codegraph export --help
Usage: codegraph export [OPTIONS]

  Export graph data for LLM consumption.

Options:
  -f, --format TEXT      Output format: markdown, json, tree [default: markdown]
  -o, --output PATH      Output file path [default: stdout]
  --scope TEXT           Export scope: full, architecture, file, symbol
  --symbol TEXT          Symbol to export (for symbol scope)
  --file TEXT            File to export (for file scope)
  --tokens INTEGER       Token budget [default: 4000]
  --include-source       Include source code in export
  --no-source            Exclude source code
  --help                 Show this message and exit.
```

**Example exports**:
```bash
# Export architecture overview (fits in LLM context)
$ codegraph export --scope architecture --tokens 8000

# Export a specific file's context
$ codegraph export --scope file --file "app/Services/UserService.php" --tokens 4000

# Export full graph as JSON
$ codegraph export --format json --scope full -o graph.json

# Export tree view (like aider's repo map)
$ codegraph export --format tree --scope full
```

#### `codegraph serve`

```
$ codegraph serve --help
Usage: codegraph serve [OPTIONS]

  Start MCP server for LLM tool integration.

  Exposes the knowledge graph as MCP tools that LLMs can call
  to understand code structure and relationships.

Options:
  --transport TEXT    Transport: stdio or sse [default: stdio]
  --host TEXT         Host for SSE transport [default: 127.0.0.1]
  --port INTEGER      Port for SSE transport [default: 3333]
  --help              Show this message and exit.
```

#### `codegraph info`

```
$ codegraph info --help
Usage: codegraph info [OPTIONS]

  Show graph statistics and project information.

Options:
  --json    Output as JSON
  --help    Show this message and exit.
```

**Example output**:
```
$ codegraph info
CodeGraph — Project Information

Project: my-app
Root: /home/user/my-app
Graph: .codegraph/graph.db (12.4 MB)
Last parsed: 2024-03-10 14:23:45 (2 minutes ago)

Languages:
  PHP:        1,842 files  (56.7%)
  JavaScript:   987 files  (30.4%)
  TypeScript:   418 files  (12.9%)

Nodes: 4,521
  Classes:      342    Interfaces:    89    Functions:    567
  Methods:    1,234    Properties:   456    Constants:    123
  Routes:        89    Components:   156    Hooks:         43
  Models:        34    Events:        12    Imports:     1,376

Edges: 8,934 (avg confidence: 0.89)
  calls:      2,345    imports:    1,876    extends:      234
  implements:   156    contains:   1,567    routes_to:     89
  renders:      234    api_calls:    67     passes_prop:  312

Frameworks:
  Laravel 11.x:  89 routes, 34 models, 12 events
  React 18.x:    156 components, 43 hooks, 12 contexts

Cross-Language:
  API connections: 67 (PHP → JS/TS)
  Shared types: 12 contracts

Architecture:
  Communities: 8 detected clusters
  Top nodes by PageRank:
    1. App\Http\Kernel (0.0234)
    2. App\Models\User (0.0198)
    3. App\Services\AuthService (0.0187)
```

#### `codegraph clean`

```
$ codegraph clean --help
Usage: codegraph clean [OPTIONS]

  Remove generated .codegraph directory.

Options:
  --force    Skip confirmation prompt
  --help     Show this message and exit.
```

### 7.4 CLI Implementation

```python
# src/codegraph/cli/main.py
import click
from pathlib import Path


@click.group()
@click.option("-c", "--config", type=click.Path(), default=None,
              help="Path to codegraph.yaml config file")
@click.option("-d", "--project-dir", type=click.Path(exists=True), default=".",
              help="Project root directory")
@click.option("-v", "--verbose", count=True, help="Increase verbosity")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output except errors")
@click.version_option()
@click.pass_context
def cli(ctx, config, project_dir, verbose, quiet):
    """CodeGraph — Build knowledge graphs from codebases for LLM consumption."""
    ctx.ensure_object(dict)
    ctx.obj["project_dir"] = str(Path(project_dir).resolve())
    ctx.obj["config_path"] = config
    ctx.obj["verbosity"] = 0 if quiet else verbose + 1  # 0=quiet, 1=normal, 2=info, 3=debug


@cli.command()
@click.option("--full", is_flag=True, help="Force full re-parse")
@click.option("--no-resolve", is_flag=True, help="Skip resolution phase")
@click.option("--no-frameworks", is_flag=True, help="Skip framework detection")
@click.option("--no-cross-language", is_flag=True, help="Skip cross-language matching")
@click.option("--no-enrichment", is_flag=True, help="Skip enrichment phase")
@click.option("--workers", type=int, default=None, help="Parallel workers")
@click.option("--dry-run", is_flag=True, help="Show what would be parsed")
@click.option("--profile", is_flag=True, help="Enable profiling")
@click.pass_context
def parse(ctx, full, no_resolve, no_frameworks, no_cross_language,
          no_enrichment, workers, dry_run, profile):
    """Parse codebase and build the knowledge graph."""
    from codegraph.core.config import CodeGraphConfig
    from codegraph.core.pipeline import Pipeline
    from codegraph.plugins.registry import PluginRegistry
    from codegraph.graph.sqlite_store import SQLiteGraphStore
    from codegraph.core.progress import CLIProgressReporter

    project_dir = ctx.obj["project_dir"]
    config = CodeGraphConfig.load(project_dir, ctx.obj["config_path"])

    if workers is not None:
        config.max_workers = workers

    registry = PluginRegistry()
    registry.discover()
    registry.initialize(config)

    output_path = Path(project_dir) / config.output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    store = SQLiteGraphStore(str(output_path / "graph.db"), config)
    reporter = CLIProgressReporter(verbosity=ctx.obj["verbosity"])

    pipeline = Pipeline(
        config=config,
        store=store,
        registry=registry,
        reporter=reporter,
    )

    pipeline.run(
        repo_path=project_dir,
        full_reparse=full,
        skip_resolution=no_resolve,
        skip_frameworks=no_frameworks,
        skip_cross_language=no_cross_language,
        skip_enrichment=no_enrichment,
        dry_run=dry_run,
    )
```

---

## 8. MCP Server Integration

### 8.1 MCP Architecture

CodeGraph exposes its knowledge graph as an **MCP (Model Context Protocol) server**, allowing LLMs to query code structure through standardized tool calls.

```
┌─────────────────┐     MCP Protocol      ┌──────────────────────┐
│                 │  (stdio or SSE)        │                      │
│   LLM Client    │◄─────────────────────▶│  CodeGraph MCP       │
│   (Claude, etc) │                        │  Server              │
│                 │                        │                      │
└─────────────────┘                        │  ┌────────────────┐  │
                                           │  │ Tools (8)      │  │
                                           │  │ • lookup_symbol│  │
                                           │  │ • find_usages  │  │
                                           │  │ • impact_of    │  │
                                           │  │ • ...          │  │
                                           │  └────────────────┘  │
                                           │  ┌────────────────┐  │
                                           │  │ Resources (3)  │  │
                                           │  │ • graph_summary│  │
                                           │  │ • architecture │  │
                                           │  │ • file_map     │  │
                                           │  └────────────────┘  │
                                           │  ┌────────────────┐  │
                                           │  │ GraphStore     │  │
                                           │  │ (SQLite)       │  │
                                           │  └────────────────┘  │
                                           └──────────────────────┘
```

### 8.2 MCP Tools

CodeGraph exposes **8 MCP tools** organized by use case:

#### Tool 1: `codegraph_lookup_symbol`

**Purpose**: Look up a symbol (class, function, method, etc.) and return its definition, relationships, and context.

```json
{
  "name": "codegraph_lookup_symbol",
  "description": "Look up a code symbol and return its definition, relationships, and surrounding context. Use this to understand what a class, function, method, or component does and how it connects to other code.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "Symbol name or qualified name (e.g., 'UserService', 'App\\Services\\UserService', 'UserService::createUser')"
      },
      "detail_level": {
        "type": "string",
        "enum": ["signature", "summary", "detailed", "comprehensive"],
        "default": "summary",
        "description": "Level of detail: signature (just declaration), summary (+ direct relationships), detailed (+ source code), comprehensive (+ transitive relationships)"
      },
      "token_budget": {
        "type": "integer",
        "default": 4000,
        "description": "Maximum tokens in response"
      }
    },
    "required": ["symbol"]
  }
}
```

**Example response** (summary level):
```markdown
## UserService (Class)
**File**: `app/Services/UserService.php:15-89`
**Language**: PHP | **Namespace**: `App\Services`

### Definition
```php
class UserService
{
    public function __construct(private UserRepository $repo, private EventDispatcher $events) {}
    public function createUser(array $data): User {}
    public function updateUser(int $id, array $data): User {}
    public function deleteUser(int $id): void {}
}
```

### Relationships
- **Depends on**: `UserRepository`, `EventDispatcher`, `User` (model)
- **Called by**: `UserController::store()`, `UserController::update()`, `UserController::destroy()`
- **Dispatches events**: `UserCreated`, `UserUpdated`, `UserDeleted`
- **Importance**: PageRank 0.0187 (rank #3)
```

#### Tool 2: `codegraph_find_usages`

```json
{
  "name": "codegraph_find_usages",
  "description": "Find all usages of a symbol — who calls it, imports it, extends it, or references it. Use this to understand how widely a symbol is used before making changes.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "Symbol name or qualified name"
      },
      "usage_types": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["calls", "imports", "extends", "implements", "instantiates", "type_references", "all"]
        },
        "default": ["all"],
        "description": "Types of usages to find"
      },
      "max_depth": {
        "type": "integer",
        "default": 1,
        "description": "Depth for transitive usage search (1 = direct only)"
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["symbol"]
  }
}
```

#### Tool 3: `codegraph_impact_analysis`

```json
{
  "name": "codegraph_impact_analysis",
  "description": "Analyze the blast radius of changing a symbol. Shows all code that would be affected by modifying a class, function, or method, organized by distance from the change.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "Symbol to analyze impact for"
      },
      "max_depth": {
        "type": "integer",
        "default": 3,
        "description": "Maximum depth of impact analysis"
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["symbol"]
  }
}
```

#### Tool 4: `codegraph_file_context`

```json
{
  "name": "codegraph_file_context",
  "description": "Get the structural overview of a file — all symbols defined in it, their relationships, and how the file connects to the rest of the codebase. Use this before editing a file to understand its role.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "Relative file path (e.g., 'app/Services/UserService.php')"
      },
      "include_source": {
        "type": "boolean",
        "default": true,
        "description": "Include source code in response"
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["file_path"]
  }
}
```

#### Tool 5: `codegraph_find_routes`

```json
{
  "name": "codegraph_find_routes",
  "description": "Find API routes/endpoints matching a pattern. Shows the route definition, HTTP method, controller/handler, middleware, and connected frontend code.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pattern": {
        "type": "string",
        "description": "URL pattern to search (e.g., '/api/users', '/api/*')"
      },
      "http_method": {
        "type": "string",
        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "ANY"],
        "description": "Filter by HTTP method"
      },
      "include_frontend": {
        "type": "boolean",
        "default": true,
        "description": "Include connected frontend code (API calls)"
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["pattern"]
  }
}
```

#### Tool 6: `codegraph_search`

```json
{
  "name": "codegraph_search",
  "description": "Full-text search across the codebase knowledge graph. Searches symbol names, qualified names, and docblocks. Use this when you don't know the exact symbol name.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query (supports FTS5 syntax: AND, OR, NOT, prefix*)"
      },
      "node_types": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Filter by node types (e.g., ['class', 'function', 'component'])"
      },
      "language": {
        "type": "string",
        "description": "Filter by language"
      },
      "limit": {
        "type": "integer",
        "default": 20
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["query"]
  }
}
```

#### Tool 7: `codegraph_architecture`

```json
{
  "name": "codegraph_architecture",
  "description": "Get a high-level architecture overview of the codebase. Shows the main modules/clusters, key entry points, most important symbols, and cross-language connections. Use this to understand the overall structure before diving into specifics.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "focus": {
        "type": "string",
        "enum": ["full", "backend", "frontend", "api_layer", "data_layer"],
        "default": "full",
        "description": "Focus area for the overview"
      },
      "token_budget": {
        "type": "integer",
        "default": 8000
      }
    }
  }
}
```

#### Tool 8: `codegraph_dependency_graph`

```json
{
  "name": "codegraph_dependency_graph",
  "description": "Show the dependency graph for a symbol or file. Visualizes what depends on what, including circular dependencies.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "target": {
        "type": "string",
        "description": "Symbol name or file path"
      },
      "direction": {
        "type": "string",
        "enum": ["dependencies", "dependents", "both"],
        "default": "both",
        "description": "Show what this depends on, what depends on this, or both"
      },
      "max_depth": {
        "type": "integer",
        "default": 2
      },
      "token_budget": {
        "type": "integer",
        "default": 4000
      }
    },
    "required": ["target"]
  }
}
```

### 8.3 MCP Resources

CodeGraph exposes **3 MCP resources** for passive context:

```python
# Resource 1: Graph summary (always available)
{
    "uri": "codegraph://summary",
    "name": "CodeGraph Summary",
    "description": "Knowledge graph statistics and project overview",
    "mimeType": "text/markdown"
}

# Resource 2: Architecture overview (computed on demand)
{
    "uri": "codegraph://architecture",
    "name": "Architecture Overview",
    "description": "High-level codebase architecture with key modules and entry points",
    "mimeType": "text/markdown"
}

# Resource 3: File map (tree view)
{
    "uri": "codegraph://file-map",
    "name": "File Map",
    "description": "Annotated file tree showing symbols per file",
    "mimeType": "text/markdown"
}
```

### 8.4 MCP Server Implementation

```python
# src/codegraph/mcp/server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, Resource, TextContent

from codegraph.core.config import CodeGraphConfig
from codegraph.graph.sqlite_store import SQLiteGraphStore
from codegraph.graph.networkx_bridge import NetworkXAnalyzer
from codegraph.output.context import ContextAssemblerImpl
from codegraph.output.markdown import MarkdownFormatter


def create_server(project_dir: str, config: CodeGraphConfig) -> Server:
    """Create and configure the MCP server."""
    server = Server("codegraph")
    store = SQLiteGraphStore(
        str(Path(project_dir) / config.output_dir / "graph.db"),
        config
    )
    store.initialize()
    analyzer = NetworkXAnalyzer()
    analyzer.load_from_store(store)
    formatter = MarkdownFormatter(config)
    assembler = ContextAssemblerImpl(formatter)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="codegraph_lookup_symbol",
                description="Look up a code symbol and return its definition, relationships, and context.",
                inputSchema={...}  # As defined above
            ),
            # ... all 8 tools
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        token_budget = min(
            arguments.get("token_budget", config.mcp_default_token_budget),
            config.mcp_max_token_budget
        )

        if name == "codegraph_lookup_symbol":
            result = assembler.assemble_for_symbol(
                qualified_name=arguments["symbol"],
                store=store,
                analyzer=analyzer,
                token_budget=token_budget,
                detail_level=arguments.get("detail_level", "summary"),
            )
        elif name == "codegraph_find_usages":
            # ... implementation
            pass
        elif name == "codegraph_impact_analysis":
            # ... implementation
            pass
        # ... other tools

        return [TextContent(type="text", text=result)]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="codegraph://summary",
                name="CodeGraph Summary",
                description="Knowledge graph statistics",
                mimeType="text/markdown",
            ),
            # ... other resources
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        if uri == "codegraph://summary":
            summary = store.get_summary()
            return formatter.format_graph_summary(summary)
        elif uri == "codegraph://architecture":
            return assembler.assemble(
                query="architecture overview",
                store=store,
                analyzer=analyzer,
                token_budget=config.mcp_default_token_budget,
            )
        elif uri == "codegraph://file-map":
            # Generate annotated file tree
            return _generate_file_map(store, formatter)

    return server


async def run_stdio(project_dir: str, config: CodeGraphConfig):
    """Run MCP server with stdio transport."""
    server = create_server(project_dir, config)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)
```

### 8.5 Context Window Management

The MCP server implements **token-budgeted context assembly** to ensure responses fit within LLM context windows:

```python
class ContextAssemblerImpl(ContextAssembler):
    """Token-budgeted context assembly with progressive detail."""

    # Detail level token allocations (percentage of budget)
    ALLOCATION = {
        "signature": {"definition": 0.3, "relationships": 0.5, "metadata": 0.2},
        "summary": {"definition": 0.2, "relationships": 0.4, "source": 0.2, "metadata": 0.2},
        "detailed": {"definition": 0.15, "relationships": 0.3, "source": 0.35, "metadata": 0.2},
        "comprehensive": {"definition": 0.1, "relationships": 0.25, "source": 0.4, "transitive": 0.15, "metadata": 0.1},
    }

    def assemble_for_symbol(self, qualified_name: str, store: GraphStore,
                             analyzer: GraphAnalyzer, token_budget: int = 4000,
                             detail_level: str = "summary") -> str:
        """Assemble context for a symbol within token budget."""
        node = store.get_node_by_qualified_name(qualified_name)
        if not node:
            # Try fuzzy search
            candidates = store.search_nodes(qualified_name, limit=5)
            if not candidates:
                return f"Symbol '{qualified_name}' not found in the knowledge graph."
            # Return search results
            return self._format_search_results(candidates, token_budget)

        alloc = self.ALLOCATION[detail_level]
        sections = []
        remaining = token_budget

        # 1. Definition section
        def_budget = int(token_budget * alloc["definition"])
        sections.append(self._format_definition(node, def_budget))
        remaining -= self._count_tokens(sections[-1])

        # 2. Relationships section
        rel_budget = int(token_budget * alloc["relationships"])
        edges = store.get_edges(source_id=node.id) + store.get_edges(target_id=node.id)
        related_nodes = [store.get_node(e.target_id if e.source_id == node.id else e.source_id) for e in edges]
        sections.append(self._format_relationships(node, edges, related_nodes, rel_budget))
        remaining -= self._count_tokens(sections[-1])

        # 3. Source code (if budget allows)
        if "source" in alloc and remaining > 200:
            src_budget = min(int(token_budget * alloc["source"]), remaining)
            sections.append(self._format_source(node, src_budget))
            remaining -= self._count_tokens(sections[-1])

        # 4. Transitive relationships (comprehensive only)
        if "transitive" in alloc and remaining > 200:
            trans_budget = min(int(token_budget * alloc["transitive"]), remaining)
            neighbors = store.get_neighbors(node.id, max_depth=2)
            sections.append(self._format_transitive(neighbors, trans_budget))

        return "\n\n".join(sections)
```

---

## 9. Storage Architecture

### 9.1 SQLite Schema

The knowledge graph is stored in a single SQLite database with WAL mode for concurrent reads.

```sql
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

-- ─── Nodes ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,                    -- Unique node ID
    kind TEXT NOT NULL,                     -- NodeKind enum value
    name TEXT NOT NULL,                     -- Short name
    qualified_name TEXT NOT NULL,           -- Fully-qualified name
    file_path TEXT NOT NULL,                -- Relative to project root
    start_line INTEGER NOT NULL,            -- 1-based
    end_line INTEGER NOT NULL,              -- 1-based, inclusive
    language TEXT NOT NULL,                 -- 'php', 'javascript', 'typescript'
    docblock TEXT,                          -- PHPDoc/JSDoc/TSDoc content
    content_hash TEXT,                      -- SHA-256 of source text
    metadata TEXT NOT NULL DEFAULT '{}',    -- JSON metadata
    pagerank REAL DEFAULT 0.0,             -- Computed PageRank score
    community_id INTEGER,                  -- Detected community/cluster
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_language ON nodes(language);
CREATE INDEX IF NOT EXISTS idx_nodes_qualified_name ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_pagerank ON nodes(pagerank DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_community ON nodes(community_id);

-- Full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    name,
    qualified_name,
    docblock,
    content='nodes',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- FTS triggers for automatic sync
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, name, qualified_name, docblock)
    VALUES (new.rowid, new.name, new.qualified_name, new.docblock);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, docblock)
    VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docblock);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, docblock)
    VALUES ('delete', old.rowid, old.name, old.qualified_name, old.docblock);
    INSERT INTO nodes_fts(rowid, name, qualified_name, docblock)
    VALUES (new.rowid, new.name, new.qualified_name, new.docblock);
END;

-- ─── Edges ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,                -- FK to nodes.id
    target_id TEXT NOT NULL,                -- FK to nodes.id
    kind TEXT NOT NULL,                     -- EdgeKind enum value
    confidence REAL NOT NULL DEFAULT 1.0,   -- 0.0-1.0
    line_number INTEGER,                    -- Where relationship occurs
    metadata TEXT NOT NULL DEFAULT '{}',    -- JSON metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Composite unique constraint (no duplicate edges)
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
    ON edges(source_id, target_id, kind);

-- Indexes for traversal queries
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_confidence ON edges(confidence);
CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target_id, kind);

-- ─── File Tracking (for incremental updates) ────────────────────
CREATE TABLE IF NOT EXISTS file_hashes (
    file_path TEXT PRIMARY KEY,             -- Relative to project root
    content_hash TEXT NOT NULL,             -- SHA-256
    language TEXT NOT NULL,
    plugin_name TEXT NOT NULL,
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    parse_time_ms REAL DEFAULT 0.0,
    last_parsed TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Graph Metadata ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Source Code Cache (optional, for LLM context) ──────────────
CREATE TABLE IF NOT EXISTS source_cache (
    node_id TEXT PRIMARY KEY,               -- FK to nodes.id
    source_text TEXT NOT NULL,              -- Source code of the symbol
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);
```

### 9.2 Key Query Patterns

```sql
-- Find all callers of a function (1 level)
SELECT n.* FROM nodes n
JOIN edges e ON e.source_id = n.id
WHERE e.target_id = :node_id
  AND e.kind = 'calls'
ORDER BY n.pagerank DESC;

-- Transitive callers (CTE, up to 3 levels)
WITH RECURSIVE callers(id, depth) AS (
    SELECT source_id, 1 FROM edges
    WHERE target_id = :node_id AND kind = 'calls'
    UNION ALL
    SELECT e.source_id, c.depth + 1 FROM edges e
    JOIN callers c ON e.target_id = c.id
    WHERE e.kind = 'calls' AND c.depth < :max_depth
)
SELECT DISTINCT n.*, c.depth FROM nodes n
JOIN callers c ON n.id = c.id
ORDER BY c.depth, n.pagerank DESC;

-- Blast radius (all affected nodes)
WITH RECURSIVE impact(id, depth) AS (
    SELECT target_id, 1 FROM edges
    WHERE source_id = :node_id
    UNION ALL
    SELECT e.target_id, i.depth + 1 FROM edges e
    JOIN impact i ON e.source_id = i.id
    WHERE i.depth < :max_depth
)
SELECT n.*, i.depth FROM nodes n
JOIN impact i ON n.id = i.id
ORDER BY i.depth, n.pagerank DESC;

-- Find implementations of an interface
SELECT n.* FROM nodes n
JOIN edges e ON e.source_id = n.id
WHERE e.target_id = (
    SELECT id FROM nodes WHERE qualified_name = :interface_name
)
AND e.kind = 'implements';

-- Cross-language API connections
SELECT
    backend.name AS endpoint,
    backend.file_path AS backend_file,
    frontend.name AS caller,
    frontend.file_path AS frontend_file,
    e.confidence,
    json_extract(e.metadata, '$.http_method') AS method,
    json_extract(e.metadata, '$.url_pattern') AS url
FROM edges e
JOIN nodes backend ON e.target_id = backend.id
JOIN nodes frontend ON e.source_id = frontend.id
WHERE e.kind IN ('api_calls', 'api_serves')
ORDER BY e.confidence DESC;

-- Full-text search
SELECT n.* FROM nodes n
JOIN nodes_fts fts ON n.rowid = fts.rowid
WHERE nodes_fts MATCH :query
ORDER BY rank
LIMIT :limit;

-- Architecture overview: top nodes by PageRank per community
SELECT * FROM (
    SELECT n.*, ROW_NUMBER() OVER (
        PARTITION BY n.community_id
        ORDER BY n.pagerank DESC
    ) AS rank_in_community
    FROM nodes n
    WHERE n.community_id IS NOT NULL
)
WHERE rank_in_community <= 5
ORDER BY community_id, pagerank DESC;

-- File overview: all symbols in a file with relationships
SELECT
    n.*,
    (
        SELECT json_group_array(json_object(
            'kind', e.kind,
            'target', e.target_id,
            'confidence', e.confidence
        ))
        FROM edges e WHERE e.source_id = n.id
    ) AS outgoing_edges,
    (
        SELECT json_group_array(json_object(
            'kind', e.kind,
            'source', e.source_id,
            'confidence', e.confidence
        ))
        FROM edges e WHERE e.target_id = n.id
    ) AS incoming_edges
FROM nodes n
WHERE n.file_path = :file_path
ORDER BY n.start_line;
```

### 9.3 NetworkX Bridge

The `NetworkXAnalyzer` loads the SQLite graph into an in-memory NetworkX `DiGraph` for algorithm execution:

```python
# src/codegraph/graph/networkx_bridge.py
import networkx as nx
from codegraph.graph.store import GraphStore
from codegraph.graph.models import EdgeKind


class NetworkXAnalyzer(GraphAnalyzer):
    """NetworkX-based graph analyzer."""

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._pagerank_cache: dict[str, float] | None = None
        self._centrality_cache: dict[str, float] | None = None

    def load_from_store(self, store: GraphStore) -> None:
        """Load all nodes and edges into NetworkX."""
        self.graph.clear()
        self._pagerank_cache = None
        self._centrality_cache = None

        # Load nodes
        for node in store.find_nodes(limit=999999):
            self.graph.add_node(node.id, **{
                "kind": node.kind.value,
                "name": node.name,
                "qualified_name": node.qualified_name,
                "file_path": node.file_path,
                "language": node.language,
            })

        # Load edges
        for edge in store.get_edges():
            self.graph.add_edge(edge.source_id, edge.target_id, **{
                "kind": edge.kind.value,
                "confidence": edge.confidence,
            })

    def pagerank(self, personalization=None) -> dict[str, float]:
        if self._pagerank_cache is None or personalization:
            self._pagerank_cache = nx.pagerank(
                self.graph,
                alpha=0.85,
                personalization=personalization,
                max_iter=100,
                tol=1e-06,
            )
        return self._pagerank_cache

    def betweenness_centrality(self) -> dict[str, float]:
        if self._centrality_cache is None:
            self._centrality_cache = nx.betweenness_centrality(
                self.graph, k=min(100, len(self.graph)),
            )
        return self._centrality_cache

    def community_detection(self) -> list[set[str]]:
        """Detect communities using Louvain method."""
        import community as community_louvain
        undirected = self.graph.to_undirected()
        partition = community_louvain.best_partition(undirected)
        communities: dict[int, set[str]] = {}
        for node_id, comm_id in partition.items():
            communities.setdefault(comm_id, set()).add(node_id)
        return list(communities.values())

    def shortest_path(self, source_id, target_id) -> list[str] | None:
        try:
            return nx.shortest_path(self.graph, source_id, target_id)
        except nx.NetworkXNoPath:
            return None

    def find_cycles(self, edge_kinds=None) -> list[list[str]]:
        if edge_kinds:
            subgraph = nx.DiGraph()
            for u, v, data in self.graph.edges(data=True):
                if data.get("kind") in [k.value for k in edge_kinds]:
                    subgraph.add_edge(u, v)
            return list(nx.simple_cycles(subgraph))
        return list(nx.simple_cycles(self.graph))

    def relevance_score(self, node_id: str, query_context: dict) -> float:
        """Multi-factor relevance scoring."""
        score = 0.0
        pr = self.pagerank()

        # Factor 1: PageRank (structural importance)
        score += pr.get(node_id, 0.0) * 100  # Normalize to ~0-1 range

        # Factor 2: Distance from query target
        if "target_id" in query_context:
            try:
                path_len = nx.shortest_path_length(
                    self.graph, query_context["target_id"], node_id
                )
                score += max(0, 1.0 - path_len * 0.25)  # Decay with distance
            except nx.NetworkXNoPath:
                pass

        # Factor 3: Edge type relevance
        if "preferred_edge_kinds" in query_context:
            for _, _, data in self.graph.edges(node_id, data=True):
                if data.get("kind") in query_context["preferred_edge_kinds"]:
                    score += 0.2

        # Factor 4: Name similarity
        if "query_text" in query_context:
            node_data = self.graph.nodes.get(node_id, {})
            name = node_data.get("name", "")
            if query_context["query_text"].lower() in name.lower():
                score += 0.5

        return min(score, 1.0)
```

### 9.4 Database Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  First Run   │     │ Incremental │     │   Query     │
│              │     │   Update    │     │   Mode      │
│ CREATE tables│     │ BEGIN txn   │     │ READ-ONLY   │
│ INSERT all   │     │ DELETE stale│     │ WAL mode    │
│ BUILD FTS    │     │ UPSERT new  │     │ concurrent  │
│ COMMIT       │     │ REBUILD FTS │     │ reads OK    │
│              │     │ COMMIT      │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

**WAL Mode Benefits**:
- Concurrent reads during writes (MCP server can query while parse runs)
- Better write performance (sequential log writes)
- Crash recovery (WAL is replayed on next open)

```python
# Enable WAL mode on connection
def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    return conn
```

---

## 10. Testing Strategy

### 10.1 Testing Pyramid

```
                    ┌─────────┐
                    │  E2E    │  5 tests
                    │ (CLI)   │  Full pipeline on real repos
                   ┌┴─────────┴┐
                   │Integration │  20-30 tests
                   │            │  Multi-phase pipeline, MCP server
                  ┌┴────────────┴┐
                  │  Unit Tests   │  200+ tests
                  │               │  Parsers, resolvers, formatters
                 ┌┴───────────────┴┐
                 │  Static Analysis │  mypy, ruff, bandit
                 └─────────────────┘
```

### 10.2 Unit Tests

#### Parser/Extractor Tests

Each language plugin's extractor is tested against small, focused code samples:

```python
# tests/unit/plugins/php/test_extractor.py
import pytest
from codegraph.plugins.php.extractor import PHPExtractor
from codegraph.graph.models import NodeKind, EdgeKind


class TestPHPClassExtraction:
    """Test PHP class extraction from tree-sitter AST."""

    def test_simple_class(self, php_parser):
        source = b"""
        <?php
        namespace App\\Services;

        class UserService
        {
            public function createUser(array $data): User
            {
                return new User($data);
            }
        }
        """
        tree = php_parser.parse(source)
        extractor = PHPExtractor()
        result = extractor.extract("app/Services/UserService.php", tree, source)

        # Verify class node
        class_nodes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "UserService"
        assert class_nodes[0].qualified_name == "App\\Services\\UserService"

        # Verify method node
        method_nodes = [n for n in result.nodes if n.kind == NodeKind.METHOD]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "createUser"

        # Verify return type edge
        type_edges = [e for e in result.edges if e.kind == EdgeKind.RETURNS_TYPE]
        assert len(type_edges) == 1

    def test_abstract_class_with_interface(self, php_parser):
        source = b"""
        <?php
        abstract class BaseRepository implements RepositoryInterface
        {
            abstract public function find(int $id): ?Model;
        }
        """
        tree = php_parser.parse(source)
        extractor = PHPExtractor()
        result = extractor.extract("app/Repositories/BaseRepository.php", tree, source)

        class_nodes = [n for n in result.nodes if n.kind == NodeKind.CLASS]
        assert class_nodes[0].metadata["is_abstract"] is True

        impl_edges = [e for e in result.edges if e.kind == EdgeKind.IMPLEMENTS]
        assert len(impl_edges) == 1

    def test_trait_usage(self, php_parser):
        source = b"""
        <?php
        class User extends Model
        {
            use HasFactory, SoftDeletes;
        }
        """
        tree = php_parser.parse(source)
        extractor = PHPExtractor()
        result = extractor.extract("app/Models/User.php", tree, source)

        trait_edges = [e for e in result.edges if e.kind == EdgeKind.USES_TRAIT]
        assert len(trait_edges) == 2

    def test_parse_error_tolerance(self, php_parser):
        """Tree-sitter should handle syntax errors gracefully."""
        source = b"""
        <?php
        class Broken {
            public function foo( { // missing closing paren
                return 42;
            }
        }
        """
        tree = php_parser.parse(source)
        extractor = PHPExtractor()
        result = extractor.extract("broken.php", tree, source)

        # Should still extract the class, even with errors
        assert len(result.nodes) > 0
        assert len(result.errors) > 0
```

#### Resolver Tests

```python
# tests/unit/plugins/javascript/test_resolver.py
import pytest
from codegraph.plugins.javascript.resolver import JSModuleResolver


class TestJSModuleResolver:
    """Test JavaScript module resolution."""

    @pytest.fixture
    def resolver(self, tmp_path):
        """Create resolver with a mock project structure."""
        # Create mock files
        (tmp_path / "src" / "utils").mkdir(parents=True)
        (tmp_path / "src" / "utils" / "helpers.js").write_text("export const foo = 1;")
        (tmp_path / "src" / "utils" / "index.js").write_text("export * from './helpers';")
        (tmp_path / "src" / "components" / "Button.jsx").touch()
        (tmp_path / "node_modules" / "lodash" / "package.json").write_text(
            '{"name": "lodash", "main": "lodash.js"}'
        )
        (tmp_path / "node_modules" / "lodash" / "lodash.js").touch()
        (tmp_path / "package.json").write_text('{"type": "module"}')

        return JSModuleResolver(
            project_root=str(tmp_path),
            config={"aliases": {"@": "src"}}
        )

    def test_relative_import_exact(self, resolver):
        result = resolver.resolve("./helpers", "src/utils/index.js")
        assert result.resolved_path.endswith("src/utils/helpers.js")
        assert result.confidence >= 0.95

    def test_relative_import_with_extension(self, resolver):
        result = resolver.resolve("./helpers.js", "src/utils/index.js")
        assert result.resolved_path.endswith("src/utils/helpers.js")
        assert result.confidence == 1.0

    def test_directory_index_resolution(self, resolver):
        result = resolver.resolve("./utils", "src/app.js")
        assert result.resolved_path.endswith("src/utils/index.js")

    def test_alias_resolution(self, resolver):
        result = resolver.resolve("@/utils/helpers", "src/components/Button.jsx")
        assert result.resolved_path.endswith("src/utils/helpers.js")
        assert result.resolution_strategy == "alias"

    def test_node_modules_resolution(self, resolver):
        result = resolver.resolve("lodash", "src/utils/helpers.js")
        assert result.is_external is True
        assert result.resolved_path.endswith("lodash/lodash.js")

    def test_unresolved_import(self, resolver):
        result = resolver.resolve("./nonexistent", "src/app.js")
        assert result.resolved_path is None
        assert result.confidence <= 0.1
```

#### Framework Detector Tests

```python
# tests/unit/plugins/php/test_laravel.py
import pytest
from codegraph.plugins.php.frameworks.laravel import LaravelDetector


class TestLaravelRouteDetection:
    """Test Laravel route extraction."""

    def test_basic_route(self, php_parser):
        source = b"""
        <?php
        Route::get('/users', [UserController::class, 'index']);
        Route::post('/users', [UserController::class, 'store']);
        """
        tree = php_parser.parse(source)
        detector = LaravelDetector()
        patterns = detector.detect("routes/api.php", tree, source, [], [])

        route_nodes = []
        for p in patterns:
            route_nodes.extend([n for n in p.nodes if n.kind == NodeKind.ROUTE])

        assert len(route_nodes) == 2
        assert route_nodes[0].metadata["http_method"] == "GET"
        assert route_nodes[0].metadata["path"] == "/users"
        assert route_nodes[1].metadata["http_method"] == "POST"

    def test_route_group(self, php_parser):
        source = b"""
        <?php
        Route::prefix('api/v1')->middleware('auth:sanctum')->group(function () {
            Route::get('/users', [UserController::class, 'index']);
        });
        """
        tree = php_parser.parse(source)
        detector = LaravelDetector()
        patterns = detector.detect("routes/api.php", tree, source, [], [])

        route_nodes = []
        for p in patterns:
            route_nodes.extend([n for n in p.nodes if n.kind == NodeKind.ROUTE])

        assert len(route_nodes) == 1
        assert route_nodes[0].metadata["path"] == "/api/v1/users"
        assert "auth:sanctum" in route_nodes[0].metadata["middleware"]

    def test_resource_route(self, php_parser):
        source = b"""
        <?php
        Route::apiResource('users', UserController::class);
        """
        tree = php_parser.parse(source)
        detector = LaravelDetector()
        patterns = detector.detect("routes/api.php", tree, source, [], [])

        route_nodes = []
        for p in patterns:
            route_nodes.extend([n for n in p.nodes if n.kind == NodeKind.ROUTE])

        # apiResource generates 5 routes: index, store, show, update, destroy
        assert len(route_nodes) == 5
```

#### Graph Store Tests

```python
# tests/unit/graph/test_sqlite_store.py
import pytest
from codegraph.graph.sqlite_store import SQLiteGraphStore
from codegraph.graph.models import Node, Edge, NodeKind, EdgeKind


@pytest.fixture
def store(tmp_path):
    """Create an in-memory SQLite store for testing."""
    db_path = str(tmp_path / "test.db")
    s = SQLiteGraphStore(db_path)
    s.initialize()
    yield s
    s.close()


class TestSQLiteGraphStore:

    def test_upsert_and_get_node(self, store):
        node = Node(
            id="test:1:UserService",
            kind=NodeKind.CLASS,
            name="UserService",
            qualified_name="App\\Services\\UserService",
            file_path="app/Services/UserService.php",
            start_line=10,
            end_line=50,
            language="php",
        )
        store.upsert_node(node)
        retrieved = store.get_node("test:1:UserService")
        assert retrieved is not None
        assert retrieved.name == "UserService"
        assert retrieved.kind == NodeKind.CLASS

    def test_bulk_upsert(self, store):
        nodes = [
            Node(id=f"test:{i}:Func{i}", kind=NodeKind.FUNCTION,
                 name=f"func{i}", qualified_name=f"func{i}",
                 file_path="test.php", start_line=i, end_line=i+5,
                 language="php")
            for i in range(100)
        ]
        count = store.upsert_nodes(nodes)
        assert count == 100

    def test_full_text_search(self, store):
        node = Node(
            id="test:1:UserService",
            kind=NodeKind.CLASS,
            name="UserService",
            qualified_name="App\\Services\\UserService",
            file_path="app/Services/UserService.php",
            start_line=10, end_line=50, language="php",
            docblock="Service for managing user accounts and authentication",
        )
        store.upsert_node(node)
        results = store.search_nodes("authentication")
        assert len(results) >= 1
        assert results[0].name == "UserService"

    def test_delete_nodes_for_file(self, store):
        nodes = [
            Node(id=f"test:{i}:Func{i}", kind=NodeKind.FUNCTION,
                 name=f"func{i}", qualified_name=f"func{i}",
                 file_path="test.php", start_line=i, end_line=i+5,
                 language="php")
            for i in range(10)
        ]
        store.upsert_nodes(nodes)
        deleted = store.delete_nodes_for_file("test.php")
        assert deleted == 10
        assert store.find_nodes(file_path="test.php") == []

    def test_get_neighbors(self, store):
        # Create nodes
        store.upsert_node(Node(
            id="a", kind=NodeKind.CLASS, name="A", qualified_name="A",
            file_path="a.php", start_line=1, end_line=10, language="php"))
        store.upsert_node(Node(
            id="b", kind=NodeKind.CLASS, name="B", qualified_name="B",
            file_path="b.php", start_line=1, end_line=10, language="php"))
        store.upsert_node(Node(
            id="c", kind=NodeKind.CLASS, name="C", qualified_name="C",
            file_path="c.php", start_line=1, end_line=10, language="php"))

        # Create edges: A -> B -> C
        store.upsert_edge(Edge(source_id="a", target_id="b", kind=EdgeKind.CALLS))
        store.upsert_edge(Edge(source_id="b", target_id="c", kind=EdgeKind.CALLS))

        # Depth 1: A's outgoing neighbors = [B]
        neighbors = store.get_neighbors("a", direction="outgoing", max_depth=1)
        assert len(neighbors) == 1
        assert neighbors[0][0].name == "B"

        # Depth 2: A's outgoing neighbors = [B, C]
        neighbors = store.get_neighbors("a", direction="outgoing", max_depth=2)
        assert len(neighbors) == 2

    def test_blast_radius(self, store):
        # Create a dependency chain: A -> B -> C, A -> D
        for name in ["A", "B", "C", "D"]:
            store.upsert_node(Node(
                id=name.lower(), kind=NodeKind.CLASS, name=name,
                qualified_name=name, file_path=f"{name.lower()}.php",
                start_line=1, end_line=10, language="php"))

        store.upsert_edge(Edge(source_id="a", target_id="b", kind=EdgeKind.CALLS))
        store.upsert_edge(Edge(source_id="b", target_id="c", kind=EdgeKind.CALLS))
        store.upsert_edge(Edge(source_id="a", target_id="d", kind=EdgeKind.CALLS))

        radius = store.blast_radius("a", max_depth=3)
        assert "1" in radius  # depth 1: B, D
        assert len(radius["1"]) == 2
        assert "2" in radius  # depth 2: C
        assert len(radius["2"]) == 1
```

### 10.3 Integration Tests

```python
# tests/integration/test_full_pipeline.py
import pytest
from pathlib import Path
from codegraph.core.config import CodeGraphConfig
from codegraph.core.pipeline import Pipeline
from codegraph.plugins.registry import PluginRegistry
from codegraph.graph.sqlite_store import SQLiteGraphStore
from codegraph.core.progress import NullProgressReporter


@pytest.fixture
def laravel_fixture():
    """Path to the Laravel test fixture."""
    return str(Path(__file__).parent.parent / "fixtures" / "php" / "laravel-app")


@pytest.fixture
def react_fixture():
    """Path to the React test fixture."""
    return str(Path(__file__).parent.parent / "fixtures" / "javascript" / "react-app")


@pytest.fixture
def mixed_fixture():
    """Path to the mixed Laravel+React fixture."""
    return str(Path(__file__).parent.parent / "fixtures" / "mixed" / "laravel-react")


class TestFullPipeline:

    def test_php_pipeline(self, laravel_fixture, tmp_path):
        """Test full pipeline on a Laravel project."""
        config = CodeGraphConfig(output_dir=str(tmp_path / ".codegraph"))
        registry = PluginRegistry()
        registry.discover()
        registry.initialize(config)

        store = SQLiteGraphStore(str(tmp_path / ".codegraph" / "graph.db"))
        pipeline = Pipeline(config, store, registry, NullProgressReporter())

        summary = pipeline.run(laravel_fixture)

        assert summary.total_nodes > 0
        assert summary.total_edges > 0
        assert "php" in summary.files_by_language
        assert summary.parse_errors == 0

        # Verify specific nodes exist
        user_model = store.get_node_by_qualified_name("App\\Models\\User")
        assert user_model is not None
        assert user_model.kind == NodeKind.CLASS

        # Verify routes were detected
        routes = store.find_nodes(kind=NodeKind.ROUTE)
        assert len(routes) > 0

    def test_react_pipeline(self, react_fixture, tmp_path):
        """Test full pipeline on a React project."""
        config = CodeGraphConfig(output_dir=str(tmp_path / ".codegraph"))
        registry = PluginRegistry()
        registry.discover()
        registry.initialize(config)

        store = SQLiteGraphStore(str(tmp_path / ".codegraph" / "graph.db"))
        pipeline = Pipeline(config, store, registry, NullProgressReporter())

        summary = pipeline.run(react_fixture)

        assert summary.total_nodes > 0
        components = store.find_nodes(kind=NodeKind.COMPONENT)
        assert len(components) > 0

    def test_cross_language_pipeline(self, mixed_fixture, tmp_path):
        """Test cross-language matching in a mixed project."""
        config = CodeGraphConfig(
            output_dir=str(tmp_path / ".codegraph"),
            cross_language_enabled=True,
        )
        registry = PluginRegistry()
        registry.discover()
        registry.initialize(config)

        store = SQLiteGraphStore(str(tmp_path / ".codegraph" / "graph.db"))
        pipeline = Pipeline(config, store, registry, NullProgressReporter())

        summary = pipeline.run(mixed_fixture)

        # Verify cross-language edges exist
        api_edges = store.get_edges(kind=EdgeKind.API_CALLS)
        assert len(api_edges) > 0

    def test_incremental_update(self, laravel_fixture, tmp_path):
        """Test that incremental updates only re-parse changed files."""
        config = CodeGraphConfig(output_dir=str(tmp_path / ".codegraph"))
        registry = PluginRegistry()
        registry.discover()
        registry.initialize(config)

        store = SQLiteGraphStore(str(tmp_path / ".codegraph" / "graph.db"))
        pipeline = Pipeline(config, store, registry, NullProgressReporter())

        # First run: full parse
        summary1 = pipeline.run(laravel_fixture)

        # Second run: no changes, should skip all files
        summary2 = pipeline.run(laravel_fixture)

        # All files should be skipped on second run
        # (summary2 should show 0 files parsed)
        assert summary2.total_parse_time_ms < summary1.total_parse_time_ms
```

### 10.4 Test Fixtures

Test fixtures are **minimal but realistic** project structures:

```
tests/fixtures/
├── php/
│   └── laravel-app/              # ~10 files, covers key Laravel patterns
│       ├── composer.json          # PSR-4 autoloading config
│       ├── routes/api.php         # Route definitions
│       ├── app/Models/User.php    # Eloquent model with traits
│       ├── app/Http/Controllers/UserController.php  # Controller
│       └── app/Services/UserService.php             # Service class
├── javascript/
│   └── react-app/                # ~8 files, covers React patterns
│       ├── package.json           # Dependencies
│       ├── src/App.jsx            # Root component
│       ├── src/components/UserList.jsx  # Component with hooks
│       └── src/hooks/useUsers.js  # Custom hook
├── typescript/
│   └── nextjs-app/               # ~8 files, covers Next.js + TS patterns
│       ├── package.json
│       ├── tsconfig.json          # Path aliases
│       ├── app/page.tsx           # App Router page
│       └── app/api/users/route.ts # API route
└── mixed/
    └── laravel-react/            # ~12 files, covers cross-language
        ├── composer.json
        ├── package.json
        ├── routes/api.php         # PHP API routes
        ├── app/Http/Controllers/ApiController.php
        └── resources/js/api/client.js  # JS fetch calls to PHP API
```

### 10.5 Test Configuration

```toml
# pyproject.toml — test configuration
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks integration tests",
    "php: marks tests requiring PHP binary",
]
addopts = [
    "--strict-markers",
    "-ra",
    "--tb=short",
]

[tool.coverage.run]
source = ["src/codegraph"]
omit = ["*/tests/*", "*/__main__.py"]

[tool.coverage.report]
show_missing = true
fail_under = 80
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "@abstractmethod",
    "raise NotImplementedError",
]
```

### 10.6 Shared Test Fixtures

```python
# tests/conftest.py
import pytest
import tree_sitter_php as tspython_php
import tree_sitter_javascript as ts_javascript
import tree_sitter_typescript as ts_typescript
from tree_sitter import Language, Parser


@pytest.fixture(scope="session")
def php_language():
    return Language(tspython_php.language())


@pytest.fixture(scope="session")
def js_language():
    return Language(ts_javascript.language())


@pytest.fixture(scope="session")
def ts_language():
    return Language(ts_typescript.language_typescript())


@pytest.fixture(scope="session")
def tsx_language():
    return Language(ts_typescript.language_tsx())


@pytest.fixture
def php_parser(php_language):
    parser = Parser(php_language)
    return parser


@pytest.fixture
def js_parser(js_language):
    parser = Parser(js_language)
    return parser


@pytest.fixture
def ts_parser(ts_language):
    parser = Parser(ts_language)
    return parser


@pytest.fixture
def tsx_parser(tsx_language):
    parser = Parser(tsx_language)
    return parser
```

---

## 11. Dependency Management

### 11.1 Core Dependencies

```toml
# pyproject.toml
[project]
name = "codegraph"
version = "1.0.0"
description = "Build knowledge graphs from codebases for LLM consumption"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [{name = "CodeGraph Team"}]
readme = "README.md"

dependencies = [
    # ── Parsing ────────────────────────────────────────────
    "tree-sitter>=0.23.0,<1.0",
    # Tree-sitter language grammars (pre-compiled wheels)
    "tree-sitter-php>=0.23.0",
    "tree-sitter-javascript>=0.23.0",
    "tree-sitter-typescript>=0.23.0",

    # ── Graph ─────────────────────────────────────────────
    "networkx>=3.2,<4.0",
    # Community detection for NetworkX
    "python-louvain>=0.16,<1.0",

    # ── Configuration ─────────────────────────────────────
    "pyyaml>=6.0,<7.0",

    # ── CLI ───────────────────────────────────────────────
    "click>=8.1,<9.0",
    "rich>=13.0,<14.0",

    # ── MCP Server ────────────────────────────────────────
    "mcp>=1.0,<2.0",

    # ── Utilities ─────────────────────────────────────────
    "pathspec>=0.12,<1.0",
    # Token counting for LLM context budgeting
    "tiktoken>=0.7,<1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9.0",
    "pytest-cov>=5.0,<6.0",
    "pytest-xdist>=3.5,<4.0",
    "mypy>=1.8,<2.0",
    "ruff>=0.3,<1.0",
    "pre-commit>=3.6,<4.0",
]

[project.scripts]
codegraph = "codegraph.cli.main:cli"

[project.entry-points."codegraph.plugins"]
php = "codegraph.plugins.php:PHPPlugin"
javascript = "codegraph.plugins.javascript:JavaScriptPlugin"
typescript = "codegraph.plugins.typescript:TypeScriptPlugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/codegraph"]
```

### 11.2 Dependency Justification

| Package | Purpose | Why This One |
|---------|---------|-------------|
| `tree-sitter` | AST parsing | Fast (C-based), incremental, error-tolerant, multi-language |
| `tree-sitter-php` | PHP grammar | Official grammar, pre-compiled wheels |
| `tree-sitter-javascript` | JS grammar | Official grammar, includes JSX support |
| `tree-sitter-typescript` | TS grammar | Official grammar, includes TSX support |
| `networkx` | Graph algorithms | De facto standard, PageRank, centrality, community detection |
| `python-louvain` | Community detection | Best Louvain implementation for NetworkX |
| `pyyaml` | YAML config parsing | Standard, fast, well-maintained |
| `click` | CLI framework | Composable, well-documented, supports groups and plugins |
| `rich` | Terminal output | Beautiful progress bars, tables, syntax highlighting |
| `mcp` | MCP server SDK | Official Python SDK for Model Context Protocol |
| `pathspec` | Gitignore matching | Implements full gitignore spec including negation patterns |
| `tiktoken` | Token counting | OpenAI's tokenizer, accurate for LLM context budgeting |
| `pytest` | Testing | Standard, extensible, excellent fixture system |
| `mypy` | Type checking | Static type analysis for Python |
| `ruff` | Linting + formatting | Fast (Rust-based), replaces flake8 + black + isort |

### 11.3 External Tool Dependencies (Optional)

| Tool | Purpose | Required? |
|------|---------|----------|
| `php` (binary) | PHP name resolution via nikic/PHP-Parser | Optional — degrades gracefully |
| `composer` | Install PHP-Parser | Optional — only if PHP name resolution needed |
| `phpstan` / `larastan` | PHP type enrichment | Optional — enrichment phase |
| `git` | Git metadata enrichment | Optional — enrichment phase |

### 11.4 No-Dependency Alternatives

For environments where external tools are unavailable:

| Feature | With External Tool | Without External Tool |
|---------|-------------------|---------------------|
| PHP name resolution | nikic/PHP-Parser (accurate) | Tree-sitter + heuristic namespace resolution (80% accuracy) |
| PHP type enrichment | PHPStan/Larastan | Skip — no type enrichment |
| Git metadata | `git log` subprocess | Skip — no change frequency data |
| Token counting | tiktoken (accurate) | Character-based estimation (÷4 heuristic) |

---

## 12. Implementation Roadmap

### 12.1 Phase Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Implementation Phases                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  P0: Foundation (Days 1-5)                                       │
│  ├── Project scaffolding, config, plugin system                  │
│  ├── PHP extractor (tree-sitter)                                 │
│  ├── SQLite graph store                                          │
│  └── Basic CLI (parse + info)                                    │
│                                                                  │
│  P1: Core Features (Days 6-11)                                   │
│  ├── JS/TS extractors                                            │
│  ├── Module resolution (PHP + JS/TS)                             │
│  ├── Laravel framework detector                                  │
│  ├── React framework detector                                    │
│  └── CLI query + export commands                                 │
│                                                                  │
│  P2: Advanced Features (Days 12-17)                              │
│  ├── Cross-language matching                                     │
│  ├── MCP server integration                                      │
│  ├── NetworkX graph algorithms                                   │
│  ├── Token-budgeted context assembly                             │
│  └── Incremental updates                                         │
│                                                                  │
│  P3: Polish & Enrichment (Days 18-22)                            │
│  ├── PHPStan enrichment                                          │
│  ├── Git metadata enrichment                                     │
│  ├── Additional framework detectors (Next.js, Vue, Express)      │
│  ├── Performance optimization                                    │
│  └── Documentation & packaging                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 12.2 P0: Foundation (Days 1-5)

**Goal**: Parse a PHP codebase and store the graph in SQLite.

| Day | Task | Deliverable |
|-----|------|------------|
| 1 | Project scaffolding | `pyproject.toml`, directory structure, CI setup |
| 1 | Configuration system | `CodeGraphConfig`, YAML loading, validation |
| 1 | Plugin registry | `PluginRegistry` with entry point discovery |
| 2 | Data models | `Node`, `Edge`, `NodeKind`, `EdgeKind`, `ExtractionResult` |
| 2 | SQLite graph store | Full `SQLiteGraphStore` with schema, CRUD, FTS5 |
| 3 | PHP extractor | Tree-sitter queries for classes, functions, methods, properties |
| 3 | PHP plugin | `PHPPlugin` implementing `LanguagePlugin` interface |
| 4 | Pipeline orchestrator | 8-phase pipeline (phases 1-3 + 8 functional) |
| 4 | File scanner | Discovery, hashing, incremental tracking |
| 5 | CLI: parse + info | `codegraph parse` and `codegraph info` commands |
| 5 | Unit tests | Tests for extractor, store, config, scanner |

**P0 Exit Criteria**:
- `codegraph parse` on a PHP project produces a populated SQLite database
- `codegraph info` shows correct node/edge counts
- All unit tests pass
- 80%+ code coverage on implemented modules

### 12.3 P1: Core Features (Days 6-11)

**Goal**: Multi-language support with framework detection and querying.

| Day | Task | Deliverable |
|-----|------|------------|
| 6 | JS extractor | Tree-sitter queries for JS functions, classes, imports, exports |
| 6 | JS plugin | `JavaScriptPlugin` with ESM/CJS detection |
| 7 | TS extractor | TypeScript-specific: interfaces, type aliases, generics, decorators |
| 7 | TS plugin | `TypeScriptPlugin` extending `JavaScriptPlugin` |
| 8 | PHP resolver | nikic/PHP-Parser subprocess for FQCN resolution |
| 8 | JS/TS resolver | `JSModuleResolver` with aliases, tsconfig paths, node_modules |
| 9 | Laravel detector | Route extraction, model detection, event detection |
| 9 | React detector | Component detection, hook detection, context detection |
| 10 | CLI: query | `codegraph query` with symbol lookup, callers, impact |
| 10 | CLI: export | `codegraph export` with markdown, JSON, tree formats |
| 11 | Markdown formatter | Token-budgeted structured markdown output |
| 11 | Integration tests | Full pipeline tests for PHP, JS, TS projects |

**P1 Exit Criteria**:
- Parse PHP + JS + TS projects successfully
- Framework patterns detected for Laravel and React
- `codegraph query "ClassName"` returns useful results
- `codegraph export` produces LLM-ready context

### 12.4 P2: Advanced Features (Days 12-17)

**Goal**: Cross-language matching, MCP server, and graph intelligence.

| Day | Task | Deliverable |
|-----|------|------------|
| 12 | Cross-language matcher | Multi-strategy URL matching (exact → fuzzy) |
| 12 | API endpoint extraction | Laravel routes → `APIEndpoint` objects |
| 13 | API call detection | JS fetch/axios → `APICall` objects |
| 13 | Type contract matching | PHP Resources ↔ TS interfaces |
| 14 | NetworkX bridge | Load graph, PageRank, centrality, communities |
| 14 | Relevance scoring | Multi-factor scoring for context assembly |
| 15 | Context assembler | Token-budgeted assembly with progressive detail |
| 15 | MCP server: tools | 8 MCP tools implemented |
| 16 | MCP server: resources | 3 MCP resources, server lifecycle |
| 16 | CLI: serve | `codegraph serve` with stdio/SSE transport |
| 17 | Incremental updates | Content-hash tracking, selective re-parse |
| 17 | Integration tests | Cross-language, MCP, incremental tests |

**P2 Exit Criteria**:
- Cross-language edges detected in mixed PHP+JS projects
- MCP server responds to all 8 tool calls correctly
- Incremental re-parse completes in <2s for unchanged codebases
- PageRank and community detection produce meaningful results

### 12.5 P3: Polish & Enrichment (Days 18-22)

**Goal**: Production-ready with enrichment and additional frameworks.

| Day | Task | Deliverable |
|-----|------|------------|
| 18 | PHPStan enrichment | Subprocess integration, type resolution |
| 18 | Git metadata | Change frequency, co-change analysis |
| 19 | Next.js detector | File-based routing, server/client components |
| 19 | Vue detector | SFC parsing, Composition API |
| 20 | Express detector | Route extraction, middleware chains |
| 20 | CLI: init | Interactive project initialization |
| 21 | Performance optimization | Profiling, batch optimization, caching |
| 21 | Error handling | Comprehensive error messages, graceful degradation |
| 22 | Documentation | README, getting-started, plugin guide, query cookbook |
| 22 | Packaging | PyPI-ready package, GitHub Actions CI/CD |

**P3 Exit Criteria**:
- All framework detectors functional
- Full pipeline completes in <2 minutes for 5,000-file codebase
- Comprehensive documentation
- Package installable via `pip install codegraph`

### 12.6 Success Metrics

| Metric | Target |
|--------|--------|
| Parse accuracy (nodes extracted) | >95% of declarations captured |
| Resolution accuracy | >90% of imports resolved |
| Framework detection | >85% of routes/components detected |
| Cross-language matching | >70% of API connections matched |
| Incremental update speed | <2s for unchanged codebase |
| Full parse speed (5K files) | <2 minutes |
| MCP response latency | <500ms per tool call |
| Test coverage | >80% |
| SQLite database size | <50MB for 5K-file project |

---

## Appendix A: Node Type Reference

| # | Node Kind | Description | Languages |
|---|-----------|-------------|----------|
| 1 | `file` | Source file | All |
| 2 | `directory` | Directory | All |
| 3 | `package` | Package/library | All |
| 4 | `class` | Class declaration | All |
| 5 | `interface` | Interface declaration | PHP, TS |
| 6 | `trait` | Trait declaration | PHP |
| 7 | `function` | Function declaration | All |
| 8 | `method` | Method declaration | All |
| 9 | `property` | Class property | All |
| 10 | `constant` | Constant declaration | All |
| 11 | `enum` | Enum declaration | PHP, TS |
| 12 | `type_alias` | Type alias | TS |
| 13 | `variable` | Variable/export | JS, TS |
| 14 | `namespace` | Namespace | PHP |
| 15 | `module` | Module | JS, TS |
| 16 | `parameter` | Function parameter | All |
| 17 | `import` | Import statement | All |
| 18 | `export` | Export statement | JS, TS |
| 19 | `decorator` | Decorator/attribute | PHP 8, TS |
| 20 | `route` | API route/endpoint | Framework |
| 21 | `component` | UI component | Framework |
| 22 | `hook` | React hook | Framework |
| 23 | `model` | Data model | Framework |
| 24 | `event` | Event class | Framework |
| 25 | `middleware` | Middleware | Framework |

## Appendix B: Edge Type Reference

| # | Edge Kind | Source → Target | Confidence |
|---|-----------|----------------|------------|
| 1 | `contains` | Directory/File → Declaration | 1.0 |
| 2 | `defined_in` | Declaration → File | 1.0 |
| 3 | `member_of` | Method/Property → Class | 1.0 |
| 4 | `extends` | Class → Parent Class | 0.95-1.0 |
| 5 | `implements` | Class → Interface | 0.95-1.0 |
| 6 | `uses_trait` | Class → Trait | 0.95-1.0 |
| 7 | `has_type` | Property/Param → Type | 0.80-1.0 |
| 8 | `returns_type` | Function/Method → Type | 0.80-1.0 |
| 9 | `generic_of` | Type → Generic Parameter | 0.90-1.0 |
| 10 | `union_of` | Type → Union Member | 0.90-1.0 |
| 11 | `intersection_of` | Type → Intersection Member | 0.90-1.0 |
| 12 | `imports` | File → File/Module | 0.80-1.0 |
| 13 | `imports_type` | File → Type (type-only import) | 0.85-1.0 |
| 14 | `exports` | File → Declaration | 1.0 |
| 15 | `re_exports` | File → File (re-export) | 0.90-1.0 |
| 16 | `dynamic_imports` | Function → File | 0.40-0.80 |
| 17 | `depends_on` | File → File (aggregate) | 0.70-1.0 |
| 18 | `calls` | Function → Function | 0.70-1.0 |
| 19 | `instantiates` | Function → Class | 0.85-1.0 |
| 20 | `dispatches_event` | Function → Event | 0.80-0.95 |
| 21 | `listens_to` | Function → Event | 0.80-0.95 |
| 22 | `routes_to` | Route → Controller/Handler | 0.90-1.0 |
| 23 | `renders` | Component → Component | 0.90-1.0 |
| 24 | `passes_prop` | Component → Component | 0.85-0.95 |
| 25 | `uses_hook` | Component → Hook | 0.95-1.0 |
| 26 | `provides_context` | Component → Context | 0.90-1.0 |
| 27 | `api_calls` | Frontend → Backend Endpoint | 0.40-0.95 |
| 28 | `api_serves` | Backend Endpoint → Frontend | 0.40-0.95 |
| 29 | `shares_type_contract` | TS Interface → PHP Resource | 0.30-0.80 |
| 30 | `co_changes_with` | File → File (git-derived) | 0.30-0.90 |

---

*End of Architecture Design Document*
