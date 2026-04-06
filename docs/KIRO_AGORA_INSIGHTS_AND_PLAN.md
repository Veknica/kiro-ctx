# Kiro × agora-kiro — insights, what works, and what to build next

**Purpose:** This is internal design memory for evolving the **Kiro-first** line of work (the experience you get when MCP + steering + `.kiro/hooks` are wired to `agora-kiro`). Use it to **plan improvements**, **onboard**, and **decide what to document next** — not as marketing copy.

**Companion pieces:**
- **`docs/KIRO_HOOKS.md`** — concrete mapping: trigger types, tool matching, inventory of every shipped `.kiro.hook`.
- **`docs/KIRO_PLATFORM_AND_AGORA_PLAN.md`** — where durable state lives (Kiro vs `memory.db`) and related repos on your machine.
- **`docs/KIRO_USER_PATH_AND_CONTEXT.md`** — Kiro user journey through CLI/MCP + context/token table (investigation / new-product).
- **`docs/KIRO_CODEBASE_AUDIT_AND_GAPS.md`** — module inventory vs Kiro, what to ask Kiro docs for, and known drift/risks.
- **`docs/REFACTOR_REWIRE_PLAN.md`** — Kiro doc checklist, agora file read status, finding template (tweak → rewire → full rewrite).
- **`docs/planning/`** — **agora-kiro-kiro** only: Kiro IDE inputs + product direction (not shipped user docs).
- **`KIRO.md`** — operator setup (install, copy files, verify).

---

## 1. What we believe works today

| Layer | Role | Status |
|--------|------|--------|
| **MCP `agora-kiro`** | Exposes DB + tools (`summarize_file`, `index_file`, `store_learning`, …) to the agent | **Core** — same server other editors use; Kiro is “just” another MCP client. |
| **Steering** | Tells the model *when* to call tools and when to **stop** after one MCP call (e.g. after `store_learning`) | **Essential** if you skip hooks — empty steering = silent failure even when MCP connects. |
| **Shell hooks** | `inject` / `checkpoint` on prompt, agent stop, spec tasks | **Cheap, reliable** — no credits; deterministic; good default. |
| **Ask Kiro hooks** | Pre-read summarize, post-write index, grep logging, interaction summary | **Works** but **costs credits** and depends on the model following the prompt + steering. |
| **Lexicographic ordering** | Naming `agora-summarize-interaction` so it runs before `agora-auto-checkpoint` on `agentStop` | **Fragile convention** — works until Kiro changes ordering rules; worth revisiting explicitly in product docs. |
| **`memory.db` + project scoping** | Git-remote–keyed memory separate from Kiro’s chat files | **Clear split of concerns** — Kiro owns chat UX; agora-kiro owns cross-session **structured** memory. |

---

## 2. Grounded elaboration — tied to this repo’s code (not hand-wavy)

This section expands the slogans you asked about and ties them to **files that exist today**.

### 2.1 Ground truth: what is shell vs Ask Kiro in `.kiro/hooks/`

Counted from the shipped JSON (`then.type`):

| Action | Hooks (file name prefix) | Count |
|--------|---------------------------|------|
| **`runCommand` (shell)** | `agora-session-inject`, `agora-inject-before-task`, `checkpoint-after-task`, `agora-auto-checkpoint` | **4** |
| **`askAgent` (Ask Kiro)** | `agora-summarize-interaction`; `agora-summarize-before-read`; `agora-index-after-write`; `agora-log-grep-results`; `agora-index-on-save` | **5** |

Hooks now use Kiro's stable **category matchers** (`read`, `write`) rather than concrete tool names. The previous 3 pre-read hooks and 3 post-write hooks are each collapsed into one. So **today** the Kiro pack is **not** shell-only: anything that needs **`summarize_file` / `read_file_range` / `index_file` / `log_search` / `store_learning` over MCP** is implemented as **Ask Kiro** instructions, because the hook JSON does not invoke `agora-kiro summarize` / `agora-kiro index` with a file path.

