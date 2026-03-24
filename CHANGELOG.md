# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-24

### Added
- **Go language plugin** with tree-sitter-go extractor, resolver, and tests
- **Rust language plugin** with tree-sitter-rust extractor, resolver, and tests
- **`coderag grep` command** — ranked semantic search across codebase (CLI + MCP tool)
- **`coderag launch` command** — Smart Launcher for AI tool integration (Claude Code, Cursor, Codex)
  - `--dry-run` mode for headless validation
  - `--context-only` mode for context output to stdout
  - `--token-budget` option for controlling context size
  - Auto-detects installed AI tools
  - Generates CLAUDE.md, .claude/settings.local.json, .cursor/mcp.json
- **`coderag validate` command** for configuration and environment validation
- **`coderag benchmark` command** for token cost benchmarking across pricing models
- **`coderag update` command** with auto-update system (version check, cache, opt-in auto-update)
- **Session Memory & Context Persistence** — cross-session memory for reads, edits, decisions, tasks, facts
  - 8 new MCP tools for session tracking
  - CLI commands: `session list`, `session show`, `session context`
  - Automatic context injection on session start
- **MkDocs Material documentation site** with GitHub Actions deployment
- **Docker support** with multi-stage build and compose
- **Enhanced Vue framework detector** — 29 additional edge types (Nuxt, Pinia, Vuex, Vue Router, Teleport, KeepAlive)
- **Enhanced Symfony framework detector** — 14 additional edge types (Twig, Doctrine, Messenger, Security, Console)
- **Enhanced Angular framework detector** — 10 additional edge types (Signals, standalone components, control flow)
- **Tiered community detection** — Leiden for medium graphs, label propagation for large graphs
- **CSS and SCSS language plugins** with tree-sitter parsing
- **Tailwind CSS framework detector**
- **Semantic search** with vector embeddings (FAISS + fastembed ONNX)
- **Large-scale optimization**: parallel extraction, SQLite batching, memory management
- **Live file watcher** with parallel pipeline phases and DB-level parallelism
- **5 CLI commands** for full MCP-to-CLI parity: find-usages, impact, file-context, routes, deps
- **E2E test suite** validating full workflow against real repositories
- **Comprehensive documentation**: quickstart, launcher, session memory, cost savings, AI tool setup guides
- Installer auto-generates `CLAUDE.md` and `.mcp.json` for Claude Code integration
- Conditional CI test matrix: full 3.11/3.12/3.13 on PRs, single 3.12 on push
- 8 dogfood session logs documenting real-world usage

### Changed
- **Renamed PyPI package** from `coderag` to `coderag-cli` to resolve name conflict
- **Replaced sentence-transformers with fastembed** for local ONNX-based embeddings
  - No PyTorch dependency (~2GB savings)
  - Models run locally via ONNX Runtime (~90MB)
  - Same all-MiniLM-L6-v2 model, backward-compatible with existing vector indices
- Comprehensive README rewrite with accurate stats and full feature coverage
- Architecture tool reads pre-computed data from SQLite instead of live graph analysis
- PageRank scores persisted to DB; framework metadata key mismatch fixed
- Python, JS/TS, mixed-language benchmark reports updated

### Fixed
- Monorepo detection for React/NextJS/Express and Vue projects
- `.vue` SFC parsing support and phantom PHP language on placeholder nodes
- TypeScript `__dict__` crash in monorepo Vue detection
- Search deprioritizes external nodes; PageRank excludes CSS
- TUI monitor showing 0 stats and unresponsive metrics
- `enrich` command missing `store.initialize()` causing DB connection error
- `TypeError` in config.py when `db_path` missing from YAML
- POSIX-compatible install script (macOS sh compatibility)
- CI test failures: mock side_effect cleanup, search_semantic mock, ruff format
- CI failures: lint, mypy, test dependencies, dynamic repo_root for CI compatibility

## [0.1.0] - 2026-03-14

### Added
- Core foundation: models, config, registry, SQLite storage (P0 Part 1)
- PHP plugin with Tree-sitter extractor and pipeline orchestrator (P0 Part 2)
- CLI commands and Markdown output formatter — P0 MVP complete (P0 Part 3)
- Phase 4 reference resolver for cross-file typed edges
- FTS5 search with PascalCase/camelCase support and SQL-level kind filter
- JavaScript language plugin with Tree-sitter extractor and Node.js module resolver
- TypeScript language plugin with TS/TSX grammar support, interfaces, type aliases, enums, and tsconfig path resolution
- Professional installer system
- Graph analysis (PageRank, blast radius, circular deps) and context assembler
- Framework detectors and cross-language matching
- MCP server with 8 tools and 3 resources
- Git metadata enrichment: change frequency, co-change, ownership
- Multi-format export, hot-reload, comprehensive test suite
- Next.js and Vue framework detectors
- PHPStan type enrichment with CLI command
- Python language plugin with tree-sitter extractor, resolver, and module resolution
- Django, Flask, FastAPI framework detectors for Python plugin
- TUI monitoring dashboard with 5 screens and vim keybindings
- GitHub Actions CI/CD (ci, release, benchmark workflows)

### Fixed
- FTS5 search for PascalCase/camelCase with SQL-level kind filter
- Invalid `limit` parameter in React detector `get_edges` call

[0.2.0]: https://github.com/dmnkhorvath/coderag-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dmnkhorvath/coderag-cli/releases/tag/v0.1.0
