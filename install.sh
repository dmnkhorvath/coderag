#!/bin/sh
# CodeRAG Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install.sh | sh
#
# Environment variables:
#   CODERAG_INSTALL_DIR  - Override install location (default: ~/.coderag)
#   CODERAG_BRANCH       - Git branch to install (default: main)
#   CODERAG_MINIMAL      - Set to "true" for core-only install without
#                          optional dependencies like TUI monitor and
#                          semantic search (default: false)

set -e

# ─── Constants ────────────────────────────────────────────────────────────────

REPO_URL="https://github.com/dmnkhorvath/coderag-cli.git"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
DEFAULT_INSTALL_DIR="$HOME/.coderag"
BRANCH="${CODERAG_BRANCH:-main}"
MINIMAL="${CODERAG_MINIMAL:-false}"

# ─── Terminal Colors ──────────────────────────────────────────────────────────

setup_colors() {
    if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
        BOLD=$(tput bold 2>/dev/null || printf '')
        DIM=$(tput dim 2>/dev/null || printf '')
        RED=$(tput setaf 1 2>/dev/null || printf '')
        GREEN=$(tput setaf 2 2>/dev/null || printf '')
        YELLOW=$(tput setaf 3 2>/dev/null || printf '')
        BLUE=$(tput setaf 4 2>/dev/null || printf '')
        MAGENTA=$(tput setaf 5 2>/dev/null || printf '')
        CYAN=$(tput setaf 6 2>/dev/null || printf '')
        RESET=$(tput sgr0 2>/dev/null || printf '')
    else
        BOLD='' DIM='' RED='' GREEN='' YELLOW=''
        BLUE='' MAGENTA='' CYAN='' RESET=''
    fi
}

# ─── Output Helpers ───────────────────────────────────────────────────────────

info()    { printf "%s\n" "${CYAN}info${RESET}  $*"; }
success() { printf "%s\n" "${GREEN}  ✓${RESET}  $*"; }
warn()    { printf "%s\n" "${YELLOW}warn${RESET}  $*"; }
err()     { printf "%s\n" "${RED}error${RESET} $*" >&2; }

abort() {
    err "$@"
    err "Installation failed. For help, visit:"
    err "  https://github.com/dmnkhorvath/coderag-cli/issues"
    exit 1
}

# ─── Cleanup Trap ─────────────────────────────────────────────────────────────

cleanup() {
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        err ""
        err "Installation did not complete successfully."
        if [ -d "$INSTALL_DIR" ] && [ "$FRESH_INSTALL" = "true" ]; then
            err "Cleaning up partial installation..."
            rm -rf "$INSTALL_DIR"
        fi
    fi
    exit $exit_code
}
trap cleanup EXIT

# ─── OS / Arch Detection ─────────────────────────────────────────────────────

detect_platform() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Linux*)  OS="linux" ;;
        Darwin*) OS="macos" ;;
        *)       abort "Unsupported operating system: $OS" ;;
    esac

    case "$ARCH" in
        x86_64|amd64)  ARCH="x86_64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *)             warn "Unusual architecture: $ARCH (proceeding anyway)" ;;
    esac

    info "Detected platform: ${BOLD}${OS}/${ARCH}${RESET}"
}

# ─── Dependency Checks ───────────────────────────────────────────────────────

check_command() {
    command -v "$1" >/dev/null 2>&1
}

suggest_python_install() {
    err "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required but was not found."
    err ""
    case "$OS" in
        linux)
            if check_command apt-get; then
                err "Install with apt (Ubuntu/Debian):"
                err "  ${BOLD}sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip${RESET}"
            elif check_command dnf; then
                err "Install with dnf (Fedora/RHEL):"
                err "  ${BOLD}sudo dnf install python3.11${RESET}"
            elif check_command pacman; then
                err "Install with pacman (Arch):"
                err "  ${BOLD}sudo pacman -S python${RESET}"
            elif check_command apk; then
                err "Install with apk (Alpine):"
                err "  ${BOLD}sudo apk add python3 py3-pip${RESET}"
            else
                err "Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ from:"
                err "  https://www.python.org/downloads/"
            fi
            ;;
        macos)
            if check_command brew; then
                err "Install with Homebrew:"
                err "  ${BOLD}brew install python@3.12${RESET}"
            else
                err "Install Homebrew first:"
                err "  ${BOLD}/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${RESET}"
                err "Then:"
                err "  ${BOLD}brew install python@3.12${RESET}"
            fi
            ;;
    esac
    exit 1
}

# Check Python version meets minimum requirement
# Usage: check_python_version /path/to/python
# Returns 0 if version >= MIN_PYTHON_MAJOR.MIN_PYTHON_MINOR
check_python_version() {
    _py="$1"
    _version=$($_py -c "import sys; v=sys.version_info; print(str(v.major)+'.'+str(v.minor))" 2>/dev/null) || return 1
    _major=$(printf "%s" "$_version" | cut -d. -f1)
    _minor=$(printf "%s" "$_version" | cut -d. -f2)

    if [ "$_major" -gt "$MIN_PYTHON_MAJOR" ] 2>/dev/null; then
        return 0
    elif [ "$_major" -eq "$MIN_PYTHON_MAJOR" ] && [ "$_minor" -ge "$MIN_PYTHON_MINOR" ] 2>/dev/null; then
        return 0
    fi
    return 1
}

