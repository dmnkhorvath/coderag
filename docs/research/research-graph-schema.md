# Code Knowledge Graph Schema Design: Comprehensive Technical Research

> **Status**: Work in Progress — Research Phase  
> **Date**: 2026-03-10  
> **Purpose**: Inform the architecture of a custom tool that parses PHP, JavaScript, and TypeScript codebases and builds a queryable knowledge graph for LLM context retrieval.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Node Types Taxonomy](#2-node-types-taxonomy)
3. [Edge/Relationship Types](#3-edgerelationship-types)
4. [Existing Tool Analysis](#4-existing-tool-analysis)
5. [Graph Storage Options](#5-graph-storage-options)
6. [Graph Queries for LLM Context Retrieval](#6-graph-queries-for-llm-context-retrieval)
7. [Schema Design Patterns](#7-schema-design-patterns)
8. [LLM-Optimized Output Formats](#8-llm-optimized-output-formats)
9. [Recommendations](#9-recommendations)

---

## 1. Executive Summary

This document presents comprehensive research on designing a code knowledge graph schema optimized for LLM context retrieval. The research synthesizes findings from analysis of six existing tools (code-graph-rag, codebase-memory-mcp, rag-code-mcp, Sourcetrail, LSIF, and aider), evaluation of five storage backends, and design of query patterns for context assembly, impact analysis, and codebase discovery.

### Key Findings

- **Optimal Node Count**: A unified schema for PHP/JS/TS should define **20-25 node types** — enough to capture language-specific constructs without over-fragmenting the graph. Existing tools range from 7 (rag-code-mcp) to 15 (code-graph-rag) node types.
- **Edge Richness Matters**: The most useful tools define **15-25 edge types** covering structural containment, inheritance, call graphs, type system relationships, and framework-specific connections.
- **SQLite is the Sweet Spot**: For a portable, single-file tool targeting 5,000-file codebases, SQLite with recursive CTEs provides the best balance of query performance (<1ms for most traversals), zero infrastructure, and Python integration.
- **PageRank for Context Selection**: Aider's approach of using PageRank on a file-dependency graph to select the most relevant code context for LLMs is proven and effective.
- **Tree-sitter is Universal**: Every major tool uses tree-sitter for multi-language parsing. It supports 64+ languages with consistent AST output.

### Recommended Schema Summary

| Dimension | Recommendation |
|-----------|---------------|
| Node Types | 22 unified types (see Section 2) |
| Edge Types | 24 unified types (see Section 3) |
| Storage | SQLite with WAL mode + FTS5 |
| Query Engine | Recursive CTEs + Python graph algorithms |
| Output Format | Structured markdown with token budgeting |
| Indexing | Tree-sitter + incremental content-hash updates |

---

## 2. Node Types Taxonomy

### 2.1 Comprehensive Node Type Registry

The following taxonomy unifies node types across PHP, JavaScript, and TypeScript, informed by analysis of existing tools and our prior parsing research.

#### 2.1.1 File-Level Nodes

| Node Type | Required Properties | Optional Properties | Language Applicability | Notes |
|-----------|-------------------|--------------------|-----------------------|-------|
| **Project** | `name`, `root_path` | `version`, `type` (monorepo/single), `framework` | All | Root node; one per indexed codebase |
| **Directory** | `path`, `name` | `depth`, `is_package` | All | File system directory |
| **File** | `path`, `name`, `extension`, `language` | `size_bytes`, `line_count`, `hash`, `last_modified` | All | Source file; key structural unit |
| **Package** | `name`, `qualified_name`, `path` | `version`, `type` (npm/composer), `is_workspace` | All | npm package, Composer package, or namespace root |

#### 2.1.2 Declaration-Level Nodes

| Node Type | Required Properties | Optional Properties | Language Applicability | Notes |
|-----------|-------------------|--------------------|-----------------------|-------|
| **Class** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `visibility`, `is_abstract`, `is_final`, `is_readonly`, `decorators[]`, `docblock` | All | PHP classes, JS/TS classes |
| **Interface** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `docblock`, `extends[]` | PHP, TS | PHP interfaces, TS interfaces |
| **Trait** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `docblock` | PHP | PHP traits only |
| **Enum** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `backed_type` (string/int), `is_const`, `docblock` | PHP, TS | PHP 8.1 enums, TS enums |
| **Function** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `is_async`, `is_generator`, `is_exported`, `is_arrow`, `decorators[]`, `docblock`, `signature` | All | Top-level/standalone functions |
| **Method** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `visibility`, `is_static`, `is_abstract`, `is_async`, `is_generator`, `decorators[]`, `docblock`, `signature` | All | Class/interface/trait methods |
| **Property** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `visibility`, `is_static`, `is_readonly`, `type`, `default_value` | All | Class properties |
| **Variable** | `name`, `file_path`, `start_line` | `kind` (const/let/var), `is_exported`, `type` | JS/TS | Module-level variables/constants |
| **Constant** | `name`, `qualified_name`, `file_path`, `start_line` | `value`, `type`, `visibility` | PHP | PHP class constants and `define()` |
| **TypeAlias** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `is_exported`, `docblock` | TS | TypeScript `type X = ...` |
| **Namespace** | `name`, `qualified_name` | `file_path` | PHP, TS | PHP namespaces, TS namespaces/modules |

#### 2.1.3 Structural Nodes

| Node Type | Required Properties | Optional Properties | Language Applicability | Notes |
|-----------|-------------------|--------------------|-----------------------|-------|
| **Parameter** | `name`, `position`, `parent_qualified_name` | `type`, `default_value`, `is_variadic`, `is_reference`, `is_optional` | All | Function/method parameters |
| **Decorator** | `name`, `file_path`, `start_line` | `arguments`, `target_type` | PHP (Attributes), TS | PHP 8 attributes, TS/Angular decorators |

#### 2.1.4 Import/Export Nodes

| Node Type | Required Properties | Optional Properties | Language Applicability | Notes |
|-----------|-------------------|--------------------|-----------------------|-------|
| **ImportStatement** | `source`, `file_path`, `start_line` | `specifiers[]`, `is_type_only`, `is_dynamic`, `is_side_effect` | JS/TS | ES imports, require() calls |
| **ExportStatement** | `file_path`, `start_line` | `specifiers[]`, `is_default`, `is_type_only`, `is_reexport`, `source` | JS/TS | ES exports |

#### 2.1.5 Framework-Specific Nodes

| Node Type | Required Properties | Optional Properties | Language Applicability | Notes |
|-----------|-------------------|--------------------|-----------------------|-------|
| **Route** | `method` (GET/POST/etc), `path`, `handler_qualified_name` | `middleware[]`, `name`, `prefix`, `is_api` | All | HTTP routes (Laravel, Express, Fastify, NestJS) |
| **Component** | `name`, `qualified_name`, `file_path`, `start_line`, `end_line` | `props[]`, `is_lazy`, `is_server`, `is_client`, `framework` | JS/TS | React/Vue/Angular components |
| **Hook** | `name`, `file_path`, `start_line`, `end_line` | `dependencies[]`, `is_custom` | JS/TS (React) | React hooks (useState, useEffect, custom) |
| **Middleware** | `name`, `qualified_name`, `file_path` | `priority`, `groups[]` | All | HTTP middleware |
| **ServiceProvider** | `name`, `qualified_name`, `file_path` | `bindings[]`, `singletons[]`, `deferred` | PHP (Laravel) | Laravel service providers |
| **EventListener** | `event_name`, `listener_qualified_name`, `file_path` | `priority`, `is_queued` | All | Event-listener bindings |
| **Migration** | `name`, `file_path`, `timestamp` | `table_name`, `operations[]` | PHP (Laravel) | Database migrations |
| **Model** | `name`, `qualified_name`, `file_path` | `table`, `fillable[]`, `guarded[]`, `casts{}`, `relations[]` | PHP (Laravel) | Eloquent models |

### 2.2 Cross-Tool Node Type Comparison

| Node Type | code-graph-rag | codebase-memory-mcp | rag-code-mcp | Sourcetrail | Our Schema |
|-----------|---------------|--------------------|--------------|-----------|-----------|
| Project | ✅ | ✅ | — | — | ✅ |
| Directory/Folder | ✅ | ✅ | — | — | ✅ |
| File | ✅ | ✅ | — | ✅ | ✅ |
| Package | ✅ | ✅ | — | — | ✅ |
| Module | ✅ | ✅ | — | — | (merged into File) |
| Class | ✅ | ✅ | ✅ | ✅ | ✅ |
| Interface | ✅ | ✅ | ✅ | — | ✅ |
| Trait | — | — | ✅ | — | ✅ |
| Enum | ✅ | ✅ | — | — | ✅ |
| Function | ✅ | ✅ | ✅ | ✅ | ✅ |
| Method | ✅ | ✅ | ✅ | — | ✅ |
| Property | — | — | ✅ | — | ✅ |
| Variable | — | — | — | ✅ | ✅ |
| Constant | — | — | ✅ | — | ✅ |
| TypeAlias/Type | ✅ | ✅ | — | — | ✅ |
| Route | — | ✅ | — | — | ✅ |
| Component | — | — | — | — | ✅ |
| Hook | — | — | — | — | ✅ |
| External Package | ✅ | — | — | — | (via Package) |
| Union | ✅ | — | — | — | (via TypeAlias) |

---

## 3. Edge/Relationship Types

### 3.1 Comprehensive Edge Type Registry

#### 3.1.1 Structural Edges

| Edge Type | Source → Target | Properties | Directionality | Notes |
|-----------|----------------|------------|---------------|-------|
| **contains** | Directory → File, File → Class/Function/etc | — | Directed | Hierarchical containment |
| **defined_in** | Class/Function/etc → File | `start_line`, `end_line` | Directed | Where a symbol is defined |
| **member_of** | Method/Property → Class/Interface/Trait | `visibility` | Directed | Class membership |
| **has_parameter** | Function/Method → Parameter | `position` | Directed | Parameter relationship |
| **belongs_to_namespace** | Class/Function/etc → Namespace | — | Directed | Namespace membership |

#### 3.1.2 Inheritance & Type System Edges

| Edge Type | Source → Target | Properties | Directionality | Notes |
|-----------|----------------|------------|---------------|-------|
| **extends** | Class → Class, Interface → Interface | — | Directed | Class/interface inheritance |
| **implements** | Class → Interface | — | Directed | Interface implementation |
| **uses_trait** | Class → Trait | `conflict_resolutions{}` | Directed | PHP trait usage |
| **has_type** | Property/Variable/Parameter → TypeAlias/Class/Interface | `is_nullable`, `is_union` | Directed | Type annotation |
| **returns_type** | Function/Method → TypeAlias/Class/Interface | `is_nullable`, `is_union`, `is_void` | Directed | Return type |
| **generic_of** | Class/Function → TypeAlias | `constraint` | Directed | Generic type parameter |
| **union_of** | TypeAlias → TypeAlias/Class/Interface | `position` | Directed | Union type member |
| **intersection_of** | TypeAlias → TypeAlias/Class/Interface | `position` | Directed | Intersection type member |

#### 3.1.3 Dependency Edges

| Edge Type | Source → Target | Properties | Directionality | Notes |
|-----------|----------------|------------|---------------|-------|
| **imports** | File → File, File → Package | `specifiers[]`, `is_type_only`, `is_dynamic` | Directed | Module imports |
| **exports** | File → Class/Function/Variable | `is_default`, `is_type_only`, `alias` | Directed | Module exports |
| **re_exports** | File → File | `specifiers[]` | Directed | Re-export (barrel files) |
| **depends_on** | Package → Package | `version_spec`, `dep_type` (runtime/dev/peer) | Directed | Package dependency |

#### 3.1.4 Call Graph Edges

| Edge Type | Source → Target | Properties | Directionality | Notes |
|-----------|----------------|------------|---------------|-------|
| **calls** | Function/Method → Function/Method | `line_number`, `is_conditional`, `is_async` | Directed | Function/method calls |
| **instantiates** | Function/Method → Class | `line_number` | Directed | `new ClassName()` |
| **dispatches_event** | Function/Method → EventListener | `event_name` | Directed | Event dispatching |

#### 3.1.5 Framework-Specific Edges

| Edge Type | Source → Target | Properties | Directionality | Notes |
|-----------|----------------|------------|---------------|-------|
| **routes_to** | Route → Function/Method | `http_method`, `path` | Directed | Route → handler mapping |
| **renders** | Component → Component | `props_passed[]` | Directed | Component rendering |
| **injects** | Class → Class/Interface | `token`, `scope` | Directed | Dependency injection |
| **provides** | ServiceProvider → Class/Interface | `binding_type` (singleton/transient) | Directed | Service container binding |
| **listens_to** | EventListener → Class | `event_class` | Directed | Event listener registration |
| **middleware_of** | Middleware → Route | `priority` | Directed | Middleware applied to route |
| **has_relationship** | Model → Model | `type` (hasOne/hasMany/belongsTo/etc), `foreign_key`, `local_key` | Directed | Eloquent relationships |

### 3.2 Cross-Tool Edge Type Comparison

| Edge Type | code-graph-rag | codebase-memory-mcp | rag-code-mcp | Sourcetrail | Our Schema |
|-----------|---------------|--------------------|--------------|-----------|-----------|
| contains/member | ✅ (4 types) | ✅ (MEMBER_OF) | — | ✅ (EDGE_MEMBER) | ✅ |
| defines | ✅ (2 types) | ✅ | — | — | ✅ (defined_in) |
| imports | ✅ | ✅ | — | ✅ (EDGE_IMPORT) | ✅ |
| exports | ✅ (2 types) | — | — | — | ✅ |
| calls | ✅ | ✅ | — | ✅ (EDGE_CALL) | ✅ |
| inherits/extends | ✅ | ✅ | (metadata) | ✅ (EDGE_INHERITANCE) | ✅ |
| implements | ✅ | ✅ | (metadata) | — | ✅ |
| overrides | ✅ | — | — | ✅ (EDGE_OVERRIDE) | (via calls) |
| type_usage | — | ✅ (USES_TYPE) | — | ✅ (EDGE_TYPE_USAGE) | ✅ (has_type) |
| HTTP calls | — | ✅ (HTTP_CALLS) | — | — | ✅ (routes_to) |
| async calls | — | ✅ (ASYNC_CALLS) | — | — | ✅ (calls.is_async) |
| tests | — | ✅ (TESTS) | — | — | (future) |
| configures | — | ✅ (CONFIGURES) | — | — | (future) |
| writes | — | ✅ (WRITES) | — | — | (future) |
| file_changes_with | — | ✅ | — | — | (future) |

---

## 4. Existing Tool Analysis

### 4.1 code-graph-rag (vitali87/code-graph-rag)

**Overview**: An accurate RAG system that analyzes multi-language codebases using Tree-sitter, builds comprehensive knowledge graphs in Memgraph, and enables natural language querying.

#### Graph Schema

**Storage Backend**: Memgraph (Cypher-compatible graph database)

**Node Types (15)**:

| Category | Node Labels | Unique Key | Key Properties |
|----------|------------|------------|----------------|
| Structural | `Project` | `name` | `name` |
| Structural | `Package` | `qualified_name` | `qualified_name`, `name`, `path` |
| Structural | `Folder` | `path` | `path`, `name` |
| Structural | `File` | `path` | `path`, `name`, `extension` |
| Structural | `External_Package` | `name` | `name`, `version_spec` |
| Code Entity | `Module` | `qualified_name` | `qualified_name`, `name`, `path` |
| Code Entity | `Class` | `qualified_name` | `qualified_name`, `name`, `decorators[]` |
| Code Entity | `Function` | `qualified_name` | `qualified_name`, `name`, `decorators[]` |
| Code Entity | `Method` | `qualified_name` | `qualified_name`, `name`, `decorators[]` |
| Code Entity | `Interface` | `qualified_name` | `qualified_name`, `name` |
| Code Entity | `Enum` | `qualified_name` | `qualified_name`, `name` |
| Code Entity | `Type` | `qualified_name` | `qualified_name`, `name` |
| Code Entity | `Union` | `qualified_name` | `qualified_name`, `name` |
| Code Entity | `Module_Interface` | `qualified_name` | `qualified_name`, `name` |
| Code Entity | `Module_Implementation` | `qualified_name` | `qualified_name`, `name` |

**Edge Types (14)**:

| Category | Edge Type | Source → Target |
|----------|-----------|----------------|
| Containment | `CONTAINS_PACKAGE` | Project/Package/Folder → Package |
| Containment | `CONTAINS_FOLDER` | Project/Package/Folder → Folder |
| Containment | `CONTAINS_FILE` | Project/Package/Folder → File |
| Containment | `CONTAINS_MODULE` | Project/Package/Folder → Module |
| Definition | `DEFINES` | Module → Class/Function |
| Definition | `DEFINES_METHOD` | Class → Method |
| Import/Export | `IMPORTS` | Module → Module |
| Import/Export | `EXPORTS` | Module → Class/Function |
| Import/Export | `EXPORTS_MODULE` | Module → Module_Interface |
| Import/Export | `IMPLEMENTS_MODULE` | Module → Module_Implementation |
| Type System | `INHERITS` | Class → Class |
| Type System | `IMPLEMENTS` | Class/Module_Impl → Interface/Module_Interface |
| Type System | `OVERRIDES` | Method → Method |
| Call Graph | `CALLS` | Function/Method → Function/Method |

**Qualified Name Format**: Hierarchical dot-separated (e.g., `project_name.package.module.ClassName.method_name`)

**Key Design Decisions**:
- Uses `MERGE` operations with unique constraints to prevent duplicate nodes
- Separate node types for Module_Interface and Module_Implementation (OCaml/ReasonML specific)
- No framework-specific nodes (no Route, Component, etc.)
- Relatively flat property model — decorators stored as list on node

#### Supported Queries
- Finding functions with specific decorators
- Tracing class method definitions via `DEFINES_METHOD`
- Following call chains via `CALLS` edges
- Discovering inheritance hierarchies via `INHERITS`
- Semantic search (via RAG integration)

#### Strengths & Limitations

| Strengths | Limitations |
|-----------|------------|
| Clean, well-defined schema | No framework-specific nodes |
| Memgraph provides fast Cypher queries | Requires running Memgraph server |
| Good multi-language support via tree-sitter | No property/variable tracking |
| Unique constraints prevent duplicates | No type system edges beyond inheritance |
| MCP server integration | OCaml-specific types may be unnecessary |

---

### 4.2 codebase-memory-mcp (DeusData/codebase-memory-mcp)

**Overview**: A single Go binary MCP server that indexes codebases into a persistent knowledge graph with sub-millisecond queries. Supports 64 languages.

#### Graph Schema

**Storage Backend**: SQLite (WAL mode), persisted to `~/.cache/codebase-memory-mcp/codebase-memory.db`

**Node Types (12)**: `Project`, `Package`, `Folder`, `File`, `Module`, `Class`, `Function`, `Method`, `Interface`, `Enum`, `Type`, `Route`

**Common Node Properties**: `name`, `qualified_name`, `file_path`, `start_line`, `end_line`

**Extended Properties by Node Type**:
- `Function`/`Method`: `signature`, `return_type`, `receiver`, `decorators`, `is_exported`, `is_entry_point`
- `Route`: `method`, `path`, `handler`
- `Module`: `constants`

**Edge Types (18)**:

| Category | Edge Type | Properties |
|----------|-----------|------------|
| Containment | `CONTAINS_PACKAGE`, `CONTAINS_FOLDER`, `CONTAINS_FILE` | — |
| Definition | `DEFINES`, `DEFINES_METHOD` | — |
| Import | `IMPORTS` | — |
| Call Graph | `CALLS` | `via` (e.g., "route_registration") |
| Call Graph | `HTTP_CALLS` | `confidence` (0.0-1.0), `url_path`, `http_method` |
| Call Graph | `ASYNC_CALLS` | — |
| Type System | `IMPLEMENTS`, `USES_TYPE` | — |
| Framework | `HANDLES` | — |
| Data Flow | `USAGE`, `CONFIGURES`, `WRITES` | — |
| Membership | `MEMBER_OF` | — |
| Testing | `TESTS` | — |
| Co-change | `FILE_CHANGES_WITH` | — |

#### Architecture & Performance

**Multi-Pass Indexing Pipeline**:
1. **Structure** — File/directory discovery
2. **Definitions** — Tree-sitter AST extraction
3. **Calls** — Cross-file call resolution (import-aware, type-inferred)
4. **HTTP Links** — REST route/call-site matching with confidence scoring
5. **Communities** — Louvain community detection on call edges
6. **Tests** — Test relationship identification

**Performance Benchmarks**:
- Cypher-like traversal queries: <1ms (600x faster than earlier versions)
- BFS call path tracing at depth 5: <10ms
- Regex name searches: <10ms (SQL LIKE pre-filtering + Go regex)
- Incremental reindex: ~1.2s for Django-sized codebase (49K nodes, 196K edges)
- Full scan: ~6s for same codebase

**Key Design Decisions**:
- SQLite with WAL mode for zero-infrastructure deployment
- Content-hash based incremental reindexing
- Background watcher with adaptive polling intervals
- Louvain community detection for architectural analysis
- Risk classification on git diff impact analysis
- Custom Cypher-like query language (subset: MATCH, WHERE, RETURN, ORDER BY, LIMIT)

#### MCP Tools (12)

| Category | Tool | Purpose |
|----------|------|---------|
| Indexing | `index_repository` | Initial codebase indexing |
| Indexing | `list_projects` | List indexed projects |
| Indexing | `delete_project` | Remove project data |
| Query | `search_graph` | Structured search with filters |
| Query | `query_graph` | Cypher-like graph queries |
| Query | `trace_call_path` | BFS call path traversal (depth 1-5) |
| Query | `detect_changes` | Git diff → affected symbols + blast radius |
| Query | `get_code_snippet` | Read source by qualified name |
| Query | `search_code` | Grep-like text search |
| Architecture | `get_architecture` | Codebase overview (languages, entry points, hotspots, layers, clusters) |
| Architecture | `manage_adr` | Architecture Decision Records CRUD |
| Architecture | `get_graph_schema` | Node/edge counts and patterns |

#### Strengths & Limitations

| Strengths | Limitations |
|-----------|------------|
| Zero infrastructure (single binary + SQLite) | Go binary, not Python-native |
| Sub-millisecond queries | Custom Cypher subset (no WITH, COLLECT, OPTIONAL MATCH) |
| 64 language support | No property/variable node types |
| Git diff impact analysis | No type system edges beyond IMPLEMENTS |
| Louvain community detection | No component/hook framework nodes |
| Incremental reindexing | — |
| Route node type | — |

---

### 4.3 rag-code-mcp (doITmagic/rag-code-mcp)

**Overview**: Semantic code navigation MCP server using RAG with multi-language support, local LLMs (Ollama), and vector search (Qdrant).

#### Schema Approach

**Storage Backend**: Qdrant (vector database) — NOT a graph database

**Key Insight**: rag-code-mcp does NOT use a graph schema. Instead, it stores richly-annotated **CodeChunk** objects in a vector store for semantic search. Relationships are embedded as metadata within chunks rather than as explicit graph edges.

**CodeChunk Types (7 for PHP)**:

| Type | Description | Key Metadata |
|------|-------------|-------------|
| `class` | PHP class | `extends`, `implements[]`, `traits[]`, `abstract`, `final`, `docblock` |
| `method` | Class method | `class_name`, `visibility`, `static`, `abstract`, `final`, `parameters[]`, `return_type` |
| `function` | Global function | `namespace`, `parameters[]`, `return_type`, `docblock` |
| `interface` | Interface | `methods[]`, `docblock` |
| `trait` | Trait | `methods[]`, `docblock` |
| `const` | Class constant | `value`, `visibility` |
| `property` | Class property | `type`, `visibility`, `default_value` |

**Laravel-Specific Metadata**:
- Eloquent models: `fillable[]`, `guarded[]`, `casts{}`, `table`, `primaryKey`, `relations[]` (with related model, foreign/local keys), `scopes[]`, `accessors[]`, `mutators[]`
- Controllers: `actions[]`, HTTP method mappings, resource controller detection
- Routes: HTTP methods, URIs, controller bindings, route names

**PHP Parser**: VKCOM/php-parser v0.8.2 (Go implementation, PHP 8.0-8.2 syntax support)

#### MCP Tools (9)

| Tool | Purpose |
|------|---------|
| `search_code` | Semantic search by meaning |
| `hybrid_search` | Combined keyword + semantic search |
| `get_function_details` | Complete function source code |
| `find_type_definition` | Type/class definitions with fields and methods |
| `find_implementations` | All usages and callers of a symbol |
| `list_package_exports` | Exported symbols in a package/namespace |
| `search_docs` | Markdown documentation search |
| `get_code_context` | Code snippet with surrounding context |
| `index_workspace` | Trigger reindexing |

#### Strengths & Limitations

| Strengths | Limitations |
|-----------|------------|
| Rich PHP/Laravel metadata extraction | No graph structure — vector search only |
| Semantic search via embeddings | Cannot traverse relationships |
| VKCOM parser handles PHP 8.0-8.2 | No call graph analysis |
| Local LLM support (Ollama) | No impact analysis |
| Good Laravel-specific extraction | Requires Qdrant server |

---

### 4.4 Sourcetrail (CoatiSoftware/Sourcetrail)

**Overview**: Open-source cross-platform source explorer with interactive graph visualization. Now archived but influential in code graph design.

#### Graph Schema

**Storage Backend**: SQLite (custom schema)

**Node Types**: Generic — nodes represent any code entity (function, class, variable, file) with a `type` field distinguishing them. No fixed enumeration of node labels.

**Node Properties**:
- `type`: Code entity kind
- `name_hierarchy`: Fully qualified name
- `definition_kind`: Whether defined, implicit, or explicit
- `edges[]`: References to all relationships
- `child_count`: Number of child nodes

**Edge Types (10)**:

| Edge Type | Description |
|-----------|-------------|
| `EDGE_MEMBER` | Parent-child relationship between code elements |
| `EDGE_TYPE_USAGE` | When code uses a type (variable declarations) |
| `EDGE_USAGE` | When code uses another element (variable usages) |
| `EDGE_CALL` | Function/method calls |
| `EDGE_INHERITANCE` | Class inheritance |
| `EDGE_OVERRIDE` | Method overrides |
| `EDGE_INCLUDE` | File inclusion (C/C++ #include) |
| `EDGE_IMPORT` | Import statements (Python, etc.) |
| `EDGE_TEMPLATE_SPECIALIZATION` | Template specializations (C++) |
| `EDGE_BUNDLED_EDGES` | Multiple edges grouped together |

**Visualization-Specific Node Types (DummyNode)**:
- `DUMMY_DATA`: Actual code entity
- `DUMMY_ACCESS`: Groups by access modifier
- `DUMMY_EXPAND_TOGGLE`: Expand/collapse toggle
- `DUMMY_BUNDLE`: Grouped nodes
- `DUMMY_QUALIFIER`: Namespace qualifiers
- `DUMMY_TEXT`: Text display
- `DUMMY_GROUP`: Related node groups

#### Key Design Decisions
- Generic node type system (type field rather than labeled nodes)
- SQLite for portable, single-file storage
- Visualization-oriented dummy nodes for graph rendering
- Separate USAGE vs TYPE_USAGE edges
- BUNDLED_EDGES for visual simplification
- Supported C, C++, Java, Python

#### Strengths & Limitations

| Strengths | Limitations |
|-----------|------------|
| Proven SQLite storage for code graphs | Archived/unmaintained |
| Clean edge type taxonomy | Limited language support |
| Interactive visualization | No framework-specific analysis |
| Portable single-file database | No MCP/LLM integration |

---

### 4.5 LSIF (Language Server Index Format)

**Overview**: A standard format for language servers to emit pre-computed code intelligence data as a graph, enabling rich code navigation without running a live language server.

#### Graph Structure

LSIF models code intelligence as a directed graph of **vertices** and **edges**:

**Vertex Types**:
- `document`: Source file (properties: `uri`, `languageId`)
- `range`: Code range within a document (properties: `start`, `end` positions)
- `hoverResult`: Hover information (type signatures, documentation)
- `foldingRangeResult`: Folding range information
- `definitionResult`: Go-to-definition targets
- `referenceResult`: Find-all-references results
- `implementationResult`: Go-to-implementation targets
- `documentSymbolResult`: Document symbol list

**Edge Types**:
- `contains`: Document → Range (document contains this range)
- `textDocument/hover`: Range → HoverResult
- `textDocument/foldingRange`: Document → FoldingRangeResult
- `textDocument/definition`: Range → DefinitionResult
- `textDocument/references`: Range → ReferenceResult
- `textDocument/implementation`: Range → ImplementationResult
- `textDocument/documentSymbol`: Document → DocumentSymbolResult

**Data Model**: Tuples of `[request, document, range] → result` for position-based requests, or `[request, document] → result` for document-level requests.

**Key Design Decisions**:
- Streaming-friendly: data emitted incrementally during parsing
- Range-based (not position-based) for compactness
- Each vertex/edge has unique `id`, `type`, and `label`
- Edges use `outV`/`inV` for source/target references
- Designed for persistence in databases for offline querying

#### Relevance to Our Schema

LSIF is complementary to a code knowledge graph — it provides **position-level** intelligence (hover, go-to-definition) while our schema provides **structural** intelligence (call graphs, inheritance, dependencies). A hybrid approach could:
1. Use our knowledge graph for structural queries
2. Use LSIF-style data for precise source location mapping
3. Share the `range` concept for linking graph nodes to exact source positions

---

### 4.6 Aider (Repository Map)

**Overview**: AI coding assistant that uses a repository map to provide code context to LLMs. Not a graph database, but uses graph algorithms for context selection.

#### Architecture

**Graph Construction**:
- Extracts tags (definitions and references) from all repository files using **tree-sitter** parsers
- Falls back to **Pygments** for languages where tree-sitter only provides definitions
- Builds a **file-dependency graph** using **NetworkX** where:
  - Nodes = source files
  - Edges = dependencies based on definitions/references
  - Edge weights = computed from identifier characteristics

**Context Selection Algorithm**:
1. Build file-dependency graph from tree-sitter tags
2. Run **PageRank** with personalization vector:
   - Files in chat: weight `100 / num_files`
   - Mentioned filenames: same weight
   - Files matching mentioned identifiers: boosted
3. Rank all tags by PageRank scores
4. Binary search over token budget to select highest-ranked tags
5. Render as compact tree representation using `TreeContext` from `grep_ast`

**Output Format**:
~~~
aider/coders/base_coder.py:
│class Coder:
│    def __init__(self, ...):
│⋮...
│    def run(self, ...):
│⋮...
│    def get_repo_map(self):
│⋮...
aider/repo_map.py:
│class RepoMap:
│    def get_ranked_tags(self, ...):
│⋮...
~~~

**Token Budget Management**:
- Default: 1024 tokens for repo map
- When no files in chat: multiplied by 8x (8192 tokens)
- Binary search converges in ~10 iterations
- Sampling-based token counting for efficiency

#### Key Insights for Our Design

1. **PageRank is effective** for identifying the most important code elements relative to a query
2. **Tree-sitter tags** (definitions + references) are sufficient for building useful dependency graphs
3. **Token budgeting** is essential — not all graph data can fit in LLM context
4. **Compact tree format** with elision markers (`⋮...`) is readable by LLMs
5. **File-level granularity** for the dependency graph, with symbol-level detail in output

---

## 5. Graph Storage Options

### 5.1 Comparison Matrix

| Feature | NetworkX | Neo4j | SQLite + CTEs | Custom SQLite | DuckDB | RDF/SPARQL |
|---------|----------|-------|--------------|---------------|--------|------------|
| **Type** | In-memory Python | Graph DB server | Relational + graph | Adjacency list | Analytical DB | Semantic web |
| **Setup** | `pip install` | Docker/server | Built into Python | Built into Python | `pip install` | Server required |
| **Portability** | Memory only | Server required | Single file | Single file | Single file | Server required |
| **Query Language** | Python API | Cypher | SQL + recursive CTEs | SQL | SQL | SPARQL |
| **Graph Traversal** | Native (BFS, DFS, etc.) | Native (Cypher paths) | Recursive CTEs | Application-level | Recursive CTEs | SPARQL property paths |
| **Graph Algorithms** | PageRank, centrality, community detection | GDS library | Manual implementation | Manual implementation | Limited | Limited |
| **Persistence** | None (pickle/JSON export) | Built-in | Built-in | Built-in | Built-in | Built-in |
| **Incremental Updates** | Easy (in-memory) | Easy (MERGE) | Easy (UPSERT) | Easy (UPSERT) | Easy (UPSERT) | Easy |
| **FTS (Full-Text Search)** | No | Built-in | FTS5 extension | FTS5 extension | Limited | No |
| **Python Integration** | Native | neo4j-driver | sqlite3 (stdlib) | sqlite3 (stdlib) | duckdb package | rdflib |
| **Memory (5K files)** | ~50-200MB | ~500MB+ (server) | ~10-50MB (file) | ~10-50MB (file) | ~20-100MB | ~200MB+ |
| **Query Performance** | <1ms (in-memory) | 1-10ms (network) | <1ms (local) | <1ms (local) | <1ms (local) | 10-100ms |
| **Scalability** | ~100K nodes | Millions of nodes | ~1M nodes | ~500K nodes | Millions of rows | Millions of triples |

### 5.2 Detailed Analysis

#### 5.2.1 NetworkX (In-Memory Python Graph)

**Pros**:
- Native Python — zero serialization overhead
- Rich graph algorithm library (PageRank, betweenness centrality, community detection, shortest paths)
- Easy to build and modify graphs programmatically
- Excellent for prototyping and analysis
- Used by aider for repository map generation

**Cons**:
- No persistence — must serialize/deserialize on each use
- Memory-bound — entire graph must fit in RAM
- No query language — all queries are Python code
- No concurrent access
- No full-text search

**Best For**: Graph algorithm computation (PageRank, centrality), prototyping, small codebases (<1000 files)

**Typical Usage Pattern**:
~~~python
import networkx as nx

G = nx.DiGraph()
G.add_node("MyClass", type="class", file="src/MyClass.php", line=10)
G.add_node("myMethod", type="method", file="src/MyClass.php", line=25)
G.add_edge("MyClass", "myMethod", type="member_of")

# PageRank for importance
ranks = nx.pagerank(G, personalization={"MyClass": 1.0})

# Shortest path
path = nx.shortest_path(G, "FileA", "FileB")

# All descendants
descendants = nx.descendants(G, "MyClass")
~~~

#### 5.2.2 Neo4j

**Pros**:
- Purpose-built for graph data — optimized traversals
- Cypher query language is expressive and readable
- Graph Data Science (GDS) library for algorithms
- ACID transactions
- Excellent visualization tools
- Used by code-graph-rag (via Memgraph, Cypher-compatible)

**Cons**:
- Requires running a server (Docker or native)
- Significant memory overhead (~500MB+ for server)
- Network latency for queries
- Complex setup for a "simple" tool
- Overkill for single-user, single-codebase use case

**Best For**: Large-scale multi-codebase analysis, team environments, when Cypher expressiveness is needed

**Typical Cypher Query**:
~~~cypher
// Find all classes that implement an interface
MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface {name: "Payable"})
RETURN c.name, c.file_path

// Trace call chain from function
MATCH path = (f:Function {name: "processOrder"})-[:CALLS*1..5]->(target)
RETURN path

// Find blast radius of changing a class
MATCH (c:Class {name: "UserService"})<-[:CALLS|IMPORTS|USES_TYPE*1..3]-(dependent)
RETURN DISTINCT dependent.name, dependent.file_path
~~~

#### 5.2.3 SQLite with Recursive CTEs

**Pros**:
- Zero infrastructure — single file, ships with Python
- Sub-millisecond queries (proven by codebase-memory-mcp)
- FTS5 for full-text search
- JSON1 extension for flexible property storage
- Recursive CTEs enable graph traversal in pure SQL
- WAL mode for concurrent reads
- Proven at scale: codebase-memory-mcp handles 49K nodes, 196K edges

**Cons**:
- Graph traversal via CTEs is less expressive than Cypher
- No built-in graph algorithms (must implement in Python)
- Recursive CTE depth limits (default 1000, configurable)
- Single-writer limitation

**Best For**: Production deployment, portable tools, medium codebases (1K-10K files)

**Schema Design**:
~~~sql
-- Nodes table
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    qualified_name TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- class, function, method, etc.
    file_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    properties JSON,  -- flexible property storage
    content_hash TEXT  -- for incremental updates
);

-- Edges table
CREATE TABLE edges (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES nodes(id),
    target_id INTEGER NOT NULL REFERENCES nodes(id),
    type TEXT NOT NULL,  -- calls, extends, imports, etc.
    properties JSON,
    UNIQUE(source_id, target_id, type)
);

-- Indexes
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type ON edges(type);

-- Full-text search
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    name, qualified_name, content=nodes, content_rowid=id
);
~~~

**Graph Traversal via Recursive CTE**:
~~~sql
-- Find all transitive callers of a function (up to depth 5)
WITH RECURSIVE call_chain(id, name, depth, path) AS (
    -- Base case: the target function
    SELECT n.id, n.name, 0, n.name
    FROM nodes n
    WHERE n.qualified_name = 'App\\Services\\OrderService::processOrder'
    
    UNION ALL
    
    -- Recursive case: find callers
    SELECT n.id, n.name, cc.depth + 1, cc.path || ' <- ' || n.name
    FROM call_chain cc
    JOIN edges e ON e.target_id = cc.id AND e.type = 'calls'
    JOIN nodes n ON n.id = e.source_id
    WHERE cc.depth < 5
    AND n.name NOT IN (SELECT name FROM call_chain)  -- cycle prevention
)
SELECT DISTINCT name, depth, path FROM call_chain ORDER BY depth;
~~~

#### 5.2.4 Custom Adjacency List in JSON/SQLite

**Pros**:
- Maximum simplicity
- Easy to understand and debug
- Can be stored as JSON for human readability or SQLite for performance
- No dependencies beyond Python stdlib

**Cons**:
- Must implement all traversal algorithms manually
- No query optimization
- JSON files don't scale well beyond ~10K nodes
- No concurrent access for JSON

**Best For**: Prototyping, very small codebases, when simplicity is paramount

#### 5.2.5 DuckDB

**Pros**:
- Excellent analytical query performance
- Columnar storage efficient for aggregations
- Good Python integration
- Supports recursive CTEs
- Single-file database

**Cons**:
- Optimized for analytics, not graph traversal
- Less mature than SQLite for general-purpose use
- Larger binary size
- Overkill for simple graph queries

**Best For**: When heavy analytical queries are needed (aggregations, statistics over the graph)

#### 5.2.6 RDF/SPARQL

**Verdict**: Overkill for code knowledge graphs. RDF's triple-based model adds unnecessary complexity. SPARQL is powerful but verbose. The semantic web standards (OWL, RDFS) provide no benefit for code analysis. Not recommended.

### 5.3 Storage Recommendation

**Primary Storage: SQLite with WAL mode + FTS5**
- Proven by codebase-memory-mcp at scale (49K nodes, 196K edges, sub-ms queries)
- Zero infrastructure, single file, ships with Python
- Recursive CTEs handle 90% of graph traversal needs
- FTS5 provides fast text search
- JSON1 extension for flexible property storage

**Secondary: NetworkX for Graph Algorithms**
- Load SQLite graph into NetworkX for PageRank, centrality, community detection
- Use for context selection (aider's approach)
- Keep in-memory, rebuild from SQLite as needed

**Hybrid Architecture**:
~~~
SQLite (persistence + queries) ←→ NetworkX (algorithms + analysis)
         ↓                                    ↓
    Graph traversal                    PageRank, centrality
    Text search (FTS5)                 Community detection
    Incremental updates                Context selection
    Impact analysis                    Importance ranking
~~~

---

## 6. Graph Queries for LLM Context Retrieval

### 6.1 Context Assembly Queries

#### 6.1.1 "Give me everything related to this function"

**Algorithm**: Multi-hop neighborhood expansion

**SQLite Implementation**:
~~~sql
-- Get function and its immediate context
WITH target AS (
    SELECT id FROM nodes WHERE qualified_name = :qname
),
related AS (
    -- Direct relationships (callers, callees, types used)
    SELECT n.id, n.qualified_name, n.type, e.type as rel_type, 'outgoing' as direction
    FROM target t
    JOIN edges e ON e.source_id = t.id
    JOIN nodes n ON n.id = e.target_id
    
    UNION ALL
    
    SELECT n.id, n.qualified_name, n.type, e.type as rel_type, 'incoming' as direction
    FROM target t
    JOIN edges e ON e.target_id = t.id
    JOIN nodes n ON n.id = e.source_id
    
    UNION ALL
    
    -- The function itself
    SELECT n.id, n.qualified_name, n.type, 'self' as rel_type, 'self' as direction
    FROM target t
    JOIN nodes n ON n.id = t.id
    
    UNION ALL
    
    -- Sibling methods in same class
    SELECT sibling.id, sibling.qualified_name, sibling.type, 'sibling' as rel_type, 'sibling' as direction
    FROM target t
    JOIN edges e1 ON e1.source_id = t.id AND e1.type = 'member_of'
    JOIN edges e2 ON e2.target_id = e1.target_id AND e2.type = 'member_of'
    JOIN nodes sibling ON sibling.id = e2.source_id
    WHERE sibling.id != t.id
)
SELECT * FROM related ORDER BY 
    CASE direction WHEN 'self' THEN 0 WHEN 'outgoing' THEN 1 WHEN 'incoming' THEN 2 ELSE 3 END;
~~~

**NetworkX Implementation**:
~~~python
def get_function_context(G, qualified_name, max_depth=2):
    """Get everything related to a function."""
    context = {"target": qualified_name, "callers": [], "callees": [], 
               "types_used": [], "siblings": [], "file_context": []}
    
    # Direct callees
    for _, target, data in G.out_edges(qualified_name, data=True):
        if data.get("type") == "calls":
            context["callees"].append(target)
        elif data.get("type") in ("has_type", "returns_type"):
            context["types_used"].append(target)
    
    # Direct callers
    for source, _, data in G.in_edges(qualified_name, data=True):
        if data.get("type") == "calls":
            context["callers"].append(source)
    
    # Sibling methods (same class)
    for _, parent, data in G.out_edges(qualified_name, data=True):
        if data.get("type") == "member_of":
            for child, _, d in G.in_edges(parent, data=True):
                if d.get("type") == "member_of" and child != qualified_name:
                    context["siblings"].append(child)
    
    return context
~~~

**LLM Output Format**:
~~~markdown
## Function: App\Services\OrderService::processOrder

### Source (lines 45-78 in src/Services/OrderService.php)
```php
public function processOrder(Order $order, PaymentMethod $payment): OrderResult
{
    // ... source code ...
}
```

### Called By (3 callers)
- `App\Http\Controllers\OrderController::store` (line 23)
- `App\Console\Commands\ProcessPendingOrders::handle` (line 15)
- `App\Jobs\ProcessOrderJob::handle` (line 12)

### Calls (4 callees)
- `App\Services\PaymentService::charge` (line 52)
- `App\Services\InventoryService::reserve` (line 56)
- `App\Events\OrderProcessed::dispatch` (line 72)
- `App\Models\Order::save` (line 74)

### Types Used
- `App\Models\Order` (parameter)
- `App\Contracts\PaymentMethod` (parameter, interface)
- `App\DTOs\OrderResult` (return type)

### Sibling Methods in OrderService
- `cancelOrder(Order $order): void`
- `refundOrder(Order $order, float $amount): RefundResult`
~~~

#### 6.1.2 "What classes implement this interface?"

**SQLite**:
~~~sql
SELECT n.qualified_name, n.file_path, n.start_line
FROM nodes n
JOIN edges e ON e.source_id = n.id
JOIN nodes target ON target.id = e.target_id
WHERE target.qualified_name = :interface_qname
AND e.type = 'implements'
ORDER BY n.qualified_name;
~~~

#### 6.1.3 "Trace data flow from API endpoint to database"

**Algorithm**: BFS from route handler, following `calls` edges, stopping at known database operations

**SQLite**:
~~~sql
WITH RECURSIVE flow(id, name, depth, path) AS (
    -- Start from route handler
    SELECT n.id, n.qualified_name, 0, n.qualified_name
    FROM nodes n
    JOIN edges e ON e.target_id = n.id AND e.type = 'routes_to'
    JOIN nodes route ON route.id = e.source_id
    WHERE route.type = 'route' 
    AND json_extract(route.properties, '$.path') = '/api/orders'
    AND json_extract(route.properties, '$.method') = 'POST'
    
    UNION ALL
    
    SELECT n.id, n.qualified_name, f.depth + 1, f.path || ' -> ' || n.qualified_name
    FROM flow f
    JOIN edges e ON e.source_id = f.id AND e.type = 'calls'
    JOIN nodes n ON n.id = e.target_id
    WHERE f.depth < 10
    AND n.qualified_name NOT IN (SELECT name FROM flow)
)
SELECT * FROM flow ORDER BY depth;
~~~

### 6.2 Impact Analysis Queries

#### 6.2.1 "If I change this method signature, what breaks?"

**Algorithm**: Find all callers (transitive), all implementors (if interface method), all overriders

**SQLite**:
~~~sql
WITH RECURSIVE impact(id, name, type, depth, reason) AS (
    -- Direct callers
    SELECT n.id, n.qualified_name, n.type, 1, 'direct_caller'
    FROM nodes target
    JOIN edges e ON e.target_id = target.id AND e.type = 'calls'
    JOIN nodes n ON n.id = e.source_id
    WHERE target.qualified_name = :method_qname
    
    UNION ALL
    
    -- Transitive callers
    SELECT n.id, n.qualified_name, n.type, i.depth + 1, 'transitive_caller'
    FROM impact i
    JOIN edges e ON e.target_id = i.id AND e.type = 'calls'
    JOIN nodes n ON n.id = e.source_id
    WHERE i.depth < 5
    AND n.id NOT IN (SELECT id FROM impact)
)
SELECT DISTINCT name, type, MIN(depth) as min_depth, reason
FROM impact
GROUP BY name
ORDER BY min_depth;
~~~

#### 6.2.2 "What is the blast radius of modifying this class?"

**Algorithm**: Multi-edge-type BFS — follow calls, imports, uses_type, extends, implements

~~~sql
WITH RECURSIVE blast(id, name, file_path, depth, via) AS (
    SELECT id, qualified_name, file_path, 0, 'origin'
    FROM nodes WHERE qualified_name = :class_qname
    
    UNION ALL
    
    SELECT n.id, n.qualified_name, n.file_path, b.depth + 1, e.type
    FROM blast b
    JOIN edges e ON e.target_id = b.id
    JOIN nodes n ON n.id = e.source_id
    WHERE e.type IN ('calls', 'imports', 'has_type', 'extends', 'implements', 'uses_trait', 'instantiates')
    AND b.depth < 3
    AND n.id NOT IN (SELECT id FROM blast)
)
SELECT DISTINCT file_path, COUNT(*) as affected_symbols, MIN(depth) as distance
FROM blast
WHERE depth > 0
GROUP BY file_path
ORDER BY distance, affected_symbols DESC;
~~~

### 6.3 Discovery Queries

#### 6.3.1 "What are the main entry points?"

**Algorithm**: Find nodes with high in-degree but low out-degree to callers (entry points are called but don't call much), or nodes marked as routes/commands/jobs.

~~~sql
-- Route-based entry points
SELECT n.qualified_name, json_extract(n.properties, '$.method') as http_method,
       json_extract(n.properties, '$.path') as path
FROM nodes n
WHERE n.type = 'route'
ORDER BY path;

-- Command/Job entry points
SELECT n.qualified_name, n.type
FROM nodes n
WHERE n.type IN ('class')
AND (
    n.qualified_name LIKE '%Command%'
    OR n.qualified_name LIKE '%Job%'
    OR n.qualified_name LIKE '%Controller%'
);
~~~

#### 6.3.2 "What are the most connected/important nodes?"

**NetworkX Implementation** (PageRank):
~~~python
import networkx as nx

def find_important_nodes(G, top_n=20):
    """Find most important nodes using PageRank."""
    ranks = nx.pagerank(G)
    sorted_nodes = sorted(ranks.items(), key=lambda x: x[1], reverse=True)
    return sorted_nodes[:top_n]

def find_hub_nodes(G, top_n=20):
    """Find nodes with highest betweenness centrality (bridges between modules)."""
    centrality = nx.betweenness_centrality(G)
    sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    return sorted_nodes[:top_n]
~~~

#### 6.3.3 "Find circular dependencies"

**NetworkX Implementation**:
~~~python
def find_circular_dependencies(G):
    """Find all circular dependencies in the import graph."""
    import_graph = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        if data.get("type") == "imports":
            import_graph.add_edge(u, v)
    
    cycles = list(nx.simple_cycles(import_graph))
    return sorted(cycles, key=len)
~~~

#### 6.3.4 "What are the architectural layers?"

**Algorithm**: Analyze dependency direction — layers should only depend downward

~~~python
def detect_layers(G):
    """Detect architectural layers via dependency direction analysis."""
    # Build condensation (DAG of strongly connected components)
    condensation = nx.condensation(G)
    
    # Topological sort gives layer ordering
    layers = list(nx.topological_generations(condensation))
    
    return layers
~~~

---

## 7. Schema Design Patterns

### 7.1 Unified Multi-Language Schema

**Pattern**: Use a single `type` field on nodes rather than separate tables per language construct. Language-specific properties go in a JSON `properties` column.

~~~json
{
    "id": 42,
    "qualified_name": "App\\Services\\OrderService",
    "name": "OrderService",
    "type": "class",
    "file_path": "src/Services/OrderService.php",
    "start_line": 10,
    "end_line": 150,
    "language": "php",
    "properties": {
        "visibility": "public",
        "is_abstract": false,
        "is_final": true,
        "extends": "App\\Services\\BaseService",
        "implements": ["App\\Contracts\\OrderServiceInterface"],
        "docblock": "Handles order processing logic."
    }
}
~~~

**Advantages**:
- Single nodes table, single edges table — simple schema
- Language-specific properties in JSON — flexible, no schema migrations
- Type field enables filtering without joins
- Same query patterns work across languages

### 7.2 Property Graph vs Labeled Property Graph

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| **Property Graph** (our choice) | Nodes have `type` field + JSON properties | Simple schema, flexible | Type checking in application layer |
| **Labeled Property Graph** | Nodes have multiple labels (Neo4j style) | Rich type system | Requires graph DB, complex queries |
| **RDF** | Subject-predicate-object triples | Standards-based | Verbose, poor performance |

**Recommendation**: Property graph with JSON properties in SQLite. This matches codebase-memory-mcp's proven approach.

### 7.3 Schema Evolution Strategy

1. **Node types**: Add new types by inserting rows with new `type` values — no schema change needed
2. **Edge types**: Same approach — new `type` values in edges table
3. **Properties**: JSON column absorbs new properties without migration
4. **Indexes**: Add new indexes as query patterns emerge
5. **Version field**: Store schema version in a metadata table for migration scripts

~~~sql
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO schema_meta VALUES ('schema_version', '1.0.0');
INSERT INTO schema_meta VALUES ('created_at', '2026-03-10T00:00:00Z');
~~~

### 7.4 Handling Unresolved References

**Problem**: Dynamic dispatch, external dependencies, and runtime-only resolution mean some references can't be statically resolved.

**Solution**: Create "phantom" nodes with a `resolution` property:

~~~json
{
    "qualified_name": "__unresolved__::someFunction",
    "name": "someFunction",
    "type": "function",
    "properties": {
        "resolution": "unresolved",
        "confidence": 0.0,
        "reason": "dynamic_dispatch",
        "call_site": "src/app.js:42"
    }
}
~~~

**Confidence Levels**:
- `1.0`: Statically resolved, exact match
- `0.8`: Resolved via type inference
- `0.5`: Resolved via naming convention
- `0.3`: Multiple candidates, best guess
- `0.0`: Unresolvable

### 7.5 Indexing Strategies

~~~sql
-- Primary lookups
CREATE UNIQUE INDEX idx_nodes_qname ON nodes(qualified_name);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_nodes_name ON nodes(name);

-- Edge traversal
CREATE INDEX idx_edges_source ON edges(source_id, type);
CREATE INDEX idx_edges_target ON edges(target_id, type);
CREATE INDEX idx_edges_type ON edges(type);

-- Composite for common queries
CREATE INDEX idx_nodes_type_file ON nodes(type, file_path);
CREATE INDEX idx_edges_source_type ON edges(source_id, type);
CREATE INDEX idx_edges_target_type ON edges(target_id, type);

-- Full-text search
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    name, qualified_name, 
    content=nodes, content_rowid=id
);
~~~

---

## 8. LLM-Optimized Output Formats

### 8.1 Format Comparison

| Format | Token Efficiency | LLM Comprehension | Structure Preservation | Best For |
|--------|-----------------|-------------------|----------------------|----------|
| **Raw Code Snippets** | Low (verbose) | High (familiar) | High | Small, focused queries |
| **Structured Markdown** | Medium | High | High | General context |
| **Aider Tree Format** | High (compact) | Medium | Medium | Repository overview |
| **Graph Description** | Medium | Medium | High | Relationship queries |
| **JSON Schema** | Low (verbose) | Medium | Very High | Structured data |
| **Compressed Summary** | Very High | Medium | Low | Token-constrained |

### 8.2 Recommended Output Templates

#### 8.2.1 Function Context Template

~~~markdown
## [Function/Method] `qualified_name`
File: `file_path` (lines start-end) | Visibility: public | Returns: ReturnType

### Signature
```language
function_signature_here
```

### Relationships
- Called by: `caller1` (file:line), `caller2` (file:line)
- Calls: `callee1`, `callee2`
- Uses types: `Type1`, `Type2`
- Part of: `ClassName`

### Source
```language
// full source code
```
~~~

**Token cost**: ~200-500 tokens per function

#### 8.2.2 Class Overview Template

~~~markdown
## Class `ClassName` extends `ParentClass` implements `Interface1`, `Interface2`
File: `file_path` | Lines: start-end | Visibility: public

### Properties
| Name | Type | Visibility | Default |
|------|------|-----------|--------|
| $prop1 | string | protected | null |

### Methods
| Name | Signature | Visibility | Lines |
|------|-----------|-----------|-------|
| method1 | method1(Type $param): ReturnType | public | 25-40 |

### Relationships
- Extended by: `ChildClass1`, `ChildClass2`
- Uses traits: `Trait1`, `Trait2`
- Injected into: `ServiceA`, `ServiceB`
~~~

**Token cost**: ~300-800 tokens per class

#### 8.2.3 Impact Analysis Template

~~~markdown
## Impact Analysis: Changing `qualified_name`

### Direct Impact (depth 1) — 5 files
| File | Symbols Affected | Relationship |
|------|-----------------|-------------|
| src/Controllers/OrderController.php | store(), update() | calls |
| src/Jobs/ProcessOrderJob.php | handle() | calls |

### Transitive Impact (depth 2-3) — 12 files
| File | Distance | Via |
|------|----------|----|
| src/Http/Routes/api.php | 2 | OrderController → routes_to |
| tests/Feature/OrderTest.php | 2 | OrderController → calls |

### Risk Assessment
- **High Risk**: 3 files (direct callers with signature dependency)
- **Medium Risk**: 5 files (transitive callers)
- **Low Risk**: 4 files (type references only)
~~~

### 8.3 Token Budget Management

**Strategy**: Hierarchical detail levels with progressive disclosure

| Budget | Strategy | Content |
|--------|----------|---------|
| <500 tokens | Signature only | Function signatures, class names, key relationships |
| 500-2000 tokens | Summary | Signatures + relationship lists + brief descriptions |
| 2000-8000 tokens | Detailed | Full source code + relationships + sibling context |
| 8000+ tokens | Comprehensive | Multi-hop context, call chains, type definitions |

**Implementation**:
~~~python
def format_context(graph_results, token_budget):
    """Format graph query results within token budget."""
    if token_budget < 500:
        return format_signatures_only(graph_results)
    elif token_budget < 2000:
        return format_summary(graph_results)
    elif token_budget < 8000:
        return format_detailed(graph_results)
    else:
        return format_comprehensive(graph_results)
~~~

### 8.4 Relevance Ranking for Context Selection

**Multi-factor scoring**:

~~~python
def relevance_score(node, query_context):
    score = 0.0
    
    # PageRank importance (0-1)
    score += pagerank[node] * 0.3
    
    # Distance from query target (inverse)
    score += (1.0 / (1 + distance)) * 0.25
    
    # Relationship type weight
    rel_weights = {"calls": 1.0, "extends": 0.9, "implements": 0.9,
                   "imports": 0.7, "has_type": 0.6, "member_of": 0.5}
    score += rel_weights.get(relationship, 0.3) * 0.25
    
    # Recency (recently modified files)
    score += recency_factor(node) * 0.1
    
    # Name similarity to query
    score += name_similarity(node, query) * 0.1
    
    return score
~~~

---

## 9. Recommendations

### 9.1 Recommended Architecture

~~~
┌─────────────────────────────────────────────────────────┐
│                    Code Knowledge Graph                   │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │  Tree-sitter  │    │   Module     │    │  Framework │ │
│  │   Parsers     │───▶│  Resolver    │───▶│  Detector  │ │
│  │  (PHP/JS/TS)  │    │              │    │            │ │
│  └──────────────┘    └──────────────┘    └────────────┘ │
│          │                    │                  │        │
│          ▼                    ▼                  ▼        │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Graph Builder (Python)                   │ │
│  │  - Node extraction from AST                          │ │
│  │  - Edge inference from references                    │ │
│  │  - Incremental updates via content hash              │ │
│  └─────────────────────────────────────────────────────┘ │
│          │                                                │
│          ▼                                                │
│  ┌──────────────────┐    ┌──────────────────────────┐   │
│  │  SQLite Storage   │◀──▶│  NetworkX (in-memory)    │   │
│  │  - Nodes table    │    │  - PageRank              │   │
│  │  - Edges table    │    │  - Centrality            │   │
│  │  - FTS5 index     │    │  - Community detection   │   │
│  │  - JSON properties│    │  - Cycle detection       │   │
│  └──────────────────┘    └──────────────────────────┘   │
│          │                          │                     │
│          ▼                          ▼                     │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Query Engine                             │ │
│  │  - Recursive CTE traversals                          │ │
│  │  - FTS5 text search                                  │ │
│  │  - Graph algorithm results                           │ │
│  │  - Token-budgeted output formatting                  │ │
│  └─────────────────────────────────────────────────────┘ │
│          │                                                │
│          ▼                                                │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              MCP Server / API                         │ │
│  │  - Context assembly for LLMs                         │ │
│  │  - Impact analysis                                   │ │
│  │  - Discovery queries                                 │ │
│  │  - Code search                                       │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
~~~

### 9.2 Implementation Priority

| Phase | Components | Effort | Value |
|-------|-----------|--------|-------|
| **Phase 1** | SQLite schema, Tree-sitter parsing, basic node/edge extraction | 2-3 weeks | Foundation |
| **Phase 2** | Call graph analysis, import resolution, basic queries | 2-3 weeks | Core functionality |
| **Phase 3** | Framework detection (Laravel, React, etc.), route mapping | 2 weeks | Framework intelligence |
| **Phase 4** | NetworkX integration, PageRank, context selection | 1-2 weeks | LLM optimization |
| **Phase 5** | MCP server, token budgeting, output formatting | 1-2 weeks | Integration |
| **Phase 6** | Incremental updates, file watching, performance optimization | 1-2 weeks | Production readiness |

### 9.3 Key Design Decisions

1. **SQLite over Neo4j**: Zero infrastructure, proven performance, Python stdlib
2. **Property graph with JSON**: Flexible, evolvable, no migrations for new properties
3. **Tree-sitter for all languages**: Consistent AST, 64+ languages, fast parsing
4. **Hybrid SQLite + NetworkX**: Best of both worlds — persistence + algorithms
5. **Token-budgeted output**: Essential for LLM integration, progressive detail levels
6. **Content-hash incremental updates**: Only re-parse changed files
7. **Qualified names as primary keys**: Unique, hierarchical, human-readable
8. **Confidence scoring on edges**: Handle dynamic dispatch and uncertain references

### 9.4 Schema Summary (Final)

**22 Node Types**: Project, Directory, File, Package, Class, Interface, Trait, Enum, Function, Method, Property, Variable, Constant, TypeAlias, Namespace, Parameter, Decorator, Route, Component, Hook, Middleware, Model

**24 Edge Types**: contains, defined_in, member_of, has_parameter, belongs_to_namespace, extends, implements, uses_trait, has_type, returns_type, generic_of, union_of, intersection_of, imports, exports, re_exports, depends_on, calls, instantiates, dispatches_event, routes_to, renders, injects, provides

**Storage**: SQLite (WAL mode) + NetworkX (in-memory for algorithms)

**Query Patterns**: Recursive CTEs for traversal, FTS5 for text search, PageRank for importance ranking

---

*This document is a living research artifact. Sections will be expanded as implementation progresses.*
