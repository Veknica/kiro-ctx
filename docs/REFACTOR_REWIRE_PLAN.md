# Refactor / rewire plan (Kiro × agora-kiro)

**What this is:** A working doc for **findings → options**. You’re not committing to a big bang refactor. Use **tweak** first, **rewire** when behavior crosses module boundaries, and treat **full rewrite** as the **breaker switch** only when the model is wrong (wrong abstraction, unmaintainable split).

**How to add a row:** Copy the template under §3. Link deeper detail to **`docs/KIRO_CODEBASE_AUDIT_AND_GAPS.md`** when the finding is already written up there.

**Companion docs:** `docs/KIRO_HOOKS.md`, `docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`, `docs/KIRO_USER_PATH_AND_CONTEXT.md`, `KIRO.md`.

---

## 1. Kiro documentation we still need (checklist)

We do **not** have stable filenames from Kiro’s repo/site in this project; treat each line as **something to locate in official Kiro docs or support** (pages, spec sections, or release notes).

| # | What to find | Why |
|---|----------------|-----|
| K1 | **`.kiro.hook` schema** — all `when.type` values, required fields, validation rules | Match JSON we ship; avoid invalid hooks across versions. |
| K2 | **`toolTypes` semantics** — literal tool names vs categories (`read`, `write`, `@mcp`), regex | Decide if we should migrate hooks to categories to survive renames. |
| K3 | **Multiple hooks, same event — execution order** | We rely on naming for `agentStop` (`agora-summarize-interaction` before `agora-auto-checkpoint`). |
| K4 | **`runCommand` contract** — env vars and/or **stdin JSON** for Pre/Post Tool Use (tool name, args, **paths**) | Enables **shell-first** summarize/index without Ask Kiro. |
| K5 | **Working directory** for hooks and MCP child process | Path bugs, relative vs absolute file args. |
| K6 | **`fileSaved` (and friends)** — exact enum strings vs UI labels | Align `agora-index-on-save.kiro.hook` with product truth. |
| K7 | **Ask Kiro** — loop limits, interaction with MCP, “stop after one tool” guarantees | Steering text must match real guardrails. |
| K8 | **Credits / billing** — what counts as a billable step (Ask Kiro vs main turn) | Product tradeoff: shell vs agent hooks. |
| K9 | **Remote MCP** — timeouts, auth, stdio vs HTTP | If we document non-local `agora-kiro`. |

When you obtain a source, add a column **“Source URL / doc id + date”** in your own notes or append a small **§1.1 Provenance** table here.

### 1.1 Kiro files / excerpts you add later

**Large Kiro IDE doc dumps** for **agora-kiro-kiro** planning belong in **`docs/planning/`** (see **`docs/planning/README.md`**) so they are **not** treated as shipped agora user docs.

For **this** checklist, use **§1.1** only for short provenance you want next to refactor rows: add a row with **path**, **topic**, **date / version**, and cite it in **§4** column **B** when useful.

*(Provenance table — fill as you go.)*

| Local path / link | Topic | Kiro version or date |
|-------------------|--------|----------------------|
| *—* | *—* | *—* |

---

## 2. agora-kiro files — read / audit status

**Legend:** **Full** = line-by-line read in service of Kiro work. **Summarize** = `agora-kiro summarize` + structural pass, not a full read. **Scoped** = grep / handler-only. **N/A** = not on Kiro memory path.

| Path | Status | Kiro memory path? |
|------|--------|-------------------|
| `agora_kiro/cli.py` | **Full** | Yes |
| `agora_kiro/memory_server.py` | **Full** | Yes |
| `agora_kiro/session.py` | Summarize | Yes |
| `agora_kiro/vector_store.py` | Summarize | Yes |
| `agora_kiro/indexer.py` | Summarize | Yes |
| `agora_kiro/summarizer.py` | Summarize | Yes |
| `agora_kiro/compress.py` | Summarize | Yes |
| `agora_kiro/embeddings.py` | Summarize | Yes |
| `agora_kiro/log.py` | Scoped | Indirect |
| `agora_kiro/models.py` | Scoped | N/A |
| `agora_kiro/scanner.py` | Summarize | N/A |
| `agora_kiro/agent.py` | Summarize | N/A (`serve` / API MCP) |
| `agora_kiro/workflows.py` | Summarize | N/A |
| `agora_kiro/extractors/*` | Not audited | N/A |
| `.kiro/hooks/*.kiro.hook` | Reviewed (inventory) | Yes |
| `.kiro/steering/agora-kiro.md` | Reviewed | Yes |
| `.claude/hooks/*`, `.cursor/hooks/*` | Not Kiro | **Contrast** reference (shell-first line) |

**Update this table** when you finish a full read of another module.

---

## 3. Finding template (A / B / C + escalation)

Use one row per finding.

**Column B — name:** **`B — Contrast`** (not “peer,” so we don’t lose context). Put **anything that contrasts with column A** here:

| Kind of contrast | Examples |
|--------------------|----------|
| **Shell-first editor line (default)** | **Claude Code / Cursor hooks** in this repo — e.g. `pre-read.sh` + `agora-kiro summarize --json-output` (no extra LLM for summarize). |
| **Official Kiro behavior** | Quotes or pointers to **§1.1** or **`docs/planning/KIRO_EDITOR_DOCS_INPUT.md`**. |
| **Other product / prior art** | “VS Code task,” “Git hook,” etc., when useful. |

If a row has **no** good contrast, write **N/A** in **B** and lean on **C** + fixes.

| Field | What to write |
|--------|----------------|
| **ID** | Short slug, e.g. `F-001` |
| **A — Agora + Kiro today** | What we ship: hook type, CLI, MCP tool, code entrypoints. |
| **B — Contrast** | Claude/Cursor shell line, **and/or** Kiro doc excerpt + **§1.1** path, **and/or** other reference. |
| **C — Causes** | Symptom: cost, confusion, bug, drift, fragility. |
| **Tweak** | Doc fix, one function, steering copy, hook JSON only. |
| **Rewire** | New shared helper, change hook action type, align inject vs MCP output, new CLI flag consumed by `runCommand`. |
| **Full rewrite (breaker)** | New process model, split package, replace MCP surface, new storage — only if rewire can’t fix the **core** mistake. |

---

## 4. Logged findings (seed rows — extend as you go)

| ID | A — Agora + Kiro today | B — Contrast | C — Causes | Tweak | Rewire | Full rewrite (breaker) |
|----|-------------------------|--------------|------------|-------|--------|-------------------------|
| F-001 | Prompt hook: `inject` → `_build_recalled_context()`. MCP: `get_session_context` → session.json + `session_restored_banner`. | N/A (no second implementation to compare yet; add Kiro doc quote here if docs clarify “session injection”). | Model told “inject already loaded it”; **two different text shapes** → confusion / duplicate context. | Steering + KIRO docs: name the two bundles explicitly. | **One function** used by both inject and MCP for the “recall” paragraph; banner as optional block. | New session model API — only if we redesign all consumers. |
| F-002 | Pre-read on Kiro: **Ask Kiro** → `summarize_file` + `read_file_range` MCP. | **Claude:** `pre-read.sh` → `agora-kiro summarize --json-output` from stdin; **no** extra LLM for summarize. *(Add **Kiro official** stdin/env for Pre Tool Use in **B** once §1.1 has it.)* | **Credits** on every read boundary; model must comply. | Document cost tradeoff in `KIRO.md` / hooks doc. | If K4 satisfied: **runCommand** pre-read calling `agora-kiro summarize` + pass outline into context (product-dependent). | Drop MCP summarize entirely for Kiro — only if shell contract is always sufficient. |
| F-003 | ~~Post-write: multiple **Ask Kiro** hooks (`fsWrite`, `strReplace`, `editCode`, `fileSaved`) can all drive `index_file`.~~ **FIXED:** collapsed to one hook using `write` category matcher. `fileSaved` hook still separate (covers manual saves). | **Other stacks:** single debounced index or one post-save hook. | Redundant **index_file** / extra turns. | ~~Steering: “skip if same path indexed this turn”~~ Done via hook consolidation. | **Debounce** in `indexer`/`vector_store` by (path, mtime) — still open for `fileSaved` + `write` overlap. | Central event bus for file changes — heavy. |
| F-004 | ~~MCP `_handle_index_file` expects dict; `indexer.index_file` returns **int**.~~ **FIXED:** handler now uses return value directly as `int`. | N/A | ~~Success text shows **0 symbols** when work succeeded.~~ | Done. | N/A | N/A |
| F-005 | `agentStop`: `agora-summarize-interaction` then `agora-auto-checkpoint` assumed **lexicographic** order. | Explicit ordering in other systems. | **Checkpoint before learning** if order wrong. | Confirm with K3; document assumption. | Hook **priority** field if Kiro adds it; or merge into one hook with two steps. | N/A |
| F-006 | 16 tools on `agora-kiro`; Kiro registers **whole** server. | Smaller tool lists in minimal integrations. | Cognitive load; “what is Kiro minimal?” unclear. | Doc: **minimal tool subset** for mental model. | **`memory-server --tools`** whitelist or two server modes. | Split package: `agora-kiro-core` vs full. |
| F-007 | ~~`cli.py` docstring still says memory-server has **6 tools**.~~ **FIXED:** docstring updated to list all 16 tools. | N/A | ~~Misleading for contributors.~~ | Done. | N/A | N/A |

---

## 5. Escalation rule of thumb

1. **Tweak** until the **user-visible lie** or **small bug** is gone.  
2. **Rewire** when the same logic is duplicated (inject vs MCP, multiple index hooks) or when **Kiro gives us stdin/env** and we can move work off Ask Kiro.  
3. **Full rewrite** when the **data model or public contract** is wrong — not when a one-line fix or a shared function would do.

---

*Last seeded: Mar 2026. Bump the date when you add Kiro provenance or change status rows.*

**agora-kiro-kiro planning** (Kiro IDE doc corpus, product backlog): **`docs/planning/`** — keep that separate from wiring findings into core `KIRO.md` / hooks docs until you promote deliberately.