find_python() {
    # Try specific versions first (highest to lowest), then generic names
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if check_command "$candidate" && check_python_version "$candidate"; then
            PYTHON="$(command -v "$candidate")"
            PYTHON_VERSION=$($PYTHON -c "import sys; v=sys.version_info; print(str(v.major)+'.'+str(v.minor)+'.'+str(v.micro))")
            success "Found Python ${BOLD}${PYTHON_VERSION}${RESET} at ${DIM}${PYTHON}${RESET}"
            return 0
        fi
    done
    return 1
}

check_git() {
    if ! check_command git; then
        err "git is required but was not found."
        case "$OS" in
            linux)
                if check_command apt-get; then
                    err "  ${BOLD}sudo apt install git${RESET}"
                elif check_command dnf; then
                    err "  ${BOLD}sudo dnf install git${RESET}"
                fi
                ;;
            macos)
                err "  ${BOLD}xcode-select --install${RESET}"
                ;;
        esac
        exit 1
    fi
    success "Found git $(git --version | cut -d' ' -f3)"
}

check_dependencies() {
    info "Checking dependencies..."
    check_git
    if ! find_python; then
        suggest_python_install
    fi
}

# ─── Installation ─────────────────────────────────────────────────────────────

install_coderag() {
    INSTALL_DIR="${CODERAG_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
    SRC_DIR="$INSTALL_DIR/src"
    VENV_DIR="$INSTALL_DIR/venv"
    BIN_DIR="$INSTALL_DIR/bin"
    FRESH_INSTALL="false"

    printf "\n"
    info "Installing to ${BOLD}${INSTALL_DIR}${RESET}"

    # Handle existing installation
    if [ -d "$INSTALL_DIR" ]; then
        if [ -d "$SRC_DIR/.git" ]; then
            warn "Existing installation found. Updating..."
            cd "$SRC_DIR"
            git fetch origin "$BRANCH" --quiet
            git reset --hard "origin/$BRANCH" --quiet
            success "Source updated"
        else
            warn "Directory exists but is not a valid installation. Removing..."
            rm -rf "$INSTALL_DIR"
            FRESH_INSTALL="true"
        fi
    else
        FRESH_INSTALL="true"
    fi

    # Clone repository
    if [ "$FRESH_INSTALL" = "true" ]; then
        mkdir -p "$INSTALL_DIR"
        info "Cloning repository..."
        git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR" --quiet 2>/dev/null || \
            git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR"
        success "Repository cloned"
    fi

    # Create virtual environment
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment..."
        "$PYTHON" -m venv "$VENV_DIR" || abort "Failed to create virtual environment. Ensure python3-venv is installed."
        success "Virtual environment created"
    fi

    # Install package
    info "Installing CodeRAG and dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>/dev/null
    if [ "$MINIMAL" = "true" ]; then
        info "Minimal install (core only — no TUI monitor or semantic search)"
        "$VENV_DIR/bin/pip" install -e "$SRC_DIR" --quiet 2>/dev/null || \
            "$VENV_DIR/bin/pip" install -e "$SRC_DIR"
    else
        info "Full install (includes TUI monitor and semantic search)"
        "$VENV_DIR/bin/pip" install -e "$SRC_DIR[full]" --quiet 2>/dev/null || \
            "$VENV_DIR/bin/pip" install -e "$SRC_DIR[full]"
    fi
    success "Package installed"

    # Create bin directory and wrapper scripts
    mkdir -p "$BIN_DIR"

    # Main CLI wrapper
    cat > "$BIN_DIR/coderag" << WRAPPER
#!/bin/sh
# CodeRAG CLI wrapper — auto-activates the virtual environment
set -e
exec "$VENV_DIR/bin/coderag" "\$@"
WRAPPER
    chmod +x "$BIN_DIR/coderag"

    # Update wrapper
    cat > "$BIN_DIR/coderag-update" << WRAPPER
#!/bin/sh
# CodeRAG updater — pulls latest changes and reinstalls
set -e
exec sh "$SRC_DIR/update.sh"
WRAPPER
    chmod +x "$BIN_DIR/coderag-update"

    success "CLI wrappers created"
}

# ─── PATH Configuration ──────────────────────────────────────────────────────

configure_path() {
    BIN_DIR="$INSTALL_DIR/bin"
    PATH_LINE="export PATH=\"$BIN_DIR:\$PATH\""
    MARKER="# CodeRAG"
    SHELL_BLOCK="\n${MARKER}\n${PATH_LINE}\n"

    # Check if already in PATH
    case ":$PATH:" in
        *":$BIN_DIR:"*)
            success "PATH already configured"
            return 0
            ;;
    esac

    info "Configuring PATH..."

    UPDATED_SHELLS=""

    for rcfile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if [ -f "$rcfile" ]; then
            # Skip if already present
            if grep -qF "$MARKER" "$rcfile" 2>/dev/null; then
                continue
            fi
            printf "%b" "$SHELL_BLOCK" >> "$rcfile"
            UPDATED_SHELLS="$UPDATED_SHELLS $(basename "$rcfile")"
        fi
    done

    # If no rc files exist, create .profile
    if [ -z "$UPDATED_SHELLS" ]; then
        printf "%b" "$SHELL_BLOCK" >> "$HOME/.profile"
        UPDATED_SHELLS=".profile (created)"
    fi

    success "Updated:${UPDATED_SHELLS}"
}

