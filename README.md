# agora-kiro

Persistent memory for [Kiro](https://kiro.dev) AI coding sessions. A Kiro-exclusive fork of [agora-code](https://github.com/thebnbrkr/agora-code).

Goals, learnings, file symbols, and search history survive context resets and session restarts — stored locally in a SQLite database, injected back into context automatically.

---

## How it works

```
Session start  → inject hook fires → last checkpoint + learnings in context (free)
You work       → summarize_file before reads, index_file after edits (small credit cost)
Agent stops    → store_learning (one sentence) + checkpoint saved (free)
Next session   → inject fires again — you're back in context in ~200 tokens
```

All memory lives in `~/.agora-kiro/memory.db`. Nothing leaves your machine.

---

## Setup

**1. Install**
```bash
pip install git+https://github.com/Veknica/kiro-ctx
```

**2. Get the full binary path** — Kiro's subprocess has a thin PATH so you need the full path
```bash
which agora-kiro
```

**3. Add MCP server** — paste into `.kiro/settings/mcp.json` in your project (replace the path):
```json
{
  "mcpServers": {
    "agora-kiro": {
      "command": "/paste/output/of/which/agora-kiro/here",
      "args": ["memory-server"],
      "autoApprove": [
        "get_session_context", "save_checkpoint", "store_learning",
        "recall_learnings", "complete_session", "get_memory_stats",
        "list_sessions", "recall_file_history", "get_file_symbols",
        "search_symbols", "summarize_file", "read_file_range",
        "index_file", "log_search", "store_team_learning", "recall_team"
      ]
    }
  }
}
```

**4. Add hooks** — in Kiro's Hook UI, create these two free hooks:

| Title | Event | Action | Command |
|---|---|---|---|
| `agora-session-inject` | Prompt Submit | Run Command | `agora-kiro inject --quiet` |
| `agora-auto-checkpoint` | Agent Stop | Run Command | `agora-kiro checkpoint --quiet` |

Optional hooks (cost small credits, save tokens on large files):

| Title | Event | Action | Command |
|---|---|---|---|
| `agora-summarize-before-read` | Pre Tool Use (`read`) | Ask Kiro | Call `summarize_file` then `read_file_range` instead of loading the full file |
| `agora-index-after-write` | Post Tool Use (`write`) | Ask Kiro | Call `index_file` on the edited file |
| `agora-summarize-interaction` | Agent Stop | Ask Kiro | Call `store_learning` with one sentence summary then stop |

**5. Add steering** — in Kiro's Steering UI, create a new doc with inclusion set to **Always** and paste the contents of `.kiro/steering/agora-memory.md`.

**6. Restart Kiro** — hooks and MCP load on restart.

**7. Verify**
```bash
agora-kiro status          # DB path + row counts
agora-kiro inject          # see what gets injected into context
agora-kiro list-learnings  # everything stored so far
agora-kiro recall "query"  # test search
```

---

## Credit cost

| Hook | Cost |
|---|---|
| Session inject (every prompt) | Free — shell command |
| Checkpoint (every agent stop) | Free — shell command |
| Summarize before read | Small — one MCP tool call per file |
| Index after write | Small — one MCP tool call per file |
| Store learning on agent stop | Small — one MCP tool call per turn |

The main token saving is from `summarize_file` → `read_file_range` instead of loading full files. A 500-line file costs ~50 tokens as a summary vs ~2000 tokens loaded in full.

---

## MCP tools

| Tool | When to use |
|---|---|
| `get_session_context` | Need full session detail (goal, hypothesis, files changed) |
| `save_checkpoint` | Completed a meaningful step |
| `store_learning` | Found something non-obvious |
| `recall_learnings` | Starting a task — check if solved before |
| `complete_session` | Done for the day |
| `summarize_file` | About to read a large file — get AST outline first |
| `read_file_range` | Read specific lines after summarizing |
| `index_file` | Just edited a file — make symbols searchable |
| `search_symbols` | Find a function/class across the codebase |
| `get_file_symbols` | List all symbols in a specific file |
| `recall_file_history` | See what changed in a file across past sessions |
| `log_search` | Log a search query and matched files |
| `get_memory_stats` | Check DB stats |
| `list_sessions` | Browse past sessions |
| `store_team_learning` | Save a finding for the whole team |
| `recall_team` | Search team-wide knowledge |

---

## CLI

```bash
agora-kiro status           # DB path and counts
agora-kiro memory           # dump sessions, learnings, symbols
agora-kiro inject           # manually trigger session inject
agora-kiro recall "query"   # search past learnings
agora-kiro list-sessions    # all past sessions
agora-kiro list-learnings   # everything stored so far
agora-kiro checkpoint --goal "What you're working on"
agora-kiro learn "finding"
```
