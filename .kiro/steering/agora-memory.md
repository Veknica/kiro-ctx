---
inclusion: always
---

# Persistent Memory via agora-kiro MCP

You have access to the `agora-kiro` MCP server. Two shell hooks run automatically at no credit cost:

- **Every prompt** → `agora-kiro inject` has already run. Your session context (goal, last checkpoint, recent learnings, git state, symbol index) is already in this context. **Do not call `get_session_context` unless you need the full structured session detail** — inject already loaded the recall bundle.
- **Every agent stop** → `agora-kiro checkpoint` runs automatically. Session state is saved.

---

## Before starting any task

Call `recall_learnings("topic")` to check if this was solved before. Do this first, every time.

---

## Reading files

Large files will blow your context window. Always:
1. Call `summarize_file(path)` — returns an AST outline (functions, classes, line numbers). Served from DB cache when available, no disk read needed.
2. Call `read_file_range(path, start_line, end_line)` — read only the section you need.

Never load an entire large file when you can summarize + range-read instead.

---

## When to call tools manually

| Situation | Tool |
|---|---|
| Starting any task | `recall_learnings("topic")` |
| Found something non-obvious | `store_learning(finding, type="finding")` |
| Completed a meaningful step | `save_checkpoint(goal, current_action, next_steps)` |
| About to read a large file | `summarize_file(path)` → `read_file_range(path, start, end)` |
| Just edited a file | `index_file(path)` — keeps symbol search current |
| Need full structured session (goal + hypothesis + files changed) | `get_session_context()` |
| Session done for the day | `complete_session()` |
| Team-wide finding worth preserving | `store_team_learning(finding)` |
| Search team knowledge | `recall_team("topic")` |

---

## inject vs get_session_context — know the difference

| | `agora-kiro inject` (shell hook) | `get_session_context` (MCP tool) |
|---|---|---|
| **Runs** | Automatically before every prompt | When you call it manually |
| **Contains** | Recall bundle: last checkpoint, recent learnings, git log, uncommitted files, symbol index | Full structured session: goal, hypothesis, files changed, decisions, next steps — formatted banner |
| **Use when** | Already done for you | You need the full session structure explicitly |

---

## Rules

1. **Don't call `get_session_context` on every prompt** — inject already gave you the recall bundle.
2. **Call `recall_learnings` before starting a non-trivial task** — always.
3. **Call `store_learning` mid-task** when you find something non-obvious — don't wait for the end.
4. **Summarize before reading large files** — `summarize_file` then `read_file_range`, not a full file load.
5. **Call `index_file` after editing** — keeps the symbol index current for future reads.
