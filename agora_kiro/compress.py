"""
compress.py — Session state compression for agora-kiro.

Compresses session state into compact representations before injecting
into Kiro's context window. No LLM required — pure structural extraction.

Session compression levels:
  index   ~50 t   goal only
  summary ~200 t  + hypothesis + discoveries + next steps  (DEFAULT)
  detail  ~500 t  + files changed, decisions, full endpoint status
  full    raw JSON
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agora_kiro.summarizer import estimate_tokens

LEVELS = ["index", "summary", "detail", "full"]

SESSION_DEFAULT_BUDGET = 2000


# --------------------------------------------------------------------------- #
#  Session state compression                                                   #
# --------------------------------------------------------------------------- #

def compress_session(session: dict, level: str = "summary") -> str:
    """Compress a session dict for injection into Kiro's context."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")

    if level == "index":
        return _session_index(session)
    elif level == "summary":
        return _session_summary(session)
    elif level == "detail":
        return _session_detail(session)
    else:
        return json.dumps(session, indent=2)


def auto_compress_session(
    session: dict,
    token_budget: int = SESSION_DEFAULT_BUDGET,
) -> str:
    """Auto-pick highest-detail session compression that fits token_budget."""
    for level in ["detail", "summary", "index"]:
        text = compress_session(session, level)
        if estimate_tokens(text) <= token_budget:
            return text
    return compress_session(session, "index")


def session_restored_banner(session: dict, token_budget: int = SESSION_DEFAULT_BUDGET) -> str:
    """
    Generate the banner shown to the AI on MCP server startup.
    Injected once so the AI knows exactly where you left off.
    """
    compressed = auto_compress_session(session, token_budget)
    age = _session_age_str(session)
    age_line = f"  Last active: {age}\n" if age else ""

    return (
        "═" * 63 + "\n"
        f"🔄  SESSION RESTORED: {session.get('session_id', 'unknown')}\n"
        f"{age_line}"
        "\n"
        f"{compressed}\n"
        "\n"
        "Ready to continue where you left off.\n"
        + "═" * 63
    )


# --------------------------------------------------------------------------- #
#  Session level implementations                                               #
# --------------------------------------------------------------------------- #

def _session_index(session: dict) -> str:
    goal = session.get("goal") or "No goal set"
    return f"Goal: {goal}"


def _session_summary(session: dict) -> str:
    lines: list[str] = []

    if session.get("goal"):
        lines.append(f"GOAL: {session['goal']}")
    if session.get("status", "in_progress") != "in_progress":
        lines.append(f"STATUS: {session['status']}")
    if session.get("hypothesis"):
        lines.append(f"HYPOTHESIS: {session['hypothesis']}")
    if session.get("current_action"):
        lines.append(f"NOW: {session['current_action']}")

    discoveries = session.get("discoveries", [])
    if discoveries:
        lines.append("WHAT YOU DISCOVERED:")
        for d in discoveries[:4]:
            mark = "  ✓" if d.get("confidence") == "confirmed" else "  ~"
            lines.append(f"{mark} {d['finding']}")
        if len(discoveries) > 4:
            lines.append(f"  … +{len(discoveries)-4} more")

    next_steps = session.get("next_steps", [])
    if next_steps:
        lines.append("NEXT STEPS:")
        for step in next_steps[:3]:
            lines.append(f"  → {step}")

    blockers = session.get("blockers", [])
    for b in blockers[:2]:
        desc = b if isinstance(b, str) else b.get("description", str(b))
        lines.append(f"  ⚠️  {desc}")

    return "\n".join(lines)


def _session_detail(session: dict) -> str:
    lines = [_session_summary(session)]

    files = session.get("files_changed", [])
    if files:
        lines.append("\nFILES CHANGED:")
        for f in files[:10]:
            if isinstance(f, dict):
                fname = f.get("file", "")
                what = f.get("what", "")
                lines.append(f"  • {fname} — {what}" if what else f"  • {fname}")
            else:
                lines.append(f"  • {f}")
        if len(files) > 10:
            lines.append(f"  … +{len(files) - 10} more")

    decisions = session.get("decisions_made", [])
    if decisions:
        lines.append("\nDECISIONS MADE:")
        for d in decisions:
            lines.append(f"  – {d}")

    return "\n".join(lines)


def _session_age_str(session: dict) -> str:
    """'2 hours ago', '3 days ago', etc."""
    try:
        from datetime import datetime, timezone
        last = session.get("last_active", "")
        if not last:
            return ""
        dt = datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds()/60)} minutes ago"
        elif hours < 24:
            return f"{int(hours)} hours ago"
        else:
            return f"{int(hours/24)} days ago"
    except Exception:
        return ""
