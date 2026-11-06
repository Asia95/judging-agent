"""
guardian/gateway.py — the only path from the worker to a tool.

ToolGateway.execute() checks a call and runs it in one step, so the worker
never holds the tools or the Drive credentials itself:

  fixed rules → metadata lookup → resource checks → risk tier → judge → human
  → execute → record provenance → audit

assess() is the middle of that pipeline (resource checks, risk tier, judge).
It is a plain function so evals/judge_golden can run exactly the same steps
without a Drive.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from judging_agent.config import settings
from judging_agent.drive.base import DriveBackend
from judging_agent.guardian import audit
from judging_agent.guardian.decision import LOW, Decision
from judging_agent.guardian.escalation import EscalationHandler
from judging_agent.guardian.provenance import ProvenanceTracker, Sighting
from judging_agent.guardian.risk import risk_tier
from judging_agent.guardian.rules import check_resource, check_rules
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import TOOLS


def assess(
    tool_name: str,
    args: dict,
    metadata: dict,
    sighting: Sighting,
    task: str,
    scope: TaskScope,
    history: list[dict],
    judge,
) -> tuple[Decision, dict | None]:
    """Resource checks, risk tier and judge for a call that passed check_rules.

    Returns the Guardian's decision (before any human) and the judge context,
    or None as context if a resource check blocked the call.
    """
    spec = TOOLS[tool_name]
    blocked = check_resource(spec, metadata)
    if blocked:
        return blocked, None

    tier, tier_reason = risk_tier(spec.action, metadata, sighting, scope)
    ctx = {
        "task": task,
        "scope": scope,
        "tool": tool_name,
        "action": spec.action,
        "args": args,
        "metadata": metadata,
        "sighting": sighting,
        "tier": tier,
        "tier_reason": tier_reason,
        "history": history,
    }
    if tier == LOW:
        return Decision("allow", f"Low risk: {tier_reason}.", "tier", tier), ctx
    return judge.decide(ctx), ctx


@dataclass
class ToolOutcome:
    tool: str
    args: dict
    decision: Decision
    result: dict
    resource: str | None = None     # path if known, else the raw ID

    @property
    def judged(self) -> str:
        """The Guardian's verdict before any human: allow | block | escalate."""
        return "escalate" if self.decision.escalated else self.decision.outcome


@dataclass
class ToolGateway:
    task: str
    scope: TaskScope
    backend: DriveBackend
    judge: object                       # LLMJudge | StubJudge
    escalate: EscalationHandler
    audit_path: str | Path = field(default_factory=lambda: settings().audit_path)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    verbose: bool = True

    def __post_init__(self):
        self.provenance = ProvenanceTracker(self.task)
        self.outcomes: list[ToolOutcome] = []

    # ── public API ────────────────────────────────────────────────────────────

    def execute(self, tool_name: str, args: dict) -> ToolOutcome:
        decision, ctx = self._decide(tool_name, args)

        if decision.approved:
            spec = TOOLS[tool_name]
            try:
                result = spec.run(self.backend, args)
                self.provenance.ingest(spec.action, args, result)
            except Exception as exc:
                result = {"error": f"Tool failed: {exc}"}
        else:
            result = {"error": "blocked by guardian", "reason": decision.reason}

        spec = TOOLS.get(tool_name)
        resource = ctx["metadata"]["path"] if ctx else str(args.get(spec.resource_arg)) if spec else None
        outcome = ToolOutcome(tool_name, args, decision, result, resource)
        self.outcomes.append(outcome)
        audit.append(self.audit_path, audit.audit_record(self.run_id, self.task, outcome, ctx))
        if self.verbose:
            icon = "✅" if decision.approved else "🚫"
            tier = f", tier {decision.tier}" if decision.tier else ""
            print(f"  [GUARDIAN] {icon} {outcome.judged.upper()} ({decision.layer}{tier}): {decision.reason}")
        return outcome

    def summary(self) -> str:
        lines = [f"Task : {self.task}", f"Scope: {self.scope.to_dict()}", ""]
        for i, o in enumerate(self.outcomes, 1):
            status = "✅ ALLOW" if o.decision.approved else "🚫 BLOCK"
            via = " (human)" if o.decision.escalated else ""
            lines.append(f"[{i}] {status}{via} [{o.decision.layer}] {o.tool}({audit.short_args(o.args)})")
            lines.append(f"     Reason: {o.decision.reason}")
        return "\n".join(lines)

    # ── internals ─────────────────────────────────────────────────────────────

    def _decide(self, tool_name: str, args: dict) -> tuple[Decision, dict | None]:
        if "_unparsed" in args:
            return Decision("block", "Tool arguments were not a valid JSON object.", "rule"), None
        spec = TOOLS.get(tool_name)
        resource_id = args.get(spec.resource_arg) if spec else None
        sighting = self.provenance.best(resource_id) if isinstance(resource_id, str) else None

        blocked = check_rules(tool_name, args, self.scope, sighting)
        if blocked:
            return blocked, None

        metadata = self.backend.get_metadata(resource_id)
        if metadata is None:
            return Decision("block", f"Resource '{resource_id}' does not exist.", "rule"), None
        history = [
            {"tool": o.tool, "resource": o.resource, "outcome": o.decision.outcome}
            for o in self.outcomes
        ]
        decision, ctx = assess(
            tool_name, args, metadata, sighting, self.task, self.scope, history, self.judge,
        )
        if decision.outcome == "escalate":
            approved = self.escalate(ctx, decision.reason)
            decision = Decision(
                "allow" if approved else "block",
                f"{'Approved' if approved else 'Denied'} by human. Guardian said: {decision.reason}",
                "human",
                decision.tier,
                escalated=True,
                raw=decision.raw,
            )
        return decision, ctx
