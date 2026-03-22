# 💰 Cost Savings Guide

CodeRAG dramatically reduces AI coding tool costs by providing precise, graph-ranked context instead of dumping entire files into the context window.

## The Problem

AI coding tools like Claude Code, Cursor, and Codex CLI waste tokens on irrelevant context:

- **Without CodeRAG**: The AI reads entire files, directory listings, and unrelated code to find what it needs. A simple "find the entry point" task might consume 29,000+ tokens.
- **With CodeRAG**: The AI receives only the relevant symbols, relationships, and architecture — typically under 2,400 tokens for the same task.

This difference compounds quickly. At 100 tasks/month, the savings can exceed **$36/month** per project.

## How CodeRAG Reduces Costs

CodeRAG uses three techniques to minimize token usage:

### 1. PageRank-Based Symbol Ranking

Not all code is equally important. CodeRAG runs PageRank on the knowledge graph to identify the most central symbols — the classes, functions, and methods that everything else depends on. These are served first.

### 2. Graph-Aware Context Selection

Instead of reading entire files, CodeRAG traverses the knowledge graph to find exactly the symbols, relationships, and dependencies relevant to a task. A "find usages of Router" query returns only the callers, importers, and extenders — not the entire codebase.

### 3. Token-Budgeted Responses

Every response is constrained to a token budget (default: 4,000 tokens). Context is added in priority order until the budget is exhausted, ensuring the AI gets the most valuable information first.

## Benchmark Methodology

The `coderag benchmark` command simulates 8 common coding tasks and compares token usage with and without CodeRAG:

| Task | Description |
|------|-------------|
| Find the main entry point | Locate the primary application class |
| Understand a symbol | Get definition, relationships, and context |
| Find all usages of a symbol | Locate callers, importers, extenders |
| Impact analysis | Determine blast radius of a change |
| Architecture overview | Understand module structure |
| File context | Get context for a specific file |
| Cross-language connections | Find API endpoints and bridges |
| Framework detection | Identify frameworks and patterns |

For each task:
- **Without CodeRAG**: Estimates tokens needed to read all relevant files manually
- **With CodeRAG**: Measures actual tokens in the CodeRAG response

## Real Results

Benchmark against the [Slim PHP framework](https://github.com/slimphp/Slim) (125 files, 1,883 nodes, 7,998 edges):

| Metric | Without CodeRAG | With CodeRAG | Savings |
|--------|----------------:|-------------:|--------:|
| Avg tokens/task | 17,617 | 2,400 | **86.4%** |
| Total tokens (8 tasks) | 140,943 | 19,200 | **86.4%** |
| Est. cost (8 tasks) | $0.4228 | $0.0576 | **86.4%** |
| Est. cost/month* | $42.28 | $5.76 | **86.4%** |
| Context hit rate | N/A | 100.0% | — |

*Estimated at 100 tasks/month using Claude Sonnet 4 pricing.

### Per-Task Breakdown

| Task | Without | With | Savings |
|------|--------:|-----:|--------:|
| Find the main entry point | 29,515 | 2,400 | 91.9% |
| Understand a symbol | 3,096 | 2,400 | 22.5% |
| Find all usages of a symbol | 44,297 | 2,400 | 94.6% |
| Impact analysis | 5,160 | 2,400 | 53.5% |

The largest savings come from tasks that would otherwise require reading many files (find usages: 94.6%, find entry point: 91.9%).

## Supported Pricing Models

CodeRAG includes pricing data for 8 popular AI models:

| Model | Input ($/1M) | Output ($/1M) | Cached ($/1M) | Context Window |
|-------|-------------:|--------------:|---------------:|---------------:|
| Claude Sonnet 4 | $3.00 | $15.00 | $0.30 | 200K |
| Claude Opus 4 | $15.00 | $75.00 | $1.50 | 200K |
| Claude Haiku 3.5 | $0.80 | $4.00 | $0.08 | 200K |
| GPT-4o | $2.50 | $10.00 | $1.25 | 128K |
| GPT-4.1 | $2.00 | $8.00 | $0.50 | 1M |
| GPT-4.1 Mini | $0.40 | $1.60 | $0.10 | 1M |
| Gemini 2.5 Pro | $1.25 | $10.00 | $0.315 | 1M |
| Gemini 2.5 Flash | $0.15 | $0.60 | $0.0375 | 1M |

## Running Your Own Benchmark

```bash
# Basic benchmark (uses Claude Sonnet 4 pricing)
coderag benchmark /path/to/project

# Benchmark with a different model
coderag benchmark /path/to/project --model gpt-4o

# Output as JSON
coderag benchmark /path/to/project --format json --output results.json

# Output as markdown
coderag benchmark /path/to/project --format markdown

# Custom token budget
coderag benchmark /path/to/project --token-budget 8000
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `claude-sonnet-4` | Model for cost estimation |
| `--format` | `table` | Output format: `table`, `json`, `markdown` |
| `--output` | — | Save JSON results to file |
| `--token-budget` | `4000` | Token budget for CodeRAG responses |
| `--prompts` | — | Custom prompts JSON file |

## Interpreting Results

- **Savings > 80%**: Excellent — CodeRAG is providing highly targeted context
- **Savings 50-80%**: Good — significant cost reduction on most tasks
- **Savings < 50%**: The project may be small enough that full-file reading is comparable
- **Context hit rate**: Should be 100% — indicates all tasks found relevant graph data

## Cost Estimation Formula

```
cost = (input_tokens / 1,000,000) × input_price
      + (output_tokens / 1,000,000) × output_price
      + (cached_tokens / 1,000,000) × cached_price
```

Token estimation uses the approximation: **1 token ≈ 4 characters**.
