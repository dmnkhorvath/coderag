#!/usr/bin/env bash
# setup-mcp.sh — Configure CodeRAG MCP server for your project
#
# Usage:
#   coderag-setup-mcp [PROJECT_DIR]    # defaults to current directory
#
# This script:
#   1. Parses the codebase (if not already parsed)
#   2. Creates/updates .mcp.json in the project root
#   3. Creates CLAUDE.md with tool usage instructions
#   4. Verifies the setup works

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}ℹ${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*"; }

PROJECT_DIR="${1:-.}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     CodeRAG MCP Setup                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""
info "Project: $PROJECT_NAME"
info "Path:    $PROJECT_DIR"
echo ""

# ── Step 1: Check coderag is installed ────────────────────────
if ! command -v coderag &>/dev/null; then
    err "coderag not found on PATH"
    echo "  Install with: curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh"
    exit 1
fi
ok "coderag found: $(which coderag)"

# ── Step 2: Detect coderag binary path ────────────────────────
CODERAG_BIN="$(which coderag)"

# ── Step 3: Parse codebase if needed ──────────────────────────
DB_PATH="$PROJECT_DIR/.codegraph/graph.db"
if [ -f "$DB_PATH" ]; then
    ok "Knowledge graph exists: $DB_PATH"
    read -rp "   Re-parse? (y/N) " REPARSE
    if [[ "$REPARSE" =~ ^[Yy]$ ]]; then
        info "Parsing codebase (incremental)..."
        coderag parse "$PROJECT_DIR" --incremental
        ok "Parse complete"
    fi
else
    info "No knowledge graph found. Parsing codebase..."
    coderag parse "$PROJECT_DIR"
    ok "Parse complete"
fi

# ── Step 4: Show graph stats ──────────────────────────────────
echo ""
info "Graph statistics:"
coderag info "$PROJECT_DIR" 2>/dev/null || warn "Could not read graph stats"
echo ""

# ── Step 5: Create .mcp.json ──────────────────────────────────
MCP_JSON="$PROJECT_DIR/.mcp.json"
if [ -f "$MCP_JSON" ]; then
    warn ".mcp.json already exists"
    read -rp "   Overwrite? (y/N) " OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        info "Keeping existing .mcp.json"
    else
        cat > "$MCP_JSON" << MCPEOF
{
  "mcpServers": {
    "coderag": {
      "command": "$CODERAG_BIN",
      "args": ["serve", "."],
      "env": {}
    }
  }
}
MCPEOF
        ok "Created $MCP_JSON"
    fi
else
    cat > "$MCP_JSON" << MCPEOF
{
  "mcpServers": {
    "coderag": {
      "command": "$CODERAG_BIN",
      "args": ["serve", "."],
      "env": {}
    }
  }
}
MCPEOF
    ok "Created $MCP_JSON"
fi

# ── Step 6: Create CLAUDE.md if not exists ────────────────────
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
if [ -f "$CLAUDE_MD" ]; then
    warn "CLAUDE.md already exists — skipping (won\'t overwrite your instructions)"
else
    # Find the CLAUDE.md template from coderag installation
    CODERAG_ROOT=""
    if [ -d "$HOME/.coderag/src" ]; then
        CODERAG_ROOT="$HOME/.coderag/src"
    elif [ -f "$CODERAG_BIN" ]; then
        # Try to find the package root from the binary
        CODERAG_ROOT="$(python3 -c "import coderag; import os; print(os.path.dirname(os.path.dirname(coderag.__file__)))" 2>/dev/null || true)"
    fi

    if [ -n "$CODERAG_ROOT" ] && [ -f "$CODERAG_ROOT/CLAUDE.md" ]; then
        cp "$CODERAG_ROOT/CLAUDE.md" "$CLAUDE_MD"
        ok "Created $CLAUDE_MD (from template)"
    else
        # Write a minimal CLAUDE.md
        cat > "$CLAUDE_MD" << 'CLAUDEEOF'
# CodeRAG — Codebase Knowledge Graph

This project has CodeRAG configured. Use the MCP tools to understand the codebase:

- `coderag_lookup_symbol(symbol)` — Look up any symbol
- `coderag_find_usages(symbol)` — Find all usages
- `coderag_impact_analysis(symbol)` — Blast radius analysis
- `coderag_file_context(file_path)` — Understand a file
- `coderag_find_routes(pattern)` — Find API routes
- `coderag_search(query)` — Search the graph
- `coderag_architecture()` — Architecture overview
- `coderag_dependency_graph(target)` — Dependency visualization

Re-parse after changes: `coderag parse . --incremental`
CLAUDEEOF
        ok "Created $CLAUDE_MD (minimal)"
    fi
fi

# ── Step 7: Verify MCP server starts ──────────────────────────
echo ""
info "Verifying MCP server..."
if timeout 3 coderag serve "$PROJECT_DIR" </dev/null >/dev/null 2>&1; then
    ok "MCP server starts successfully"
else
    # timeout returns 124 if it timed out (which means server started and was running)
    if [ $? -eq 124 ]; then
        ok "MCP server starts successfully (stdio mode)"
    else
        warn "MCP server may have issues — try running: coderag serve $PROJECT_DIR"
    fi
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Setup Complete!                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  Files created/updated:"
[ -f "$MCP_JSON" ]  && echo "    ✓ $MCP_JSON"
[ -f "$CLAUDE_MD" ] && echo "    ✓ $CLAUDE_MD"
echo ""
echo "  Next steps:"
echo "    1. Open this project in Claude Code / Cursor"
echo "    2. The MCP server will start automatically"
echo "    3. Use coderag_* tools to explore your codebase"
echo ""
echo "  Manual server test:"
echo "    coderag serve $PROJECT_DIR"
echo ""
