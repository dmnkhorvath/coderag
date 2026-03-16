#!/bin/sh
# CodeRAG Updater
# Usage: coderag-update
#    or: curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/update.sh | sh

set -e

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_INSTALL_DIR="$HOME/.coderag"

# ─── Terminal Colors ──────────────────────────────────────────────────────────

setup_colors() {
    if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
        BOLD=$(tput bold 2>/dev/null || printf '')
        DIM=$(tput dim 2>/dev/null || printf '')
        RED=$(tput setaf 1 2>/dev/null || printf '')
        GREEN=$(tput setaf 2 2>/dev/null || printf '')
        YELLOW=$(tput setaf 3 2>/dev/null || printf '')
        CYAN=$(tput setaf 6 2>/dev/null || printf '')
        RESET=$(tput sgr0 2>/dev/null || printf '')
    else
        BOLD='' DIM='' RED='' GREEN='' YELLOW='' CYAN='' RESET=''
    fi
}

info()    { printf "%s\n" "${CYAN}info${RESET}  $*"; }
success() { printf "%s\n" "${GREEN}  ✓${RESET}  $*"; }
warn()    { printf "%s\n" "${YELLOW}warn${RESET}  $*"; }
err()     { printf "%s\n" "${RED}error${RESET} $*" >&2; }

abort() {
    err "$@"
    exit 1
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    setup_colors

    printf "\n"
    printf "%s\n" "${BOLD}${CYAN}  CodeRAG Updater${RESET}"
    printf "\n"

    INSTALL_DIR="${CODERAG_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
    SRC_DIR="$INSTALL_DIR/src"
    VENV_DIR="$INSTALL_DIR/venv"

    # Validate installation
    if [ ! -d "$SRC_DIR/.git" ]; then
        abort "CodeRAG installation not found at $INSTALL_DIR"
    fi

    if [ ! -d "$VENV_DIR" ]; then
        abort "Virtual environment not found at $VENV_DIR"
    fi

    cd "$SRC_DIR"

    # Capture current commit for comparison
    BEFORE=$(git rev-parse HEAD 2>/dev/null)

    # Pull latest changes
    info "Fetching latest changes..."
    git fetch origin --quiet

    REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

    if [ "$BEFORE" = "$REMOTE_HEAD" ]; then
        success "Already up to date"
        printf "\n"

        VERSION=$("$VENV_DIR/bin/pip" show coderag 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
        printf "%s\n" "  ${DIM}Current version:${RESET} ${BOLD}${VERSION:-unknown}${RESET}"
        printf "\n"
        exit 0
    fi

    git reset --hard "$REMOTE_HEAD" --quiet
    success "Source updated"

    # Show what changed
    COMMIT_COUNT=$(git rev-list --count "${BEFORE}..HEAD" 2>/dev/null || echo "?")
    printf "\n"
    printf "%s\n" "  ${BOLD}${COMMIT_COUNT} new commit(s):${RESET}"
    printf "\n"
    git log --oneline --no-decorate "${BEFORE}..HEAD" 2>/dev/null | while IFS= read -r line; do
        printf "%s\n" "    ${DIM}•${RESET} $line"
    done
    printf "\n"

    # Reinstall package
    info "Reinstalling package..."
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
    "$VENV_DIR/bin/pip" install -e "$SRC_DIR[full]" --quiet 2>/dev/null || \
        "$VENV_DIR/bin/pip" install -e "$SRC_DIR[full]"
    success "Package reinstalled"

    # Verify
    if "$INSTALL_DIR/bin/coderag" --help >/dev/null 2>&1; then
        success "Verification passed"
    else
        warn "Verification failed — coderag command may not work correctly"
    fi

    VERSION=$("$VENV_DIR/bin/pip" show coderag 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
    printf "\n"
    printf "%s\n" "${GREEN}${BOLD}  ✨ CodeRAG updated to ${VERSION:-latest}!${RESET}"
    printf "\n"
}

main "$@"
