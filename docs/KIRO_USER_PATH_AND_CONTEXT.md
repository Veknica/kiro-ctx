# Kiro user path through agora-kiro + context effects (investigation notes)

**Audience:** Internal — product investigation, Kiro-first fork (`kiro-ctx`), almost-new-product thinking.  
**Companion docs:** `KIRO.md` (setup), `docs/KIRO_HOOKS.md`, `docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`, `docs/KIRO_PLATFORM_AND_AGORA_PLAN.md`, `docs/KIRO_CODEBASE_AUDIT_AND_GAPS.md`.

This file is grounded in the **current codebase**: entrypoint `agora-kiro` → `agora_code.cli:main` (`pyproject.toml` `[project.scripts]`), with Kiro wiring under `.kiro/`.

---

## 1. How a Kiro user actually uses agora-kiro

### One-time (per machine / project)

1. **`pip install agora-kiro`** (or editable install from a clone) so the **`agora-kiro`** binary exists. Prefer a **full path** in MCP config if Kiro’s subprocess has a thin `PATH`.
2. **MCP:** Add `.kiro/settings/mcp.json` (or `~/.kiro/settings/mcp.json`) so Kiro starts:
   - `command`: `agora-kiro` (or full path)
   - `args`: `["memory-server"]`  
   That runs `memory_server()` in `agora_kiro/cli.py`, which calls `agora_code.memory_server.serve_memory` — stdio MCP exposing tools such as `get_session_context`, `store_learning`, `summarize_file`, `read_file_range`, `index_file`, `log_search`, etc. (the `memory-server` docstring in `cli.py` lists a subset; the server registers more in `memory_server.py`).
3. **Steering:** Copy `.kiro/steering/agora-kiro.md` — `inclusion: always` so the agent is instructed **when** to use MCP and how (e.g. summarize before read, stop after one `store_learning` on agent stop).
4. **Hooks:** Copy `.kiro/hooks/*.kiro.hook` — see §2.

### Every session / turn (automatic)

- **Prompt submit:** shell hook runs **`agora-kiro inject --quiet`** → `inject()` in `cli.py` → `_build_recalled_context()` in `agora_kiro/session.py` builds text from **SQLite + git** (not from Kiro chat files). Stdout is appended to the agent context.
- **Agent stop:** (1) Ask Kiro hook → model calls **`store_learning`** via MCP; (2) shell hook → **`agora-kiro checkpoint --quiet`** → `checkpoint()` / `update_session()` in `cli.py` / `session.py` (session JSON + dual-write to DB where applicable).
- **Pre read / post write / grep / file save:** Ask Kiro hooks instruct MCP calls (`summarize_file`, `read_file_range`, `index_file`, `log_search`, …) implemented in **`memory_server.py`**.

### Optional manual (same as any agora-kiro user)

From Kiro’s terminal or any shell in the repo:

- `agora-kiro status`, `agora-kiro memory`, `agora-kiro list-learnings`, `agora-kiro recall "…"`, `agora-kiro complete --summary "…"`, etc. — all live under **`agora_kiro/cli.py`** as Click subcommands.

### What a Kiro user typically *does not* touch

- **`agora-kiro scan` / `serve` / `agentify`** — API-route / workflow features; orthogonal to the **memory** path unless they use those product lines too.
- **Claude/Cursor hook scripts** under `.claude/` / `.cursor/` — different IDE; same **`memory.db`** if `project_id` matches.

---

## 2. How hooks tie to the CLI vs MCP (managed where)

| Hook action | What runs | Defined in |
|-------------|-----------|------------|
| **`runCommand`** | Subprocess string, e.g. `agora-kiro inject --quiet` | `.kiro/hooks/*.kiro.hook` → `then.command` |
| **`askAgent`** | Prompt to the model; model calls **MCP tools** | Same JSON files + steering; MCP server is **`agora-kiro memory-server`** from `mcp.json` |

There is **no** separate “Kiro CLI” — only **`agora-kiro`** plus Kiro’s Hook UI / JSON. Versioning = git on `.kiro/` + global `~/.kiro/` if used.

---

## 3. “Kiro learnings” vs agora learnings

**Same store.** `store_learning` in `memory_server.py` calls into the vector store / SQLite used everywhere. Tags (e.g. `conversation`, `checkpoint`) distinguish **kinds** of rows, not “Kiro vs Cursor.” Kiro is just one **ingress** (MCP + hooks + steering).

---

## 4. Context / tokens — mechanism vs tendency (investigation table)

Use this table when deciding whether the **current integrated approach** helps or hurts context windows and product story.

| Mechanism | Tendency |
|-----------|----------|
| **`inject` (shell)** | Adds a **bounded** block (roughly the “~350 token” style bundle from `_build_recalled_context` in `session.py` — checkpoint-ish learnings, recent learnings, git, symbols, etc.). So **more** tokens than an empty prompt, but **capped** by design. |
| **Pre-read: `summarize_file` + `read_file_range`** | **Usually reduces** context vs dumping whole files — that’s the main token strategy in steering. |
| **Post-tool: `index_file`, `log_search`** | Tool responses add **some** tokens to **that** turn; they don’t paste whole files into chat by default. |
| **`agentStop` Ask Kiro + `store_learning`** | **Costs** an extra agent step (credits); the **next** session gets a **short** learning via `inject` instead of replaying a huge chat — so **long-term** context **in the window** can go **down** if the pipeline works. |
| **Kiro’s own chat transcript** | Still grows in Kiro’s UI/storage; agora-kiro **doesn’t replace** that — it adds **structured memory beside** it. |

---

## 5. Key implementation files (for deeper reading)

