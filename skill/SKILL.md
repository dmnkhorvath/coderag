---
name: "coderag"
description: "CodeRAG MCP server skill — teaches coding agents how to configure, launch, and use CodeRAG's 8 MCP tools and 3 resources for AST-based codebase intelligence. Use when working with PHP, JavaScript, or TypeScript codebases and needing symbol lookup, impact analysis, route discovery, or architecture overview."
version: "0.1.0"
author: "dmnkhorvath"
tags: ["mcp", "code-analysis", "knowledge-graph", "ast", "php", "javascript", "typescript", "codebase", "rag"]
trigger_patterns:
  - "coderag"
  - "code graph"
  - "knowledge graph"
  - "symbol lookup"
  - "impact analysis"
  - "find usages"
  - "codebase architecture"
  - "mcp server"
  - "parse codebase"
---

# CodeRAG — Codebase Knowledge Graph for LLMs

CodeRAG builds an AST-based knowledge graph from your codebase and exposes it
via MCP (Model Context Protocol). It supports **PHP**, **JavaScript**, and
**TypeScript** with framework detection for Laravel, React, Vue, Angular,
Next.js, Express, NestJS, Tailwind CSS, and more.

## Quick Start

### 1. Install CodeRAG

```bash
# Option A: One-line installer
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install.sh | sh

# Option B: From source
git clone https://github.com/dmnkhorvath/coderag-cli.git
cd coderag && pip install -e .[full]
```

### 2. Parse Your Codebase

```bash
# Parse the current project
coderag parse /path/to/your/project

# With incremental updates (skips unchanged files)
coderag parse /path/to/your/project --incremental
```

### 3. Start the MCP Server

```bash
coderag serve /path/to/your/project --watch
```

### 4. Configure Your AI Tool

Add to your project\'s `.mcp.json`:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "."]
    }
  }
}
```

Or for Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coderag": {
      "command": "/path/to/coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

> **Tip**: If installed via `install.sh`, the binary is at `~/.coderag/bin/coderag`.
> If installed via pip, it\'s on your PATH.

> **Automated:** `install-coderag.sh` generates both `.mcp.json` and `CLAUDE.md` automatically.

---

## MCP Tools Reference

CodeRAG exposes **8 tools** via MCP. Each tool accepts a `token_budget`
parameter (default: 4000, max: 16000) to control response size.

### Tool 1: `coderag_lookup_symbol`

Look up a code symbol (class, function, method) and return its definition,
relationships, and context.

**When to use**: Understanding what a symbol is, where it\'s defined, and how
it relates to other code.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | *required* | Symbol name or qualified name |
| `detail_level` | enum | `"summary"` | `signature` \| `summary` \| `detailed` \| `comprehensive` |
| `token_budget` | int | 4000 | Max tokens for response (500-16000) |

**Examples**:
```
coderag_lookup_symbol(symbol="UserController")
coderag_lookup_symbol(symbol="App\\Http\\Controllers\\UserController", detail_level="comprehensive")
coderag_lookup_symbol(symbol="handleSubmit", detail_level="detailed", token_budget=8000)
```

---

### Tool 2: `coderag_find_usages`

Find all usages of a symbol — where it\'s called, imported, extended,
implemented, or instantiated.

**When to use**: Understanding how widely a symbol is used and by whom.
Essential before renaming or deprecating.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | *required* | Symbol name to find usages of |
| `usage_types` | list[enum] | all | `calls` \| `imports` \| `extends` \| `implements` \| `instantiates` \| `type_references` \| `all` |
| `max_depth` | int | 1 | Hops to traverse (1=direct, 2+=transitive, max 5) |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_find_usages(symbol="BaseController", usage_types=["extends"])
coderag_find_usages(symbol="UserService", max_depth=2)
coderag_find_usages(symbol="formatDate", usage_types=["calls", "imports"])
```

---

### Tool 3: `coderag_impact_analysis`

Analyze the blast radius of changing a symbol. Shows all code that would be
affected by a change, organized by depth level.

