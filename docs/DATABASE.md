# agora-kiro Database

Single SQLite file at `~/.agora-kiro/memory.db`. Shared across all projects, isolated per project by `project_id` (derived from the git remote URL).

Optional: `sqlite-vec` extension for vector similarity search. Falls back to FTS5 keyword search if not installed.

---

## Tables

### `sessions`
One row per coding session.

| Column | What it stores |
|---|---|
| `session_id` | UUID, primary key |
| `project_id` | Git remote URL (isolates projects) |
| `branch` | Git branch at session start |
| `commit_sha` | HEAD commit SHA |
| `session_data` | JSON blob — goal, hypothesis, next_steps, blockers, compressed transcript |
| `status` | `active` or `archived` |
| `last_active` | Timestamp, used to find the most recent session |

**How it's used:** On session start, `agora-kiro inject` loads the most recent session for this project. The compressed transcript from the last session is included so the agent has continuity. On session end, `on-stop.sh` / `agora-summarize-interaction` updates the session with a structured checkpoint.

---

### `learnings`
Long-term memory — non-obvious findings, gotchas, decisions, checkpoints.

| Column | What it stores |
|---|---|
| `learning_id` | UUID, primary key |
| `session_id` | Which session created this |
| `project_id` | Project scope |
| `finding` | The actual text of the learning |
| `evidence` | Supporting context or example |
| `confidence` | `confirmed`, `likely`, or `hypothesis` |
| `tags` | Comma-separated: `checkpoint`, `structured`, `conversation`, `tool-failure`, etc. |
| `embedding` | Float vector blob (if sqlite-vec installed) |
| `last_injected_at` | When this was last surfaced to the agent |

**How it's used:** `agora-kiro recall "<query>"` searches this table by keyword (FTS5) or semantic similarity (sqlite-vec). On every prompt, `on-prompt.sh` / `agora-session-inject` runs a recall and appends matching learnings to context. Checkpoints from `on-stop.sh` are stored here as structured JSON in the `evidence` field with tag `checkpoint,structured`.

---

### `commit_learnings`
Junction table linking learnings to git commits.

| Column | What it stores |
|---|---|
| `commit_sha` | Git commit SHA |
| `learning_id` | FK → `learnings` |
| `project_id` | Project scope |

**How it's used:** When `agora-kiro learn-from-commit` runs (automatically after every `git commit` via `on-bash.sh`), it derives learnings from file change notes and links them to the commit SHA here. On inject, learnings for the last 3 commits on the current branch are surfaced.

---

### `file_changes`
Per-file diff history — what changed in each file and why.

| Column | What it stores |
|---|---|
| `change_id` | UUID, primary key |
| `file_path` | Absolute or repo-relative path |
| `diff_summary` | AI-written or regex-derived 1-2 sentence note |
| `status` | `uncommitted` or `committed` |
| `commit_sha` | Set when the change is committed |
| `project_id` | Project scope |
| `branch` | Git branch |

**How it's used:** `agora-kiro track-diff <file>` writes a row here after every edit. On inject, uncommitted file changes are surfaced so the agent knows what's been touched in the current working session. On git commit, `on-bash.sh` calls `tag_commit()` which updates `status → committed` and sets `commit_sha`.

---

### `symbol_notes`
Per-function/class index — AST-extracted symbol metadata.

| Column | What it stores |
|---|---|
| `symbol_id` | UUID, primary key |
| `file_path` | Source file |
| `symbol_type` | `function`, `method`, `class`, etc. |
| `symbol_name` | Name of the symbol |
| `start_line` | Line number where it starts |
| `end_line` | Line number where it ends |
| `signature` | Full function signature |
| `note` | Docstring or first comment |
| `code_block` | Raw source (capped at ~50 lines) |
| `commit_sha` | Commit when indexed |
| `project_id` / `branch` | Scope |

**How it's used:** Every file read or edit triggers indexing via `on-read.sh` / `on-edit.sh`. `agora-kiro summarize <file>` reads from here if the file is already indexed at the current commit — zero re-parsing cost. `search_symbols` and `get_file_symbols` expose this to MCP tools so the agent can find functions without reading files.

---

### `file_snapshots`
AST outline cache — one compressed structural summary per file.

| Column | What it stores |
|---|---|
| `snapshot_id` | UUID, primary key |
| `file_path` | Source file |
| `summary` | Tree-sitter/AST outline text (functions, classes, line numbers) |
| `commit_sha` | Commit when generated |
| `project_id` / `branch` | Scope |

**How it's used:** `agora-kiro summarize <file>` checks here first. If the file hasn't changed since the last index (same commit SHA), it returns the cached summary instantly. If stale, it re-parses with tree-sitter and updates the cache. This is the main mechanism behind the 75-95% token reduction on large file reads.

---

### `api_calls`
API call log — used by the `serve` and `chat` commands for route discovery stats.

| Column | What it stores |
|---|---|
| `call_id` | UUID |
| `method` / `path` | HTTP method and endpoint |
| `status_code` | Response status |
| `latency_ms` | Round-trip time |
| `project_id` | Project scope |

**How it's used:** Only populated when using `agora-kiro serve` or `agora-kiro chat` to call live APIs. Powers `agora-kiro stats` which shows call patterns and failure rates per endpoint. Not used during normal coding sessions.

---

### `logs`
Internal warning/error log from the Python package itself.

Written by `_SQLiteLogHandler` in `log.py` for WARNING+ level events. Useful for debugging hook failures.

---

## How the tables connect

```
sessions
  └─ session_id → learnings (session_id)
                → file_changes (via project_id/branch)

learnings
  └─ learning_id → commit_learnings → commit_sha

file_changes
  └─ commit_sha → commit_learnings (same SHA)

symbol_notes
  └─ file_path + commit_sha → file_snapshots (same file + SHA)
```

---

## Key behaviors

**Project isolation:** Every query is scoped by `project_id` (git remote URL). Two projects never see each other's learnings, symbols, or sessions.

**Recency scoring:** `recall_learnings` blends BM25/semantic rank with recency, current branch match, and confidence level. Recent learnings on the current branch score highest.

**Commit tagging:** When `git commit` runs, `tag_commit()` bulk-updates `file_changes.commit_sha` and `symbol_notes.commit_sha` for all files in that commit. This is how inject knows which learnings are from recent commits vs old ones.

**Semantic search:** If `sqlite-vec` is installed and an embedding provider is configured (`OPENAI_API_KEY`, `GEMINI_API_KEY`, or local sentence-transformers), recall uses cosine similarity. Otherwise falls back to FTS5 BM25 keyword search — which still works well for code.
