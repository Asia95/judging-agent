"""
guardian/audit.py — the audit log: one JSON Lines record per tool call.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from judging_agent.guardian.prompts import PROMPT_VERSION


def short_args(args: dict) -> dict:
    """Args for logs: long write content replaced by its length."""
    return {
        k: (f"<{len(v)} chars>" if k == "new_content" and isinstance(v, str) else v)
        for k, v in args.items()
    }


def audit_record(run_id: str, task: str, outcome, ctx: dict | None) -> dict:
    """Build the record for one ToolOutcome (ctx is None if a rule blocked early)."""
    d = outcome.decision
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "prompt_version": PROMPT_VERSION,
        "task": task,
        "tool": outcome.tool,
        "args": short_args(outcome.args),
        "path": ctx["metadata"]["path"] if ctx else None,
        "discovered_via": ctx["sighting"].describe() if ctx else None,
        "tier": d.tier,
        "judged": outcome.judged,
        "executed": d.approved,
        "layer": d.layer,
        "reason": d.reason,
        "raw_llm": d.raw,
    }


def append(path: str | Path, record: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
