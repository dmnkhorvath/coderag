#!/bin/sh
# CodeRAG Uninstaller
# Usage: curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag/main/uninstall.sh | sh

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

# ─── PATH Cleanup ─────────────────────────────────────────────────────────────

remove_path_entries() {
    INSTALL_DIR="$1"
    MARKER="# CodeRAG"

    info "Cleaning shell configuration files..."

    for rcfile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$rcfile" ]; then
            if grep -qF "$MARKER" "$rcfile" 2>/dev/null; then
                # Remove the CodeRAG block (marker line + export line + surrounding blank lines)
                # Use a temp file for POSIX compatibility
                tmpfile=$(mktemp)
                sed '/# CodeRAG/d; /\.coderag\/bin/d' "$rcfile" > "$tmpfile"
                mv "$tmpfile" "$rcfile"
                success "Cleaned $(basename "$rcfile")"
            fi
        fi
    done
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    setup_colors

    printf "\n"
    printf "%s\n" "${BOLD}${CYAN}  CodeRAG Uninstaller${RESET}"
    printf "\n"

    INSTALL_DIR="${CODERAG_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

    if [ ! -d "$INSTALL_DIR" ]; then
        info "No installation found at ${BOLD}${INSTALL_DIR}${RESET}"
        info "Nothing to uninstall."
        printf "\n"
        exit 0
    fi

    # Show what will be removed
    info "This will remove:"
    printf "%s\n" "    ${DIM}•${RESET} $INSTALL_DIR  ${DIM}(source, venv, binaries)${RESET}"
    printf "%s\n" "    ${DIM}•${RESET} PATH entries from shell configs"
    printf "\n"

    # Prompt for confirmation (skip if piped)
    if [ -t 0 ]; then
        printf "%s" "  ${BOLD}Proceed? [y/N]${RESET} "
        read -r REPLY
        case "$REPLY" in
            [yY]|[yY][eE][sS]) ;;
            *)
                info "Uninstall cancelled."
                exit 0
                ;;
        esac
    fi

    # Remove PATH entries from shell configs
    remove_path_entries "$INSTALL_DIR"

    # Remove installation directory
    info "Removing ${BOLD}${INSTALL_DIR}${RESET}..."
    rm -rf "$INSTALL_DIR"
    success "Installation directory removed"

    printf "\n"
    printf "%s\n" "${GREEN}${BOLD}  ✓ CodeRAG has been uninstalled.${RESET}"
    printf "\n"
    printf "%s\n" "  ${DIM}Restart your terminal to apply PATH changes.${RESET}"
    printf "%s\n" "  ${DIM}Thanks for trying CodeRAG!${RESET}"
    printf "\n"
}

main "$@"
