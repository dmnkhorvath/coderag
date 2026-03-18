#!/usr/bin/env bash
# install-coderag.sh — Full CodeRAG setup for any project
#
# Usage:
#   ./install-coderag.sh [PROJECT_DIR]    # defaults to current directory
#
# Uses only coderag CLI commands documented in SKILL.md:
#   init, parse, validate, info, embed, serve --watch
#
# This script:
#   1. Verifies coderag is installed
#   2. Initializes config          (coderag init)
#   3. Parses the codebase         (coderag parse)
#   4. Validates configuration     (coderag validate)
#   5. Shows graph statistics      (coderag info)
#   6. Generates embeddings        (coderag embed)       [optional]
#   7. Installs SKILL.md           (OpenSkill format)
#   8. Verifies MCP server         (coderag serve --watch)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}ℹ${NC}  $*"; }
ok()    { echo -e "${GREEN}✓${NC}  $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
err()   { echo -e "${RED}✗${NC}  $*"; }
step()  { echo -e "\n${CYAN}── $* ──${NC}"; }

PROJECT_DIR="${1:-.}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  ${BOLD}CodeRAG Installer${NC}${BLUE}                            ║${NC}"
echo -e "${BLUE}║  Knowledge Graph · MCP Server · AI Skill     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""
info "Project: ${BOLD}$PROJECT_NAME${NC}"
info "Path:    $PROJECT_DIR"

# ── Step 1: Verify coderag is installed ───────────────────────
step "Step 1/8: Checking coderag installation"
if ! command -v coderag &>/dev/null; then
    err "coderag not found on PATH"
    echo ""
    echo "  Install with:"
    echo "    pip install coderag"
    echo "  or:"
    echo "    curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/install.sh | sh"
    exit 1
fi
ok "coderag found: $(which coderag)"

# ── Step 2: Initialize config (coderag init) ──────────────────
step "Step 2/8: Initializing configuration"
CONFIG_FILE="$PROJECT_DIR/codegraph.yaml"
if [ -f "$CONFIG_FILE" ]; then
    ok "Config already exists: codegraph.yaml"
else
    info "Creating default configuration..."
    (cd "$PROJECT_DIR" && coderag init)
    if [ -f "$CONFIG_FILE" ]; then
        ok "Created codegraph.yaml"
    else
        warn "Config file not created — using defaults"
    fi
fi

# ── Step 3: Parse codebase (coderag parse) ────────────────────
step "Step 3/8: Building knowledge graph"
DB_DIR="$PROJECT_DIR/.codegraph"
DB_PATH="$DB_DIR/graph.db"
if [ -f "$DB_PATH" ]; then
    ok "Knowledge graph exists: .codegraph/graph.db"
    read -rp "   Re-parse incrementally? [y/N] " REPARSE
    if [[ "$REPARSE" =~ ^[Yy]$ ]]; then
        info "Running incremental parse..."
        coderag parse "$PROJECT_DIR" --incremental
        ok "Incremental parse complete"
    fi
else
    info "Parsing codebase (this may take a moment)..."
    coderag parse "$PROJECT_DIR"
    ok "Parse complete"
fi

# ── Step 4: Validate configuration (coderag validate) ─────────
step "Step 4/8: Validating configuration"
if coderag validate "$PROJECT_DIR" 2>/dev/null; then
    ok "Validation passed"
else
    warn "Validation reported issues — check output above"
fi

# ── Step 5: Show graph statistics (coderag info) ──────────────
step "Step 5/8: Graph statistics"
coderag info "$PROJECT_DIR" 2>/dev/null || warn "Could not read graph stats"

# ── Step 6: Semantic embeddings (coderag embed) ───────────────
step "Step 6/8: Semantic embeddings (optional)"
read -rp "   Generate semantic embeddings? [y/N] " DO_EMBED
if [[ "$DO_EMBED" =~ ^[Yy]$ ]]; then
    info "Generating embeddings (this may take a while)..."
    if coderag embed "$PROJECT_DIR" 2>/dev/null; then
        ok "Embeddings generated — semantic search enabled"
    else
        warn "Embedding generation failed — semantic search unavailable"
        warn "Retry later: coderag embed $PROJECT_DIR"
    fi
else
    info "Skipped — run later: coderag embed $PROJECT_DIR"
fi

# ── Step 7: Install SKILL.md (OpenSkill format) ───────────────
step "Step 7/8: Installing AI skill (OpenSkill)"
SKILL_DIR="$PROJECT_DIR/.coderag/skill"
SKILL_MD="$SKILL_DIR/SKILL.md"

_install_skill() {
    mkdir -p "$SKILL_DIR"

    # Find SKILL.md from the coderag installation
    local SKILL_SRC=""
    local CODERAG_ROOT=""

    # Try standard install location
    if [ -d "$HOME/.coderag/src" ]; then
        CODERAG_ROOT="$HOME/.coderag/src"
    else
        CODERAG_ROOT="$(python3 -c "
import coderag, os
print(os.path.dirname(os.path.dirname(coderag.__file__)))
" 2>/dev/null || true)"
    fi

    if [ -n "$CODERAG_ROOT" ] && [ -f "$CODERAG_ROOT/skill/SKILL.md" ]; then
        SKILL_SRC="$CODERAG_ROOT/skill/SKILL.md"
    fi

    if [ -n "$SKILL_SRC" ]; then
        cp "$SKILL_SRC" "$SKILL_MD"
        ok "Installed SKILL.md (from: $SKILL_SRC)"
    else
        # Fallback: download from GitHub
        info "Local template not found, downloading from GitHub..."
        if curl -fsSL "https://raw.githubusercontent.com/dmnkhorvath/coderag/main/skill/SKILL.md" \
             -o "$SKILL_MD" 2>/dev/null; then
            ok "Installed SKILL.md (downloaded from GitHub)"
        else
            err "Could not install SKILL.md"
            echo "  Download manually:"
            echo "    https://github.com/dmnkhorvath/coderag/blob/main/skill/SKILL.md"
            return 1
        fi
    fi

    # Create root symlink for discoverability
    local SKILL_LINK="$PROJECT_DIR/SKILL.md"
    if [ ! -f "$SKILL_LINK" ] && [ ! -L "$SKILL_LINK" ]; then
        ln -s ".coderag/skill/SKILL.md" "$SKILL_LINK" 2>/dev/null && \
            ok "Symlink: SKILL.md → .coderag/skill/SKILL.md" || true
    fi
}

if [ -f "$SKILL_MD" ]; then
    warn "SKILL.md already exists at $SKILL_MD"
    read -rp "   Overwrite? [y/N] " OVERWRITE
    if [[ "$OVERWRITE" =~ ^[Yy]$ ]]; then
        _install_skill
    else
        info "Keeping existing SKILL.md"
    fi
else
    _install_skill
fi

# ── Step 8: Verify MCP server (coderag serve --watch) ─────────
step "Step 8/8: Verifying MCP server"
info "Testing MCP server startup (with file watcher)..."
if timeout 3 coderag serve "$PROJECT_DIR" --watch </dev/null >/dev/null 2>&1; then
    ok "MCP server + file watcher starts successfully"
else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 124 ]; then
        ok "MCP server + file watcher starts successfully (stdio mode)"
    else
        warn "MCP server may have issues — test manually:"
        warn "  coderag serve $PROJECT_DIR --watch"
    fi
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ${BOLD}Installation Complete!${NC}${GREEN}                        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Files created:${NC}"
[ -f "$CONFIG_FILE" ]  && echo "    ✓ codegraph.yaml           — configuration"
[ -f "$DB_PATH" ]      && echo "    ✓ .codegraph/graph.db      — knowledge graph"
[ -f "$SKILL_MD" ]     && echo "    ✓ .coderag/skill/SKILL.md  — AI skill"
[ -L "$PROJECT_DIR/SKILL.md" ] && echo "    ✓ SKILL.md                 — symlink"
echo ""
echo -e "  ${BOLD}CLI commands used (all from SKILL.md):${NC}"
echo "    coderag init              → created config"
echo "    coderag parse             → built knowledge graph"
echo "    coderag validate          → verified configuration"
echo "    coderag info              → displayed statistics"
echo "    coderag embed             → semantic embeddings"
echo "    coderag serve --watch     → MCP server + file watcher"
echo ""
echo -e "  ${BOLD}Start serving:${NC}"
echo "    coderag serve $PROJECT_DIR --watch"
echo ""
echo -e "  ${BOLD}Other useful commands:${NC}"
echo "    coderag parse $PROJECT_DIR --incremental   # re-parse changes"
echo "    coderag monitor $PROJECT_DIR               # TUI dashboard"
echo "    coderag architecture $PROJECT_DIR          # architecture overview"
echo "    coderag search $PROJECT_DIR <query>         # search the graph"
echo "    coderag find-usages $PROJECT_DIR <symbol>   # find symbol usages"
echo "    coderag impact $PROJECT_DIR <symbol>        # blast radius analysis"
echo ""