**CLI already exists for a shell-first future:** `agora-kiro inject` and `agora-kiro checkpoint` (see `agora_kiro/cli.py`); `agora-kiro summarize <path> [--json-output]` and `agora-kiro index <path>` (same module). Claude-style pre-read uses `--json-output`; the same primitive could drive Kiro **if** Kiro exposes the target path (or JSON on stdin) to shell hooks — that contract is what **`docs/KIRO_ENV_CONTRACT.md`** is for once we know it.

**If your product direction is “shell first + tokens/context”:** you are aiming to **replace as many of the 9 Ask Kiro hooks as possible** with `runCommand` lines that call `agora-kiro …`. **Blockers today:** (1) per-event **file path** (and for grep, query + paths) into the shell; (2) **interaction summary** — a one-sentence `store_learning` is inherently LLM-shaped unless you drop it or pipe fixed text from somewhere else.

### 2.2 “Shell = cheap / Ask Kiro = credits + compliance” — elaborated

- **Shell:** Kiro runs a subprocess; **no second agent loop** → **no extra LLM credits** for that step. Success path: **stdout** is appended to the agent context (per Kiro’s hook behavior). Our shell hooks only run `agora-kiro inject --quiet` or `agora-kiro checkpoint --quiet` — both are **deterministic** and write/read project + DB via `session.py` / vector store.
- **Ask Kiro:** Kiro injects a **prompt**; the **model** may call MCP tools. That **does** consume credits and can fail if the model **does not** follow steering (e.g. extra tool calls after `store_learning`).

**Token / context angle:** The **main token win** in this stack is **summarize → read range**, not the shell hooks. Steering explicitly tells the model to call `summarize_file` then `read_file_range` (`.kiro/steering/agora-kiro.md`). The MCP tool descriptions in `agora_kiro/memory_server.py` reinforce the same. **Shell `inject`** then adds a **bounded** text block: `_build_recalled_context()` in `agora_kiro/session.py` is documented there as targeting **~350 tokens** for the structured inject sections (checkpoint, learnings, git, symbols, etc. — see the docstring and implementation starting ~line 576).

### 2.3 “Steering must be non-empty” — elaborated

**What steering is in our tree:** `.kiro/steering/agora-kiro.md` starts with YAML frontmatter `inclusion: always` so Kiro **always** merges this file into the agent’s instructions.

**What it does:** It names **`agora-kiro`**, lists which hooks run and at what **cost** (free vs small), gives the **CRITICAL** block for `agora-summarize-interaction` (exactly one `store_learning` then stop), and rules like “don’t call `get_session_context` every prompt — inject already loaded context” and “before reading any file, `summarize_file` then `read_file_range`”.

**Why “empty = failure”:** MCP only **registers tools**; it does not force the model to call them. If global or project steering is **blank or still the template**, the model has **no standing instruction** to use `get_session_context`, `summarize_file`, etc. Hooks help, but **Ask Kiro** hooks are themselves **prompts** — steering is what keeps behavior **consistent** across turns and aligns with **hook ordering** (e.g. stop after one tool).

### 2.4 “Kiro chat files ≠ agora memory” — elaborated

- **Kiro** persists **conversation UI state** under its app data (see `docs/KIRO_PLATFORM_AND_AGORA_PLAN.md` — e.g. `*.chat` under `kiro.kiroagent`). That is **opaque to agora-kiro**, not keyed the same way as our **project_id** (git remote), and not designed for **structured** recall (learnings, checkpoints, symbol index, file snapshots).
- **agora-kiro** stores **long-lived project memory** in **`~/.agora-kiro/memory.db`** (override with `AGORA_KIRO_DB`) plus **active working state** in **`.agora-kiro/session.json`** (see header comments in `agora_kiro/session.py`). **`inject`** composes context from the **DB + git** via `_build_recalled_context()` — checkpoints (tagged learnings), recent learnings, git log, uncommitted files, symbol hints — not from Kiro’s chat files.

