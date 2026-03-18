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
#   8. Installs global skill       (~/.claude/ for all projects)
#   9. Installs CLAUDE.md          (Claude Code instructions)
#  10. Installs .mcp.json          (MCP server config)
#  11. Verifies MCP server         (coderag serve --watch)


main() {
    set -eu

    # ── Colors (using printf for POSIX compatibility) ─────────────
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'

    info()  { printf "${BLUE}ℹ${NC}  %s\n" "$*"; }
    ok()    { printf "${GREEN}✓${NC}  %s\n" "$*"; }
    warn()  { printf "${YELLOW}⚠${NC}  %s\n" "$*"; }
    err()   { printf "${RED}✗${NC}  %s\n" "$*"; }
    step()  { printf "\n${CYAN}── %s ──${NC}\n" "$*"; }

    # ── Prompt helper (POSIX-safe, reads from /dev/tty for curl|sh) ─
    if [ -t 0 ] || [ -e /dev/tty ]; then
        INTERACTIVE=true
    else
        INTERACTIVE=false
    fi

    ask() {
        if [ "$INTERACTIVE" = true ]; then
            printf "   %s " "$1"
            read -r REPLY < /dev/tty
        else
            REPLY="N"
        fi
    }

    PROJECT_DIR="${1:-.}"
    PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
    PROJECT_NAME="$(basename "$PROJECT_DIR")"

    echo ""
    printf "${BLUE}╔══════════════════════════════════════════════╗${NC}\n"
    printf "${BLUE}║  ${BOLD}CodeRAG Installer${NC}${BLUE}                            ║${NC}\n"
    printf "${BLUE}║  Knowledge Graph · MCP Server · AI Skill     ║${NC}\n"
    printf "${BLUE}╚══════════════════════════════════════════════╝${NC}\n"
    echo ""
    info "Project: ${BOLD}$PROJECT_NAME${NC}"
    info "Path:    $PROJECT_DIR"

    # ── Step 1: Verify coderag is installed ───────────────────────
    step "Step 1/11: Checking coderag installation"
    if ! command -v coderag >/dev/null 2>&1; then
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
    step "Step 2/11: Initializing configuration"
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
    step "Step 3/11: Building knowledge graph"
    DB_DIR="$PROJECT_DIR/.codegraph"
    DB_PATH="$DB_DIR/graph.db"
    if [ -f "$DB_PATH" ]; then
        ok "Knowledge graph exists: .codegraph/graph.db"
        ask "Re-parse incrementally? [y/N]"
        case "$REPLY" in
            [Yy]*)
                info "Running incremental parse..."
                coderag parse "$PROJECT_DIR" --incremental
                ok "Incremental parse complete"
                ;;
        esac
    else
        info "Parsing codebase (this may take a moment)..."
        coderag parse "$PROJECT_DIR"
        ok "Parse complete"
    fi

    # ── Step 4: Validate configuration (coderag validate) ─────────
    step "Step 4/11: Validating configuration"
    if coderag validate "$PROJECT_DIR" 2>/dev/null; then
        ok "Validation passed"
    else
        warn "Validation reported issues — check output above"
    fi

    # ── Step 5: Show graph statistics (coderag info) ──────────────
    step "Step 5/11: Graph statistics"
    coderag info "$PROJECT_DIR" 2>/dev/null || warn "Could not read graph stats"

    # ── Step 6: Semantic embeddings (coderag embed) ───────────────
    step "Step 6/11: Semantic embeddings (optional)"
    ask "Generate semantic embeddings? [y/N]"
    case "$REPLY" in
        [Yy]*)
            info "Generating embeddings (this may take a while)..."
            if coderag embed "$PROJECT_DIR" 2>/dev/null; then
                ok "Embeddings generated — semantic search enabled"
            else
                warn "Embedding generation failed — semantic search unavailable"
                warn "Retry later: coderag embed $PROJECT_DIR"
            fi
            ;;
        *)
            info "Skipped — run later: coderag embed $PROJECT_DIR"
            ;;
    esac

    # ── Step 7: Install SKILL.md (OpenSkill format) ───────────────
    step "Step 7/11: Installing AI skill (OpenSkill)"
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
        ask "Overwrite? [y/N]"
        case "$REPLY" in
            [Yy]*) _install_skill ;;
            *)     info "Keeping existing SKILL.md" ;;
        esac
    else
        _install_skill
    fi

    # ── Step 8: Install global skill (~/.claude/) ───────────────
    step "Step 8/11: Installing global Claude skill"
    GLOBAL_SKILL_DIR="$HOME/.claude/skills/coderag"
    GLOBAL_SKILL_MD="$GLOBAL_SKILL_DIR/SKILL.md"

    _install_global_skill() {
        mkdir -p "$GLOBAL_SKILL_DIR"

        # Source: use the project-local SKILL.md we just installed
        if [ -f "$SKILL_MD" ]; then
            cp "$SKILL_MD" "$GLOBAL_SKILL_MD"
            ok "Installed global skill: $GLOBAL_SKILL_MD"
        else
            # Fallback: download from GitHub
            info "Local SKILL.md not found, downloading from GitHub..."
            if curl -fsSL "https://raw.githubusercontent.com/dmnkhorvath/coderag/main/skill/SKILL.md"                  -o "$GLOBAL_SKILL_MD" 2>/dev/null; then
                ok "Installed global skill (downloaded from GitHub)"
            else
                err "Could not install global skill"
                return 1
            fi
        fi

        # Create a convenience symlink at ~/.claude/coderag-SKILL.md
        local GLOBAL_LINK="$HOME/.claude/coderag-SKILL.md"
        if [ ! -f "$GLOBAL_LINK" ] && [ ! -L "$GLOBAL_LINK" ]; then
            ln -s "skills/coderag/SKILL.md" "$GLOBAL_LINK" 2>/dev/null &&                 ok "Symlink: ~/.claude/coderag-SKILL.md -> skills/coderag/SKILL.md" || true
        fi

        info "CodeRAG skill is now globally available for all Claude projects"
    }

    if [ -f "$GLOBAL_SKILL_MD" ]; then
        warn "Global skill already exists at $GLOBAL_SKILL_MD"
        ask "Overwrite? [y/N]"
        case "$REPLY" in
            [Yy]*) _install_global_skill ;;
            *)     info "Keeping existing global skill" ;;
        esac
    else
        _install_global_skill
    fi

    # ── Step 9: Install CLAUDE.md (Claude Code instructions) ──────
    step "Step 9/11: Installing Claude Code instructions"
    CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"

    _install_claude_md() {
        local CLAUDE_SRC=""
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

        if [ -n "$CODERAG_ROOT" ] && [ -f "$CODERAG_ROOT/CLAUDE.md" ]; then
            CLAUDE_SRC="$CODERAG_ROOT/CLAUDE.md"
        fi

        if [ -n "$CLAUDE_SRC" ]; then
            cp "$CLAUDE_SRC" "$CLAUDE_MD"
            ok "Installed CLAUDE.md (from: $CLAUDE_SRC)"
        else
            # Fallback: download from GitHub
            info "Local template not found, downloading from GitHub..."
            if curl -fsSL "https://raw.githubusercontent.com/dmnkhorvath/coderag/main/CLAUDE.md"              -o "$CLAUDE_MD" 2>/dev/null; then
                ok "Installed CLAUDE.md (downloaded from GitHub)"
            else
                err "Could not install CLAUDE.md"
                echo "  Download manually:"
                echo "    https://github.com/dmnkhorvath/coderag/blob/main/CLAUDE.md"
                return 1
            fi
        fi
    }

    if [ -f "$CLAUDE_MD" ]; then
        warn "CLAUDE.md already exists at $CLAUDE_MD"
        ask "Overwrite? [y/N]"
        case "$REPLY" in
            [Yy]*) _install_claude_md ;;
            *)     info "Keeping existing CLAUDE.md" ;;
        esac
    else
        _install_claude_md
    fi

    # ── Step 10: Install .mcp.json (MCP server config) ────────────
    step "Step 10/11: Installing MCP server configuration"
    MCP_JSON="$PROJECT_DIR/.mcp.json"

    _install_mcp_json() {
        # Detect coderag binary path
        local CODERAG_BIN
        CODERAG_BIN="$(command -v coderag 2>/dev/null || echo "coderag")"

        cat > "$MCP_JSON" << MCPEOF
{
  "mcpServers": {
    "coderag": {
      "command": "$CODERAG_BIN",
      "args": [
        "serve",
        ".",
        "--watch"
      ],
      "env": {}
    }
  }
}
MCPEOF
        ok "Created .mcp.json (command: $CODERAG_BIN serve . --watch)"
    }

    if [ -f "$MCP_JSON" ]; then
        warn ".mcp.json already exists at $MCP_JSON"
        ask "Overwrite? [y/N]"
        case "$REPLY" in
            [Yy]*) _install_mcp_json ;;
            *)     info "Keeping existing .mcp.json" ;;
        esac
    else
        _install_mcp_json
    fi

    # ── Step 11: Verify MCP server (coderag serve --watch) ────────
    step "Step 11/11: Verifying MCP server"
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
    printf "${GREEN}╔══════════════════════════════════════════════╗${NC}\n"
    printf "${GREEN}║  ${BOLD}Installation Complete!${NC}${GREEN}                        ║${NC}\n"
    printf "${GREEN}╚══════════════════════════════════════════════╝${NC}\n"
    echo ""
    printf "  ${BOLD}Files created:${NC}\n"
    [ -f "$CONFIG_FILE" ]  && echo "    ✓ codegraph.yaml           — configuration"
    [ -f "$DB_PATH" ]      && echo "    ✓ .codegraph/graph.db      — knowledge graph"
    [ -f "$SKILL_MD" ]     && echo "    ✓ .coderag/skill/SKILL.md  — AI skill"
    [ -L "$PROJECT_DIR/SKILL.md" ] && echo "    ✓ SKILL.md                 — symlink"
    [ -f "$GLOBAL_SKILL_MD" ]  && echo "    ✓ ~/.claude/skills/coderag — global skill"
    [ -L "$HOME/.claude/coderag-SKILL.md" ] && echo "    ✓ ~/.claude/coderag-SKILL.md — global symlink"
    [ -f "$CLAUDE_MD" ]    && echo "    ✓ CLAUDE.md                — Claude Code instructions"
    [ -f "$MCP_JSON" ]     && echo "    ✓ .mcp.json                — MCP server config"
    echo ""
    printf "  ${BOLD}CLI commands used (all from SKILL.md):${NC}\n"
    echo "    coderag init              → created config"
    echo "    coderag parse             → built knowledge graph"
    echo "    coderag validate          → verified configuration"
    echo "    coderag info              → displayed statistics"
    echo "    coderag embed             → semantic embeddings"
    echo "    coderag serve --watch     → MCP server + file watcher"
    echo ""
    printf "  ${BOLD}Start serving:${NC}\n"
    echo "    coderag serve $PROJECT_DIR --watch"
    echo ""
    printf "  ${BOLD}Other useful commands:${NC}\n"
    echo "    coderag parse $PROJECT_DIR --incremental   # re-parse changes"
    echo "    coderag monitor $PROJECT_DIR               # TUI dashboard"
    echo "    coderag architecture $PROJECT_DIR          # architecture overview"
    echo "    coderag search $PROJECT_DIR <query>         # search the graph"
    echo "    coderag find-usages $PROJECT_DIR <symbol>   # find symbol usages"
    echo "    coderag impact $PROJECT_DIR <symbol>        # blast radius analysis"
    echo ""

}

main "$@"
