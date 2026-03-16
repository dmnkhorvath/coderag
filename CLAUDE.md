# CodeRAG — Codebase Knowledge Graph

CodeRAG builds an AST-based knowledge graph from your codebase and exposes it
via MCP. It supports PHP, JavaScript, TypeScript, CSS, and SCSS with framework
detection for Laravel, React, Vue, Angular, Next.js, Express, NestJS, and more.

## Setup

Before using CodeRAG tools, parse your codebase first:

```bash
coderag parse .
```

The MCP server is configured in `.mcp.json` and starts automatically.

## Available MCP Tools

You have 8 CodeRAG tools available:

### `coderag_lookup_symbol`
Look up any symbol (class, function, method) to see its definition, relationships, and context.
```
coderag_lookup_symbol(symbol="UserController", detail_level="summary")
```

### `coderag_find_usages`
Find everywhere a symbol is called, imported, extended, or instantiated.
```
coderag_find_usages(symbol="BaseController", usage_types=["extends", "calls"])
```

### `coderag_impact_analysis`
Analyze blast radius before refactoring. Shows all affected code by depth.
```
coderag_impact_analysis(symbol="UserService", max_depth=3)
```

### `coderag_file_context`
Understand a file\'s role — all symbols, relationships, and importance scores.
```
coderag_file_context(file_path="src/Controllers/UserController.php")
```

### `coderag_find_routes`
Discover API endpoints matching a pattern, including frontend callers.
```
coderag_find_routes(pattern="/api/users/*", include_frontend=true)
```

### `coderag_search`
Full-text or semantic search across the knowledge graph.
```
coderag_search(query="authentication", node_types=["class", "function"])
```

### `coderag_architecture`
High-level architecture overview with communities, key nodes, and entry points.
```
coderag_architecture(focus="backend")
```

### `coderag_dependency_graph`
Visualize dependency relationships for a symbol or file.
```
coderag_dependency_graph(target="UserService", direction="both", max_depth=2)
```

## Resources (passive context)

- `coderag://summary` — Graph statistics and project overview
- `coderag://architecture` — High-level architecture with communities
- `coderag://file-map` — Annotated file tree with symbol counts

## Best Practices

1. **Start with architecture** — Use `coderag_architecture()` to understand the big picture
2. **Before refactoring** — Always run `coderag_impact_analysis()` first
3. **Use search for discovery** — `coderag_search()` when you don\'t know exact names
4. **Check file context** — `coderag_file_context()` before editing unfamiliar files
5. **Token budgets** — All tools accept `token_budget` (default 4000, max 16000)

## Re-parsing

After significant code changes, re-parse to update the graph:
```bash
coderag parse . --incremental
```

The MCP server supports hot-reload — it detects database changes automatically.
