"""
cli.py — agora-kiro command line interface.

Memory commands:
    agora-kiro memory-server   — start the MCP server for Kiro
    agora-kiro inject          — load last session context into current prompt
    agora-kiro checkpoint      — save current session progress
    agora-kiro complete        — archive session to long-term memory
    agora-kiro status          — show DB path and row counts
    agora-kiro memory          — dump sessions, learnings, symbols
    agora-kiro summarize       — get AST outline of a file
    agora-kiro index           — index a file's symbols into memory DB
    agora-kiro recall          — search past learnings
    agora-kiro learn           — store a learning manually
    agora-kiro track-diff      — record what changed in a file and why
    agora-kiro show            — rich view of current session + git state

Requires: pip install agora-kiro
Rich output via 'rich' if installed, plain fallback otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import click


# --------------------------------------------------------------------------- #
#  CLI group                                                                   #
# --------------------------------------------------------------------------- #

@click.group()
@click.version_option(package_name="agora-kiro")
def main():
    """agora-kiro — Persistent memory for Kiro AI coding sessions."""
    from agora_kiro.log import configure
    configure()


# --------------------------------------------------------------------------- #
#  status                                                                      #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--project", "-p", is_flag=True, default=False,
              help="Scope counts to the current repo only")
def status(project):
    """Show current session state and recent call stats.

    \b
    agora-kiro status           # global counts
    agora-kiro status --project # scoped to this repo
    agora-kiro status -p
    """
    from agora_kiro.session import load_session, _get_project_id
    from agora_kiro.compress import compress_session, _session_age_str
    from agora_kiro.vector_store import get_store

    session = load_session()
    if not session:
        _echo("No active session. Start one with:")
        _echo("   agora-kiro checkpoint --goal \"What you're trying to do\"")
    else:
        age = _session_age_str(session)
        started = session.get("started_at", "")[:19].replace("T", " ")
        last = session.get("last_active", "")[:19].replace("T", " ")
        _echo(f"session: {session.get('session_id', 'unknown')}")
        _echo(f"  started:     {started} UTC")
        _echo(f"  last active: {last} UTC  ({age})")
        _echo(compress_session(session, level="detail"))

    store = get_store()
    conn = store._conn_()
    if project:
        pid = _get_project_id()
        if not pid:
            _echo("No project_id (not in a git repo).")
            return
        sessions   = conn.execute("SELECT COUNT(*) FROM sessions WHERE project_id=?", (pid,)).fetchone()[0]
        learnings  = conn.execute("SELECT COUNT(*) FROM learnings WHERE project_id=?", (pid,)).fetchone()[0]
        snapshots  = conn.execute("SELECT COUNT(*) FROM file_snapshots WHERE project_id=?", (pid,)).fetchone()[0]
        symbols    = conn.execute("SELECT COUNT(*) FROM symbol_notes WHERE project_id=?", (pid,)).fetchone()[0]
        _echo(f"\nproject: {pid}")
        _echo(f"  {sessions} sessions  {learnings} learnings  {snapshots} file snapshots  {symbols} symbols")
    else:
        stats = store.get_stats()
        _echo(f"\nmemory (global): {stats['sessions']} sessions  {stats['learnings']} learnings  "
              f"{stats['api_calls']} API calls  [DB: {stats['db_path']}]"
              f"  [vector: {'on' if stats['vector_search'] else 'off'}]")


# --------------------------------------------------------------------------- #
#  memory                                                                     #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--limit", "-n", default=10, help="Max sessions and learnings to list (default 10)")
@click.option("--verbose", "-v", is_flag=True, help="Show stored AST summaries and code blocks from the DB")
@click.argument("limit_arg", required=False, type=int)
def memory(limit, limit_arg, verbose):
    """Show DB path, counts, and a short dump of recent sessions and learnings.

    Each time a file is read and indexed (on-read / on-edit hooks), we store:
    - The full AST summary in file_snapshots.summary
    - The full code block (source lines) per function/class in symbol_notes.code_block
    Use --verbose to print a sample of that stored content.

    For full inspection: sqlite3 <path from status or memory>.

    Examples:
      agora-kiro memory
      agora-kiro memory 20
      agora-kiro memory --limit 20 --verbose
    """
    if limit_arg is not None:
        limit = limit_arg
    from agora_kiro.vector_store import get_store

    store = get_store()
    stats = store.get_stats()
    _echo(f"DB path: {stats['db_path']}")
    _echo(f"Counts:  {stats['sessions']} sessions, {stats['learnings']} learnings, "
          f"{stats['api_calls']} API calls, {stats.get('file_snapshots', 0)} file snapshots (AST), "
          f"{stats.get('symbol_notes', 0)} symbol notes  [vector: {'on' if stats['vector_search'] else 'off'}]")
    _echo("")

    sessions = store.list_sessions(limit=limit)
    if sessions:
        _echo(f"Recent sessions (last {len(sessions)}):")
        for s in sessions:
            status_icon = {"in_progress": "🔄", "complete": "✅", "abandoned": "❌"}.get(
                s.get("status", ""), "📋"
            )
            goal_str = s.get("goal") or ""
            goal = goal_str[:50] + ("..." if len(goal_str) > 50 else "")
            _echo(f"  {status_icon} {s.get('session_id', '')[:44]}  {s.get('last_active', '')[:10]}  {goal}")
        _echo("")
    else:
        _echo("No sessions in DB yet.")
        _echo("")

    learnings = store.search_learnings_keyword("", k=limit)
    if learnings:
        _echo(f"Recent learnings (last {len(learnings)}):")
        for L in learnings:
            finding_str = L.get("finding") or ""
            finding = finding_str[:60] + ("..." if len(finding_str) > 60 else "")
            _echo(f"  · [{L.get('type', 'finding')}] {finding}")
        _echo("")
    else:
        _echo("No learnings in DB yet.")
        _echo("")

    # Indexed files (AST summaries from read/edit hooks)
    snapshots = store.search_file_snapshots("", k=limit)
    if snapshots:
        _echo(f"Indexed files (AST snapshots, last {len(snapshots)}):")
        for snp in snapshots:
            fp = snp.get("file_path", "")
            ts = (snp.get("timestamp") or "")[:10]
            summary = (snp.get("summary") or "").strip()
            symbols_col = snp.get("symbols") or ""
            n_symbols = len(symbols_col.split("\n")) if symbols_col else 0
            try:
                import json
                names = json.loads(symbols_col) if symbols_col.strip().startswith("[") else []
                n_symbols = len(names) if isinstance(names, list) else n_symbols
            except Exception:
                pass
            _echo(f"  📄 {fp}  [{ts}]  {n_symbols} symbols")
            if summary:
                preview = summary[:80] + ("..." if len(summary) > 80 else "")
                _echo(f"      {preview}")
            if verbose and summary:
                # Show stored AST summary (first 400 chars)
                excerpt = summary[:400] + ("\n      ... [truncated]" if len(summary) > 400 else "")
                for line in excerpt.splitlines():
                    _echo(f"      | {line}")
        _echo("")
    else:
        _echo("No file snapshots (AST) in DB yet. Read/edit hooks populate these.")
        _echo("")

    # Symbol index (functions/classes from AST) — each has code_block stored
    symbols = store.search_symbol_notes("", k=min(limit * 3, 50))
    if symbols:
        _echo(f"Symbol index (functions/classes, sample {len(symbols)}):")
        for sym in symbols:
            fp = sym.get("file_path", "")
            name = sym.get("symbol_name", "")
            stype = sym.get("symbol_type", "?")
            line = sym.get("start_line") or "?"
            sig = (sym.get("signature") or "").strip()[:50]
            if len((sym.get("signature") or "")) > 50:
                sig += "..."
            _echo(f"  {stype}: {name} @ {fp}:{line}  {sig}")
        _echo("")
        if verbose:
            syms_with_blocks = store.list_recent_symbol_notes_with_blocks(limit=5)
            if syms_with_blocks:
                _echo("Stored code blocks (sample, last 5 by timestamp):")
                for sym in syms_with_blocks:
                    block = (sym.get("code_block") or "").strip()
                    if not block:
                        continue
                    _echo(f"  --- {sym.get('symbol_type')} {sym.get('symbol_name')} @ {sym.get('file_path')}:{sym.get('start_line')} ---")
                    lines = block.splitlines()[:25]
                    for ln in lines:
                        _echo(f"  | {ln}")
                    if block.count("\n") >= 25:
                        _echo("  | ... [truncated]")
                    _echo("")
    else:
        _echo("No symbol notes in DB yet. Read/edit hooks populate these.")
        _echo("")

    _echo("For full inspection: sqlite3 " + stats["db_path"])


# --------------------------------------------------------------------------- #
#  list-* — see every DB table without SQL                                     #
# --------------------------------------------------------------------------- #

@main.command("list-sessions")
@click.option("--limit", "-n", default=20, help="Max sessions to show")
def list_sessions(limit):
    """List sessions in the DB (no SQL). Same data as memory, sessions section."""
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id
    store = get_store()
    pid = _get_project_id()
    sessions = store.list_sessions(limit=limit, project_id=pid)
    if not sessions:
        _echo("No sessions in DB. Use checkpoint / complete to create some.")
        return
    _echo(f"Sessions (last {len(sessions)}):")
    for s in sessions:
        status_icon = {"in_progress": "🔄", "complete": "✅", "abandoned": "❌"}.get(s.get("status", ""), "📋")
        goal = (s.get("goal") or "")[:60]
        _echo(f"  {status_icon} {s.get('session_id', '')[:44]}  {s.get('last_active', '')[:10]}  {goal}")


@main.command("list-learnings")
@click.option("--limit", "-n", default=20, help="Max learnings to show")
def list_learnings(limit):
    """List recent learnings in the DB (no SQL)."""
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id
    store = get_store()
    learnings = store.search_learnings_keyword("", k=limit, project_id=_get_project_id())
    if not learnings:
        _echo("No learnings in DB. Use learn or let on-stop extract from transcripts.")
        return
    _echo(f"Learnings (last {len(learnings)}):")
    for L in learnings:
        finding = (L.get("finding") or "")[:80]
        _echo(f"  [{L.get('type', 'finding')}] {finding}")


@main.command("list-snapshots")
@click.option("--limit", "-n", default=20, help="Max file snapshots to show")
def list_snapshots(limit):
    """List file_snapshots (AST summaries) in the DB (no SQL)."""
    from agora_kiro.vector_store import get_store
    store = get_store()
    snapshots = store.search_file_snapshots("", k=limit)
    if not snapshots:
        _echo("No file snapshots. Read/edit hooks populate these when you open or edit files.")
        return
    _echo(f"File snapshots (last {len(snapshots)}):")
    for s in snapshots:
        _echo(f"  📄 {s.get('file_path', '')}  {s.get('timestamp', '')[:10]}")


@main.command("list-symbols")
@click.option("--limit", "-n", default=30, help="Max symbol notes to show")
@click.option("--file", "file_path", default=None, help="Filter by file path")
def list_symbols(limit, file_path):
    """List symbol_notes (functions/classes) in the DB (no SQL)."""
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id, _get_git_branch
    store = get_store()
    if file_path:
        syms = store.get_symbols_for_file(file_path, project_id=_get_project_id(), branch=_get_git_branch())
        syms = syms[:limit] if syms else []
    else:
        syms = store.search_symbol_notes("", k=limit)
    if not syms:
        _echo("No symbol notes. Read/edit hooks populate these when you open or edit code files.")
        return
    _echo(f"Symbol notes ({len(syms)}):")
    for s in syms:
        _echo(f"  {s.get('symbol_type', '?')}: {s.get('symbol_name', '')} @ {s.get('file_path', '')}:{s.get('start_line', '?')}")


@main.command("list-file-changes")
@click.option("--limit", "-n", default=20, help="Max file changes to show")
def list_file_changes(limit):
    """List recent file_changes in the DB (no SQL). Per-file history: file-history <path>."""
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id
    store = get_store()
    pid = _get_project_id()
    if not pid:
        _echo("No project_id (e.g. not in a git repo). file-history <path> still works.")
        return
    changes = store.get_recent_file_changes_for_project(pid, limit=limit)
    if not changes:
        _echo("No file changes in DB. Edits + track-diff populate these.")
        return
    _echo(f"File changes (last {len(changes)}):")
    for c in changes:
        st = c.get("status") or "uncommitted"
        sha = c.get("commit_sha") or c.get("recorded_at_commit_sha") or ""
        sha_str = f"  [{st}]" + (f" {sha[:8]}" if sha else "")
        _echo(f"  {c.get('file_path', '')}  {c.get('timestamp', '')[:10]}{sha_str}  {(c.get('diff_summary') or '')[:50]}")


# --------------------------------------------------------------------------- #
#  checkpoint                                                                  #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--goal", default=None, help="What you're trying to accomplish")
@click.option("--hypothesis", default=None, help="Current working theory")
@click.option("--action", default=None, help="What you're doing right now")
@click.option("--context", default=None, help="Free-text project context or notes")
@click.option("--api", default=None, help="Base URL of the API being tested")
@click.option("--next", "next_step", default=None, multiple=True, help="Next steps (repeatable)")
@click.option("--blocker", default=None, multiple=True, help="Blockers (repeatable)")
@click.option("--file", "file_changed", default=None, multiple=True,
              help="File you changed, optionally with note: 'auth.py:added retry logic'")
@click.option("--quiet", is_flag=True, default=False,
              help="Suppress output — for hook/automation use")
def checkpoint(goal, hypothesis, action, context, api, next_step, blocker, file_changed, quiet):
    """Save current session state to .agora-kiro/session.json.

    \b
    Works for any project — API or non-API:

    agora-kiro checkpoint --goal "Refactor auth module"
    agora-kiro checkpoint --hypothesis "SessionManager needs lock"
    agora-kiro checkpoint --action "Adding retry logic to validate()"
    agora-kiro checkpoint --file "auth.py:added retry" --file "tests/test_auth.py:updated tests"
    agora-kiro checkpoint --next "Write test for edge case" --blocker "Waiting for review"
    """
    from agora_kiro.session import load_session, new_session, update_session

    updates: dict = {}
    if goal:       updates["goal"] = goal
    if hypothesis: updates["hypothesis"] = hypothesis
    if action:     updates["current_action"] = action
    if context:    updates["context"] = context
    if api:        updates["api_base_url"] = api
    if next_step:  updates["next_steps"] = list(next_step)
    if blocker:    updates["blockers"] = [b for b in blocker]
    if file_changed:
        files = []
        for f in file_changed:
            if ":" in f:
                fname, what = f.split(":", 1)
                files.append({"file": fname.strip(), "what": what.strip()})
            else:
                files.append({"file": f.strip(), "what": ""})
        updates["files_changed"] = files

    session = update_session(updates)
    if not quiet:
        _echo(f"✅ Session saved: {session['session_id']}")
        _echo(f"   Goal: {session.get('goal') or '(none)'} | Status: {session.get('status', 'in_progress')}")


# --------------------------------------------------------------------------- #
#  complete                                                                    #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--summary", default=None, help="What you accomplished")
@click.option("--outcome", default="success", type=click.Choice(["success", "partial", "abandoned"]),
              help="How the session ended")
def complete(summary, outcome):
    """Archive the current session and store it in memory.

    \b
    agora-kiro complete --summary "Refactored auth, added retry logic"
    agora-kiro complete --outcome partial
    """
    from agora_kiro.session import archive_session

    session = archive_session(summary=summary, outcome=outcome)
    _echo(f"✅ Session '{session.get('session_id')}' archived ({outcome}).")
    if summary:
        _echo(f"   Summary: {summary}")
    _echo("   Session stored in memory for future recall.")


# --------------------------------------------------------------------------- #
#  inject                                                                      #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--level", default=None,
              type=click.Choice(["index", "summary", "detail", "full"]),
              help="Compression level — auto-picks under --token-budget if not set")
@click.option("--token-budget", default=2000, help="Max tokens for auto-level picking")
@click.option("--raw", is_flag=True, default=False, help="Print raw session JSON")
@click.option("--quiet", is_flag=True, default=False,
              help="Exit silently if no session exists (for hook use)")
def inject(level, token_budget, raw, quiet):
    """Print compressed session context for injection into any coding agent.

    \b
    Use with Claude Code hooks (.claude/settings.json):
        {"hooks": {"PreToolUse": [{"command": "agora-kiro inject"}]}}

    Or pipe directly:
        agora-kiro inject | pbcopy   # paste into any chat
        agora-kiro inject --level detail
        agora-kiro inject --raw      # full session JSON
    """
    from agora_kiro.session import (
        load_session_if_recent, load_session,
        _build_recalled_context,
    )

    if raw:
        session = load_session_if_recent(max_age_hours=48) or load_session()
        if session:
            import json as _json
            click.echo(_json.dumps(session, indent=2))
        return

    # Always build fresh — never serve stale cache from session.json
    recalled = _build_recalled_context()
    if recalled:
        click.echo(recalled)
    elif not quiet:
        click.echo("No session context found.", err=True)



# --------------------------------------------------------------------------- #
#  restore                                                                     #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("session_id", required=False)
def restore(session_id):
    """Restore a past session as the active session.

    \b
    agora-kiro restore                                  # list sessions
    agora-kiro restore 2026-03-08-debug-post-users      # restore specific
    """
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import save_session
    from agora_kiro.compress import compress_session

    vs = get_store()

    if not session_id:
        # List recent sessions
        sessions = vs.list_sessions(limit=10)
        if not sessions:
            _echo("📭 No sessions in memory yet.")
            return
        _echo("\n📚 Recent sessions (use restore <session_id>):\n")
        for s in sessions:
            _echo(f"  {s['status'][:1].upper()}  {s['session_id']:<45} {s['last_active'][:10]}  {s.get('goal','')[:40]}")
        return

    data = vs.load_session(session_id)
    if not data:
        _echo(f"❌ Session '{session_id}' not found.")
        sys.exit(1)

    # Restore: mark in_progress, resave to JSON
    data["status"] = "in_progress"
    save_session(data)
    _echo(f"✅ Session '{session_id}' restored as active.")
    _echo("")
    _echo(compress_session(data, level="summary"))


# --------------------------------------------------------------------------- #
#  learn                                                                       #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("finding")
@click.option("--endpoint", default=None, help="e.g. 'POST /users'")
@click.option("--api", default=None, help="Base URL of the API")
@click.option("--evidence", default=None, help="Supporting evidence or example")
@click.option("--confidence", default="confirmed",
              type=click.Choice(["confirmed", "likely", "hypothesis"]))
@click.option("--tags", default=None, help="Comma-separated tags")
def learn(finding, endpoint, api, evidence, confidence, tags):
    """Store a permanent learning about an API.

    \b
    agora-kiro learn "POST /users rejects + in emails" --tags email,validation
    agora-kiro learn "Rate limit is 100 req/min" --endpoint "GET /data" --confidence confirmed
    """
    from agora_kiro.vector_store import get_store
    from agora_kiro.embeddings import get_embedding
    from agora_kiro.session import load_session, _get_project_id, _get_git_branch

    session = load_session()
    session_id = session.get("session_id") if session else None
    # Important: learnings must be stored with the current repo's project_id.
    # `agora-kiro inject` scopes by project_id when building the context.
    project_id = _get_project_id()
    branch = _get_git_branch()

    method = path = None
    if endpoint:
        parts = endpoint.strip().split(None, 1)
        method = parts[0].upper() if len(parts) >= 1 else None
        path   = parts[1] if len(parts) >= 2 else None

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    embed = get_embedding(finding + " " + (evidence or ""))

    lid = get_store().store_learning(
        finding=finding,
        session_id=session_id,
        api_base_url=api,
        endpoint_method=method,
        endpoint_path=path,
        evidence=evidence,
        confidence=confidence,
        tags=tag_list,
        embedding=embed,
        project_id=project_id,
        branch=branch,
    )
    _echo(f"✅ Learning stored (id: {lid[:8]}…)")
    if embed is None:
        _echo("   ⚠️  No embedding generated — set OPENAI_API_KEY for semantic recall.")
        _echo("   Keyword search will still work.")


# --------------------------------------------------------------------------- #
#  remove                                                                      #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("learning_id")
def remove(learning_id):
    """Remove a learning by ID — scoped to the current repo.

    \b
    agora-kiro remove abc12345
    """
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id

    project_id = _get_project_id()
    vs = get_store()
    conn = vs._conn_()

    row = conn.execute(
        "SELECT id, finding, project_id FROM learnings WHERE id LIKE ?",
        (f"{learning_id}%",)
    ).fetchone()

    if not row:
        _echo(f"❌ No learning found matching '{learning_id}'.")
        return

    if row["project_id"] != project_id:
        _echo(f"❌ Learning '{row['id'][:8]}' belongs to a different repo ({row['project_id']}) — cannot remove.")
        return

    conn.execute("DELETE FROM learnings WHERE id = ?", (row["id"],))
    conn.commit()
    _echo(f"✅ Removed learning: {row['finding'][:80]}")


# --------------------------------------------------------------------------- #
#  recall                                                                      #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("query", required=False, default=None)
@click.option("--limit", "-n", default=5, help="Max results")
def recall(query, limit):
    """Search your learnings knowledge base semantically.

    \b
    agora-kiro recall "email validation"
    agora-kiro recall "rate limit" --limit 10
    agora-kiro recall                        # show most recent learnings
    """
    from agora_kiro.vector_store import get_store
    from agora_kiro.embeddings import get_query_embedding
    from agora_kiro.session import _get_project_id

    vs = get_store()
    project_id = _get_project_id()

    if not query:
        # No query — show most recent learnings
        results = vs.search_learnings_keyword("", k=limit, project_id=project_id)
        mode = "recent"
    else:
        embed = get_query_embedding(query)
        if embed:
            results = vs.search_learnings_semantic(embed, k=limit, project_id=project_id)
            mode = "semantic"
        else:
            results = []
            mode = None

        if not results:
            results = vs.search_learnings_keyword(query, k=limit, project_id=project_id)
            mode = "keyword"

    if not results:
        if query:
            _echo(f"📭 No learnings match '{query}'.")
        else:
            _echo("📭 No learnings stored yet.")
        _echo("   Store one with: agora-kiro learn \"your finding\"")
        return

    label = "most recent" if mode == "recent" else f"{mode} search"
    _echo(f"\n🔍 {len(results)} result(s) [{label}]:\n")
    for i, r in enumerate(results, 1):
        ep = ""
        if r.get("endpoint_method") and r.get("endpoint_path"):
            ep = f"  [{r['endpoint_method']} {r['endpoint_path']}]"
        conf_emoji = {"confirmed": "✓", "likely": "~", "hypothesis": "?"}.get(r.get("confidence", ""), "")
        tags = ", ".join(r.get("tags") or [])
        _echo(f"  {i}. {conf_emoji} {r['finding']}{ep}")
        if r.get("evidence"):
            _echo(f"     Evidence: {r['evidence']}")
        if tags:
            _echo(f"     Tags: {tags}")
        _echo("")



# --------------------------------------------------------------------------- #
#  index                                                                       #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("file_path", type=click.Path(exists=True))
def index(file_path):
    """Re-index a file into the DB (symbol_notes + file_snapshots). Call after edits so the AST cache stays in sync.

    Hooks (e.g. on-edit, after-file-edit) should call this so each change updates the DB.
    """
    from agora_kiro.indexer import index_file
    from agora_kiro.session import _get_project_id, _get_git_branch, _get_commit_sha
    path = Path(file_path).resolve()
    count = index_file(
        str(path),
        project_id=_get_project_id(),
        branch=_get_git_branch(),
        commit_sha=_get_commit_sha(),
    )
    if count:
        _echo(f"✅ Indexed {path.name}: {count} symbols, AST snapshot updated.")
    else:
        _echo(f"📄 {path.name}: not a code file or no symbols extracted (no DB update).")


# --------------------------------------------------------------------------- #
#  track-diff                                                                  #
# --------------------------------------------------------------------------- #

@main.command("track-diff")
@click.argument("file_path", required=False)
@click.option("--all", "all_files", is_flag=True, default=False,
              help="Track all uncommitted (staged + unstaged) files")
@click.option("--committed", is_flag=True, default=False,
              help="Diff against HEAD~1 (last commit) rather than working tree")
@click.option("--note", default=None,
              help="One sentence describing what changed and why — written by the agent")
def track_diff(file_path, all_files, committed, note):
    """Capture a git diff for a file and store a compact summary in memory.

    Pass --note with a sentence you write describing what changed and why.
    This is more accurate than auto-generated notes.

    \b
    agora-kiro track-diff agora_kiro/auth.py --note "changed _check_expiry to use utcnow — fixes tz offset, called by authenticate()"
    agora-kiro track-diff --all
    agora-kiro track-diff agora_kiro/auth.py --committed
    """
    import subprocess as sp
    from agora_kiro.session import _get_uncommitted_files

    if all_files:
        files = _get_uncommitted_files()
        if not files:
            _echo("No uncommitted files to track.")
            return
        for fp in files:
            _track_diff_one(fp, committed, note=note)
        return
    if not file_path:
        _echo("Error: Missing argument FILE_PATH (or use --all for all uncommitted files).", err=True)
        raise SystemExit(2)
    _track_diff_one(file_path, committed, note=note)


def _track_diff_one(file_path: str, committed: bool, note: Optional[str] = None) -> None:
    """Run track-diff for a single file."""
    import subprocess as sp
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import load_session, _get_git_branch, _get_commit_sha, _get_git_author, _get_project_id

    if committed:
        cmd = ["git", "diff", "HEAD~1", "--", file_path]
    else:
        cmd = ["git", "diff", "HEAD", "--", file_path]

    try:
        result = sp.run(cmd, capture_output=True, text=True, timeout=10)
        raw_diff = result.stdout.strip()
    except Exception as e:
        _echo(f"⚠️  Could not get diff for {file_path}: {e}")
        return

    if not raw_diff:
        try:
            r2 = sp.run(["git", "status", "--short", "--", file_path],
                        capture_output=True, text=True, timeout=5)
            status = r2.stdout.strip()
            if "??" in status:
                raw_diff = f"[new untracked file: {file_path}]"
            else:
                return
        except Exception as e:
            _echo(f"⚠️  git status failed for {file_path}: {e}", err=True)
            return

    summary = note if note else _summarize_diff(raw_diff, file_path)
    changed_lines = [l for l in raw_diff.splitlines()
                     if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))]
    snippet = '\n'.join(changed_lines)
    session = load_session()
    store = get_store()
    store.save_file_change(
        file_path=file_path,
        diff_summary=summary,
        diff_snippet=snippet,
        commit_sha=_get_commit_sha(),
        session_id=session.get("session_id") if session else None,
        branch=_get_git_branch(),
        agent_id=_get_git_author(),
        project_id=_get_project_id(),
    )
    _echo(f"📌 Tracked: {file_path} — {summary}")



def _llm_change_note(diff: str, file_path: str, symbols: str = "") -> Optional[str]:
    """
    Generate a 1-2 sentence change note using the configured LLM provider.
    Uses LLM_PROVIDER / ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY (auto-detect).
    Returns None if no provider available — caller falls back to regex.
    """
    try:
        from agora_kiro.extractors.llm import _detect_provider
        provider, model = _detect_provider()
        if not provider:
            return None

        symbol_hint = f"\nKnown symbols in this file: {symbols}" if symbols else ""
        prompt = (
            f"You are summarizing a code change for a developer memory system.\n"
            f"File: {file_path}{symbol_hint}\n\n"
            f"Diff:\n{diff[:3000]}\n\n"
            f"Write exactly 1-2 sentences: what changed, why (if inferrable), "
            f"and what it connects to (callers/callees if visible). "
            f"Format: 'changed <symbol> to <what> [— connects to <other>]'. "
            f"Be specific. No preamble."
        )

        import asyncio
        if provider in ("claude", "anthropic"):
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=model, max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            note = resp.content[0].text.strip() if resp.content else ""
        elif provider == "openai":
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=model, max_tokens=120, temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            note = resp.choices[0].message.content.strip()
        elif provider == "gemini":
            import google.generativeai as genai
            m = genai.GenerativeModel(model)
            resp = m.generate_content(prompt)
            note = resp.text.strip() if resp.text else ""
        else:
            return None
        return note if note else None
    except Exception:
        return None


def _summarize_diff(diff: str, file_path: str) -> str:
    """
    Content-aware diff summarizer.
    Tries LLM-generated note first; falls back to regex if unavailable.
    """
    # Try LLM first — pull symbol context from DB if available
    try:
        from agora_kiro.vector_store import get_store
        from agora_kiro.session import _get_project_id, _get_git_branch
        store = get_store()
        snaps = store.search_file_snapshots(file_path, k=1)
        symbols = snaps[0].get("symbols", "") if snaps else ""
        llm_note = _llm_change_note(diff, file_path, symbols=symbols)
        if llm_note:
            import re as _re
            scale = f"+{len([l for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++')])}" \
                    f"/-{len([l for l in diff.splitlines() if l.startswith('-') and not l.startswith('---')])}"
            return f"{llm_note} ({scale})"
    except Exception:
        pass

    import re
    lines = diff.splitlines()
    added   = [l[1:].strip() for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:].strip() for l in lines if l.startswith("-") and not l.startswith("---")]

    if not added and not removed:
        return f"{file_path}: no changes detected"

    # --- What functions/classes were touched ---
    fn_re = re.compile(r"(?:def |class |async def )(\w+)")
    added_fns, removed_fns = [], []
    for line in added:
        for m in fn_re.finditer(line):
            name = m.group(1)
            if name not in added_fns:
                added_fns.append(name)
    for line in removed:
        for m in fn_re.finditer(line):
            name = m.group(1)
            if name not in removed_fns:
                removed_fns.append(name)

    # --- What imports changed ---
    new_imports = [l for l in added if l.startswith(("import ", "from "))]
    del_imports = [l for l in removed if l.startswith(("import ", "from "))]

    # --- Meaningful added snippets (non-blank, non-comment, non-decorator) ---
    meaningful_added = [
        l for l in added
        if l and not l.startswith("#") and not l.startswith("@")
        and not l.startswith(("import ", "from ", "class ", "def ", "async def "))
    ]
    meaningful_removed = [
        l for l in removed
        if l and not l.startswith("#") and not l.startswith("@")
        and not l.startswith(("import ", "from ", "class ", "def ", "async def "))
    ]

    # --- Build description ---
    parts = []

    # New/modified functions
    new_fns = [f for f in added_fns if f not in removed_fns]
    mod_fns = [f for f in added_fns if f in removed_fns]
    del_fns = [f for f in removed_fns if f not in added_fns]

    if new_fns:
        parts.append(f"added {', '.join(new_fns[:3])}()")
    if mod_fns:
        parts.append(f"modified {', '.join(mod_fns[:3])}()")
    if del_fns:
        parts.append(f"removed {', '.join(del_fns[:2])}()")

    # Import changes
    if new_imports:
        import_names = [i.split()[-1] for i in new_imports[:2]]
        parts.append(f"imported {', '.join(import_names)}")
    if del_imports:
        import_names = [i.split()[-1] for i in del_imports[:2]]
        parts.append(f"removed import {', '.join(import_names)}")

    # Fallback: show a snippet of the most significant added line
    if not parts and meaningful_added:
        snippet = meaningful_added[0][:80].rstrip()
        parts.append(f"added: `{snippet}`")
    elif not parts and meaningful_removed:
        snippet = meaningful_removed[0][:80].rstrip()
        parts.append(f"removed: `{snippet}`")

    scale = f"+{len(added)}/-{len(removed)} lines"
    desc = "; ".join(parts) if parts else "modified"
    return f"{file_path}: {desc} ({scale})"


# --------------------------------------------------------------------------- #
#  file-history                                                                #
# --------------------------------------------------------------------------- #

@main.command("file-history")
@click.argument("file_path")
@click.option("--limit", "-n", default=20, help="Max entries to show")
def file_history(file_path, limit):
    """Show the tracked change history for a file.

    \b
    agora-kiro file-history agora_kiro/auth.py
    agora-kiro file-history agora_kiro/session.py --limit 5
    """
    from agora_kiro.vector_store import get_store

    history = get_store().get_file_history(file_path, limit=limit)
    if not history:
        _echo(f"📭 No tracked changes for '{file_path}'.")
        _echo("   Changes are tracked automatically via git post-commit hook.")
        _echo("   Install with: agora-kiro install-hooks")
        _echo(f"   Or run manually: agora-kiro track-diff {file_path}")
        return

    _echo(f"\n📋 Change history for {file_path} ({len(history)} entries):\n")
    for entry in history:
        ts = entry.get("timestamp", "")[:16]
        branch = f" [{entry['branch']}]" if entry.get("branch") else ""
        sha = f" @{entry['commit_sha'][:8]}" if entry.get("commit_sha") else ""
        author = f" by {entry['author']}" if entry.get("author") else ""
        session = f" (session: {entry['session_id'][:20]}...)" if entry.get("session_id") else ""
        _echo(f"  {ts}{branch}{sha}{author}")
        _echo(f"    {entry.get('diff_summary', '(no summary)')}{session}")
    _echo("")


# --------------------------------------------------------------------------- #
#  learn-from-commit                                                           #
# --------------------------------------------------------------------------- #

@main.command("learn-from-commit")
@click.argument("sha", required=False, default=None)
@click.option("--quiet", "-q", is_flag=True, default=False)
def learn_from_commit(sha, quiet):
    """Derive and store learnings from a git commit (defaults to HEAD).

    Called automatically by on-bash.sh after every git commit.
    Uses LLM to extract structural facts and design decisions.
    Falls back to storing commit message as a raw learning if no LLM key.

    \b
    agora-kiro learn-from-commit           # HEAD
    agora-kiro learn-from-commit abc1234   # specific commit
    """
    import subprocess as sp
    import json as _json
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id, _get_git_branch, load_session

    # Resolve SHA
    if not sha:
        r = sp.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
        sha = r.stdout.strip()
    if not sha:
        _echo("⚠  Could not determine commit SHA.", err=True)
        return

    # Commit message
    r = sp.run(["git", "log", "--format=%B", "-1", sha], capture_output=True, text=True)
    commit_message = r.stdout.strip()
    if not commit_message:
        if not quiet:
            _echo(f"⚠  No commit message found for {sha}.")
        return

    # Files changed in this commit
    r = sp.run(["git", "diff-tree", "--no-commit-id", "-r", "--name-only", sha],
               capture_output=True, text=True)
    files = [f for f in r.stdout.strip().splitlines() if f.strip()]
    if not files:
        r = sp.run(["git", "show", "--name-only", "--format=", sha],
                   capture_output=True, text=True)
        files = [f for f in r.stdout.strip().splitlines() if f.strip()]

    store = get_store()
    project_id = _get_project_id()
    branch = _get_git_branch()
    session = load_session()
    session_id = session.get("session_id") if session else None

    # Get ALL change notes for each committed file — every attempt, not just the last one.
    import re as _re
    stored = 0
    for fp in files:
        rows = store.get_file_changes_for_commit(fp, sha, project_id=project_id)
        if not rows:
            # fallback: most recent note for this file regardless of SHA
            history = store.get_file_history(fp, limit=1)
            rows = history if history else []

        for row in rows:
            note = (row.get("diff_summary") or "").strip()
            # Strip any leading "filepath: " prefix stored by _summarize_diff
            clean = _re.sub(r'^[^\s:]+[/\\][^\s:]*:\s*', '', note)
            if not clean or (clean.startswith("modified ") and len(clean) < 20):
                continue
            finding = f"{clean}  [{fp.split('/')[-1]}]"
            store.store_learning(
                finding=finding,
                evidence=f"commit {sha}: {commit_message[:80]}",
                confidence="confirmed",
                tags=["commit", "change-note"],
                type="finding",
                branch=branch,
                files=[fp],
                project_id=project_id,
                session_id=session_id,
                commit_sha=sha,
            )
            stored += 1

    # If no file notes had content, store the commit message as a minimal signal
    if stored == 0:
        store.store_learning(
            finding=commit_message.splitlines()[0][:120],
            evidence=f"commit {sha} — no change notes available",
            confidence="likely",
            tags=["commit"],
            type="finding",
            branch=branch,
            files=files,
            project_id=project_id,
            session_id=session_id,
            commit_sha=sha,
        )
        stored = 1

    if not quiet:
        _echo(f"✅ {stored} learning(s) stored for commit {sha}: {commit_message.splitlines()[0][:60]}")


# --------------------------------------------------------------------------- #
#  show  — pretty view of what inject loaded                                   #
# --------------------------------------------------------------------------- #

@main.command("show")
@click.option("--json-out", "json_out", is_flag=True, default=False, help="Output as JSON")
def show(json_out):
    """Show everything currently in session context — what inject would load.

    Renders as a rich markdown table in the terminal so you can see exactly
    what the AI is working with.

    \b
    agora-kiro show
    agora-kiro show --json-out
    """
    import subprocess as sp
    import json as _json
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import (
        load_session, _get_project_id, _get_git_branch,
        _get_commit_sha, _get_uncommitted_files,
    )

    store = get_store()
    project_id = _get_project_id()
    branch = _get_git_branch()
    session = load_session()
    session_data = _json.loads(session.get("session_data") or "{}") if session else {}

    # ── Recent commits on branch ──────────────────────────────────────────────
    r = sp.run(
        ["git", "log", "--format=%h|%s|%ai", "-6"],
        capture_output=True, text=True,
    )
    recent_commits = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            recent_commits.append({"sha": parts[0], "msg": parts[1], "date": parts[2][:10]})

    # ── Learnings for last 3 commits on this branch ──────────────────────────
    branch_shas = [c["sha"] for c in recent_commits[:3]]
    commit_learnings = store.get_learnings_for_commits(branch_shas, project_id=project_id)

    # ── Uncommitted file changes — always read live from git ─────────────────
    try:
        import subprocess as _sp
        _u = _sp.run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True, timeout=5)
        _s = _sp.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, timeout=5)
        dirty_files = list(dict.fromkeys(
            [f for f in _u.stdout.strip().splitlines() if f] +
            [f for f in _s.stdout.strip().splitlines() if f]
        ))
    except Exception:
        dirty_files = []
    uncommitted_changes = store.get_uncommitted_file_changes(
        project_id=project_id, branch=branch
    ) if dirty_files else []

    # ── Session checkpoint ────────────────────────────────────────────────────
    session_goal = session.get("goal", "") if session else ""
    session_decisions = session_data.get("decisions_made", []) if session_data else []
    session_next = session_data.get("next_steps", []) if session_data else []

    if json_out:
        import json
        click.echo(json.dumps({
            "session": {
                "goal": session_goal,
                "decisions": session_decisions,
                "next_steps": session_next,
            },
            "uncommitted_changes": uncommitted_changes,
            "commit_learnings": commit_learnings,
            "recent_commits": recent_commits,
            "dirty_files": dirty_files,
        }, indent=2))
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        console = Console()
        _use_rich = True
    except ImportError:
        console = None
        _use_rich = False

    def _line(s=""):
        click.echo(s)

    _line("# AGORA SESSION CONTEXT")
    _line()

    # Session checkpoint
    _line("## Last Session")
    if session_goal:
        _line(f"  goal:      {session_goal}")
    if session_decisions:
        for d in session_decisions[:3]:
            _line(f"  decided:   {d}")
    if session_next:
        for n in session_next[:2]:
            _line(f"  next:      {n}")
    if not session_goal:
        _line("  (no session checkpoint)")
    _line()

    # Uncommitted work
    if uncommitted_changes:
        _line("## Uncommitted Work")
        if _use_rich:
            t = Table(show_header=True, header_style="bold cyan")
            t.add_column("File", style="yellow")
            t.add_column("Change Note")
            for ch in uncommitted_changes[:10]:
                fp = ch.get("file_path", "")
                note = ch.get("diff_summary", "(no note)")
                t.add_row(fp.split("/")[-1], note)
            console.print(t)
        else:
            for ch in uncommitted_changes[:10]:
                _line(f"  {ch.get('file_path','')}")
                _line(f"    {ch.get('diff_summary','')}")
        _line()
    elif dirty_files:
        _line("## Uncommitted Work")
        _line("  dirty files (no change notes yet — run agora-kiro track-diff):")
        for f in dirty_files[:8]:
            _line(f"    {f}")
        _line()

    # Commit learnings
    if commit_learnings:
        _line(f"## Learnings (last {len(branch_shas)} commits on {branch})")
        if _use_rich:
            t = Table(show_header=True, header_style="bold cyan")
            t.add_column("Finding")
            t.add_column("Commit", width=8)
            t.add_column("Tags", width=20)
            for lrn in commit_learnings[:8]:
                tags = lrn.get("tags") or "[]"
                if isinstance(tags, str):
                    try:
                        import json
                        tags = ", ".join(json.loads(tags))
                    except Exception:
                        pass
                finding = lrn.get("finding", "")[:80]
                sha = (lrn.get("commit_sha") or "")[:7]
                t.add_row(finding, sha, str(tags)[:20])
            console.print(t)
        else:
            for lrn in commit_learnings[:8]:
                sha = (lrn.get("commit_sha") or "")[:7]
                _line(f"  [{sha}] {lrn.get('finding','')}")
        _line()

    # Git state
    _line("## Git State")
    _line(f"  branch:  {branch or '(unknown)'}")
    _line(f"  dirty:   {', '.join(dirty_files) if dirty_files else '(clean)'}")
    if recent_commits:
        _line("  recent commits:")
        for c in recent_commits[:4]:
            _line(f"    {c['sha']}  {c['date']}  {c['msg'][:60]}")
    _line()


# --------------------------------------------------------------------------- #
#  notes  — view AI-written change notes                                       #
# --------------------------------------------------------------------------- #

@main.command("notes")
@click.argument("file_path", required=False, default=None)
@click.option("--limit", "-n", default=20)
def notes(file_path, limit):
    """Show AI-written change notes for files.

    \b
    agora-kiro notes                     # all recent notes
    agora-kiro notes agora_kiro/auth.py  # notes for a specific file
    """
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id

    store = get_store()
    project_id = _get_project_id()

    if file_path:
        rows = store.get_file_history(file_path, limit=limit)
    else:
        rows = store.get_recent_file_changes_for_project(project_id, limit=limit)

    if not rows:
        _echo("📭 No change notes found.")
        _echo("   Notes are written automatically when files are edited.")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        console = Console()
        t = Table(show_header=True, header_style="bold cyan")
        t.add_column("File", style="yellow", max_width=30)
        t.add_column("Change Note")
        t.add_column("Commit", width=8)
        t.add_column("Date", width=10)
        for row in rows:
            fp = (row.get("file_path") or "").split("/")[-1]
            note = row.get("diff_summary") or "(no note)"
            sha = (row.get("commit_sha") or "")[:7]
            date = (row.get("timestamp") or "")[:10]
            t.add_row(fp, note, sha, date)
        console.print(t)
    except ImportError:
        for row in rows:
            ts = (row.get("timestamp") or "")[:10]
            sha = (row.get("commit_sha") or "")[:7]
            _echo(f"  [{ts}] @{sha}  {row.get('file_path','')}:")
            _echo(f"    {row.get('diff_summary','')}")


# --------------------------------------------------------------------------- #
#  commit-log  — learnings per commit                                          #
# --------------------------------------------------------------------------- #

@main.command("commit-log")
@click.argument("sha", required=False, default=None)
@click.option("--limit", "-n", default=5, help="Number of recent commits to show")
def commit_log(sha, limit):
    """Show learnings stored per commit.

    \b
    agora-kiro commit-log              # last N commits with their learnings
    agora-kiro commit-log abc1234      # specific commit
    """
    import subprocess as sp
    from agora_kiro.vector_store import get_store
    from agora_kiro.session import _get_project_id

    store = get_store()
    project_id = _get_project_id()

    if sha:
        commits = [{"sha": sha, "msg": "", "date": ""}]
    else:
        r = sp.run(["git", "log", "--format=%h|%s|%ai", f"-{limit}"],
                   capture_output=True, text=True)
        commits = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"sha": parts[0], "msg": parts[1], "date": parts[2][:10]})

    if not commits:
        _echo("📭 No commits found.")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
        console = Console()
        _use_rich = True
    except ImportError:
        _use_rich = False

    for commit in commits:
        c_sha = commit["sha"]
        c_msg = commit["msg"]
        c_date = commit["date"]
        learnings = store.get_learnings_for_commit(c_sha, project_id=project_id)

        header = f"  {c_sha}  {c_date}  {c_msg[:60]}" if c_msg else f"  {c_sha}"
        click.echo(f"\n{header}")
        if learnings:
            if _use_rich:
                t = Table(show_header=False, box=None, padding=(0, 2))
                t.add_column("type", style="dim", width=10)
                t.add_column("finding")
                for lrn in learnings:
                    import json
                    tags = lrn.get("tags") or "[]"
                    try:
                        tags_str = ", ".join(json.loads(tags)) if isinstance(tags, str) else ", ".join(tags)
                    except Exception:
                        tags_str = str(tags)
                    t.add_row(
                        lrn.get("type", "finding"),
                        f"{lrn.get('finding','')}" + (f"  [{tags_str}]" if tags_str else ""),
                    )
                console.print(t)
            else:
                for lrn in learnings:
                    click.echo(f"    · {lrn.get('finding','')}")
        else:
            click.echo("    (no learnings stored — run: agora-kiro learn-from-commit " + c_sha + ")")


# --------------------------------------------------------------------------- #
#  summarize                                                                   #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("file_path")
@click.option("--max-tokens", default=500, help="Token budget for summary")
@click.option("--json-output", "json_out", is_flag=True, default=False,
              help="Output JSON for hook consumption")
@click.option("--threshold", default=100, help="Line threshold — files below this pass through")
def summarize(file_path, max_tokens, json_out, threshold):
    """Summarize a file's structure for token-efficient context injection.

    Uses cached AST from DB when the file was already indexed at the same git
    commit (no re-read from disk). Otherwise reads from disk and summarizes.

    \b
    Used by preToolUse hooks to intercept large file reads:
      agora-kiro summarize agora_kiro/session.py
      agora-kiro summarize package.json --json-output

    Files under --threshold lines return empty (signal: let it through).
    """
    from agora_kiro.summarizer import summarize_file, FILE_SIZE_THRESHOLD
    import os

    path = Path(file_path).resolve()

    # Restrict to paths the user actually owns: CWD subtree or home subtree.
    # This prevents hooks from being weaponised to read system files.
    _allowed_roots = [Path.cwd().resolve(), Path.home().resolve()]
    if not any(str(path).startswith(str(r)) for r in _allowed_roots):
        if json_out:
            click.echo(json.dumps({"action": "allow", "reason": "path outside allowed roots"}))
        return

    if not path.exists():
        if json_out:
            click.echo(json.dumps({"action": "allow", "reason": "file not found"}))
        return

    # Use cached AST from DB when we have a snapshot at the same git commit (no disk read).
    try:
        from agora_kiro.vector_store import get_store
        from agora_kiro.session import _get_project_id, _get_git_branch, _get_commit_sha
        from agora_kiro.summarizer import estimate_tokens as _est_tokens
        store = get_store()
        pid = _get_project_id()
        branch = _get_git_branch()
        current_sha = _get_commit_sha()
        snapshot = store.get_file_snapshot(str(path), project_id=pid, branch=branch)
        if snapshot and snapshot.get("summary") and snapshot.get("commit_sha") == current_sha:
            summary = snapshot["summary"]
            if json_out:
                click.echo(json.dumps({
                    "action": "summarize",
                    "parser": "cached",
                    "summary": summary,
                    "original_lines": 0,
                    "original_tokens": 0,
                    "summary_tokens": _est_tokens(summary),
                }))
            else:
                _echo(f"📄 {file_path}: served from DB (cached at {current_sha or 'n/a'})\n")
                click.echo(summary)
            return
    except Exception:
        pass

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        if json_out:
            click.echo(json.dumps({"action": "allow", "reason": "unreadable"}))
        return

    summary = summarize_file(str(file_path), content, max_tokens=max_tokens, threshold=threshold)

    if summary is None:
        if json_out:
            click.echo(json.dumps({"action": "allow", "reason": "below threshold"}))
        else:
            _echo(f"✅ {file_path}: {len(content.splitlines())} lines — below threshold, pass through")
        return

    from agora_kiro.summarizer import estimate_tokens
    original_tokens = estimate_tokens(content)
    summary_tokens = estimate_tokens(summary)
    reduction = round((1 - summary_tokens / original_tokens) * 100, 1) if original_tokens > 0 else 0

    # Extract parser tag from summary footer
    parser = "unknown"
    for line in summary.splitlines()[-3:]:
        if line.startswith("[parser="):
            parser = line[8:].rstrip("]")
            break

    if json_out:
        click.echo(json.dumps({
            "action": "summarize",
            "parser": parser,
            "summary": summary,
            "original_lines": len(content.splitlines()),
            "original_tokens": original_tokens,
            "summary_tokens": summary_tokens,
        }))
    else:
        _echo(f"📊 {file_path}: {original_tokens} → {summary_tokens} tokens ({reduction}% reduction)\n")
        click.echo(summary)


# --------------------------------------------------------------------------- #
#  memory-server                                                               #
# --------------------------------------------------------------------------- #

@main.command("memory-server")
def memory_server():
    """Start a project-agnostic MCP server for day-to-day coding.

    \b
    Exposes 16 memory tools to any AI coding assistant (see _TOOLS in memory_server.py):
      get_session_context  — what you're working on (auto-injected on start)
      save_checkpoint      — save goal, hypothesis, files changed
      store_learning       — permanent findings across all projects
      recall_learnings     — search past findings semantically
      complete_session     — archive session to long-term memory
      get_memory_stats     — storage stats
      summarize_file       — AST outline for token-efficient reads
      read_file_range      — read a specific line range from a file
      index_file           — index a file's symbols into memory DB
      get_file_symbols     — get all indexed symbols for a file
      search_symbols       — search symbols across all indexed files
      recall_file_history  — see past changes to a file across sessions
      log_search           — log a search query and matched files
      list_sessions        — list all past sessions
      store_team_learning  — save a finding shared across the team
      recall_team          — search team-wide knowledge

    No target directory or running API needed.

    \b
    Add to Antigravity / Claude Desktop (.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "agora-memory": {
          "command": "agora-kiro",
          "args": ["memory-server"]
        }
      }
    }
    """
    from agora_kiro.memory_server import serve_memory
    asyncio.run(serve_memory())


