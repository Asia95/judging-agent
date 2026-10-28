"""
gateway.py — the only path from the worker to a tool.

ToolGateway.execute() checks a call and runs it in one step, so the worker
never holds the tools or the Drive credentials itself:

  fixed rules → metadata lookup → risk tier → judge → human → execute
  → record provenance → audit

Every call is appended to the audit log as one JSON Lines record.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from judge import LOW, PROMPT_VERSION, Decision, TaskScope, check_rules, risk_tier
from provenance import ProvenanceTracker
from tools import TOOLS, DriveBackend

EscalationHandler = Callable[[dict, str], bool]


@dataclass
class ToolOutcome:
    tool: str
    args: dict
    decision: Decision
    result: dict

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
    audit_path: str = "audit.jsonl"
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

        outcome = ToolOutcome(tool_name, args, decision, result)
        self.outcomes.append(outcome)
        self._audit(outcome, ctx)
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
            lines.append(f"[{i}] {status}{via} [{o.decision.layer}] {o.tool}({_short_args(o.args)})")
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
        if metadata["is_folder"] != (spec.action == "list"):
            kind = "a folder" if metadata["is_folder"] else "a file"
            return Decision("block", f"'{metadata['name']}' is {kind}; wrong tool for it.", "rule"), None

        tier, tier_reason = risk_tier(spec.action, metadata, sighting, self.scope)
        ctx = {
            "task": self.task,
            "scope": self.scope,
            "tool": tool_name,
            "action": spec.action,
            "args": args,
            "metadata": metadata,
            "sighting": sighting,
            "tier": tier,
            "tier_reason": tier_reason,
            "history": [
                {"tool": o.tool, "args": _short_args(o.args), "outcome": o.decision.outcome}
                for o in self.outcomes
            ],
        }

        if tier == LOW:
            return Decision("allow", f"Low risk: {tier_reason}.", "tier", tier), ctx

        decision = self.judge.decide(ctx)
        if decision.outcome == "escalate":
            approved = self.escalate(ctx, decision.reason)
            decision = Decision(
                "allow" if approved else "block",
                f"{'Approved' if approved else 'Denied'} by human. Guardian said: {decision.reason}",
                "human",
                tier,
                escalated=True,
                raw=decision.raw,
            )
        return decision, ctx

    def _audit(self, outcome: ToolOutcome, ctx: dict | None):
        d = outcome.decision
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "prompt_version": PROMPT_VERSION,
            "task": self.task,
            "tool": outcome.tool,
            "args": _short_args(outcome.args),
            "path": ctx["metadata"]["path"] if ctx else None,
            "discovered_via": ctx["sighting"].describe() if ctx else None,
            "tier": d.tier,
            "judged": outcome.judged,
            "executed": d.approved,
            "layer": d.layer,
            "reason": d.reason,
            "raw_llm": d.raw,
        }
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def _short_args(args: dict) -> dict:
    """Args for logs: long write content replaced by its length."""
    return {
        k: (f"<{len(v)} chars>" if k == "new_content" and isinstance(v, str) else v)
        for k, v in args.items()
    }
