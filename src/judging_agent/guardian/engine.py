"""
guardian/engine.py — the Guardian's decision, with no side effects.

PolicyEngine.evaluate() runs every check for one call and returns the
Guardian's decision before any human, plus the CallContext it was based on:

  1. unparseable arguments → fixed rules → session budget
  2. metadata lookup (any error blocks: fail closed)
  3. resource checks: workspace boundary, folder vs. file, file type
  4. risk tier: LOW is allowed here; MEDIUM and HIGH go to the judge
  5. HIGH guard: a judge can never allow a HIGH call; "allow" becomes "escalate"
  6. confirmation: tools with needs_confirmation always go to a human

It never executes a tool or writes anything, so the gateway, the evals and a
future UI all get exactly the same decision from the same code.
"""

from dataclasses import dataclass, field
from typing import Callable

from judging_agent.drive.base import ResourceMeta
from judging_agent.guardian.context import CallContext
from judging_agent.guardian.decision import Decision, Layer, Tier, Verdict
from judging_agent.guardian.judges import Judge
from judging_agent.guardian.risk import risk_tier
from judging_agent.guardian.rules import Budget, check_budget, check_resource, check_rules
from judging_agent.guardian.scope import TaskScope
from judging_agent.guardian.session import Session
from judging_agent.tools import TOOLS

Lookup = Callable[[str], ResourceMeta | None]


@dataclass
class PolicyEngine:
    task: str
    scope: TaskScope
    judge: Judge
    workspace_root: str | None = None   # folder ID; None = the whole Drive
    budget: Budget = field(default_factory=Budget)

    def evaluate(
        self, tool_name: str, args: dict, session: Session, lookup: Lookup,
    ) -> tuple[Decision, CallContext | None]:
        """The Guardian's decision for one call. Context is None if a check blocked it before the judge."""
        if "_unparsed" in args:
            return Decision.block("Tool arguments were not a valid JSON object."), None
        spec = TOOLS.get(tool_name)
        resource_id = args.get(spec.resource_arg) if spec else None
        sighting = session.provenance.best(resource_id) if isinstance(resource_id, str) else None

        blocked = (
            check_rules(tool_name, args, self.scope, sighting, session.provenance.read_ids)
            or check_budget(spec, args, session.usage, self.budget)
        )
        if blocked:
            return blocked, None

        try:
            resource = lookup(resource_id)
        except Exception as exc:
            return Decision.block(f"Could not verify resource '{resource_id}' ({exc}); blocked to be safe."), None
        if resource is None:
            return Decision.block(f"Resource '{resource_id}' does not exist or isn't visible."), None
        blocked = check_resource(spec, resource, self.workspace_root)
        if blocked:
            return blocked, None

        taint = tuple(session.provenance.taint)
        tier, tier_reason = risk_tier(spec.action, resource, sighting, self.scope, taint)
        ctx = CallContext(
            task=self.task, scope=self.scope, tool=tool_name, action=spec.action, args=args,
            resource_arg=spec.resource_arg, resource=resource, sighting=sighting,
            tier=tier, tier_reason=tier_reason, history=tuple(session.history), taint=taint,
        )
        if tier == Tier.LOW:
            return Decision(Verdict.ALLOW, f"Low risk: {tier_reason}.", Layer.TIER, tier), ctx

        decision = self.judge.decide(ctx)
        if tier == Tier.HIGH and decision.approved:
            decision = Decision(
                Verdict.ESCALATE, f"High-risk call; judge would allow: {decision.reason}",
                decision.layer, tier, raw=decision.raw,
            )
        if decision.approved and spec.needs_confirmation:
            decision = Decision(
                Verdict.ESCALATE, f"{tool_name} always needs human confirmation; judge would allow: {decision.reason}",
                decision.layer, tier, raw=decision.raw,
            )
        return decision, ctx
