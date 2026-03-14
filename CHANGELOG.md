# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `coderag validate` CLI command for configuration and environment validation
- CHANGELOG.md following Keep a Changelog format

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
- Graph analysis (PageRank, blast radius, circular deps) and context assembler (P2 Part 1)
- Framework detectors and cross-language matching (P2 Part 2)
- MCP server with 8 tools and 3 resources (P2 Part 3)
- Git metadata enrichment: change frequency, co-change, ownership (P3 Part 1)
- Multi-format export, hot-reload, comprehensive test suite (P3 Complete)
- Next.js and Vue framework detectors with 52 tests
- PHPStan type enrichment with CLI command and 47 tests
- Python language plugin with tree-sitter extractor, resolver, and module resolution
- Django, Flask, FastAPI framework detectors for Python plugin
- Semantic search with vector embeddings (FAISS + sentence-transformers)
- Large-scale optimization: parallel extraction, SQLite batching, memory management
- TUI monitoring dashboard with 5 screens, vim keybindings, and command mode
- GitHub Actions CI/CD (ci, release, benchmark workflows)
- Django framework detector tests (100% coverage)
- Laravel framework detector tests (100% coverage)
- Python framework detector tests (Flask, FastAPI, Django)
- Live file watcher with parallel pipeline phases and DB-level parallelism
- 5 CLI commands for full MCP-to-CLI parity: find-usages, impact, file-context, routes, deps
- Wiki pages: Installation, MCP Setup, CLI Reference, Configuration
- CSS and SCSS language plugins with tree-sitter parsing
- Tailwind CSS framework detector
- Conditional CI test matrix: full 3.11/3.12/3.13 on PRs, single 3.12 on push

### Fixed
- FTS5 search for PascalCase/camelCase with SQL-level kind filter
- Invalid `limit` parameter in React detector `get_edges` call
- CI test failures: mock side_effect cleanup, search_semantic mock, ruff format
- CI failures: lint, mypy, test dependencies
- Watchdog added to core dependencies (fixes CI test collection failure)

### Changed
- Comprehensive README with 596 lines and PyPI-ready pyproject.toml
- Python benchmark report covering 10 repositories
- Mixed-language benchmark: 4 repos (koel, monica, flarum, bagisto)
- JS/TS benchmark: 15 repos, 49K files, 352K nodes, 762K edges, 97% query accuracy
- CLI documentation for find-usages, impact, file-context, routes, deps, watch

[Unreleased]: https://github.com/dmnkhorvath/coderag/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dmnkhorvath/coderag/releases/tag/v0.1.0
