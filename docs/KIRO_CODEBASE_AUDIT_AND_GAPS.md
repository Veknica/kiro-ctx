# agora_code audit (Kiro-relevant) + Kiro doc gaps + misuse / drift

**Scope:** All Python modules under `agora_kiro/`, with **full line-by-line** reads already done for `cli.py` and `memory_server.py`, and **summarize + structure review** for the rest (Mar 2026). **Excluded from deep content review:** `claude_instructions.md`, `SKILL.md` (editor packaging), and repo-level `.claude/` / `hooks/` scripts — they do not change runtime behavior for Kiro MCP/hooks.

---

## 1. Module inventory — role vs Kiro

| File | ~Lines | Role | Touches Kiro path? |
|------|--------|------|--------------------|
| **`memory_server.py`** | 1006 | stdio MCP `agora-kiro`; 16 tools | **Yes** — primary |
| **`cli.py`** | 2879 | `inject`, `checkpoint`, `summarize`, `index`, `memory-server`, DB listing, API commands | **Yes** — shell hooks + entrypoint |
| **`session.py`** | 785 | `session.json`, `_build_recalled_context`, `update_session`, `archive_session`, git/project helpers | **Yes** — inject + MCP `get_session_context` |
| **`vector_store.py`** | 1462 | SQLite, learnings, snapshots, symbols, file_changes, sessions | **Yes** — all persistence |
| **`indexer.py`** | 434 | `index_file`, `tag_commit`, symbol extractors | **Yes** — MCP `index_file` + CLI `index` |
| **`summarizer.py`** | 885 | AST/outline summaries, token estimate | **Yes** — MCP `summarize_file` + CLI `summarize` |
| **`compress.py`** | 406 | `compress_session`, `session_restored_banner` | **Yes** — MCP session banner vs API route TLDR |
| **`embeddings.py`** | 278 | Provider selection, `get_embedding` | **Yes** — learnings recall quality |
| **`log.py`** | 101 | Logging config | Indirect |
| **`models.py`** | 322 | `Route`, `RouteCatalog` | **No** for Kiro memory (API scan path) |
| **`scanner.py`** | 175 | Route discovery cascade | **No** for Kiro memory |
| **`agent.py`** | 535 | MCP server for **HTTP API** tools (`agora-kiro serve`) | **No** for Kiro memory (separate MCP product) |
| **`workflows.py`** | 545 | `agentify` / workflow detection | **No** for Kiro memory |
| **`extractors/*`** | — | openapi, regex, python_ast, llm | **No** for Kiro memory |
| **`__init__.py`** | — | Package exports + version | Indirect |

**Takeaway:** Kiro integration depends on **seven** core files (`memory_server`, `cli`, `session`, `vector_store`, `indexer`, `summarizer`, `compress`) plus **`embeddings`**.

---

## 2. What we still need from **Kiro** docs / product

These are **not** inferable from our repo; they determine whether we can go shell-first, fix hook reliability, or document accurately.

| Topic | Why it matters |
|--------|----------------|
| **`.kiro.hook` JSON schema** | Official list of `when.type` values, required fields, and whether `toolTypes` accepts only strings or also category tokens (`read`, `write`, `@mcp`). |
| **Hook execution order** | Multiple hooks on the same event: **sort key** (name, creation time, user priority?). We rely on **filename** for `agentStop` ordering — need confirmation or a priority field. |
| **`runCommand` environment** | For **Pre Tool Use** / **Post Tool Use**: exact **env vars** or **stdin JSON** with tool name, arguments, and **target file paths**. Unblocks `agora-kiro summarize` / `index` without Ask Kiro. |
| **Working directory** | When Kiro spawns MCP or shell hooks, **cwd** = workspace root? File URI root? Explains occasional path bugs. |
| **`fileSaved` vs UI “File Save”** | Confirm JSON enum matches docs; we ship `fileSaved` in JSON. |
| **Ask Kiro loop rules** | How Kiro prevents infinite hook ↔ agent loops; we tell the model “stop after one tool” — need to match Kiro’s actual guardrails. |
| **Credits model** | Which actions bill; helps decide shell vs Ask Kiro product-wide. |
| **Remote MCP** | If users move `agora-kiro` off local stdio, any constraints (auth, timeout) we should document. |

---

## 3. What stands out — **drift / misuse / risk**

These are **our** issues or **Kiro vs our assumptions**, not “Kiro is wrong.”

### 3.1 Two different “session context” shapes (real bug class for UX)

