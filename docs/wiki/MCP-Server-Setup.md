# MCP Server Setup

CodeRAG includes a full [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes your codebase knowledge graph to AI agents like Claude, Cursor, Windsurf, and other MCP-compatible tools.

---

## Quick Start

```bash
# 1. Parse your codebase first
coderag parse /path/to/your/project

# 2. Start the MCP server
coderag serve /path/to/your/project
```

That's it! The server runs over **stdio** transport and is ready to be connected to any MCP client.

---

> **Tip:** Running `install-coderag.sh` (see [Installation](Installation)) automatically generates `.mcp.json` and `CLAUDE.md` for your project. You can skip the manual configuration below if you've already run the installer.

## Configuring MCP Clients

### Claude Desktop

Add to your Claude Desktop configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

> **Note:** Replace `/path/to/your/project` with the absolute path to your parsed codebase.

If you installed CodeRAG to a custom location, use the full path to the binary:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "/home/user/.coderag/bin/coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

### Claude Code (CLI)

Add the MCP server using the Claude Code CLI:

```bash
claude mcp add coderag -- coderag serve /path/to/your/project
```

Or add to your project's `.mcp.json`:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

### Cursor

Add to Cursor's MCP configuration at `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

Or configure globally in Cursor Settings → MCP Servers → Add Server.

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

### VS Code (Copilot)

Add to `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "coderag": {
      "type": "stdio",
      "command": "coderag",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

### Zed

Add to Zed's settings (`~/.config/zed/settings.json`):

```json
{
  "context_servers": {
    "coderag": {
      "command": {
        "path": "coderag",
        "args": ["serve", "/path/to/your/project"]
      }
    }
  }
}
```

---

## Server Options

```bash
coderag serve [PROJECT_DIR] [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `PROJECT_DIR` | `.` | Path to the parsed project |
| `--db PATH` | auto | Override database path (default: `.codegraph/graph.db`) |
| `--no-reload` | false | Disable hot-reload (auto-detect database changes) |

### Hot-Reload

By default, the MCP server watches the database file for changes every 2 seconds. When you re-parse your codebase (`coderag parse`), the server automatically picks up the new data without restarting.

Disable this with `--no-reload` if you want static data:
```bash
coderag serve /path/to/project --no-reload
```

---

## Available MCP Tools

Once connected, your AI agent has access to these 8 tools:

### `coderag_lookup_symbol`
Look up a symbol's definition, relationships, and context.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | required | Symbol name to look up |
| `detail_level` | string | `"standard"` | `"minimal"`, `"standard"`, or `"detailed"` |
| `token_budget` | int | `4000` | Max tokens in response |

**Example prompt:** *"Look up the UserController class and show me its methods and dependencies"*

### `coderag_find_usages`
Find all usages of a symbol (calls, imports, extends, etc.).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | required | Symbol to find usages of |
| `usage_types` | list | all | Filter by edge types |
| `max_depth` | int | `1` | Transitive usage depth |

**Example prompt:** *"Find all files that import or use the AuthService"*

### `coderag_impact_analysis`
Analyze the blast radius of changing a symbol.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | required | Symbol to analyze |
| `max_depth` | int | `3` | How far to trace impact |
| `token_budget` | int | `4000` | Max tokens in response |

**Example prompt:** *"What would be affected if I change the User model?"*

### `coderag_file_context`
Get all symbols and relationships in a file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to the file |
| `token_budget` | int | `4000` | Max tokens in response |

**Example prompt:** *"Show me everything defined in app/Models/User.php"*

### `coderag_find_routes`
Find API routes with optional HTTP method filtering.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pattern` | string | `"*"` | Glob pattern for route paths |
| `http_method` | string | all | Filter by GET, POST, etc. |

**Example prompt:** *"Show me all POST routes that match /api/users/*"*

### `coderag_search`
Full-text search across the knowledge graph.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query |
| `kind_filter` | string | all | Filter by node kind |
| `limit` | int | `20` | Max results |

**Example prompt:** *"Search for anything related to authentication"*

### `coderag_architecture`
Get architecture overview with configurable focus.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `focus` | string | `"full"` | `"full"`, `"backend"`, `"frontend"`, `"api_layer"`, `"data_layer"` |
| `token_budget` | int | `4000` | Max tokens in response |

**Example prompt:** *"Give me an overview of the backend architecture"*

### `coderag_dependency_graph`
Get dependency graph for a symbol.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | required | Symbol to trace |
| `direction` | string | `"both"` | `"dependencies"`, `"dependents"`, `"both"` |
| `max_depth` | int | `2` | Traversal depth |

**Example prompt:** *"Show me the dependency tree for OrderService"*

---

## Available MCP Resources

These resources provide passive context that AI agents can read:

| URI | Description |
|-----|-------------|
| `coderag://summary` | Knowledge graph statistics and project overview |
| `coderag://architecture` | High-level architecture with communities and key nodes |
| `coderag://file-map` | Annotated file tree showing symbols per file |

---

## Typical Workflow

### 1. Initial Setup

```bash
# Navigate to your project
cd /path/to/your/project

# Initialize configuration
coderag init

# Parse the codebase
coderag parse .

# Verify the knowledge graph
coderag info .
```

### 2. Configure Your AI Tool

Add the MCP server configuration to your preferred tool (see sections above).

### 3. Use with AI

Once connected, you can ask your AI agent questions like:

- *"What does the UserController do and what are its dependencies?"*
- *"If I change the Payment model, what else would be affected?"*
- *"Show me all API routes related to authentication"*
- *"Give me an architecture overview of the backend"*
- *"Find all files that use the EmailService"*

### 4. Keep It Updated

After making code changes, re-parse to update the knowledge graph:

```bash
coderag parse . --incremental
```

If hot-reload is enabled (default), the MCP server automatically picks up changes.

---

## Multiple Projects

You can run multiple CodeRAG MCP servers for different projects:

```json
{
  "mcpServers": {
    "coderag-backend": {
      "command": "coderag",
      "args": ["serve", "/path/to/backend"]
    },
    "coderag-frontend": {
      "command": "coderag",
      "args": ["serve", "/path/to/frontend"]
    }
  }
}
```

---

## Troubleshooting

### Server not connecting

1. Ensure the codebase has been parsed first: `coderag parse /path/to/project`
2. Verify the database exists: `ls /path/to/project/.codegraph/graph.db`
3. Test the server manually: `coderag serve /path/to/project` (should start without errors)

### "No nodes found" responses

The codebase may not have been parsed yet, or the database path is wrong:
```bash
coderag info /path/to/project
```

If this shows 0 nodes, re-parse:
```bash
coderag parse /path/to/project
```

### Custom database location

If your database is not at the default `.codegraph/graph.db`:
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "/path/to/project", "--db", "/custom/path/graph.db"]
    }
  }
}
```

### Hot-reload not working

Ensure you're not using `--no-reload`. The server checks the database file's modification time every 2 seconds. If using a custom `--db` path, ensure the path is correct.
