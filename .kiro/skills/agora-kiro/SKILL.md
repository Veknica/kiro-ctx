---
name: agora-kiro
description: Persistent memory for Kiro sessions. Use when you want to recall past work, save a finding, check session history, or understand how agora-kiro memory tools work.
---

# agora-kiro — Memory Skill

agora-kiro gives Kiro persistent memory across sessions. Everything is stored in a local SQLite DB at `~/.agora-kiro/memory.db`.

## What's available

| MCP Tool | When to use |
|---|---|
| `get_session_context` | Need full structured session detail (goal, hypothesis, next steps) |
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
| `get_memory_stats` | Check DB stats |
| `list_sessions` | Browse past sessions |
| `store_team_learning` | Save a finding for the whole team |
| `recall_team` | Search team-wide knowledge |

## CLI commands (run in Kiro terminal)

```bash
agora-kiro status          # DB path and row counts
agora-kiro memory          # dump sessions, learnings, symbols
agora-kiro inject          # manually trigger session inject
agora-kiro recall "query"  # search past learnings
agora-kiro list-sessions   # all past sessions
agora-kiro list-learnings  # everything stored so far
```

## How memory flows

```
Session start → inject hook fires → LEARNINGS + checkpoint in context
You work      → summarize + read_file_range for large files (90%+ token reduction)
Agent stops   → store_learning (one sentence) + checkpoint saved
Next session  → inject fires again — continuity from ~200 tokens, not 10k
```
