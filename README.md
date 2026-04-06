# Using agora-kiro with Kiro

agora-kiro gives Kiro persistent memory across sessions — goals, learnings, file history, and search logs survive restarts and context resets.

## Setup

Run this from your project root (or from this repo to test it here):

```bash
sh /path/to/kiro-ctx/kiro-setup.sh
```

That's it. The script:
1. Installs `agora-kiro` if not already present
2. Resolves the full binary path and writes it into `.kiro/settings/mcp.json`
3. Copies all 9 hooks into `.kiro/hooks/` with the correct path baked in
4. Copies the steering doc into `.kiro/steering/`
5. Runs `agora-kiro status` to confirm everything works

Then **restart Kiro** to load the hooks and MCP server.

### Manual setup (if you prefer)

<details>
<summary>Expand for manual steps</summary>

**1. Install agora-kiro**
```bash
pip install agora-kiro
```

**2. Get the full binary path** (Kiro's subprocess often has a thin PATH)
```bash
which agora-kiro
```

**3. Copy `.kiro/` into your project**

Copy `.kiro/settings/mcp.json`, `.kiro/steering/agora-kiro.md`, and `.kiro/hooks/` from this repo. Replace `"command": "agora-kiro"` in `mcp.json` with the full path from step 2. Do the same for the `command` field in any shell hook files.

</details>

### Hook inventory

**9 hooks** ship in `.kiro/hooks/` using Kiro's stable built-in category matchers (`read`, `write`) instead of fragile concrete tool names. For a full mapping to Kiro trigger types and improvement ideas, see **`docs/KIRO_HOOKS.md`**. For design notes and backlog, see **`docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`**.

| Hook | Trigger | Action |
|---|---|---|
| `agora-session-inject` | Every prompt | Injects last session context (shell, 0 credits) |
| `agora-auto-checkpoint` | Agent stop | Saves progress checkpoint (shell, 0 credits) |
| `agora-inject-before-task` | Spec task start | Loads context before each task (shell, 0 credits) |
| `checkpoint-after-task` | Spec task end | Saves checkpoint after task (shell, 0 credits) |
| `agora-summarize-before-read` | Before any `read` tool | Gets AST outline, reads only relevant section |
| `agora-index-after-write` | After any `write` tool | Indexes updated symbols into memory DB |
| `agora-log-grep-results` | After `grepSearch` | Logs search query + indexes matched files |
| `agora-index-on-save` | File saved | Indexes symbols on manual save |
| `agora-summarize-interaction` | Agent stop | Stores one-sentence learning (Ask Kiro) |

Restart Kiro after adding hooks for them to take effect.

## What you get

Once set up, Kiro automatically:

- **Remembers what you were working on** — session context is injected before every prompt
- **Saves progress** — checkpoints after every agent turn and spec task
- **Stores discoveries** — non-obvious findings are saved and recalled in future sessions
- **Reads large files efficiently** — AST summaries before reads, then targeted line ranges (90%+ token reduction)
- **Tracks your searches** — grep queries and matched files are logged persistently
- **Indexes edited files** — symbols become searchable across sessions after every edit

## Available MCP tools

| Tool | What it does |
|---|---|
| `get_session_context` | Load last session — goal, hypothesis, next steps, files changed |
| `save_checkpoint` | Save current progress mid-session |
| `complete_session` | Archive session to long-term memory when done |
| `store_learning` | Save a non-obvious finding for future sessions |
| `recall_learnings` | Search past findings before starting a task |
| `store_team_learning` | Save a finding shared across the whole team/project |
| `recall_team` | Search team-wide knowledge |
| `summarize_file` | Get AST outline of a file with function names and line numbers |
| `read_file_range` | Read a specific line range from a file |
| `index_file` | Index a file's symbols into the memory DB |
| `get_file_symbols` | Get all indexed symbols for a file |
| `search_symbols` | Search symbols across all indexed files |
| `recall_file_history` | See all past changes to a file across sessions |
| `log_search` | Log a search query and its matched files |
| `get_memory_stats` | Check DB stats — session count, learning count, symbol count |
| `list_sessions` | List all past sessions |

## Verifying it works

In Kiro's terminal:

```bash
agora-kiro status          # DB path and row counts
agora-kiro list-learnings  # everything stored so far
agora-kiro list-sessions   # all past sessions
agora-kiro inject          # manually trigger session inject, see output
agora-kiro recall "your query"  # test semantic search
```

## How it works

All memory is stored in a local SQLite database at `~/.agora-kiro/memory.db`. Nothing leaves your machine. The MCP server (`agora-kiro memory-server`) exposes this database to Kiro via the Model Context Protocol.

The shell hooks (`agora-session-inject`, `agora-auto-checkpoint`, etc.) run `agora-kiro inject` and `agora-kiro checkpoint` as zero-credit shell commands. The `askAgent` hooks (summarize, index, log) use MCP tool calls and consume a small amount of credits.
