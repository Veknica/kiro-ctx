# Kiro platform context — storage, repos, and how agora-kiro fits

**Why this exists:** When we improve the **Kiro-first** experience, we need a shared picture of **where Kiro keeps its own state**, **where agora-kiro keeps memory**, and **which local repos we use as references** — without mixing that up with install steps (`KIRO.md`) or hook mechanics (`docs/KIRO_HOOKS.md`).

**Planning and backlog:** **`docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`**

---

## 1. Kiro at a glance (for design decisions)

- AI-first IDE in the VS Code lineage: **MCP**, **steering** (Markdown), **hooks** (events → shell or agent prompt), **Powers** (bundled packs).
- **Project config:** `.kiro/settings/mcp.json`, `.kiro/steering/`, `.kiro/hooks/`.
- **Global config:** `~/.kiro/settings/`, `~/.kiro/steering/` — same ideas, all workspaces.

**Why it feels different from plain VS Code:** same broad **Electron / `User/` / SQLite** patterns, plus **agent extension** data (e.g. `kiro.kiroagent`) and chat payloads separate from your repo.

---

## 2. Local repos we use as references

Paths are examples; adjust for your machine.

| Location | Use for us |
|----------|------------|
| `~/Desktop/Kiro` | Upstream product materials — how Kiro describes itself |
| `~/Desktop/kiro-powers` | How vertical **Powers** combine MCP + steering + hooks |
| `~/Desktop/spirit-of-kiro` | Demo app — steering and “mostly agent-written” workflow patterns |
| `~/Desktop/powers`, `~/Desktop/elixir/.kiro` | Optional side projects |
| This repo | **Canonical** agora-kiro Kiro wiring: `KIRO.md`, `.kiro/*` |

---

## 3. macOS — where Kiro stores data (reference)

Base: `~/Library/Application Support/Kiro/`

| Path | Role |
|------|------|
| `User/workspaceStorage/<id>/` | Per folder/workspace; `workspace.json` → `file:///...` |
| `User/globalStorage/kiro.kiroagent/` | Agent extension global state |
| `User/globalStorage/kiro.kiroagent/**/*.chat` | Per-conversation payloads — **private** |
| `state.vscdb` (+ backup) | Extension SQLite-style state |
| Caches (`blob_storage`, `Cache`, …) | Not project memory |

**Design implication:** Kiro’s store is **chat- and session-oriented** and **not** a substitute for **git-keyed, searchable project memory**. agora-kiro’s `memory.db` (see `docs/DATABASE.md`) is the intentional second layer.

---

## 4. Lessons that stuck (verify on your Kiro build)

- MCP server is **portable**; **hooks are per-IDE** and must match events + tool names.
- **Empty global steering** + working MCP still fails — the model is never told to call tools.
- **Full path** to `agora-kiro` in MCP config when the subprocess has a thin `PATH`.
- **Smoke check:** `agora-kiro` connected + `get_session_context` runs when asked.

---

## 5. agora-kiro vs Kiro — division of labor

| Need | Kiro | agora-kiro |
|------|------|------------|
| Chat transcript | Extension / `.chat` | Not the source of truth |
| Next-day “what was I doing?” | Scroll / UI | `inject`, sessions, checkpoints |
| Durable facts, symbols, file history | Limited unless you build it | DB + MCP tools |
| Large-file discipline | Hooks + steering | `summarize_file`, snapshots |

**Doc hygiene:** clarify roles of **`DATABASE.md`** (schema) vs **`DATABASE_AND_STRUCTURED_LAYER.md`** (inject / cache / disk vs DB) so implementers are not confused.

---

## 6. References inside this repo

- **`KIRO.md`** — setup
- **`docs/KIRO_AGORA_INSIGHTS_AND_PLAN.md`** — insights, backlog, doc map
- **`docs/KIRO_HOOKS.md`** — hook inventory and trigger mapping
- **`docs/KIRO_USER_PATH_AND_CONTEXT.md`** — user path + context/token table
- **`.kiro/settings/mcp.json`**, **`.kiro/steering/agora-kiro.md`**, **`.kiro/hooks/*.kiro.hook`**
- **`power-agora-kiro/POWER.md`**

---

## Provenance (for our records)

Concepts cross-check with Kiro’s public docs and changelog; local **Kiro**, **kiro-powers**, and **spirit-of-kiro** clones inform packaging and workflow examples. macOS paths follow the usual **Application Support** layout for Electron/VS Code–family apps. agora-kiro wiring is defined in **this repository**. Re-verify paths after major Kiro upgrades.
