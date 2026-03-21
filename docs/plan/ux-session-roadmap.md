# CodeRAG — UX & Session Intelligence Roadmap

> **Inspired by:** [Dual-Graph (Codex-CLI-Compact)](https://github.com/kunal12203/Codex-CLI-Compact)
> **Created:** 2026-03-21
> **Status:** Planning
> **Goal:** Close the UX gap between CodeRAG's deep analysis engine and Dual-Graph's developer experience

---

## Executive Summary

CodeRAG has superior technical depth (41 node types, 50 edge types, 11 framework detectors, 6 languages, 3,100+ tests). However, Dual-Graph demonstrates that **developer experience and measurable cost savings** drive adoption more than raw capability. This roadmap addresses four key gaps:

| # | Gap | Dual-Graph Has | CodeRAG Needs |
|---|-----|---------------|---------------|
| 1 | **Launcher UX** | `dgc /path` → instant Claude session | Multi-step setup, no launcher |
| 2 | **Cost Benchmarking** | 80+ prompt benchmarks with $ savings | Parse accuracy benchmarks only |
| 3 | **Session Memory** | Cross-session context persistence | Stateless per-parse |
| 4 | **Auto-Update** | Self-updating on every launch | Manual `git pull` + `pip install` |

---

## Phase 1: Smart Launcher (Priority: HIGH)

**Goal:** One command to scan a project and launch an AI coding session with pre-loaded context.

**Timeline:** 3-4 days

### 1.1 — `coderag launch` Command

New CLI command that orchestrates the full workflow:

```bash
# Basic usage — parse + launch Claude Code with MCP
coderag launch /path/to/project

# With initial prompt
coderag launch /path/to/project "fix the login bug"

# Choose AI tool
coderag launch /path/to/project --tool claude-code
coderag launch /path/to/project --tool cursor
coderag launch /path/to/project --tool codex

# Short alias
cr /path/to/project
```

### 1.2 — What `launch` Does Internally

```
User runs: coderag launch /path/to/project "fix login bug"
                    ↓
1. Check if graph exists → if not, run `coderag parse` (with progress bar)
2. Check if graph is stale → if yes, run incremental update
3. Start MCP server in background (stdio or SSE)
4. Generate context pre-load:
   a. Run graph analysis (PageRank top-20 files)
   b. If prompt given, run semantic search for relevant symbols
   c. Build markdown context summary (token-budgeted)
5. Configure AI tool:
   a. Claude Code: write `.claude/settings.local.json` with MCP config
   b. Cursor: write `.cursor/mcp.json`
   c. Codex: write `codex.json` or pass via CLI args
6. Launch AI tool with pre-loaded context
7. Monitor session (optional: token tracking)
```

### 1.3 — Implementation Tasks

| Task | File | Lines (est.) | Description |
|------|------|-------------|-------------|
| 1.3.1 | `src/coderag/cli/launch.py` | ~300 | New Click command with tool detection, parse orchestration |
| 1.3.2 | `src/coderag/session/preloader.py` | ~200 | Context pre-loading: PageRank top files, semantic search if prompt given |
| 1.3.3 | `src/coderag/session/tool_config.py` | ~250 | AI tool configuration writers (Claude Code, Cursor, Codex) |
| 1.3.4 | `bin/cr` | ~20 | Short alias launcher script (POSIX shell) |
| 1.3.5 | `tests/test_launch.py` | ~200 | Unit tests for launch workflow |

### 1.4 — AI Tool Configuration Templates

**Claude Code** (`.claude/settings.local.json`):
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "--project", "/path/to/project"],
      "env": {}
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "coderag": {
      "command": "coderag",
      "args": ["serve", "--project", "/path/to/project"]
    }
  }
}
```

### 1.5 — Acceptance Criteria

- [ ] `coderag launch .` works from any project directory
- [ ] Auto-detects installed AI tools (claude, cursor, codex)
- [ ] First run: parses project, configures MCP, launches tool in <30s for small projects
- [ ] Subsequent runs: skips parse if graph is fresh, launches in <3s
- [ ] `cr` alias works after install
- [ ] Pre-loaded context includes top-20 most important files by PageRank

---

## Phase 2: Session Memory & Context Persistence (Priority: HIGH)

**Goal:** Remember what was read, edited, and queried across sessions so context compounds over time.

**Timeline:** 4-5 days

### 2.1 — Session Data Model

```python
@dataclass
class SessionEvent:
    """A single event in a coding session."""
    timestamp: datetime
    event_type: str  # "read", "edit", "query", "decision", "task"
    target: str      # file path, symbol name, or query text
    metadata: dict   # extra context (e.g., line range, query results)
    session_id: str  # groups events into sessions