**When to use**: Before refactoring or modifying shared code. Essential for
understanding risk.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | *required* | Symbol to analyze impact for |
| `max_depth` | int | 3 | Levels of dependencies to trace (1-5) |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_impact_analysis(symbol="User", max_depth=3)
coderag_impact_analysis(symbol="DatabaseConnection", max_depth=5, token_budget=8000)
```

---

### Tool 4: `coderag_file_context`

Get context for a specific file — all symbols defined in it, their
relationships, and importance scores.

**When to use**: Understanding what a file contains and how it fits into the
codebase. Great for onboarding to unfamiliar files.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | *required* | Path to file (relative or absolute, flexible matching) |
| `include_source` | bool | true | Include source code snippets |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_file_context(file_path="src/Controllers/UserController.php")
coderag_file_context(file_path="components/Dashboard.tsx", include_source=false)
coderag_file_context(file_path="UserController.php")  # flexible matching
```

---

### Tool 5: `coderag_find_routes`

Find API routes/endpoints matching a URL pattern. Shows route definitions and
optionally frontend code that calls them.

**When to use**: Discovering API endpoints, understanding frontend-backend
connections, debugging API issues.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pattern` | string | *required* | URL pattern (supports glob: `/api/users/*`) |
| `http_method` | enum | any | `GET` \| `POST` \| `PUT` \| `PATCH` \| `DELETE` \| `ANY` |
| `include_frontend` | bool | true | Include frontend API calls to matched routes |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_find_routes(pattern="/api/users/*")
coderag_find_routes(pattern="/api/auth/*", http_method="POST")
coderag_find_routes(pattern="*", include_frontend=true, token_budget=8000)
```

---

### Tool 6: `coderag_search`

Full-text search across the knowledge graph. Search for symbols by name,
qualified name, or docblock content.

**When to use**: Finding symbols when you don\'t know the exact name. Exploring
the codebase by keyword.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Search query |
| `node_types` | list[string] | all | Filter: `class`, `function`, `method`, `route`, `interface`, etc. |
| `language` | string | all | Filter: `php`, `javascript`, `typescript` |
| `mode` | string | `"auto"` | `fts` (keyword) \| `semantic` (vector) \| `hybrid` \| `auto` |
| `limit` | int | 20 | Max results (1-100) |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_search(query="authentication", node_types=["class", "function"])
coderag_search(query="user validation", language="php", mode="semantic")
coderag_search(query="handleClick", node_types=["function"], language="typescript")
```

> **Note**: Semantic search requires running `coderag embed` first.

---

### Tool 7: `coderag_architecture`

Get a high-level architecture overview of the codebase. Shows
communities/modules, important nodes (by PageRank), and entry points.

**When to use**: Getting oriented in a new codebase. Understanding the overall
structure and key components.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `focus` | enum | `"full"` | `full` \| `backend` \| `frontend` \| `api_layer` \| `data_layer` |
| `token_budget` | int | 8000 | Max tokens for response (1000-32000) |

**Examples**:
```
coderag_architecture()
coderag_architecture(focus="backend", token_budget=16000)
coderag_architecture(focus="api_layer")
```

---

### Tool 8: `coderag_dependency_graph`

Show the dependency graph for a symbol or file. Visualizes what depends on
what, including transitive dependencies.

**When to use**: Understanding coupling, planning refactors, identifying
circular dependencies.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | string | *required* | Symbol name or file path |
| `direction` | enum | `"both"` | `dependencies` \| `dependents` \| `both` |
| `max_depth` | int | 2 | Levels deep to traverse (1-5) |
| `token_budget` | int | 4000 | Max tokens for response |

**Examples**:
```
coderag_dependency_graph(target="UserService")
coderag_dependency_graph(target="src/Models/User.php", direction="dependents", max_depth=3)
coderag_dependency_graph(target="apiClient", direction="dependencies")
```

---

## MCP Resources

CodeRAG also exposes **3 passive resources** that provide context without
explicit tool calls:

| Resource URI | Description |
|-------------|-------------|
| `coderag://summary` | Knowledge graph statistics: node/edge counts, languages, frameworks, top nodes by PageRank |
| `coderag://architecture` | High-level architecture: communities, important nodes, entry points, graph statistics |
| `coderag://file-map` | Annotated file tree showing symbols per file with language breakdown |

---

## Recommended Workflows

### Workflow 1: Onboarding to a New Codebase

1. `coderag_architecture()` — get the big picture
2. `coderag_search(query="main entry", node_types=["function", "class"])` — find entry points
3. `coderag_file_context(file_path="...")` — dive into key files
4. `coderag_lookup_symbol(symbol="...")` — understand specific symbols

### Workflow 2: Before Refactoring

1. `coderag_lookup_symbol(symbol="TargetClass", detail_level="comprehensive")` — understand the symbol
2. `coderag_impact_analysis(symbol="TargetClass", max_depth=3)` — assess blast radius
3. `coderag_find_usages(symbol="TargetClass")` — find all consumers
4. `coderag_dependency_graph(target="TargetClass", direction="both")` — visualize dependencies

### Workflow 3: API Investigation

1. `coderag_find_routes(pattern="/api/*")` — discover all API endpoints
2. `coderag_find_routes(pattern="/api/users/*", include_frontend=true)` — find frontend callers
3. `coderag_lookup_symbol(symbol="UserController")` — understand the handler
4. `coderag_dependency_graph(target="UserController")` — see what it depends on

### Workflow 4: Bug Investigation

1. `coderag_search(query="error keyword")` — find related code
2. `coderag_file_context(file_path="problematic_file.php")` — understand the file
3. `coderag_find_usages(symbol="suspectFunction")` — trace callers
4. `coderag_impact_analysis(symbol="suspectFunction")` — understand scope

---

## Supported Languages & Frameworks

| Language | Frameworks Detected |
|----------|--------------------|
| PHP | Laravel (routes, Blade, Eloquent, middleware) |
| JavaScript | React, Vue, Angular, Express, Next.js |
| TypeScript | React, Angular, NestJS, Next.js |
| CSS/SCSS | Tailwind CSS |

## Node Types in the Graph

`file`, `namespace`, `class`, `interface`, `trait`, `enum`, `function`,
`method`, `property`, `constant`, `variable`, `import`, `export`, `route`,
`component`, `hook`, `middleware`, `model`, `migration`, `test`, `type_alias`,
`enum_case`, `mixin`, `decorator`, `module`

## Edge Types in the Graph

`imports`, `exports`, `extends`, `implements`, `uses_trait`, `calls`,
`instantiates`, `has_method`, `has_property`, `has_parameter`, `returns_type`,
`has_type`, `contains`, `defined_in`, `routes_to`, `renders`, `api_calls`,
`middleware_chain`, `generic_of`, `decorates`, `overrides`, `dynamic_imports`,
`imports_type`, `re_exports`, `provides`, `injects`, `emits`, `listens`,
`co_changes_with`

---

## CLI Commands Reference

| Command | Description |
|---------|-------------|
| `coderag parse <dir>` | Parse codebase and build knowledge graph |
| `coderag serve <dir> [--watch]` | Start MCP server (+ file watcher with --watch) |
| `coderag info <dir>` | Show graph statistics |
| `coderag analyze <dir> <symbol>` | Analyze a symbol |
| `coderag architecture <dir>` | Show architecture overview |
| `coderag find-usages <dir> <symbol>` | Find all usages of a symbol |
| `coderag impact <dir> <symbol>` | Impact/blast radius analysis |
| `coderag file-context <dir> <file>` | Get file context |
| `coderag routes <dir> <pattern>` | Find API routes |
| `coderag deps <dir> <target>` | Dependency graph |
| `coderag search <dir> <query>` | Search the graph |
| `coderag export <dir>` | Export graph data |
| `coderag embed <dir>` | Generate semantic embeddings |
| `coderag query <dir> <query>` | Query with semantic search |
| `coderag monitor <dir>` | TUI dashboard |
| `coderag watch <dir>` | Watch for file changes |
| `coderag validate <dir>` | Validate configuration |
| `coderag init` | Initialize config file |
| `coderag frameworks <dir>` | Detect frameworks |

---

## Troubleshooting

### "No nodes found" after parsing
- Ensure the project has `.php`, `.js`, `.ts`, `.jsx`, `.tsx` files
- Check `coderag info .` for statistics
- Verify files aren\'t in ignored directories (node_modules, vendor)

### MCP server not connecting
- Test manually: `coderag serve /path/to/project --watch` (serves + watches for changes)
- Verify `.mcp.json` path is correct and absolute
- Check that `coderag` is on PATH or use full path in config

### Slow parsing
- Use `--incremental` flag for subsequent parses
- Use `--parallel` for multi-core extraction
- Large codebases (10K+ files) may take 5-15 minutes on first parse

### Semantic search not working
- Run `coderag embed .` first to generate vector embeddings
- Requires `fastembed` and `faiss-cpu` (included in `[full]` install)
