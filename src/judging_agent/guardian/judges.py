"""
guardian/judges.py — the judges that decide MEDIUM and HIGH calls.

A judge sees the task, scope, proposed call, file metadata and where the ID
came from. It never sees the worker's reasoning or document contents.

  LLMJudge  — asks a watsonx.ai model (prompt in guardian/prompts.py)
  StubJudge — offline stand-in: escalates MEDIUM, blocks HIGH
"""

import json
from dataclasses import dataclass

from judging_agent.guardian.decision import HIGH, Decision
from judging_agent.guardian.prompts import JUDGE_SYSTEM_PROMPT
from judging_agent.llm import chat_json


def _judge_input(ctx: dict) -> str:
    args = dict(ctx["args"])
    untrusted = {
        "resource_name": ctx["metadata"]["name"],
        "resource_path": ctx["metadata"]["path"],
        "owner": ctx["metadata"]["owner"],
        "is_folder": ctx["metadata"]["is_folder"],
    }
    if "new_content" in args:
        untrusted["write_content"] = args.pop("new_content")[:2000]
    return json.dumps({
        "task": ctx["task"],
        "scope": ctx["scope"].to_dict(),
        "proposed_call": {
            "tool": ctx["tool"],
            "action": ctx["action"],
            "args": args,
            "risk_tier": ctx["tier"],
            "tier_reason": ctx["tier_reason"],
        },
        "discovered_via": ctx["sighting"].describe(),
        "untrusted": untrusted,
        "recent_history": ctx["history"][-10:],
    }, indent=2)


@dataclass
class LLMJudge:
    model: object  # ModelInference

    def decide(self, ctx: dict) -> Decision:
        try:
            data, raw = chat_json(self.model, JUDGE_SYSTEM_PROMPT, _judge_input(ctx))
        except Exception as exc:
            return Decision("escalate", f"Guardian LLM call failed ({exc}).", "error", ctx["tier"])

        outcome = str((data or {}).get("decision", "")).lower()
        if outcome not in ("allow", "block", "escalate"):
            return Decision("escalate", "Guardian LLM returned unusable output.", "error", ctx["tier"], raw=raw)

        reason = str(data.get("reason") or "No reason given.")
        if ctx["tier"] == HIGH and outcome == "allow":
            return Decision(
                "escalate", f"High-risk call; LLM would allow: {reason}", "llm", ctx["tier"], raw=raw,
            )
        return Decision(outcome, reason, "llm", ctx["tier"], raw=raw)


@dataclass
class StubJudge:
    """Offline stand-in for LLMJudge: escalates MEDIUM, blocks HIGH."""

    def decide(self, ctx: dict) -> Decision:
        if ctx["tier"] == HIGH:
            return Decision("block", f"Stub judge blocks high risk: {ctx['tier_reason']}.", "stub", HIGH)
        return Decision("escalate", f"Stub judge escalates: {ctx['tier_reason']}.", "stub", ctx["tier"])
