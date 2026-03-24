# Installation

This guide covers all methods to install CodeRAG on your system.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Required |
| pip | latest | Comes with Python |
| git | any | For cloning and git enrichment |
| C compiler | gcc/clang | For Tree-sitter grammar compilation |

### Platform-specific setup

<details>
<summary><strong>Ubuntu / Debian</strong></summary>

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip git build-essential
```
</details>

<details>
<summary><strong>Fedora / RHEL</strong></summary>

```bash
sudo dnf install python3.11 python3-pip git gcc gcc-c++
```
</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
brew install python@3.11 git
```
</details>

---

## Method 1: One-Line Installer (Recommended)

The fastest way to get started:

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install.sh | sh
```

This will:
1. Detect your OS and architecture
2. Find a compatible Python (≥3.11)
3. Clone the repository to `~/.coderag/src`
4. Create a virtual environment at `~/.coderag/venv`
5. Install CodeRAG with all dependencies
6. Add `coderag` to your PATH

### Environment overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `CODERAG_INSTALL_DIR` | `~/.coderag` | Custom install location |
| `CODERAG_BRANCH` | `main` | Git branch to install from |

Example with custom install directory:
```bash
CODERAG_INSTALL_DIR=/opt/coderag curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install.sh | sh
```

### Updating

After installing with the one-liner, update with:
```bash
coderag-update
```

Or manually:
```bash
sh ~/.coderag/src/update.sh
```

### Uninstalling

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/uninstall.sh | sh
```

Or manually:
```bash
sh ~/.coderag/src/uninstall.sh
```

---

## Project Setup

After installing CodeRAG, use `install-coderag.sh` to set up a specific project. This script performs a complete 10-step setup:

| Step | Action | Description |
|------|--------|-------------|
| 1 | Verify installation | Confirms `coderag` binary is available |
| 2 | `coderag init` | Generates `codegraph.yaml` configuration |
| 3 | `coderag parse` | Builds the knowledge graph (`.codegraph/graph.db`) |
| 4 | `coderag validate` | Validates configuration and environment |
| 5 | `coderag info` | Displays codebase statistics |
| 6 | `coderag embed` | Generates semantic embeddings (optional) |
| 7 | Install `SKILL.md` | Places OpenSkill file at `.coderag/skill/SKILL.md` with root symlink |
| 8 | Install `CLAUDE.md` | Installs Claude Code project instructions (3-tier source: local → GitHub → error) |
| 9 | Generate `.mcp.json` | Auto-detects binary path, configures MCP server with `--watch` flag |
| 10 | Verify MCP server | Confirms `coderag serve --watch` starts correctly |

### Usage

```bash
curl -fsSL https://raw.githubusercontent.com/dmnkhorvath/coderag-cli/main/install-coderag.sh | sh -s /path/to/your/project
```

> **Generated files:** `codegraph.yaml`, `.codegraph/graph.db`, `.coderag/skill/SKILL.md`, `SKILL.md` (symlink), `CLAUDE.md`, `.mcp.json`

## Method 2: pip install (Development)

For development or if you want more control:

```bash
# Clone the repository
git clone https://github.com/dmnkhorvath/coderag-cli.git
cd coderag

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Verify installation
coderag --help
```

### Development dependencies

To install with test and lint tools:
```bash
pip install -e ".[dev]"
```

---

## Method 3: pip install from GitHub

Install directly without cloning:

```bash
pip install git+https://github.com/dmnkhorvath/coderag-cli.git
```

---

## Verify Installation

After any installation method, verify it works:

```bash
# Check version and help
coderag --help

# Initialize a test project
mkdir /tmp/test-project && cd /tmp/test-project
coderag init --languages php,javascript --name test-project

# Parse a codebase (use any project with PHP/JS/TS files)
coderag parse /path/to/your/project

# View the knowledge graph
coderag info /path/to/your/project
```

Expected output from `coderag --help`:
```
Usage: coderag [OPTIONS] COMMAND [ARGS]...

  CodeRAG - Build knowledge graphs from your codebase

Options:
  -c, --config PATH   Path to codegraph.yaml
  --db PATH           Override database path
  -v, --verbose       Increase verbosity
  --help              Show this message and exit.

Commands:
  analyze         Run graph analysis algorithms
  architecture    Generate architecture overview
  cross-language  Analyze cross-language connections
  enrich          Enrich graph with additional metadata
  export          Export knowledge graph data
  frameworks      Detect framework usage
  info            Display knowledge graph statistics
  init            Initialize codegraph.yaml configuration
  parse           Parse codebase and build knowledge graph
  query           Query the knowledge graph
  serve           Start MCP server for LLM integration
```

---

## Troubleshooting

### `command not found: coderag`

The installer adds `~/.coderag/bin` to your PATH. Restart your terminal or run:
```bash
source ~/.bashrc   # or ~/.zshrc
```

### Tree-sitter compilation errors

Ensure you have a C compiler installed:
```bash
# Ubuntu/Debian
sudo apt install build-essential

# macOS
xcode-select --install
```

### Python version too old

CodeRAG requires Python 3.11+. Check your version:
```bash
python3 --version
```

Install a newer version using your package manager or [pyenv](https://github.com/pyenv/pyenv):
```bash
curl https://pyenv.run | bash
pyenv install 3.12
pyenv global 3.12
```

### Permission denied during install

The installer does not require root. If you see permission errors, ensure you're not running with `sudo` and that `~/.coderag` is writable.