@dataclass
class SessionMemory:
    """Persistent memory across coding sessions."""
    project_root: str
    sessions: list[SessionEvent]
    decisions: list[dict]     # architectural decisions made
    tasks: list[dict]         # tasks identified/completed
    facts: list[dict]         # facts learned about the codebase
    hot_files: dict[str, int] # file → access count (for prioritization)
```

### 2.2 — Storage

New SQLite tables in the existing `.codegraph/graph.db`:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    tool TEXT,           -- "claude-code", "cursor", "codex"
    prompt TEXT,         -- initial prompt if any
    total_events INTEGER DEFAULT 0
);

CREATE TABLE session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- read, edit, query, decision, task, fact
    target TEXT NOT NULL,
    metadata TEXT,             -- JSON
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE context_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,    -- "decision", "task", "fact"
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    session_id TEXT,
    active INTEGER DEFAULT 1
);

CREATE INDEX idx_events_session ON session_events(session_id);
CREATE INDEX idx_events_type ON session_events(event_type);
CREATE INDEX idx_events_target ON session_events(target);
CREATE INDEX idx_context_category ON context_store(category);
```

### 2.3 — MCP Tools for Session Tracking

New MCP tools that AI coding assistants can call:

| Tool | Description |
|------|-------------|
| `session_log_read` | Log that a file was read (AI calls this when it reads a file) |
| `session_log_edit` | Log that a file was edited |
| `session_log_decision` | Record an architectural decision |
| `session_log_task` | Record a task (identified or completed) |
| `session_log_fact` | Record a fact about the codebase |
| `session_get_history` | Get recent session history for context |
| `session_get_hot_files` | Get most frequently accessed files |
| `session_get_context` | Get persisted decisions/tasks/facts |

### 2.4 — Context Injection

On session start, automatically inject into the AI's context:

```markdown
## Session Context (from previous sessions)

### Recent Activity (last 3 sessions)
- Edited: src/auth/login.py (3 sessions ago, 12 edits total)
- Edited: src/models/user.py (2 sessions ago, 8 edits total)
- Queried: "authentication flow" (last session)

### Hot Files (most accessed)
1. src/auth/login.py — 23 reads, 12 edits
2. src/models/user.py — 18 reads, 8 edits
3. src/api/routes.py — 15 reads, 3 edits

### Decisions
- [2026-03-20] Use JWT tokens instead of session cookies for API auth
- [2026-03-19] Migrate from SQLite to PostgreSQL for production

### Open Tasks
- [ ] Add rate limiting to login endpoint
- [ ] Write tests for password reset flow
```

### 2.5 — Implementation Tasks

| Task | File | Lines (est.) | Description |
|------|------|-------------|-------------|
| 2.5.1 | `src/coderag/session/__init__.py` | ~10 | Module init |
| 2.5.2 | `src/coderag/session/models.py` | ~80 | Data models for sessions, events, context |
| 2.5.3 | `src/coderag/session/store.py` | ~250 | SQLite storage for session data |
| 2.5.4 | `src/coderag/session/tracker.py` | ~150 | Event tracking and hot file computation |
| 2.5.5 | `src/coderag/session/injector.py` | ~200 | Context injection markdown generator |
| 2.5.6 | `src/coderag/mcp/session_tools.py` | ~300 | 8 new MCP tools for session tracking |
| 2.5.7 | `tests/test_session.py` | ~400 | Comprehensive tests |

### 2.6 — Acceptance Criteria

- [ ] Session events are persisted to SQLite
- [ ] Hot files are computed from access history
- [ ] Decisions/tasks/facts survive across sessions
- [ ] Context injection produces token-budgeted markdown
- [ ] MCP tools allow AI to log reads/edits/decisions
- [ ] `coderag launch` injects session context automatically

---

## Phase 3: Token Cost Benchmarking (Priority: MEDIUM)

**Goal:** Measure and prove that CodeRAG reduces AI coding costs, not just parse accuracy.

**Timeline:** 3-4 days

### 3.1 — Token Tracking System

Integrate token counting into the MCP server to measure:
- Tokens saved by pre-loading context (vs. AI exploring on its own)
- Tokens per turn with/without CodeRAG
- Cumulative session cost

### 3.2 — Token Counter Module