So the **second layer** is intentional: **chat** is for the current thread; **memory.db** is for **cross-session, cross-thread** continuity and search.

### 2.5 “Two `agentStop` hooks — ordering by name is a hidden dependency” — elaborated

Both hooks use `"type": "agentStop"`:

1. **`agora-summarize-interaction.kiro.hook`** — `askAgent` → model should `store_learning` once.
2. **`agora-auto-checkpoint.kiro.hook`** — `runCommand` → `agora-kiro checkpoint --quiet`.

The **summarize-interaction** file is named so that, **if** Kiro runs `agentStop` hooks in **lexicographic order** by hook name, **“agora-summarize-interaction” sorts before “agora-auto-checkpoint”** — so the learning is stored **before** checkpoint snapshots. **We do not have a Kiro priority field in the JSON** in this repo — this is an **assumption** about ordering. If Kiro changes ordering (parallel execution, user-defined priority, undefined order), **checkpoint could run before learning**, and the next `inject` could miss the just-finished turn’s sentence. **Mitigation ideas:** document the assumption in release notes; if Kiro adds **explicit order / priority**, set it; or **collapse** to one `agentStop` flow (harder).

### 2.6 Docs / inputs that would make this less speculative

**From the repo (we already have):** `agora_kiro/cli.py` (`inject`, `checkpoint`, `summarize`, `index`), `agora_kiro/session.py` (`_build_recalled_context`, session file layout), `agora_kiro/memory_server.py` (MCP tool schemas), `.kiro/hooks/*.kiro.hook`, `.kiro/steering/agora-kiro.md`, `docs/DATABASE.md` + `DATABASE_AND_STRUCTURED_LAYER.md` for what the DB holds.

**Still valuable to add or obtain:**

| Need | Why |
|------|-----|
| **Kiro shell hook env / stdin spec** | Unblocks **shell-only** summarize + index (tokens without Ask Kiro). |
| **`docs/KIRO_TESTING.md`** | Proves each hook fired after changes — no guessing. |
| **Clarified merge of DATABASE docs** | One “schema”, one “runtime / inject” — less duplicate mental model. |

---

## 3. Insights gained (design-relevant)

**From Kiro’s hook model (behavioral rules, not links):**

1. **Two actions only:** agent prompt vs shell. Anything that can be a **CLI** should stay CLI to save credits and reduce nondeterminism.
2. **Pre Tool Use + non-zero exit** can **block** the tool; **Prompt Submit** can be blocked the same way. That’s a possible **future gate** (e.g. “must summarize first”) if we ever shell-wrap pre-read instead of Ask Kiro — but it needs **path/env contract** from Kiro.
3. **Tool matching** can be **broad** (`read`, `write`, `@mcp`, regex) or **narrow** (exact names). We chose **narrow** names (`readCode`, `fsWrite`, …) for clarity; **tradeoff:** breaks on Kiro renames → **migration checklist** on every Kiro upgrade.
4. **`USER_PROMPT`** on Prompt Submit (shell) is available for **optional** flows: logging, lightweight recall, guardrails — **not implemented** in our default hooks yet.
5. **File Save** (`fileSaved`) is separate from **post write** tools — we use both so **manual saves** still re-index.
6. **Spec tasks** get their own pre/post hooks — good fit for **inject** / **checkpoint** per task without overloading chat turns.

**From shipping this repo:**

7. **PATH:** MCP subprocess often lacks full shell PATH → **full path to `agora-kiro`** in `mcp.json` is a recurring fix.
8. **Steering + hooks together** beat “MCP only” for **consistency**; steering alone is enough for a minimal setup; hooks add **automation**.
9. **Interaction summary** (`store_learning` on `agentStop`) turns chat into **durable one-liners** — high leverage for next-session inject if quality stays high.

---

## 4. What is fragile or unknown

