# Dogfood Session 6: Live MCP + Claude Code Integration

**Date:** 2026-03-22
**Target:** Koel music streaming app (PHP/Laravel + Vue/TypeScript)
**Objective:** Validate CodeRAG MCP server integration with Claude Code v2.1.81
**Environment:** Dogfood sandbox at 192.168.1.168:2222

## Setup

- CodeRAG updated to latest commit (e2bd31a) on sandbox
- Koel re-parsed: **15,797 nodes**, **34,294 edges**, 127 communities
- `coderag launch . --dry-run --tool claude-code` generated:
  - `CLAUDE.md` (51 lines) with project overview, PageRank scores, MCP tool list
  - `.claude/settings.local.json` with MCP server config
- Claude Code v2.1.81 with ANTHROPIC_BASE_URL pointing to local proxy

## MCP Configuration Generated

```json
{
  "mcpServers": {
    "coderag": {
      "command": "/usr/local/bin/coderag",
      "args": ["serve", "/workspace/koel", "--watch"]
    }
  }
}
```

## Integration Tests

### Test 1: Symbol Lookup + Find Usages ✅ PASSED
**Prompt:** "Use coderag_lookup_symbol and coderag_find_usages to look up the Song model"
**Result:** Claude Code returned:
- Full class declaration with 9 traits and 3 interfaces
- 11 public methods with descriptions
- SongBuilder scopes (7 methods)
- 8 relationships (BelongsTo, BelongsToMany, HasMany)
- **179 dependent files** categorized by layer (Services 14, Streamer Adapters 10, Controllers 14, Models 10, Jobs 4, Events 4, Tests 85+)

### Test 2: Find Routes ✅ PASSED
**Prompt:** "Use coderag_find_routes to find all API routes related to playlists"
**Result:** Claude Code returned:
- **20 routes** across **7 controllers**
- Organized by category: Core Playlists (5), Playlist Songs (5), Playlist Folders (6), Collaboration (4), Download (1)
- Correct HTTP methods (GET, POST, PUT/PATCH, DELETE)
- Controller names and route patterns

### Test 3: Architecture Overview ⚠️ PARTIAL
**Prompt:** "Use coderag_architecture to give a high-level architecture overview"
**Result:** Claude Code reported "The MCP server doesn't appear to be running" for the architecture tool specifically, but still provided useful information by falling back to CLAUDE.md data:
- Correctly identified Laravel + Vue + Tailwind stack
- Listed key entry points by PageRank
- Reported 15,797 symbols, 34,294 relationships, 127 communities
- **Bug identified:** The `coderag_architecture` MCP tool may have a timeout or startup issue

### Test 4: Dependency Graph ✅ PASSED
**Prompt:** "Use coderag_dependency_graph for the User model (App\Models\User)"
**Result:** Claude Code returned:
- **What User depends on:** 9 internal deps (UserBuilder, UserPreferencesCast, Role enum, traits, observer, factory) + 7 external/framework deps (Laravel, Sanctum, Spatie, Auditing, Carbon)
- **What depends on User:** 151 files categorized (Controllers ~50, Services ~20, Repositories ~10, Policies ~10, Events ~6, Jobs 2, Resources ~5, Rules 3)

### Test 5: Full-Text Search ✅ PASSED
**Prompt:** "Use coderag_search to search for 'queue' in this codebase"
**Result:** Claude Code returned:
- **11 results** across PHP backend and Vue/TypeScript frontend
- QueueStateController, QueueService, QueueStateResource (PHP)
- queueStore.ts, QueuePlaybackService.ts, QueueScreen.vue (TypeScript/Vue)
- Migrations for queue_states, jobs, failed_jobs tables
- Helpful summary distinguishing backend queue management from frontend playback

### Test 6: Multi-Tool Workflow ✅ PASSED (Best Test)
**Prompt:** "I want to add a 'Recently Played' feature. Using CodeRAG MCP tools, investigate the Interaction model, find routes related to songs/play, check QueueScreen, then give an implementation plan."
**Result:** Claude Code used **multiple MCP tools** in sequence and discovered the feature is **already fully implemented**:
- **Backend:** Interaction model with play_count/last_played_at, InteractionService::increasePlayCount(), SongRepository::getRecentlyPlayed(), GET api/songs/recently-played, GET api/overview
- **Frontend:** recentlyPlayedStore.ts, RecentlyPlayedScreen.vue, home widgets
- **Full data flow:** Song played past 25% → POST api/interaction/play → sets last_played_at → client prepends to store
- Even found tests (RecentlyPlayedSongTest.php, recentlyPlayedStore.spec.ts) and an AI tool (PlayRecentlyPlayed.php)

## Summary

| Test | Tool(s) Tested | Result |
|------|---------------|--------|
| Symbol Lookup | coderag_lookup_symbol, coderag_find_usages | ✅ PASSED |
| Route Finding | coderag_find_routes | ✅ PASSED |
| Architecture | coderag_architecture | ⚠️ PARTIAL |
| Dependency Graph | coderag_dependency_graph | ✅ PASSED |
| Full-Text Search | coderag_search | ✅ PASSED |
| Multi-Tool Workflow | Multiple tools combined | ✅ PASSED |

**Pass Rate: 5/6 fully passed, 1/6 partial = 91.7%**

## Bugs Found

### Bug 1: coderag_architecture MCP tool intermittent failure (MEDIUM)
**Severity:** Medium
**Description:** The `coderag_architecture` tool reported "MCP server doesn't appear to be running" while other tools in the same session worked correctly. Claude Code fell back to reading CLAUDE.md data.
**Possible causes:**
- Tool-specific timeout (architecture queries may be slower on large graphs)
- MCP server startup race condition
- Tool registration issue specific to the architecture endpoint
**Impact:** Low — Claude Code gracefully falls back to CLAUDE.md data

## Key Findings

1. **MCP integration works end-to-end** — Claude Code discovers, connects to, and uses CodeRAG MCP tools automatically
2. **Multi-tool workflows work** — Claude Code chains multiple MCP tool calls to build comprehensive understanding
3. **Quality of responses is excellent** — The combination of CodeRAG's knowledge graph + Claude Code's reasoning produces highly detailed, accurate codebase analysis
4. **CLAUDE.md serves as effective fallback** — When MCP tools fail, the pre-generated context file provides baseline information
5. **Non-interactive mode (`claude -p`) works** — Enables scripted/automated testing of MCP integration

## Cumulative Dogfood Stats

| Session | Repository | Files | Nodes | Edges | Bugs Found |
|---------|-----------|-------|-------|-------|------------|
| 1 | koel (PHP+Vue) | 1,592 | 13,384 | 36,709 | 2 HIGH, 1 MED |
| 2 | paperless-ngx (Django+Angular) | 807 | 20,580 | 50,517 | 0 |
| 3 | saleor (Django GraphQL) | 4,220 | 111,076 | 260,654 | 2 HIGH, 1 LOW |
| 4 | NocoDB (TypeScript+Vue) | 1,823 | 24,367 | 74,284 | 1 HIGH, 1 MED, 2 LOW |
| 5 | Cal.com (TypeScript Turborepo) | 7,530 | 50,926 | 220,752 | 4 MED |
| 6 | koel MCP Integration | 1,594 | 15,797 | 34,294 | 1 MED |
| **Total** | **6 sessions** | **17,566** | **236,130** | **677,210** | **14 bugs** |
