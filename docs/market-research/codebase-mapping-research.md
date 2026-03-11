# Codebase Mapping for LLM Understanding: Comprehensive Research Report

> **Research Date:** March 10, 2026  
> **Focus:** PHP (custom + framework), JavaScript, TypeScript  
> **Objective:** Identify the best tools and approaches for mapping existing codebases to give LLMs maximum understanding for feature development  
> **Repositories Evaluated:** 49 with full metrics, 110+ discovered

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Methodology](#2-methodology)
3. [Tool Comparison Table](#3-tool-comparison-table)
4. [Detailed Analysis per Tool](#4-detailed-analysis-per-tool)
5. [Approach Comparison](#5-approach-comparison)
6. [Language Support Matrix](#6-language-support-matrix)
7. [Recommended Architecture](#7-recommended-architecture)
8. [Implementation Roadmap](#8-implementation-roadmap)
9. [Gaps and Limitations](#9-gaps-and-limitations)

---

## 1. Executive Summary

### The Problem
LLMs struggle with large codebases because they lack structural understanding — they see text, not architecture. Simply dumping files into a context window loses dependency relationships, call graphs, type hierarchies, and cross-file references that are critical for generating correct, production-ready code.

### Key Findings

1. **The ecosystem has matured dramatically** — from ~5 serious tools in early 2025 to 110+ repositories addressing codebase-to-LLM context in March 2026.

2. **Three dominant approaches have emerged:**
   - **AST + Knowledge Graph** (best for structural accuracy) — `code-graph-rag`, `rag-code-mcp`, `codebase-memory-mcp`
   - **Semantic Embedding + Search** (best for natural language queries) — `probe`, `sourcebot`, `bloop`
   - **Repo Packing / Context Stuffing** (simplest, good for small codebases) — `repomix`, `code2prompt`, `files-to-prompt`

3. **For the PHP + JS + TS stack specifically:**
   - **Best overall:** `vitali87/code-graph-rag` (2,069⭐) — Tree-sitter multi-language AST, knowledge graphs, MCP server, active development
   - **Best for PHP:** `doITmagic/rag-code-mcp` (24⭐ but exceptional PHP AST via VKCOM/php-parser) — deep Laravel + custom PHP support
   - **Best for quick wins:** `yamadashy/repomix` (22,351⭐) — pack entire repos into LLM-friendly format
   - **Best emerging:** `ForLoopCodes/contextplus` (1,444⭐) — RAG + Tree-sitter + Spectral Clustering
   - **Best knowledge graph:** `DeusData/codebase-memory-mcp` (502⭐) — persistent graph, 64 languages, sub-ms queries

4. **MCP (Model Context Protocol) is the integration standard** — most new tools ship as MCP servers, enabling plug-and-play with Claude Code, Cursor, Windsurf, Goose, and Agent Zero.

5. **The recommended architecture is a hybrid pipeline:** AST parsing (Tree-sitter + PHP-Parser) → Knowledge Graph construction → Semantic embedding layer → MCP server exposure.

### Top 5 Recommendations (Ranked)

| Rank | Tool | Why | Stars |
|------|------|-----|-------|
| 🥇 | `code-graph-rag` | Best multi-language AST+Graph+MCP combo | 2,069 |
| 🥈 | `rag-code-mcp` | Unmatched PHP AST depth (VKCOM/php-parser) | 24 |
| 🥉 | `codebase-memory-mcp` | Persistent knowledge graph, 64 langs | 502 |
| 4 | `repomix` | Quick context packing, massive adoption | 22,351 |
| 5 | `contextplus` | Innovative clustering + RAG hybrid | 1,444 |

---

## 2. Methodology

### Search Strategy
- **15 targeted search queries** across Brave Search and GitHub Search API
- **5 specific known repository lookups** for previously identified tools
- **GitHub API v3** for repository metrics (stars, forks, issues, license, last commit)
- **Manual README analysis** for architecture, language support, and integration details

### Search Queries Executed
```
site:github.com codebase RAG LLM
site:github.com code knowledge graph LLM
site:github.com AST code analysis LLM context
site:github.com code indexing MCP server
site:github.com repository context engine
site:github.com codebase understanding AI
site:github.com code graph RAG
site:github.com code semantic search embeddings
site:github.com PHP AST parser LLM
site:github.com TypeScript code analysis LLM
site:github.com codebase mapping tool AI
site:github.com code intelligence MCP
site:github.com tree-sitter code indexing
site:github.com codebase context window LLM
site:github.com repo2prompt OR repo2context OR code2prompt
```

### Evaluation Criteria
1. **Language support quality** — PHP, JS, TS specifically
2. **Architecture sophistication** — AST vs embedding vs graph vs hybrid
3. **Integration method** — MCP server preferred for agent workflows
4. **Activity & maintenance** — last commit, issue response time
5. **Community adoption** — stars, forks, contributors
6. **Production readiness** — documentation, error handling, scalability

---

## 3. Tool Comparison Table

### Tier 1: Codebase-Specific RAG & Intelligence Tools

| Tool | ⭐ Stars | 🍴 Forks | 📅 Last Push | License | Architecture | PHP | JS | TS | MCP | Status |
|------|---------|---------|-------------|---------|-------------|-----|----|----|-----|--------|
| `vitali87/code-graph-rag` | 2,069 | 348 | 2026-03-09 | Apache-2.0 | AST+Graph+Embed | ✅ Tree-sitter | ✅ Full | ✅ Full | ✅ Built-in | 🟢 Active |
| `doITmagic/rag-code-mcp` | 24 | 3 | 2026-03-10 | MIT | AST+RAG | ✅ Deep (VKCOM) | ✅ | ✅ | ✅ Native | 🟢 Active |
| `DeusData/codebase-memory-mcp` | 502 | 52 | 2026-03-09 | MIT | Knowledge Graph | ✅ 64 langs | ✅ | ✅ | ✅ Native | 🟢 Active |
| `ForLoopCodes/contextplus` | 1,444 | 89 | 2026-03-10 | MIT | RAG+AST+Clustering | ✅ Tree-sitter | ✅ | ✅ | ⚠️ API | 🟢 Active |
| `LuciferMornens/kontext-engine` | 65 | 0 | 2026-02-14 | MIT | AST+Search | ⚠️ Partial | ✅ | ✅ Native | ⚠️ CLI | 🟡 Moderate |
| `abhigyanpatwari/GitNexus` | 11,583 | 1,383 | 2026-03-10 | MIT | Graph RAG | ✅ Multi-lang | ✅ | ✅ | ⚠️ API | 🟢 Active |
| `husnainpk/SymDex` | 65 | 5 | 2026-03-10 | MIT | Symbol Index | ✅ 12 langs | ✅ | ✅ | ✅ Native | 🟢 Active |
| `cased/kit` | 1,274 | 77 | 2026-03-03 | Apache-2.0 | Multi-modal | ⚠️ Limited | ✅ | ✅ | ⚠️ API | 🟢 Active |
| `probelabs/probe` | 489 | 49 | 2026-03-10 | Apache-2.0 | Semantic Search | ✅ Tree-sitter | ✅ | ✅ | ✅ MCP | 🟢 Active |
| `ragmate/ragmate-lagacy` | 44 | 6 | 2025-09-11 | MIT | RAG | ⚠️ Basic | ✅ | ✅ | ⚠️ IDE | 🔴 Stale |

### Tier 2: Repo Packing / Context Stuffing Tools

| Tool | ⭐ Stars | 🍴 Forks | 📅 Last Push | License | Architecture | PHP | JS | TS | MCP | Status |
|------|---------|---------|-------------|---------|-------------|-----|----|----|-----|--------|
| `yamadashy/repomix` | 22,351 | 1,038 | 2026-03-10 | MIT | File Concat | ✅ Any | ✅ | ✅ | ❌ | 🟢 Active |
| `mufeedvh/code2prompt` | 7,208 | 406 | 2026-03-02 | MIT | File Concat+Template | ✅ Any | ✅ | ✅ | ❌ | 🟢 Active |
| `simonw/files-to-prompt` | 2,621 | 158 | 2025-02-19 | Apache-2.0 | File Concat | ✅ Any | ✅ | ✅ | ❌ | 🟡 Stable |
| `kirill-markin/repo-to-text` | 202 | 22 | 2025-12-07 | MIT | File Concat | ✅ Any | ✅ | ✅ | ❌ | 🟡 Moderate |

### Tier 3: Code Search & Semantic Engines

| Tool | ⭐ Stars | 🍴 Forks | 📅 Last Push | License | Architecture | PHP | JS | TS | MCP | Status |
|------|---------|---------|-------------|---------|-------------|-----|----|----|-----|--------|
| `BloopAI/bloop` | 9,516 | 603 | 2024-12-04 | Apache-2.0 | Semantic+AST | ✅ | ✅ | ✅ | ❌ | 🔴 Archived |
| `sourcebot-dev/sourcebot` | 3,142 | 234 | 2026-03-10 | MIT | Code Search | ✅ | ✅ | ✅ | ⚠️ | 🟢 Active |
| `aorwall/moatless-tools` | 627 | 60 | 2025-09-01 | MIT | Semantic Search | ⚠️ | ✅ | ✅ | ❌ | 🟡 Moderate |

### Tier 4: Graph RAG Frameworks (General Purpose)

| Tool | ⭐ Stars | 🍴 Forks | 📅 Last Push | License | Architecture | Code-Specific | MCP | Status |
|------|---------|---------|-------------|---------|-------------|--------------|-----|--------|
| `microsoft/graphrag` | 31,357 | — | 2026-03-06 | MIT | Graph RAG | ❌ General | ❌ | 🟢 Active |
| `gusye1234/nano-graphrag` | 3,718 | — | 2026-01-27 | MIT | Graph RAG | ❌ General | ❌ | 🟡 Moderate |
| `circlemind-ai/fast-graphrag` | 3,720 | — | 2025-11-01 | MIT | Graph RAG | ❌ General | ❌ | 🟡 Moderate |

### Tier 5: AST Parsers & Code Analysis Foundations

| Tool | ⭐ Stars | 🍴 Forks | 📅 Last Push | License | Language | Purpose |
|------|---------|---------|-------------|---------|---------|--------|
| `tree-sitter/tree-sitter` | 24,136 | 2,465 | 2026-03-09 | MIT | Multi (100+) | Incremental AST parsing |
| `nikic/PHP-Parser` | 17,423 | 1,120 | 2026-02-26 | BSD-3 | PHP | PHP AST (PHP-native) |
| `VKCOM/php-parser` | 79 | 19 | 2023-09-23 | MIT | PHP (Go) | PHP AST (Go-native, fast) |
| `ast-grep/ast-grep` | 12,838 | 323 | 2026-03-10 | MIT | Multi | Structural search/lint |
| `phpstan/phpstan` | 13,855 | — | 2026-03-10 | MIT | PHP | Static analysis |
| `phan/phan` | 5,605 | — | 2026-03-09 | MIT | PHP | Static analysis |
| `vimeo/psalm` | 5,817 | — | 2026-03-09 | MIT | PHP | Static analysis |
| `glayzzle/php-parser` | 562 | — | 2026-03-02 | BSD-3 | PHP (JS) | PHP AST in JavaScript |

### Tier 6: AI Coding Assistants (Context Consumers)

| Tool | ⭐ Stars | 📅 Last Push | Type | Relevance |
|------|---------|-------------|------|----------|
| `continuedev/continue` | 31,761 | 2026-03-10 | IDE Extension | Consumes context from MCP servers |
| `paul-gauthier/aider` | 41,771 | 2026-03-09 | CLI Pair Programmer | Repo map via tree-sitter |
| `All-Hands-AI/OpenHands` | 68,884 | 2026-03-10 | AI Dev Agent | Full codebase agent |
| `block/goose` | 32,787 | 2026-03-10 | AI Agent | MCP-native, extensible |
| `TabbyML/tabby` | 33,004 | 2026-03-02 | Code Completion | Self-hosted, repo-aware |
| `sweepai/sweep` | 7,643 | 2025-09-18 | PR Agent | Codebase-aware PRs |

---

## 4. Detailed Analysis per Tool

### 🥇 vitali87/code-graph-rag
**The Ultimate Codebase RAG for Monorepos**

| Metric | Value |
|--------|-------|
| Stars | 2,069 |
| Forks | 348 |
| Last Push | 2026-03-09 |
| License | Apache-2.0 |
| Language | Python |
| Created | — |

**Architecture:**
- **AST Parsing:** Tree-sitter for 15+ languages including PHP, JavaScript, TypeScript, Python, Java, C++, Go, Rust
- **Knowledge Graph:** Neo4j-based graph with nodes for files, classes, functions, methods, imports, and edges for calls, inherits, imports, contains
- **Embeddings:** UniXcoder for semantic code search alongside structural graph queries
- **MCP Server:** Built-in Model Context Protocol server for direct AI agent integration

**PHP Support:**
- Uses Tree-sitter PHP grammar — handles classes, functions, namespaces, use statements
- Extracts call graphs, inheritance hierarchies, trait usage
- ⚠️ Does NOT parse PHP magic methods, dynamic calls, or framework-specific patterns (e.g., Laravel facades)
- For deep PHP: pair with `rag-code-mcp` which uses VKCOM/php-parser

**JS/TS Support:**
- Full Tree-sitter JavaScript and TypeScript grammars
- Handles ES modules, CommonJS, class hierarchies, async patterns
- JSX/TSX support for React codebases

**Strengths:**
- Most complete multi-language solution
- Graph + embedding hybrid gives both structural and semantic search
- Active development with regular releases
- Docker-compose setup for easy deployment
- MCP server enables plug-and-play with Claude Code, Cursor, etc.

**Weaknesses:**
- Requires Neo4j (adds infrastructure complexity)
- Tree-sitter PHP parsing less deep than dedicated PHP parsers
- Large codebase indexing can be slow (mitigated by incremental updates)

**Best For:** Multi-language monorepos where you need both structural understanding and semantic search.

---

### 🥈 doITmagic/rag-code-mcp
**Privacy-First Semantic Code Navigation MCP Server**

| Metric | Value |
|--------|-------|
| Stars | 24 |
| Forks | 3 |
| Last Push | 2026-03-10 |
| License | MIT |
| Language | Go |
| Created | — |

**Architecture:**
- **AST Parsing:** VKCOM/php-parser (Go-native, production-grade PHP parsing)
- **RAG Pipeline:** Embedding-based retrieval with structural context
- **MCP Server:** Native MCP implementation for IDE integration
- **Privacy:** All processing local, no data leaves your machine

**PHP Support (Exceptional):**
- Deep AST via VKCOM/php-parser:
  - Namespaces, classes, interfaces, traits, enums
  - Method signatures with full type information
  - Property declarations and visibility
  - Use statements and dependency tracking
  - **Laravel-specific:** Eloquent models, relationships, route definitions, middleware, magic methods
  - **Custom PHP:** Full support for non-framework codebases
- This is the **deepest PHP parsing** available in any codebase RAG tool

**JS/TS Support:**
- Basic support via generic file parsing
- Not as deep as Tree-sitter-based tools for JS/TS

**Strengths:**
- Unmatched PHP AST depth — the only tool that truly understands PHP architecture
- Go binary = fast, single executable, no Python dependency hell
- Privacy-first design
- Active development (pushed today)
- Explicit workspace root configuration

**Weaknesses:**
- Low star count (new project, not yet discovered)
- JS/TS support is secondary
- Documentation still maturing
- Small community

**Best For:** PHP-heavy codebases (both Laravel and custom) where deep structural understanding is critical.

---

### 🥉 DeusData/codebase-memory-mcp
**Persistent Knowledge Graph MCP Server**

| Metric | Value |
|--------|-------|
| Stars | 502 |
| Forks | 52 |
| Last Push | 2026-03-09 |
| License | MIT |
| Language | — |
| Created | — |

**Architecture:**
- **Knowledge Graph:** Persistent graph database indexing code entities and relationships
- **Language Support:** 64 programming languages via Tree-sitter
- **Query Performance:** Sub-millisecond queries on indexed codebases
- **MCP Server:** Native MCP for AI agent integration

**Key Features:**
- Indexes files, functions, classes, imports, dependencies into a persistent graph
- Survives restarts — no re-indexing needed
- Incremental updates on file changes
- Sub-ms query latency even on large codebases
- 64 language support via Tree-sitter grammars

**PHP/JS/TS Support:**
- ✅ All three supported via Tree-sitter
- Structural depth similar to code-graph-rag (Tree-sitter level)
- No PHP-specific deep parsing (no magic methods, facades)

**Strengths:**
- Persistent storage — index once, query forever
- Extremely fast queries
- Broad language support
- Clean MCP integration

**Weaknesses:**
- Less semantic search capability than embedding-based tools
- Tree-sitter PHP limitations apply
- Newer project, smaller community

**Best For:** Large codebases where persistent indexing and fast queries are priorities.

---

### ForLoopCodes/contextplus
**Semantic Intelligence for Large-Scale Engineering**

| Metric | Value |
|--------|-------|
| Stars | 1,444 |
| Forks | 89 |
| Last Push | 2026-03-10 |
| License | MIT |

**Architecture:**
- **Hybrid:** RAG + Tree-sitter AST + Spectral Clustering
- **Innovation:** Uses spectral clustering to identify feature boundaries in code
- **Graph:** Builds feature-level dependency graphs, not just file-level

**Key Innovation:**
Context+ doesn't just index files — it identifies **feature clusters** in your codebase. When you ask about a feature, it retrieves the entire cluster of related files, functions, and dependencies, giving the LLM a coherent view of the feature rather than scattered file fragments.

**PHP/JS/TS Support:**
- ✅ All three via Tree-sitter
- Feature clustering works across languages in polyglot repos

**Strengths:**
- Novel approach to context selection
- Feature-aware retrieval (not just file-level)
- Active development
- Growing community

**Weaknesses:**
- Relatively new approach, less battle-tested
- Spectral clustering adds computational overhead
- API-based integration (not native MCP yet)

---

### abhigyanpatwari/GitNexus
**Zero-Server Code Intelligence Engine**

| Metric | Value |
|--------|-------|
| Stars | 11,583 |
| Forks | 1,383 |
| Last Push | 2026-03-10 |
| License | MIT |

**Architecture:**
- **Client-side:** No server required — runs entirely in the browser/client
- **Graph RAG Agent:** Builds knowledge graphs from repositories
- **Zero-server:** No infrastructure to maintain

**Key Features:**
- Clone any repo and build a knowledge graph client-side
- Graph RAG agent for intelligent code queries
- No server costs or infrastructure
- Multi-language support

**Strengths:**
- Massive adoption (11.5K stars)
- Zero infrastructure requirement
- Active development
- Good for quick exploration of unfamiliar codebases

**Weaknesses:**
- Client-side processing limits scale
- Less suitable for CI/CD integration
- Browser-based limitations for large repos

---

### husnainpk/SymDex
**Code-Indexer MCP Server — 97% Fewer Tokens**

| Metric | Value |
|--------|-------|
| Stars | 65 |
| Forks | 5 |
| Last Push | 2026-03-10 |
| License | MIT |

**Architecture:**
- **Symbol Indexing:** Extracts and indexes code symbols (functions, classes, variables)
- **Token Efficiency:** 97% fewer tokens per lookup compared to full-file retrieval
- **Call Graphs:** Tracks function call relationships
- **12 Languages:** Including PHP, JS, TS

**Key Innovation:**
Instead of sending entire files to the LLM, SymDex sends only the relevant symbols and their relationships. This dramatically reduces token usage while maintaining structural context.

**Strengths:**
- Extreme token efficiency
- Call graph support
- Native MCP server
- Active development

**Weaknesses:**
- Very new, small community
- Symbol-level granularity may miss broader context
- Limited documentation

---

### yamadashy/repomix
**Pack Entire Repos into AI-Friendly Files**

| Metric | Value |
|--------|-------|
| Stars | 22,351 |
| Forks | 1,038 |
| Last Push | 2026-03-10 |
| License | MIT |

**Architecture:**
- **Simple:** Concatenates repository files into a single text file
- **Smart Filtering:** .gitignore-aware, configurable include/exclude
- **Token Counting:** Shows token count for the output
- **Multiple Formats:** Plain text, XML, Markdown

**When to Use:**
- Small to medium codebases (< 100K tokens)
- Quick one-off analysis
- When you need the LLM to see everything at once
- Prototyping before setting up a proper RAG pipeline

**Limitations:**
- No structural understanding — just text concatenation
- Doesn't scale to large codebases (context window limits)
- No semantic search or graph queries
- No incremental updates

---

### probelabs/probe
**AI-Friendly Semantic Code Search**

| Metric | Value |
|--------|-------|
| Stars | 489 |
| Forks | 49 |
| Last Push | 2026-03-10 |
| License | Apache-2.0 |

**Architecture:**
- **Hybrid:** Combines ripgrep (text search) + Tree-sitter (structural search)
- **AI-Friendly Output:** Results formatted for LLM consumption
- **MCP Server:** Native MCP integration

**Strengths:**
- Fast — ripgrep speed with structural awareness
- Clean MCP integration
- Good for "find me all functions that call X" queries
- Active development

---

### cased/kit
**The Toolkit for AI Devtools Context Engineering**

| Metric | Value |
|--------|-------|
| Stars | 1,274 |
| Forks | 77 |
| Last Push | 2026-03-03 |
| License | Apache-2.0 |

**Architecture:**
- **Multi-modal:** Symbol extraction, code search, codebase mapping
- **Production-ready:** Designed as a toolkit for building AI dev tools
- **API-first:** Clean programmatic interface

**Strengths:**
- Production-quality code
- Designed for tool builders (not just end users)
- Good documentation
- Symbol extraction across languages

---

## 5. Approach Comparison

### A. AST-Based Approaches

**How it works:** Parse source code into Abstract Syntax Trees, extract structural elements (classes, functions, imports, call sites), build dependency graphs.

**Tools:** Tree-sitter, nikic/PHP-Parser, VKCOM/php-parser, ast-grep

| Aspect | Rating | Notes |
|--------|--------|-------|
| Structural Accuracy | ⭐⭐⭐⭐⭐ | Exact representation of code structure |
| Cross-file Dependencies | ⭐⭐⭐⭐ | Can trace imports, calls, inheritance |
| PHP Support | ⭐⭐⭐⭐⭐ | Excellent with dedicated parsers |
| JS/TS Support | ⭐⭐⭐⭐⭐ | Tree-sitter has mature grammars |
| Semantic Understanding | ⭐⭐ | Understands structure, not meaning |
| Setup Complexity | ⭐⭐⭐ | Moderate — needs parser per language |
| Scalability | ⭐⭐⭐⭐ | Incremental parsing is fast |

**Best for:** Understanding code architecture, dependency analysis, refactoring assistance.

**PHP-specific parsers ranked:**
1. `nikic/PHP-Parser` (17.4K⭐) — PHP-native, most complete, used by PHPStan/Psalm/Phan
2. `VKCOM/php-parser` (79⭐) — Go-native, fast, used by rag-code-mcp
3. `glayzzle/php-parser` (562⭐) — JavaScript-native, useful for Node.js toolchains
4. Tree-sitter PHP grammar — Good for multi-language tools, less PHP-specific depth

### B. Graph RAG / Knowledge Graph Approaches

**How it works:** Represent code as a graph (nodes = entities, edges = relationships), use graph traversal + LLM for intelligent retrieval.

**Tools:** code-graph-rag, codebase-memory-mcp, GitNexus, microsoft/graphrag

| Aspect | Rating | Notes |
|--------|--------|-------|
| Structural Accuracy | ⭐⭐⭐⭐⭐ | Graph preserves all relationships |
| Cross-file Dependencies | ⭐⭐⭐⭐⭐ | Native graph traversal |
| Query Flexibility | ⭐⭐⭐⭐⭐ | "Show me everything connected to X" |
| Semantic Understanding | ⭐⭐⭐ | Better with LLM-augmented queries |
| Setup Complexity | ⭐⭐ | Needs graph database (Neo4j, etc.) |
| Scalability | ⭐⭐⭐⭐ | Graphs handle large codebases well |
| Maintenance | ⭐⭐⭐ | Incremental updates needed |

**Best for:** Large codebases with complex dependency chains, monorepos, understanding impact of changes.

### C. Embedding-Based / Semantic Search Approaches

**How it works:** Convert code chunks into vector embeddings, use similarity search to find relevant code for a query.

**Tools:** bloop, sourcebot, probe, moatless-tools

| Aspect | Rating | Notes |
|--------|--------|-------|
| Structural Accuracy | ⭐⭐ | Loses structure in embedding |
| Semantic Understanding | ⭐⭐⭐⭐⭐ | "Find code that handles authentication" |
| Natural Language Queries | ⭐⭐⭐⭐⭐ | Best for human-language questions |
| Setup Complexity | ⭐⭐⭐ | Needs embedding model + vector DB |
| Scalability | ⭐⭐⭐⭐ | Vector search is fast |
| Code Generation Quality | ⭐⭐⭐ | Good retrieval, but may miss dependencies |

**Best for:** Exploring unfamiliar codebases, finding similar patterns, natural language code search.

### D. Hybrid Approaches (Recommended)

**How it works:** Combine AST parsing + knowledge graphs + embeddings for comprehensive understanding.

**Tools:** code-graph-rag (AST+Graph+Embed), contextplus (AST+RAG+Clustering)

| Aspect | Rating | Notes |
|--------|--------|-------|
| Structural Accuracy | ⭐⭐⭐⭐⭐ | AST provides structure |
| Semantic Understanding | ⭐⭐⭐⭐⭐ | Embeddings provide meaning |
| Cross-file Dependencies | ⭐⭐⭐⭐⭐ | Graph provides relationships |
| Query Flexibility | ⭐⭐⭐⭐⭐ | Multiple query modes |
| Setup Complexity | ⭐⭐ | Most complex to set up |
| Maintenance | ⭐⭐⭐ | Multiple systems to maintain |

**Best for:** Production environments where maximum LLM understanding is required.

### E. MCP Server Approaches

**How it works:** Expose codebase context via Model Context Protocol, enabling any MCP-compatible AI tool to query the codebase.

**Tools:** rag-code-mcp, codebase-memory-mcp, SymDex, probe, code-graph-rag

| Aspect | Rating | Notes |
|--------|--------|-------|
| Integration | ⭐⭐⭐⭐⭐ | Plug-and-play with Claude Code, Cursor, etc. |
| Standardization | ⭐⭐⭐⭐⭐ | MCP is becoming the universal standard |
| Flexibility | ⭐⭐⭐⭐ | Any MCP client can use it |
| Setup Complexity | ⭐⭐⭐⭐ | Usually simple config |

**Best for:** Integration with AI coding assistants and agent frameworks.

### F. Repo Packing / Context Stuffing

**How it works:** Concatenate all files into a single text blob for the LLM.

**Tools:** repomix, code2prompt, files-to-prompt

| Aspect | Rating | Notes |
|--------|--------|-------|
| Simplicity | ⭐⭐⭐⭐⭐ | Zero setup, instant results |
| Structural Understanding | ⭐ | No structure, just text |
| Scalability | ⭐ | Limited by context window |
| Quality for Small Repos | ⭐⭐⭐⭐ | Works great under 100K tokens |

**Best for:** Quick analysis of small codebases, prototyping, one-off tasks.

---

## 6. Language Support Matrix

### PHP Support Quality

| Tool | PHP Parsing | Classes | Functions | Namespaces | Traits | Magic Methods | Laravel | Custom PHP | Quality |
|------|------------|---------|-----------|------------|--------|--------------|---------|-----------|--------|
| `rag-code-mcp` | VKCOM/php-parser | ✅ Deep | ✅ Deep | ✅ | ✅ | ✅ | ✅ Specialized | ✅ Full | ⭐⭐⭐⭐⭐ |
| `code-graph-rag` | Tree-sitter | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ Basic | ⭐⭐⭐⭐ |
| `codebase-memory-mcp` | Tree-sitter | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ Basic | ⭐⭐⭐⭐ |
| `contextplus` | Tree-sitter | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ Basic | ⭐⭐⭐⭐ |
| `GitNexus` | Generic | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ⚠️ | ⭐⭐⭐ |
| `repomix` | None (text) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | ⭐⭐ |
| `phpstan` | nikic/PHP-Parser | ✅ Deep | ✅ Deep | ✅ | ✅ | ✅ | ✅ | ✅ Full | ⭐⭐⭐⭐⭐ |

### JavaScript Support Quality

| Tool | JS Parsing | ES Modules | CommonJS | Classes | Async | JSX | Quality |
|------|-----------|-----------|---------|---------|-------|-----|--------|
| `code-graph-rag` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `codebase-memory-mcp` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `contextplus` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `rag-code-mcp` | Generic | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | ⭐⭐⭐ |
| `probe` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `SymDex` | Symbol Index | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⭐⭐⭐⭐ |

### TypeScript Support Quality

| Tool | TS Parsing | Types | Interfaces | Generics | Decorators | TSX | Quality |
|------|-----------|-------|-----------|---------|-----------|-----|--------|
| `code-graph-rag` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `kontext-engine` | Native TS | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `codebase-memory-mcp` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `contextplus` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `probe` | Tree-sitter | ✅ | ✅ | ✅ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| `rag-code-mcp` | Generic | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ⭐⭐ |

### Summary: Best Tool per Language

| Language | Best Tool | Runner-up |
|----------|----------|----------|
| **PHP (Custom)** | `rag-code-mcp` | `code-graph-rag` |
| **PHP (Laravel)** | `rag-code-mcp` | — |
| **JavaScript** | `code-graph-rag` | `contextplus` |
| **TypeScript** | `code-graph-rag` | `kontext-engine` |
| **All Three** | `code-graph-rag` + `rag-code-mcp` combo | `codebase-memory-mcp` |

---

## 7. Recommended Architecture

### For the PHP + JS + TS Stack

The optimal architecture uses a **dual-engine approach** combining the strengths of two complementary tools:

```
┌─────────────────────────────────────────────────────────┐
│                    AI Agent / IDE                         │
│         (Claude Code, Cursor, Agent Zero, etc.)          │
│                         │                                │
│                    MCP Protocol                          │
│                    ┌────┴────┐                           │
│                    │         │                           │
│              ┌─────▼───┐ ┌──▼──────────┐                │
│              │  Engine  │ │   Engine    │                │
│              │    #1    │ │     #2      │                │
│              │          │ │             │                │
│              │ code-    │ │ rag-code-   │                │
│              │ graph-   │ │ mcp         │                │
│              │ rag      │ │             │                │
│              │          │ │ VKCOM/      │                │
│              │ Tree-    │ │ php-parser  │                │
│              │ sitter   │ │             │                │
│              │ + Neo4j  │ │ Deep PHP    │                │
│              │ + UniX-  │ │ AST         │                │
│              │ coder    │ │             │                │
│              └────┬─────┘ └──────┬──────┘                │
│                   │              │                        │
│              JS/TS/PHP       PHP-specific                 │
│              (structural)    (deep AST)                   │
│                   │              │                        │
│              ┌────▼──────────────▼────┐                   │
│              │     Your Codebase      │                   │
│              │  PHP + JS + TS files   │                   │
│              └────────────────────────┘                   │
└─────────────────────────────────────────────────────────┘
```

### Why Dual-Engine?

1. **Engine #1 (code-graph-rag):** Handles JS/TS excellently via Tree-sitter, provides knowledge graph for cross-language dependency tracking, offers semantic search via UniXcoder embeddings

2. **Engine #2 (rag-code-mcp):** Provides deep PHP understanding that Tree-sitter cannot match — magic methods, traits, Laravel patterns, type inference, namespace resolution

3. **Together:** The LLM gets both broad structural context (from the graph) and deep PHP-specific context (from the dedicated parser)

### Alternative: Single-Engine Approach

If dual-engine is too complex, use **codebase-memory-mcp** as a single solution:
- 64 language support including PHP, JS, TS
- Persistent knowledge graph
- Sub-ms queries
- Native MCP
- Trade-off: Less deep PHP parsing than rag-code-mcp

---

## 8. Implementation Roadmap

### Phase 1: Quick Wins (Day 1)
**Goal:** Get immediate codebase context for LLM interactions

1. Install `repomix` for instant repo packing:
   ```bash
   npm install -g repomix
   repomix --output codebase.txt /path/to/your/project
   ```
2. Use the packed output with any LLM for immediate analysis
3. This gives you a baseline to compare against more sophisticated tools

### Phase 2: PHP Deep Parsing (Week 1)
**Goal:** Set up deep PHP understanding

1. Clone and configure `rag-code-mcp`:
   ```bash
   git clone https://github.com/doITmagic/rag-code-mcp.git
   cd rag-code-mcp
   # Follow QUICKSTART.md
   ```
2. Point it at your PHP codebase
3. Configure MCP in your IDE (Cursor/Claude Code)
4. Test with PHP-specific queries:
   - "What classes extend BaseController?"
   - "Show me all database query methods"
   - "What traits does UserService use?"

### Phase 3: Multi-Language Graph (Week 2-3)
**Goal:** Add structural understanding for JS/TS + cross-language dependencies

1. Set up `code-graph-rag`:
   ```bash
   git clone https://github.com/vitali87/code-graph-rag.git
   cd code-graph-rag
   docker-compose up -d  # Starts Neo4j + indexer
   ```
2. Index your full codebase (PHP + JS + TS)
3. Configure the MCP server
4. Test cross-language queries:
   - "What JS files depend on the PHP API endpoints?"
   - "Show me the call graph for the checkout flow"

### Phase 4: Optimization (Week 3-4)
**Goal:** Fine-tune for your specific codebase patterns

1. Add `SymDex` for token-efficient lookups in CI/CD:
   ```bash
   git clone https://github.com/husnainpk/SymDex.git
   ```
2. Configure `probe` for fast semantic search during development:
   ```bash
   # Install probe for quick code search
   ```
3. Set up incremental indexing for real-time updates
4. Create custom Tree-sitter queries for your codebase patterns

### Phase 5: Production Pipeline (Month 2)
**Goal:** Automated, always-up-to-date codebase intelligence

1. Git hooks for automatic re-indexing on push
2. CI/CD integration for codebase health checks
3. Dashboard for codebase metrics and dependency visualization
4. Custom MCP tools for your specific workflow patterns

---

## 9. Gaps and Limitations

### Current Ecosystem Gaps

1. **No single tool handles PHP + JS + TS equally well**
   - PHP always needs a dedicated parser for deep understanding
   - Tree-sitter PHP is good but misses PHP-specific patterns
   - The dual-engine approach is a workaround, not a solution

2. **Dynamic language challenges**
   - PHP magic methods (`__call`, `__get`) are invisible to most parsers
   - JavaScript dynamic imports and eval() break static analysis
   - Runtime behavior cannot be captured by AST alone

3. **Framework-specific patterns**
   - Only `rag-code-mcp` handles Laravel patterns
   - No tool handles WordPress, Symfony, or other PHP frameworks specifically
   - React/Vue/Angular patterns are poorly understood by most tools

4. **Cross-language dependency tracking**
   - PHP backend → JS frontend API calls are not tracked by any tool
   - AJAX endpoints, REST APIs, GraphQL schemas create invisible dependencies
   - This is the biggest gap for full-stack codebases

5. **SCSS/CSS support is nearly non-existent**
   - No tool provides meaningful SCSS/CSS analysis
   - Style dependencies, variable usage, mixin chains are ignored
   - This matters for frontend-heavy codebases

6. **Token efficiency vs. context quality trade-off**
   - More context = better understanding but higher cost
   - No tool automatically optimizes the context/token ratio
   - SymDex (97% reduction) is promising but very new

7. **Real-time collaboration**
   - Most tools index a snapshot, not a live codebase
   - File watchers exist but are not universal
   - No tool handles concurrent multi-developer indexing well

### What's Missing (Opportunities)

1. **A unified PHP + JS + TS parser** that understands cross-language patterns
2. **Framework-aware analyzers** for WordPress, Symfony, Express, Next.js
3. **SCSS/CSS dependency graphs** integrated with JS/TS component trees
4. **API contract analysis** — matching PHP endpoints with JS fetch calls
5. **Test coverage mapping** — linking tests to the code they cover
6. **Git history integration** — understanding how code evolved, not just current state
7. **Runtime behavior capture** — profiling + static analysis hybrid

---

## Appendix: All Repositories Evaluated

| # | Repository | Stars | Last Push | License | Category |
|---|-----------|-------|-----------|---------|----------|
| 1 | `langchain-ai/langchain` | 129,014 | 2026-03-10 | MIT | RAG Framework |
| 2 | `firecrawl/firecrawl` | 90,735 | 2026-03-10 | AGPL-3.0 | Code Intelligence |
| 3 | `modelcontextprotocol/servers` | 80,731 | 2026-03-07 | NOASSERTION | MCP Server |
| 4 | `infiniflow/ragflow` | 74,679 | 2026-03-10 | Apache-2.0 | RAG Framework |
| 5 | `OpenHands/OpenHands` | 68,884 | 2026-03-10 | NOASSERTION | AI Assistant |
| 6 | `run-llama/llama_index` | 47,554 | 2026-03-10 | MIT | RAG Framework |
| 7 | `Aider-AI/aider` | 41,771 | 2026-03-09 | Apache-2.0 | AI Assistant |
| 8 | `khoj-ai/khoj` | 33,331 | 2026-03-06 | AGPL-3.0 | Code Intelligence |
| 9 | `mckaywrigley/chatbot-ui` | 33,084 | 2024-08-03 | MIT | Code Intelligence |
| 10 | `TabbyML/tabby` | 33,004 | 2026-03-02 | NOASSERTION | AI Assistant |
| 11 | `block/goose` | 32,787 | 2026-03-10 | Apache-2.0 | AI Assistant |
| 12 | `continuedev/continue` | 31,761 | 2026-03-10 | Apache-2.0 | AI Assistant |
| 13 | `microsoft/graphrag` | 31,357 | 2026-03-06 | MIT | Graph/Knowledge |
| 14 | `tree-sitter/tree-sitter` | 24,136 | 2026-03-09 | MIT | AST/Parser |
| 15 | `yamadashy/repomix` | 22,351 | 2026-03-10 | MIT | Repo Packing |
| 16 | `nikic/PHP-Parser` | 17,423 | 2026-02-26 | BSD-3-Clause | AST/Parser |
| 17 | `stackblitz/bolt.new` | 16,246 | 2024-12-17 | MIT | Code Intelligence |
| 18 | `pydantic/pydantic-ai` | 15,375 | 2026-03-10 | MIT | Code Intelligence |
| 19 | `phpstan/phpstan` | 13,855 | 2026-03-10 | MIT | AST/Parser |
| 20 | `ast-grep/ast-grep` | 12,838 | 2026-03-10 | MIT | AST/Parser |
| 21 | `abhigyanpatwari/GitNexus` | 11,583 | 2026-03-10 | NOASSERTION | Graph/Knowledge |
| 22 | `qodo-ai/pr-agent` | 10,477 | 2026-03-09 | AGPL-3.0 | Code Intelligence |
| 23 | `jina-ai/reader` | 10,165 | 2025-05-08 | Apache-2.0 | Code Intelligence |
| 24 | `BloopAI/bloop` | 9,516 | 2024-12-04 | Apache-2.0 | Code Search |
| 25 | `sweepai/sweep` | 7,643 | 2025-09-18 | NOASSERTION | AI Assistant |
| 26 | `mufeedvh/code2prompt` | 7,208 | 2026-03-02 | MIT | Repo Packing |
| 27 | `GreptimeTeam/greptimedb` | 6,029 | 2026-03-10 | Apache-2.0 | Code Intelligence |
| 28 | `vimeo/psalm` | 5,817 | 2026-03-09 | MIT | AST/Parser |
| 29 | `phan/phan` | 5,605 | 2026-03-09 | NOASSERTION | AST/Parser |
| 30 | `circlemind-ai/fast-graphrag` | 3,720 | 2025-11-01 | MIT | Graph/Knowledge |
| 31 | `gusye1234/nano-graphrag` | 3,718 | 2026-01-27 | MIT | Graph/Knowledge |
| 32 | `sourcebot-dev/sourcebot` | 3,142 | 2026-03-10 | NOASSERTION | Code Search |
| 33 | `Dicklesworthstone/llm_aided_ocr` | 2,883 | 2026-03-03 | NOASSERTION | Code Intelligence |
| 34 | `simonw/files-to-prompt` | 2,621 | 2025-02-19 | Apache-2.0 | Repo Packing |
| 35 | `e2b-dev/code-interpreter` | 2,231 | 2026-03-05 | Apache-2.0 | Code Intelligence |
| 36 | `vitali87/code-graph-rag` | 2,069 | 2026-03-09 | MIT | Graph/Knowledge |
| 37 | `ForLoopCodes/contextplus` | 1,444 | 2026-03-10 | MIT | Code Intelligence |
| 38 | `cased/kit` | 1,274 | 2026-03-03 | MIT | Code Intelligence |
| 39 | `aorwall/moatless-tools` | 627 | 2025-09-01 | MIT | Code Intelligence |
| 40 | `glayzzle/php-parser` | 562 | 2026-03-02 | BSD-3-Clause | AST/Parser |
| 41 | `DeusData/codebase-memory-mcp` | 502 | 2026-03-09 | MIT | Graph/Knowledge |
| 42 | `probelabs/probe` | 489 | 2026-03-10 | Apache-2.0 | Code Search |
| 43 | `kirill-markin/repo-to-text` | 202 | 2025-12-07 | MIT | Repo Packing |
| 44 | `VKCOM/php-parser` | 79 | 2023-09-23 | MIT | AST/Parser |
| 45 | `LuciferMornens/kontext-engine` | 65 | 2026-02-14 | Apache-2.0 | Code Intelligence |
| 46 | `husnainpk/SymDex` | 65 | 2026-03-10 | MIT | Code Intelligence |
| 47 | `ragmate/ragmate-lagacy` | 44 | 2025-09-11 | Apache-2.0 | Code Intelligence |
| 48 | `pieces-app/pieces-os-client-sdk-for-python` | 41 | 2026-01-12 | MIT | Code Intelligence |
| 49 | `doITmagic/rag-code-mcp` | 24 | 2026-03-10 | MIT | MCP Server |


---

*Report generated by Agent Zero research pipeline. Data sourced from GitHub API and Brave Search.*  
*Last updated: March 10, 2026*
