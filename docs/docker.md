# 🐳 Docker Guide

Run CodeRAG in Docker without installing Python or dependencies locally.

## Table of Contents

- [Quick Start](#quick-start)
- [Docker Compose](#docker-compose)
- [Building from Source](#building-from-source)
- [Volume Mounting](#volume-mounting)
- [MCP Server in Docker](#mcp-server-in-docker)
- [Environment Variables](#environment-variables)
- [Common Commands](#common-commands)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Using Docker Run

```bash
# Build the image
docker build -t coderag .

# Parse your codebase
docker run --rm -v $(pwd):/code coderag parse .

# View project info
docker run --rm -v $(pwd):/code coderag info

# Query the knowledge graph
docker run --rm -v $(pwd):/code coderag query "find all controllers"

# Analyze architecture
docker run --rm -v $(pwd):/code coderag architecture

# Find symbol usages
docker run --rm -v $(pwd):/code coderag find-usages UserController

# Export the graph
docker run --rm -v $(pwd):/code coderag export --format json
```

### Using Docker Compose

```bash
# Parse your codebase
docker compose run --rm coderag parse .

# Start the MCP server
docker compose up coderag-mcp

# Start file watcher
docker compose up coderag-watch
```

---

## Docker Compose

The `docker-compose.yml` provides three services:

| Service | Description | Usage |
|---------|-------------|-------|
| `coderag` | Main CLI (one-off commands) | `docker compose run --rm coderag <command>` |
| `coderag-mcp` | MCP server for AI tools | `docker compose up coderag-mcp` |
| `coderag-watch` | File watcher (auto re-parse) | `docker compose up coderag-watch` |

### Running CLI Commands

```bash
# Parse
docker compose run --rm coderag parse .

# Query
docker compose run --rm coderag query "find routes"

# Impact analysis
docker compose run --rm coderag impact UserController.store

# View dependencies
docker compose run --rm coderag deps
```

### Running Background Services

```bash
# Start MCP server in background
docker compose up -d coderag-mcp

# View logs
docker compose logs -f coderag-mcp

# Stop services
docker compose down
```

---

## Building from Source

```bash
# Clone the repository
git clone https://github.com/dmnkhorvath/coderag-cli.git
cd coderag

# Build the Docker image
docker build -t coderag .

# Build with a specific tag
docker build -t coderag:0.1.0 .

# Build with no cache (fresh build)
docker build --no-cache -t coderag .
```

### Image Size

The multi-stage build produces a minimal image:

| Stage | Purpose | Includes |
|-------|---------|----------|
| Builder | Compile C extensions | gcc, g++, git, full pip install |
| Runtime | Run CodeRAG | Python 3.12-slim, git, installed packages |

Build dependencies (gcc, g++) are **not** included in the final image.

---

## Volume Mounting

CodeRAG needs access to your codebase. Mount it to `/code` inside the container:

```bash
# Mount current directory
docker run --rm -v $(pwd):/code coderag parse .

# Mount a specific directory
docker run --rm -v /path/to/project:/code coderag parse .

# Mount read-only (for analysis only, no .codegraph output)
docker run --rm -v $(pwd):/code:ro coderag info
```

### Data Persistence

CodeRAG stores its knowledge graph in `.codegraph/` inside the mounted directory. Since this is on your host filesystem, data persists between container runs.

```
your-project/
├── src/
├── .codegraph/          # ← Created by CodeRAG, persists on host
│   ├── graph.db
│   └── config.yaml
└── ...
```

### Permissions

If you encounter permission issues with the mounted volume:

```bash
# Run as your current user
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/code coderag parse .
```

---

## MCP Server in Docker

Run the MCP server for AI tool integration (Claude Code, Cursor, etc.):

### Using Docker Compose (Recommended)

```bash
# Start MCP server on port 3000
docker compose up coderag-mcp

# Start in background
docker compose up -d coderag-mcp
```

### Using Docker Run

```bash
# Start MCP server
docker run --rm -v $(pwd):/code -p 3000:3000 coderag serve . --watch

# Start in background
docker run -d --name coderag-mcp -v $(pwd):/code -p 3000:3000 coderag serve . --watch
```

### Connecting AI Tools

Configure your AI tool to connect to the MCP server:

```json
{
  "mcpServers": {
    "coderag": {
      "url": "http://localhost:3000"
    }
  }
}
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYTHONUNBUFFERED` | Disable output buffering | `1` (set in Dockerfile) |
| `PYTHONDONTWRITEBYTECODE` | Skip .pyc file creation | `1` (set in Dockerfile) |

---

## Common Commands

```bash
# ── Parsing ──────────────────────────────────────────────
docker run --rm -v $(pwd):/code coderag parse .
docker run --rm -v $(pwd):/code coderag parse . --verbose

# ── Analysis ─────────────────────────────────────────────
docker run --rm -v $(pwd):/code coderag info
docker run --rm -v $(pwd):/code coderag analyze
docker run --rm -v $(pwd):/code coderag architecture
docker run --rm -v $(pwd):/code coderag frameworks

# ── Querying ─────────────────────────────────────────────
docker run --rm -v $(pwd):/code coderag query "find all models"
docker run --rm -v $(pwd):/code coderag find-usages UserController
docker run --rm -v $(pwd):/code coderag impact UserController.store
docker run --rm -v $(pwd):/code coderag file-context src/app.php
docker run --rm -v $(pwd):/code coderag routes
docker run --rm -v $(pwd):/code coderag deps

# ── Export ───────────────────────────────────────────────
docker run --rm -v $(pwd):/code coderag export --format json
docker run --rm -v $(pwd):/code coderag export --format markdown

# ── Server ───────────────────────────────────────────────
docker run --rm -v $(pwd):/code -p 3000:3000 coderag serve . --watch
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Permission denied` on mounted volume | Run with `--user $(id -u):$(id -g)` |
| `.codegraph/` not created | Ensure volume is not mounted read-only (`:ro`) |
| Build fails on tree-sitter | Ensure Docker has internet access for pip downloads |
| MCP server not accessible | Check port mapping: `-p 3000:3000` |
| Container exits immediately | Check command syntax: `docker run --rm -v $(pwd):/code coderag parse .` |
| Slow first parse | Normal — tree-sitter grammars compile on first use, subsequent runs are cached |
| Image too large | Use `docker image prune` to clean build cache |
| `git` commands fail inside container | Git is included in runtime image; ensure `.git/` is not in `.dockerignore` for git enrichment |

### Checking Image Size

```bash
docker images coderag --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
```

### Debugging

```bash
# Open a shell inside the container
docker run --rm -it -v $(pwd):/code --entrypoint /bin/bash coderag

# Check installed packages
docker run --rm coderag pip list

# Check Python version
docker run --rm --entrypoint python coderag --version
```
