"""
guardian/audit.py — the audit log: JSON Lines, one record per decision.

An approved call is recorded BEFORE it runs (status "approved"); if the record
can't be written, the gateway blocks the call. If the tool then fails, a short
"failed" record follows with the same call_id. Blocked and pending calls get
one record each; a pending call gets another when a human resolves it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from judging_agent.guardian.context import CallContext
from judging_agent.guardian.prompts import PROMPT_VERSION


def short_args(args: dict) -> dict:
    """Args for logs: long write content replaced by its length."""
    return {
        k: (f"<{len(v)} chars>" if k == "new_content" and isinstance(v, str) else v)
        for k, v in args.items()
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_record(
    *, run_id: str, call_id: str, task: str, scope: dict, judge: str, tool: str, args: dict,
    decision, judged: str, status: str, ctx: CallContext | None,
) -> dict:
    """The record for one decision (ctx is None if a check blocked the call before the judge)."""
    return {
        "timestamp": _now(),
        "run_id": run_id,
        "call_id": call_id,
        "prompt_version": PROMPT_VERSION,
        "judge": judge,
        "task": task,
        "scope": scope,
        "tool": tool,
        "args": short_args(args),
        "path": ctx.resource.path if ctx else None,
        "discovered_via": ctx.sighting.describe() if ctx else None,
        "session_taint": list(ctx.taint) if ctx else None,
        "tier": decision.tier,
        "judged": judged,
        "status": status,           # "approved" | "blocked" | "pending"
        "layer": decision.layer,
        "reason": decision.reason,
        "raw_llm": decision.raw,
    }


def failure_record(*, run_id: str, call_id: str, error: str) -> dict:
    return {"timestamp": _now(), "run_id": run_id, "call_id": call_id, "status": "failed", "error": error}


def append(path: str | Path, record: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