# ─── Verification ─────────────────────────────────────────────────────────────

verify_installation() {
    info "Verifying installation..."
    CODERAG_VERSION=$("$INSTALL_DIR/venv/bin/pip" show coderag 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
    if [ -x "$INSTALL_DIR/bin/coderag" ] && [ -x "$INSTALL_DIR/venv/bin/coderag" ]; then
        if "$INSTALL_DIR/bin/coderag" --help >/dev/null 2>&1; then
            success "CodeRAG ${CODERAG_VERSION:-} is working"
        else
            warn "CLI installed but returned an error (possibly missing optional dependencies)"
            warn "Try running: ${BOLD}coderag --help${RESET} after restarting your terminal"
        fi
    else
        warn "CLI wrapper was not created correctly"
    fi
}

# ─── Summary ──────────────────────────────────────────────────────────────────

print_summary() {
    printf "\n"
    printf "%s\n" "${GREEN}${BOLD}  ✨ CodeRAG ${CODERAG_VERSION:-0.1.0} installed successfully!${RESET}"
    printf "\n"
    printf "%s\n" "  ${DIM}Location:${RESET}  $INSTALL_DIR"
    printf "%s\n" "  ${DIM}Python:${RESET}    $PYTHON_VERSION"
    if [ "$MINIMAL" = "true" ]; then
        printf "%s\n" "  ${DIM}Install:${RESET}   minimal (core only)"
        printf "%s\n" "  ${DIM}Tip:${RESET}       Reinstall with full deps: ${BOLD}CODERAG_MINIMAL=false sh install.sh${RESET}"
    else
        printf "%s\n" "  ${DIM}Install:${RESET}   full (all features)"
    fi
    printf "\n"
    printf "%s\n" "  ${BOLD}Get started:${RESET}"
    printf "\n"

    # Check if we need to reload shell
    case ":$PATH:" in
        *":$BIN_DIR:"*)
            ;;
        *)
            printf "%s\n" "    ${YELLOW}Restart your terminal or run:${RESET}"
            printf "%s\n" "    ${BOLD}  source ~/.bashrc${RESET}  ${DIM}(or ~/.zshrc)${RESET}"
            printf "\n"
            ;;
    esac

    printf "%s\n" "    ${CYAN}# Parse a codebase${RESET}"
    printf "%s\n" "    ${BOLD}coderag parse /path/to/project --full${RESET}"
    printf "\n"
    printf "%s\n" "    ${CYAN}# View graph statistics${RESET}"
    printf "%s\n" "    ${BOLD}coderag info${RESET}"
    printf "\n"
    printf "%s\n" "    ${CYAN}# Search for symbols${RESET}"
    printf "%s\n" "    ${BOLD}coderag query \"UserController\"${RESET}"
    printf "\n"
    printf "%s\n" "  ${DIM}Update:${RESET}    coderag-update"
    printf "%s\n" "  ${DIM}Uninstall:${RESET} curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/uninstall.sh | sh"
    printf "%s\n" "  ${DIM}Docs:${RESET}      https://github.com/dmnkhorvath/coderag-cli"
    printf "\n"
}

# ─── Banner ───────────────────────────────────────────────────────────────────

print_banner() {
    printf "\n"
    printf "%s\n" "${BOLD}${MAGENTA}   ██████╗ ██████╗ ██████╗ ███████╗${CYAN}██████╗  █████╗  ██████╗${RESET}"
    printf "%s\n" "${BOLD}${MAGENTA}  ██╔════╝██╔═══██╗██╔══██╗██╔════╝${CYAN}██╔══██╗██╔══██╗██╔════╝${RESET}"
    printf "%s\n" "${BOLD}${MAGENTA}  ██║     ██║   ██║██║  ██║█████╗  ${CYAN}██████╔╝███████║██║  ███╗${RESET}"
    printf "%s\n" "${BOLD}${MAGENTA}  ██║     ██║   ██║██║  ██║██╔══╝  ${CYAN}██╔══██╗██╔══██║██║   ██║${RESET}"
    printf "%s\n" "${BOLD}${MAGENTA}  ╚██████╗╚██████╔╝██████╔╝███████╗${CYAN}██║  ██║██║  ██║╚██████╔╝${RESET}"
    printf "%s\n" "${BOLD}${MAGENTA}   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝${CYAN}╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝${RESET}"
    printf "\n"
    printf "%s\n" "  ${DIM}Knowledge graphs for codebases · PHP · JavaScript · TypeScript${RESET}"
    printf "\n"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    setup_colors
    print_banner
    detect_platform
    check_dependencies
    install_coderag
    configure_path
    verify_installation
    print_summary
}

main "$@"