| Path | Implementation |
|------|------------------|
| **`agora-kiro inject`** (Kiro prompt hook) | **`_build_recalled_context()`** only — DB + git bundle (see `session.py`). |
| **`get_session_context` MCP** | Loads **`session.json`**, may merge recalled into `context`, then **`session_restored_banner(session, token_budget=3000)`** (`compress.py`). |

**Steering** says inject already loaded context and not to spam `get_session_context` — but the **text is not the same format**. Risk: user/model confusion and duplicated or contradictory blocks if both fire.

**Fix direction:** unify output, or document “inject = recall bundle; get_session_context = structured session banner.”

### 3.2 `cli.py` `memory-server` docstring says **“6 tools”**

There are **16** tools in `_TOOLS` (`memory_server.py`). Stale doc misleads anyone skimming `cli.py` only.

### 3.3 MCP `index_file` handler vs `indexer.index_file` return type

`index_file()` in **`indexer.py`** returns **`int`** (symbol count). **`_handle_index_file`** in `memory_server.py` does `result.get("symbols", 0)` only if `isinstance(result, dict)` — so the success message often says **`0 symbols`** even when indexing succeeded.

### 3.4 **`KIRO.md`** vs actual hook JSON (**tool names**)

- **`KIRO.md`** hook table was updated to **`fsWrite` / `fsAppend`** to match **`.kiro/hooks/agora-index-after-write.kiro.hook`**.

Residual risk: Kiro’s real matcher is whatever the product accepts; if tool names change again, **docs and JSON can drift** unless we use stable **category** matchers (see K2 in **`docs/REFACTOR_REWIRE_PLAN.md`**).

### 3.5 **Claude-optimized** pre-read vs **Kiro Ask Kiro** pre-read

Claude’s **`pre-read.sh`** uses **`agora-kiro summarize <path> --json-output`** with path from hook stdin — **no extra LLM loop for summarize**.

Kiro uses **`askAgent`** prompts that tell the model to call **`summarize_file`** MCP — **extra credits**, model compliance required.

Not a “misuse” of Kiro API, but a **product inconsistency** and higher cost.

### 3.6 **Narrow `toolTypes`** vs Kiro’s **category** matchers

We use concrete names (`readCode`, `grepSearch`, …). Kiro docs describe **`read`**, **`write`**, **`@mcp`**, regex. **Risk:** renames break hooks; **mitigation:** categories where stable.

### 3.7 **`agentStop` hook ordering**

We assume **lexicographic** hook name order so **`agora-summarize-interaction`** runs before **`agora-auto-checkpoint`**. If Kiro order is undefined or user-defined, **checkpoint could run before** `store_learning`.

### 3.8 **`log_search` stores a “learning”**

Implementation uses **`store_learning`** with tags `search-log` + tool name — correct for searchability, but **semantically** it’s not only “human findings.” Steering/table language should say **search logs live in learnings table** to avoid confusion when inspecting DB.

### 3.9 **API MCP (`agent.py`) vs memory MCP**

Two different stdio servers: **`agora-kiro serve`** (per API) vs **`agora-kiro memory-server`**. Kiro should only need **memory-server** for this product; mixing both in one project increases tool surface and confusion.

---

## 4. Suggested doc / code follow-ups (prioritized)

1. Fix **`memory-server` docstring** tool count; align **`KIRO.md`** table with **`fsWrite`/`fsAppend`**.  
2. Fix **`_handle_index_file`** message when `index_file` returns `int`.  
3. Add one paragraph to **steering** or **`KIRO_USER_PATH_AND_CONTEXT.md`**: **inject** vs **get_session_context**.  
4. Obtain Kiro’s **hook env contract** → draft **`docs/KIRO_ENV_CONTRACT.md`**.  
5. Confirm **hook ordering** with Kiro → update **`KIRO_HOOKS.md`** / insights doc.

---

## 5. Cross-links

- **`docs/KIRO_USER_PATH_AND_CONTEXT.md`** — user journey + full `cli`/`memory_server` read notes.  
- **`docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`** — product insights + backlog.  
- **`docs/KIRO_HOOKS.md`** — hook file inventory.  
- **`docs/REFACTOR_REWIRE_PLAN.md`** — living refactor log: Kiro doc asks, file read matrix, tweak / rewire / breaker.  
- **`docs/planning/`** — **agora-kiro-kiro** planning only (Kiro IDE doc inputs; not core user-facing agora docs).

---

*Re-run summarize or diff this file when adding large new modules or changing MCP/tool surface.*
