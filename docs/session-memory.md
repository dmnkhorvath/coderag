# 🧠 Session Memory Guide

Session Memory gives CodeRAG the ability to remember what happened across AI coding sessions. It tracks file reads, edits, queries, decisions, tasks, and facts — then injects the most relevant context into future sessions.

## What Session Memory Tracks

Session Memory records 6 types of events:

| Event Type | Description | Example |
|------------|-------------|--------|
| **read** | File was read/viewed | `src/App.php` |
| **edit** | File was modified | `src/Routing/Router.php` |
| **query** | Symbol was searched | `UserController` |
| **decision** | Architectural decision made | "Use regex-based route matching" |
| **task** | Task created or updated | "Add unit tests for Router" |
| **fact** | Learned fact about the codebase | "Auth uses JWT tokens" |

## How It Works

Session Memory uses SQLite tables stored in the same `.codegraph/graph.db` database as the knowledge graph. This means session data lives alongside your code graph — no extra files or services needed.

### Storage Schema

Three tables manage session data:

- **`sessions`** — Tracks individual coding sessions (start time, end time, tool used, prompt)
- **`session_events`** — Stores all events with timestamps, types, targets, and metadata
- **`context_store`** — Persists decisions, tasks, and facts across sessions

Four indexes ensure fast lookups by session ID, event type, target, and context category.

### Session Lifecycle

1. **Start**: A new session is created when an AI tool connects (via MCP) or when `coderag launch` runs
2. **Track**: Events are logged as the AI reads files, makes edits, and records decisions
3. **End**: The session is closed with a summary of total events
4. **Persist**: Decisions, tasks, and facts survive across sessions in the context store

## CLI Commands

### `coderag session list`

List recent coding sessions:

```bash
coderag session list
coderag session list -n 20  # Show last 20 sessions
```

Output shows session ID, start time, tool used, prompt, and event count.

### `coderag session show <session-id>`

Show details for a specific session:

```bash
coderag session show abc123
```

Displays all events in the session with timestamps and details.

### `coderag session context`

Show persisted context (decisions, tasks, facts):

```bash
# Show all context
coderag session context

# Filter by category
coderag session context -c decision
coderag session context -c task
coderag session context -c fact
```

## MCP Tools for AI Assistants

Session Memory exposes 8 MCP tools that AI assistants call automatically:

### Logging Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `session_log_read` | Log a file read | `file_path` |
| `session_log_edit` | Log a file edit | `file_path`, `description` |
| `session_log_decision` | Record a decision | `decision`, `rationale` |
| `session_log_task` | Create/update a task | `task`, `status` (open/done) |
| `session_log_fact` | Record a learned fact | `fact`, `source` |

### Query Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `session_get_history` | Get recent events | `event_type` (optional), `limit` |
| `session_get_hot_files` | Get most active files | `limit` |
| `session_get_context` | Get persisted context | `category` (optional) |

## Context Injection

The most powerful feature of Session Memory is automatic context injection. When you run `coderag launch` or use the MCP server, session context is automatically included in the pre-loaded context.

### Priority Ordering

Context is injected in priority order (most important first):

1. **Hot Files** — Files most frequently read and edited across sessions
2. **Decisions** — Architectural decisions with rationale
3. **Open Tasks** — Tasks that haven't been completed yet
4. **Facts** — Learned facts about the codebase
5. **Recent Activity** — Latest events from the current and recent sessions

### Token Budgeting

Context injection respects a token budget (default: 4000 tokens). Each section is added in priority order until the budget is exhausted. Token estimation uses the approximation of 1 token ≈ 4 characters.

This ensures the AI tool gets the most relevant context without wasting tokens on less important information.

## Hot Files Detection

Hot files are files that appear most frequently in session events (reads + edits). They represent the files you're actively working on.

```bash
# Via CLI
coderag session context

# Via MCP tool
session_get_hot_files(limit=10)
```

Hot files are weighted: edits count more than reads, and recent events count more than older ones.

## Examples

### Viewing Session History

```bash
# List recent sessions
$ coderag session list

  Session History
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Session ID   ┃ Started             ┃ Tool         ┃ Events ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━┩
│ a1b2c3d4     │ 2026-03-22 10:30:00 │ claude-code  │     42 │
│ e5f6g7h8     │ 2026-03-21 14:15:00 │ cursor       │     28 │
└──────────────┴─────────────────────┴──────────────┴────────┘
```

### Checking Persisted Context

```bash
# View all decisions
$ coderag session context -c decision

  Persisted Decisions
  • Use regex-based route matching (rationale: faster than tree-based)
  • Separate auth middleware from routing (rationale: SRP)
```

### Using with the Launcher

```bash
# Session context is automatically included
$ coderag launch . --context-only | head -20

# CodeRAG Pre-loaded Context
## Hot Files
- src/Routing/Router.php (12 reads, 5 edits)
- src/App.php (8 reads, 2 edits)

## Decisions
- Use regex-based route matching

## Open Tasks
- Add unit tests for Router
```

## Architecture

```
src/coderag/session/
├── __init__.py          # Module exports
├── models.py            # SessionEvent, SessionMemory dataclasses
├── store.py             # SQLite storage (SessionStore)
├── tracker.py           # High-level tracking API (SessionTracker)
├── injector.py          # Token-budgeted context injection (ContextInjector)
└── cost_models.py       # AI model pricing data

src/coderag/mcp/
└── session_tools.py     # 8 MCP tools for AI assistants

src/coderag/cli/
└── session.py           # CLI commands (list, show, context)
```