```python
class TokenTracker:
    """Track token usage across a coding session."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self.events: list[TokenEvent] = []

    def log_context_injection(self, text: str) -> TokenEvent:
        """Log tokens used for pre-loaded context."""

    def log_tool_call(self, tool: str, input_text: str, output_text: str) -> TokenEvent:
        """Log tokens used for an MCP tool call."""

    def log_turn(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> TokenEvent:
        """Log a full conversation turn."""

    def get_session_stats(self) -> SessionStats:
        """Get running session statistics."""
        # Returns: total_tokens, total_cost, avg_tokens_per_turn,
        #          tokens_saved_by_preload, estimated_savings_pct

    def get_cost_comparison(self) -> CostComparison:
        """Compare with/without CodeRAG estimates."""
```

### 3.3 — Benchmark Framework

Automated benchmark suite that measures cost savings:

```bash
# Run cost benchmark against a project
coderag benchmark /path/to/project --prompts prompts.json --model claude-sonnet

# Output:
# ┌─────────────────────────────────────────────────────┐
# │ CodeRAG Cost Benchmark — my-project                 │
# ├─────────────────┬──────────────┬───────────────────┤
# │ Metric          │ Without      │ With CodeRAG      │
# ├─────────────────┼──────────────┼───────────────────┤
# │ Avg tokens/turn │ 12,400       │ 7,800 (-37%)      │
# │ Avg turns/task  │ 8.2          │ 5.1 (-38%)        │
# │ Avg cost/task   │ $0.42        │ $0.24 (-43%)      │
# │ Context hits    │ N/A          │ 89% (pre-loaded)  │
# │ Quality score   │ 81/100       │ 86/100 (+6%)      │
# └─────────────────┴──────────────┴───────────────────┘
```

### 3.4 — Dashboard

Real-time token tracking dashboard (extends existing TUI or web):

```
http://localhost:8899/tokens
```

Shows:
- Running session cost
- Token breakdown (context vs. tool calls vs. conversation)
- Cost savings estimate
- Historical trends across sessions

### 3.5 — Implementation Tasks

| Task | File | Lines (est.) | Description |
|------|------|-------------|-------------|
| 3.5.1 | `src/coderag/session/token_tracker.py` | ~200 | Token counting and cost estimation |
| 3.5.2 | `src/coderag/session/cost_models.py` | ~100 | Pricing models for Claude, GPT-4, etc. |
| 3.5.3 | `src/coderag/cli/benchmark_cost.py` | ~300 | CLI command for cost benchmarking |
| 3.5.4 | `src/coderag/mcp/token_tools.py` | ~150 | MCP tools: count_tokens, get_session_stats |
| 3.5.5 | `src/coderag/dashboard/token_dashboard.py` | ~250 | Web dashboard for token tracking |
| 3.5.6 | `benchmark/cost_prompts.json` | ~100 | Standard benchmark prompts |
| 3.5.7 | `tests/test_token_tracker.py` | ~200 | Tests |

### 3.6 — Acceptance Criteria

- [ ] Token tracker counts input/output/cached tokens per turn
- [ ] Cost estimation supports Claude, GPT-4, Gemini pricing
- [ ] `coderag benchmark` runs automated cost comparison
- [ ] Dashboard shows real-time session cost
- [ ] Benchmark report includes $ savings percentage

---

## Phase 4: Auto-Update System (Priority: MEDIUM)

**Goal:** CodeRAG self-updates on launch, no manual intervention needed.

**Timeline:** 2-3 days

### 4.1 — Update Check on Launch

Every time `coderag launch` or `cr` runs:

```
1. Check current version (from pyproject.toml or __version__)
2. Fetch latest version from GitHub API (cached for 1 hour)
3. If newer version available:
   a. Show notification: "CodeRAG v2.1.0 available (current: v2.0.3)"
   b. If --auto-update enabled: pull + reinstall automatically
   c. If not: show update command
4. Continue with launch
```

### 4.2 — Update Strategies

| Strategy | When | How |
|----------|------|-----|
| **PyPI** (preferred) | After PyPI publishing | `pip install --upgrade coderag` |
| **Git** (development) | Before PyPI | `git pull && pip install -e .` |
| **Binary** (future) | Standalone distribution | Download + replace binary |

### 4.3 — Configuration

```yaml
# In codegraph.yaml or ~/.coderag/config.yaml
update:
  auto_check: true          # Check for updates on launch
  auto_install: false       # Auto-install updates (opt-in)
  channel: stable           # stable | beta | dev
  check_interval: 3600      # Seconds between checks (default: 1 hour)
```