| Area | File(s) |
|------|---------|
| CLI entry + subcommands | `agora_kiro/cli.py` (`main`, `inject`, `checkpoint`, `summarize`, `index`, `memory-server`, …) |
| Package script name | `pyproject.toml` → `agora-kiro = "agora_code.cli:main"` |
| MCP tool handlers | `agora_kiro/memory_server.py` |
| Inject / session / checkpoint persistence | `agora_kiro/session.py` (`_build_recalled_context`, `update_session`, …) |
| DB / learnings | `agora_kiro/vector_store.py` (+ `docs/DATABASE.md`) |
| Kiro JSON | `.kiro/settings/mcp.json`, `.kiro/hooks/*.kiro.hook`, `.kiro/steering/agora-kiro.md` |

---

## 6. Full read-through: `cli.py` + `memory_server.py` (no skim)

**Verified:** `agora_kiro/memory_server.py` (1006 lines) and `agora_kiro/cli.py` (2879 lines) were read **line-by-line** in order for this section (Mar 2026). Below is the **exact** Kiro-relevant command flow and one important split people often confuse.

### 6.1 MCP server: `memory_server.py`

- **`_TOOLS`** — **16** tools (not 6 — the `memory-server` docstring in `cli.py` is stale): `get_session_context`, `save_checkpoint`, `store_learning`, `recall_learnings`, `complete_session`, `get_memory_stats`, `list_sessions`, `store_team_learning`, `recall_team`, `recall_file_history`, `get_file_symbols`, `search_symbols`, `summarize_file`, `read_file_range`, `index_file`, `log_search`.
- **`_HANDLERS`** maps tool name → async handler; `tools/call` runs the handler and wraps the string result as MCP `content` text.
- **`serve_memory()`** — connects stdin as JSON-RPC lines; loop `readline` → `_dispatch` → `_send`. On startup, may emit a **`notifications/message`** banner from `session_restored_banner` if a recent session exists (branch-change warning + compressed session).
- **`_dispatch`** — handles `initialize`, `tools/list`, `tools/call`, `ping`, `notifications/initialized`.
- **`store_learning` / `recall_learnings`** — `vector_store.get_store()`, embeddings when available; recall enriches query from `load_session()` + branch + uncommitted files; `_apply_recency_scoring` re-ranks.
- **`summarize_file`** — tries DB snapshot at **current `git rev-parse HEAD`** first; else reads disk and `summarizer.summarize_file`; small files (`threshold=0` in MCP path) can return **full file content** as string when summary is `None`.
- **`read_file_range`** — reads file, slices lines `[start_line-1 : end_line]`, prefixes each line with `lineno| `.
- **`index_file`** — resolves path vs `cwd`, calls `indexer.index_file` (returns **int** symbol count). Handler treats non-dict return as 0 symbols in the f-string path (`result.get` only if dict) — message may under-report; CLI `index` command prints count correctly.
- **`log_search`** — stores a synthetic **learning** row via `store_learning` with tags `search-log` + tool name.

### 6.2 CLI: `cli.py` — memory-related commands (Kiro-adjacent)

| Command | Role |
|---------|------|
| `inject` | **Does not** load `get_session_context`. Calls **`_build_recalled_context()`** only (plus `raw` mode for session JSON). This is what **Kiro `promptSubmit` shell hooks** run. |
| `checkpoint` | Merges flags into `session.update_session` → `.agora-kiro/session.json` + `save_session` to DB. |
| `complete` | `archive_session` → long-term session row + embedding attempt. |
| `status` / `memory` / `list-*` | Inspect DB / session; no hooks required. |
| `learn` / `recall` / `remove` | CLI path to same `learnings` table as MCP `store_learning` / `recall_learnings` (project-scoped). |
| `index` | `indexer.index_file` with `project_id`, `branch`, `commit_sha` from session helpers. |
| `summarize` | Same summarizer as MCP; **`--json-output`** for hook-style consumption; path allowlist **cwd + home**; DB cache at same commit. |
| `track-diff` / `file-history` | `vector_store.save_file_change` / `get_file_history`. |
| `show` | Rich/markdown view of session + git + commit learnings — **overlaps conceptually** with inject but **different layout** than `_build_recalled_context`. |
| `memory-server` | `asyncio.run(serve_memory())` only. |
| `install-hooks` | Generates **Claude Code** / **Cline** / git post-commit scripts — **not** used by Kiro; shows how **shell** hooks elsewhere call `inject`, `summarize --json-output`, `index`, `track-diff`, `recall`, `learn`. |

**API product commands** (`scan`, `serve`, `stats`, `auth`, `chat`, `agentify`) share the same package and DB for API call logging but are **not** on the Kiro memory hook path.

### 6.3 Critical: `inject` ≠ `get_session_context` (same product, different text)

| Path | Code | Typical use in Kiro |
|------|------|---------------------|
| **`agora-kiro inject`** | `cli.inject` → `_build_recalled_context()` only | **Shell hook** on every prompt |
| **`get_session_context` MCP** | `memory_server._handle_get_session_context` → `load_session` + optional `update_session({context: recalled})` + **`session_restored_banner(session, token_budget=3000)`** (or raw JSON) | Model-invoked tool |

So the **steering** line “inject already loaded it” refers to **shell inject text**, not necessarily the same formatting as **`get_session_context`**. For product design, decide whether Kiro should **standardize on one** or document **both** outputs.

### 6.4 MCP stdio protocol (for debugging Kiro)

One JSON object per line on stdin; responses one JSON object per line on stdout. Tool results are always `{"content":[{"type":"text","text": "<handler return string>"}]}`.

---

*Update when hook set, MCP tool list, or inject composition changes materially.*
