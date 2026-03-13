# CLI Reference

Complete command-line interface documentation for CodeRAG.

---

## Global Options

```bash
coderag [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Path to `codegraph.yaml` config file |
| `--db PATH` | Override database path |
| `-v, --verbose` | Increase verbosity (repeat for more: `-vv`, `-vvv`) |
| `--help` | Show help message |

---

## Commands

### `coderag init`

Initialize a `codegraph.yaml` configuration file in the current directory.

```bash
coderag init                                    # Interactive setup
coderag init --languages php,typescript         # Specify languages
coderag init --name "my-project"                # Set project name
```

| Option | Description |
|--------|-------------|
| `--languages` | Comma-separated list of languages (php, javascript, typescript) |
| `--name` | Project name (defaults to directory name) |

---

### `coderag parse`

Parse a codebase and build the knowledge graph.

```bash
coderag parse .                                 # Parse current directory
coderag parse /path/to/project                  # Parse specific project
coderag parse . --incremental                   # Only re-parse changed files
coderag parse . --parallel                      # Use parallel extraction
```

| Option | Description |
|--------|-------------|
| `--incremental` | Only re-parse files that changed since last parse |
| `--parallel` | Use parallel file extraction (ThreadPoolExecutor) |

---

### `coderag info`

Display knowledge graph statistics.

```bash
coderag info .                                  # Show graph summary
coderag info . --json                           # Output as JSON
```

---

### `coderag query`

Query the knowledge graph for symbols and relationships.

```bash
coderag query --name "User" .                   # Search by name
coderag query --name "UserController" --kind class .  # Filter by kind
coderag query --name "App\Models\User" --depth 2 .    # Traverse neighbors
```

| Option | Default | Description |
|--------|---------|-------------|
| `--name, -s` | required | Symbol name to search |
| `--kind` | all | Filter by node kind (class, function, etc.) |
| `--depth` | `1` | Neighbor traversal depth |
| `--format` | `rich` | Output format (`rich` or `json`) |
| `--limit` | `20` | Max results |

---

### `coderag export`

Export knowledge graph data in various formats.

```bash
coderag export                                  # Architecture overview (markdown)
coderag export -f json -s full                  # Full graph as JSON
coderag export -s symbol --symbol User          # Symbol context
coderag export -s file --file app/User.php      # File context
coderag export -f tree -s full                  # Repository map tree view
coderag export --tokens 16000 -o out.md         # Custom token budget
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `-f, --format` | `markdown`, `json`, `tree` | `markdown` | Output format |
| `-s, --scope` | `full`, `architecture`, `file`, `symbol` | `architecture` | Export scope |
| `--symbol` | string | — | Symbol name (for symbol scope) |
| `--file` | path | — | File path (for file scope) |
| `--tokens` | int | `8000` | Token budget |
| `--top` | int | `20` | Top N items for architecture |
| `--depth` | int | `2` | Traversal depth for symbol scope |
| `-o, --output` | path | stdout | Output file path |

---

### `coderag analyze`

Run graph analysis algorithms (PageRank, community detection, blast radius).

```bash
coderag analyze .                               # Full analysis
coderag analyze . --top 20                      # Show top 20 results
```

---

### `coderag architecture`

Generate architecture overview with community detection.

```bash
coderag architecture .                          # Architecture report
```

---

### `coderag frameworks`

Detect and report framework usage.

```bash
coderag frameworks .                            # Detect all frameworks
```

---

### `coderag cross-language`

Analyze cross-language connections (PHP routes ↔ JS API calls).

```bash
coderag cross-language .                        # Find cross-language matches
coderag cross-language . --min-confidence 0.8   # Higher confidence threshold
```

---

### `coderag enrich`

Enrich the knowledge graph with additional metadata.

```bash
coderag enrich --phpstan                        # Run PHPStan enrichment
coderag enrich --phpstan --level 8              # Custom analysis level (0-9)
coderag enrich --phpstan --phpstan-path vendor/bin/phpstan  # Custom binary
```

---

### `coderag serve`

Start the MCP server for AI agent integration.

```bash
coderag serve .                                 # Start with stdio transport
coderag serve . --db custom/graph.db            # Custom database path
coderag serve . --no-reload                     # Disable hot-reload
```

See the **[MCP Server Setup](MCP-Server-Setup)** page for detailed configuration.

---

### `coderag find-usages`

Find all usages of a symbol across the codebase.

```bash
coderag find-usages UserService                          # Find all usages
coderag find-usages UserService --types calls,imports     # Filter by type
coderag find-usages UserService --depth 2 --format json   # Transitive, JSON output
```

| Option | Description |
|--------|-------------|
| `--types` | Comma-separated usage types: calls, imports, extends, implements, instantiates, type_references, all |
| `--depth` | Transitive traversal depth (default: 1) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

---

### `coderag impact`

Analyze the blast radius of changing a symbol.

```bash
coderag impact UserService                    # Blast radius analysis
coderag impact UserService --depth 3          # Deeper analysis
coderag impact UserService --format json      # JSON output
```

| Option | Description |
|--------|-------------|
| `--depth` | Impact analysis depth, 1-5 (default: 3) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

---

### `coderag file-context`

Get LLM-optimized context for a specific file.

```bash
coderag file-context app/Services/UserService.php           # File overview
coderag file-context app/Services/UserService.php --no-source  # Without source code
```

| Option | Description |
|--------|-------------|
| `--no-source` | Exclude source code snippets |
| `--budget` | Token budget (default: 4000) |

---

### `coderag routes`

Find API routes by pattern with optional filtering.

```bash
coderag routes "/api/users/*"                  # Find routes by pattern
coderag routes "/api/*" --method GET           # Filter by HTTP method
coderag routes "/api/*" --no-frontend          # Exclude frontend callers
```

| Option | Description |
|--------|-------------|
| `--method` | Filter by HTTP method: GET, POST, PUT, PATCH, DELETE, ANY |
| `--no-frontend` | Exclude frontend API callers |
| `-f, --format` | Output format: markdown, json (default: markdown) |

---

### `coderag deps`

Show the dependency graph for a symbol.

```bash
coderag deps UserService                       # Show dependency graph
coderag deps UserService --direction dependents # Only show dependents
coderag deps UserService --depth 3             # Deeper traversal
```

| Option | Description |
|--------|-------------|
| `--direction` | dependencies, dependents, or both (default: both) |
| `--depth` | Traversal depth, 1-5 (default: 2) |
| `-f, --format` | Output format: markdown, json (default: markdown) |

---

### `coderag embed`

Generate vector embeddings for the knowledge graph.

```bash
coderag embed .                                # Embed current project
coderag embed . --model text-embedding-3-small # Use specific model
```

| Option | Description |
|--------|-------------|
| `--model` | Embedding model name |
| `--batch-size` | Batch size for embedding API calls (default: 100) |

---

### `coderag watch`

Watch the filesystem for changes and auto-reparse.

```bash
coderag watch .                                # Watch current directory
coderag watch /path/to/project --debounce 2.0  # Custom debounce
coderag watch . --no-incremental               # Full reparse on changes
```

| Option | Description |
|--------|-------------|
| `--debounce` | Debounce delay in seconds (default: 1.0) |
| `--no-incremental` | Full reparse instead of incremental |

---

### `coderag monitor`

Launch the TUI monitoring dashboard.

```bash
coderag monitor /path/to/project               # Start TUI monitor
coderag monitor /path/to/project --verbose     # Verbose logging
```

| Option | Description |
|--------|-------------|
| `--verbose` | Enable verbose logging in the TUI |

See the **[TUI Monitor](TUI-Monitor)** page for detailed usage.