### 4.4 — Implementation Tasks

| Task | File | Lines (est.) | Description |
|------|------|-------------|-------------|
| 4.4.1 | `src/coderag/updater/__init__.py` | ~10 | Module init |
| 4.4.2 | `src/coderag/updater/checker.py` | ~150 | Version check against GitHub/PyPI |
| 4.4.3 | `src/coderag/updater/installer.py` | ~100 | Auto-update execution (pip/git) |
| 4.4.4 | `src/coderag/updater/config.py` | ~50 | Update configuration |
| 4.4.5 | `install.sh` (update) | ~30 | Add auto-update hook to launcher |
| 4.4.6 | `update.sh` (update) | ~20 | Enhance existing update script |
| 4.4.7 | `tests/test_updater.py` | ~150 | Tests |

### 4.5 — Acceptance Criteria

- [ ] Version check runs on every `coderag launch` (cached 1hr)
- [ ] Update notification shown when newer version exists
- [ ] `coderag update` command for manual updates
- [ ] Auto-update opt-in via config
- [ ] Update doesn't break running sessions

---

## Phase 5: Polish & Integration Testing (Priority: LOW)

**Goal:** End-to-end testing of the full workflow with real AI tools.

**Timeline:** 2-3 days

### 5.1 — Integration Tests

| Test | Description |
|------|-------------|
| E2E: Claude Code | `coderag launch` → Claude Code session → verify MCP tools work |
| E2E: Cursor | `coderag launch --tool cursor` → verify MCP config written |
| E2E: Session persistence | Launch → make edits → close → relaunch → verify context injected |
| E2E: Auto-update | Mock newer version → verify notification shown |
| E2E: Cost tracking | Run 5 prompts → verify token counts and cost estimates |

### 5.2 — Documentation

| Document | Description |
|----------|-------------|
| `docs/quickstart.md` | 5-minute getting started guide |
| `docs/session-memory.md` | How session memory works |
| `docs/cost-savings.md` | Benchmark results and methodology |
| `docs/ai-tool-setup.md` | Setup guides for Claude Code, Cursor, Codex |
| `README.md` (update) | Add launcher usage, cost savings section |

### 5.3 — Acceptance Criteria

- [ ] Full E2E test passes with at least one AI tool
- [ ] Documentation covers all new features
- [ ] README updated with new workflow

---

## Summary Timeline

```
Week 1:  Phase 1 (Smart Launcher)         — 3-4 days
Week 2:  Phase 2 (Session Memory)          — 4-5 days
Week 3:  Phase 3 (Cost Benchmarking)       — 3-4 days
Week 3:  Phase 4 (Auto-Update)             — 2-3 days
Week 4:  Phase 5 (Polish & Integration)    — 2-3 days
                                           ─────────
                                Total:     ~15-19 days
```

## Estimated Line Counts

| Phase | New Code | Tests | Total |
|-------|----------|-------|-------|
| Phase 1: Smart Launcher | ~770 | ~200 | ~970 |
| Phase 2: Session Memory | ~990 | ~400 | ~1,390 |
| Phase 3: Cost Benchmarking | ~1,100 | ~200 | ~1,300 |
| Phase 4: Auto-Update | ~340 | ~150 | ~490 |
| Phase 5: Polish | ~100 | ~300 | ~400 |
| **Total** | **~3,300** | **~1,250** | **~4,550** |

This would bring CodeRAG from ~38,000 lines to ~42,500 lines.

---

## Key Design Decisions

### Why not just copy Dual-Graph?
Dual-Graph is a thin wrapper (~51KB bash) that does simple file ranking. CodeRAG's advantage is **deep structural understanding**. The launcher should leverage this:
- Pre-load context based on **PageRank importance**, not just file recency
- Session memory tracks **symbol-level** interactions, not just file reads
- Cost savings come from **precise context** (fewer tokens, higher relevance)

### Session memory vs. Dual-Graph's approach
Dual-Graph stores flat JSON files. CodeRAG should use its existing SQLite infrastructure:
- Queryable session history ("what files did I edit last week?")
- Symbol-level tracking ("how many times was UserController queried?")
- Integration with graph analysis (hot files × PageRank = smart prioritization)

### Auto-update safety
- Never auto-update during an active session
- Always show changelog before updating
- Rollback mechanism if update breaks something
- Respect `--no-update` flag for CI/CD environments