| Area | Risk |
|------|------|
| **Tool names** | `toolTypes` in JSON must match Kiro’s current built-ins. |
| **Hook ordering** | Relying on **file/name sort** for `agentStop` sequence. |
| **Ask Kiro hooks** | Model may ignore “stop after one tool” unless steering is tight. |
| **Env vars** | Unclear without a matrix from Kiro: what file path / JSON is exposed to shell hooks for pre/post tool events — **blocks** a pure-shell index/summarize pipeline. |
| **Two repos** | `agora-kiro` vs `kiro-ctx` — risk of **doc and hook drift** unless sync is intentional. |

---

## 5. Improvement themes (backlog, not committed roadmap)

Prioritize however you like; grouped for planning.

**A. Hardening**
- Smoke script: “MCP up + one inject + one tool call” from a clean project.
- After each Kiro upgrade: **diff tool list** → update `toolTypes` or switch to category `read` / `write` where stable.
- Document **explicit** `agentStop` ordering if Kiro adds priority fields.

**B. Cost / latency**
- Replace Ask Kiro **index** hooks with **shell** `agora-kiro index <path>` **if** Kiro documents stable env for touched path.
- Batch or shorten pre-read prompts if credits are an issue.

**C. Product**
- Optional **Power**-style bundle (single folder to copy) aligned with how you ship `kiro-ctx`.
- **Steering** variants: “minimal” vs “full hooks” so users pick credit tradeoff.

**D. Sync**
- Single **changelog** section for “Kiro integration” when hooks or steering change.
- Rule of thumb: **kiro-ctx** = Kiro-first narrative + experiments; upstream **agora-kiro** = shared core — decide what must stay identical (MCP contract, DB schema).

---

## 6. Doc map — what we have vs what’s still useful

| Doc | Role now | Gap / next step |
|-----|----------|-----------------|
| `KIRO.md` | Setup + quick hook table | Keep short; deep detail lives in `docs/`. |
| `docs/KIRO_HOOKS.md` | Trigger/action model + **full hook inventory** | Update when any `.kiro.hook` changes. |
| `docs/KIRO_USER_PATH_AND_CONTEXT.md` | End-to-end Kiro user path + **context/token table** | Update when inject/MCP/hook behavior changes. |
| `docs/KIRO_PLATFORM_AND_AGORA_PLAN.md` | Storage split, local repos, macOS paths | Could add **env var matrix** when we learn it from Kiro. |
| `docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md` | **This file** — insights + backlog + doc map | Revise after each planning session. |
| `docs/DATABASE.md` | Schema / tables | Good for implementers. |
| `docs/DATABASE_AND_STRUCTURED_LAYER.md` | Inject vs DB vs disk | **Merge or split roles** with `DATABASE.md` so one is “schema” and one is “runtime behavior” (called out in §4 checklist in platform doc). |
| `.kiro/steering/agora-kiro.md` | Live agent rules | Version with hook changes; consider a **short “why”** comment block in a stub doc (steering file stays lean). |
| `power-agora-kiro/POWER.md` | Distribution shape | Align with backlog **C** if you publish a Power. |

**Docs worth adding when you have bandwidth**

1. **`docs/KIRO_TESTING.md`** — repeatable verification (new project, copy `.kiro`, expected MCP tools, one prompt that should trigger inject, one read that should trigger summarize).  
2. **`docs/KIRO_ENV_CONTRACT.md`** — *only when known:* environment variables / stdin JSON Kiro passes to shell hooks per event type (unblocks shell-only index/summarize).  
3. **`docs/SYNC_KIRO_CTX.md`** — one page: what must match between `kiro-ctx` and `agora-kiro`, how you merge, who owns README voice.

---

## 7. One-line summary

**Kiro gives chat + hooks + steering; agora-kiro gives a git-aware, queryable memory layer.** The Kiro-specific work is **gluing** those with minimal credits, **stable tool matching**, and **steering that matches hook behavior** — this file is where we **record what we learned** and **what to improve next**.

---

*Update this document when you change hooks, steering, or MCP tool surface for Kiro.*
