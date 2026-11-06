"""
guardian/judges.py — the judges that decide MEDIUM and HIGH calls.

A judge sees the task, scope, proposed call, file metadata and where the ID
came from. It never sees the worker's reasoning or document contents.
Everything the worker or a document could have influenced (resource names and
paths, worker-chosen arguments such as a file name or write content, and the
call history) is passed under "untrusted".

  LLMJudge  — asks a watsonx.ai model (prompt in guardian/prompts.py). If the
              model fails or answers nonsense, writes are blocked (fail
              closed) and reads/listings are escalated.
  StubJudge — offline stand-in: escalates MEDIUM, blocks HIGH

Whatever a judge answers, the PolicyEngine never lets a HIGH call be allowed.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from judging_agent.guardian.context import CallContext
from judging_agent.guardian.decision import Decision, Layer, Tier, Verdict
from judging_agent.guardian.prompts import JUDGE_SYSTEM_PROMPT
from judging_agent.llm import chat_json
from judging_agent.tools import Action


class Judge(Protocol):
    @property
    def name(self) -> str:
        """Model ID or "stub"; written to the audit log."""

    def decide(self, ctx: CallContext) -> Decision: ...


def judge_input(ctx: CallContext) -> str:
    """The JSON the LLM judge receives. Nothing is truncated: the rules cap write size."""
    return json.dumps({
        "task": ctx.task,
        "scope": {k: v for k, v in ctx.scope.to_dict().items() if k != "source"},
        "proposed_call": {
            "tool": ctx.tool,
            "action": ctx.action,
            "risk_tier": ctx.tier,
            "tier_reason": ctx.tier_reason,
        },
        "discovered_via": ctx.sighting.describe(),
        "untrusted": {
            "resource_name": ctx.resource.name,
            "resource_path": ctx.resource.path,
            "owner": ctx.resource.owner,
            "is_folder": ctx.resource.is_folder,
            "args": ctx.worker_args,
            "recent_history": list(ctx.history[-10:]),
        },
    }, indent=2)


def _judge_failed(ctx: CallContext, problem: str, raw: str | None = None) -> Decision:
    """No usable verdict: fail closed for writes, ask a human for reads and listings."""
    if ctx.action == Action.WRITE:
        return Decision(Verdict.BLOCK, f"{problem}; writes fail closed.", Layer.ERROR, ctx.tier, raw=raw)
    return Decision(Verdict.ESCALATE, f"{problem}.", Layer.ERROR, ctx.tier, raw=raw)


@dataclass
class LLMJudge:
    model: object  # ModelInference

    @property
    def name(self) -> str:
        return str(getattr(self.model, "model_id", "llm"))

    def decide(self, ctx: CallContext) -> Decision:
        try:
            data, raw = chat_json(self.model, JUDGE_SYSTEM_PROMPT, judge_input(ctx))
        except Exception as exc:
            return _judge_failed(ctx, f"Guardian LLM call failed ({exc})")

        outcome = str((data or {}).get("decision", "")).lower()
        if outcome not in tuple(Verdict):
            return _judge_failed(ctx, "Guardian LLM returned unusable output", raw)

        reason = str(data.get("reason") or "No reason given.")
        return Decision(Verdict(outcome), reason, Layer.LLM, ctx.tier, raw=raw)


@dataclass
class StubJudge:
    """Offline stand-in for LLMJudge: escalates MEDIUM, blocks HIGH."""

    name: str = "stub"

    def decide(self, ctx: CallContext) -> Decision:
        if ctx.tier == Tier.HIGH:
            return Decision(Verdict.BLOCK, f"Stub judge blocks high risk: {ctx.tier_reason}.", Layer.STUB, Tier.HIGH)
        return Decision(Verdict.ESCALATE, f"Stub judge escalates: {ctx.tier_reason}.", Layer.STUB, ctx.tier)
