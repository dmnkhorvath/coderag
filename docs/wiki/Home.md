# 🧠 CodeRAG Wiki

**Build knowledge graphs from your codebase for LLM context retrieval**

CodeRAG parses PHP, JavaScript, TypeScript, Python, CSS, and SCSS codebases into rich knowledge graphs with framework detection, cross-language analysis, and MCP server integration for AI-powered code understanding.

---

## 📖 Wiki Pages

| Page | Description |
|------|-------------|
| **[Installation](Installation)** | How to install CodeRAG on your system |
| **[MCP Server Setup](MCP-Server-Setup)** | Configure CodeRAG as an MCP server for Claude, Cursor, and other AI tools |
| **[CLI Reference](CLI-Reference)** | Complete command-line interface documentation |
| **[Configuration](Configuration)** | `codegraph.yaml` options and project setup |

---

## ✨ Key Features

- **Multi-language** — PHP, JavaScript, TypeScript, Python, CSS, SCSS with Tree-sitter AST parsing
- **41 node types & 50 edge types** for comprehensive code modeling
- **11 framework detectors** — Laravel, Symfony, React, Express.js, Next.js, Vue, Angular, Django, Flask, FastAPI, Tailwind CSS
- **8 MCP tools** for AI agents to query the knowledge graph
- **Cross-language analysis** — PHP routes ↔ JavaScript API calls
- **Git metadata enrichment** — change frequency, co-change, ownership
- **Token-budgeted exports** — sized to fit LLM context windows
- 🔄 **Live file watching** — auto-reparse on file changes (`coderag watch`)
- 🔍 **Full CLI parity** — all 8 MCP tools available as CLI commands
- ⚡ **Parallel pipeline** — phases 3-5 and 7 run in parallel for faster parsing

## 🔗 Links

- [GitHub Repository](https://github.com/dmnkhorvath/coderag)
- [Planning Documents (Gists)](https://gist.github.com/dmnkhorvth/9e69354c87310a2ae39edaf814e3e39e)
