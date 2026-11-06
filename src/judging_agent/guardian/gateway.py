"""
guardian/gateway.py — the only path from the worker to a tool.

ToolGateway.execute() asks the PolicyEngine for a decision, then does the
side effects, so the worker never holds the tools or the Drive credentials:

  engine.evaluate()  → human (if escalated) → audit record → execute
  → session.record() (provenance, taint, usage) → notify listeners

Escalations can be answered right away (console, scripts) or later: if the
escalation handler returns PENDING, the call is held until resolve() is called.

Not thread-safe: one thread drives a gateway (execute/resolve). A UI that runs
the worker in a background thread should receive outcomes through a listener
that only puts them on a queue, and read that queue, never gateway state.
"""

import itertools
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from judging_agent.config import settings
from judging_agent.drive.base import DriveBackend, ResourceMeta
from judging_agent.guardian import audit
from judging_agent.guardian.context import CallContext
from judging_agent.guardian.decision import Decision, Layer, Verdict
from judging_agent.guardian.engine import PolicyEngine
from judging_agent.guardian.escalation import PENDING, EscalationHandler
from judging_agent.guardian.judges import Judge
from judging_agent.guardian.rules import Budget, check_write_budget
from judging_agent.guardian.scope import TaskScope
from judging_agent.guardian.session import Session
from judging_agent.tools import TOOLS


@dataclass
class ToolOutcome:
    call_id: str
    tool: str
    args: dict
    decision: Decision
    result: dict                    # what the worker sees
    status: str                     # "executed" | "blocked" | "failed" | "pending"
    resource: str | None = None     # path if known, else the raw ID

    @property
    def judged(self) -> str:
        """The Guardian's verdict before any human: allow | block | escalate."""
        return Verdict.ESCALATE if self.decision.escalated else self.decision.outcome


Listener = Callable[[ToolOutcome, CallContext | None], None]


def console_listener(outcome: ToolOutcome, ctx: CallContext | None):
    d = outcome.decision
    icon = {"executed": "✅", "pending": "⏳", "failed": "⚠️"}.get(outcome.status, "🚫")
    tier = f", tier {d.tier}" if d.tier else ""
    print(f"  [GUARDIAN] {icon} {str(outcome.judged).upper()} ({d.layer}{tier}): {d.reason}")


@dataclass
class ToolGateway:
    task: str
    scope: TaskScope
    backend: DriveBackend
    judge: Judge
    escalate: EscalationHandler
    audit_path: str | Path = field(default_factory=lambda: settings().audit_path)
    workspace_root: str | None = None   # folder ID; None = the whole Drive
    budget: Budget = field(default_factory=Budget)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    verbose: bool = True                # adds console_listener
    listeners: list[Listener] = field(default_factory=list)

    def __post_init__(self):
        self.engine = PolicyEngine(self.task, self.scope, self.judge, self.workspace_root, self.budget)
        self.session = Session(self.task)
        self.outcomes: list[ToolOutcome] = []
        self.pending: dict[str, tuple[str, dict, Decision, CallContext]] = {}
        self._ids = itertools.count(1)
        self._user_email: str | None = None
        if self.verbose:
            self.listeners.append(console_listener)

    @property
    def provenance(self):
        return self.session.provenance

    # ── public API ────────────────────────────────────────────────────────────

    def execute(self, tool_name: str, args: dict) -> ToolOutcome:
        call_id = f"{self.run_id}-{next(self._ids)}"
        decision, ctx = self.engine.evaluate(tool_name, args, self.session, self._lookup)
        self.session.usage.calls += 1

        if decision.outcome == Verdict.ESCALATE:
            answer = self.escalate(ctx, decision.reason)
            if answer is PENDING:
                self.pending[call_id] = (tool_name, args, decision, ctx)
                self._audit(audit.decision_record(**self._record_fields(
                    call_id, tool_name, args, decision, ctx, Verdict.ESCALATE, "pending")))
                result = {"status": "pending", "message": "Waiting for a human to approve this call."}
                return self._done(ToolOutcome(call_id, tool_name, args, decision, result, "pending",
                                              self._resource_label(tool_name, args, ctx)), ctx)
            decision = _human_decision(decision, bool(answer))
        return self._finish(call_id, tool_name, args, decision, ctx)

    def resolve(self, call_id: str, approved: bool) -> ToolOutcome:
        """A human's answer to a PENDING call: run it (approved) or block it.

        The write budget is checked again: other writes may have run while it waited.
        """
        if call_id not in self.pending:
            raise ValueError(f"No pending call {call_id!r}: it was never held, or it has already been answered.")
        tool_name, args, decision, ctx = self.pending.pop(call_id)
        decision = _human_decision(decision, approved)
        if approved:
            over = check_write_budget(TOOLS[tool_name], args, self.session.usage, self.budget)
            if over:
                decision = Decision(Verdict.BLOCK, f"Approved by human, but {over.reason[0].lower()}{over.reason[1:]}",
                                    Layer.RULE, decision.tier, escalated=True, raw=decision.raw)
        return self._finish(call_id, tool_name, args, decision, ctx)

    def summary(self) -> str:
        lines = [f"Task : {self.task}", f"Scope: {self.scope.to_dict()}", ""]
        for i, o in enumerate(self.outcomes, 1):
            via = " (human)" if o.decision.escalated else ""
            lines.append(f"[{i}] {o.status.upper()}{via} [{o.decision.layer}] {o.tool}({audit.short_args(o.args)})")
            lines.append(f"     Reason: {o.decision.reason}")
        return "\n".join(lines)

    # ── internals ─────────────────────────────────────────────────────────────

    def _finish(self, call_id, tool_name, args, decision: Decision, ctx) -> ToolOutcome:
        judged = Verdict.ESCALATE if decision.escalated else decision.outcome
        label = self._resource_label(tool_name, args, ctx)
        if not decision.approved:
            self._audit(audit.decision_record(**self._record_fields(call_id, tool_name, args, decision, ctx, judged, "blocked")))
            result = {"error": "blocked by guardian", "reason": decision.reason}
            return self._done(ToolOutcome(call_id, tool_name, args, decision, result, "blocked", label), ctx)

        # No record, no action: if the audit log can't be written, the call doesn't run.
        record = audit.decision_record(**self._record_fields(call_id, tool_name, args, decision, ctx, judged, "approved"))
        try:
            audit.append(self.audit_path, record)
        except Exception as exc:
            decision = Decision.block(f"Audit log could not be written ({exc}); blocked to be safe.")
            result = {"error": "blocked by guardian", "reason": decision.reason}
            return self._done(ToolOutcome(call_id, tool_name, args, decision, result, "blocked", label), ctx)

        spec = TOOLS[tool_name]
        try:
            result = spec.run(self.backend, args)
        except Exception as exc:
            result = {"error": f"Tool failed: {exc}"}
            self._audit(audit.failure_record(run_id=self.run_id, call_id=call_id, error=str(exc)))
            return self._done(ToolOutcome(call_id, tool_name, args, decision, result, "failed", label), ctx)
        self.session.record(spec, args, result, ctx.resource, self.scope, self._user())
        return self._done(ToolOutcome(call_id, tool_name, args, decision, result, "executed", label), ctx)

    def _done(self, outcome: ToolOutcome, ctx: CallContext | None) -> ToolOutcome:
        self.outcomes.append(outcome)
        self.session.history.append(
            {"tool": outcome.tool, "resource": outcome.resource, "outcome": outcome.decision.outcome})
        for listener in self.listeners:
            try:
                listener(outcome, ctx)
            except Exception as exc:     # a broken UI must never break the Guardian
                print(f"[gateway] listener failed: {exc}", file=sys.stderr)
        return outcome

    def _record_fields(self, call_id, tool_name, args, decision, ctx, judged, status) -> dict:
        return dict(run_id=self.run_id, call_id=call_id, task=self.task, scope=self.scope.to_dict(),
                    judge=self.judge.name, tool=tool_name, args=args, decision=decision,
                    judged=judged, status=status, ctx=ctx)

    def _audit(self, record: dict):
        """Audit for calls that don't run; a failure is reported but changes nothing."""
        try:
            audit.append(self.audit_path, record)
        except Exception as exc:
            print(f"[gateway] audit log could not be written: {exc}", file=sys.stderr)

    def _lookup(self, resource_id: str) -> ResourceMeta | None:
        return self.backend.get_metadata(resource_id)

    def _user(self) -> str:
        """The account the agent acts for. If it can't be read, every file counts as someone else's."""
        if self._user_email is None:
            try:
                self._user_email = self.backend.user_email()
            except Exception:
                self._user_email = "unknown"
        return self._user_email

    @staticmethod
    def _resource_label(tool_name: str, args: dict, ctx: CallContext | None) -> str | None:
        if ctx:
            return ctx.resource.path
        spec = TOOLS.get(tool_name)
        return str(args.get(spec.resource_arg)) if spec and "_unparsed" not in args else None


def _human_decision(decision: Decision, approved: bool) -> Decision:
    return Decision(
        Verdict.ALLOW if approved else Verdict.BLOCK,
        f"{'Approved' if approved else 'Denied'} by human. Guardian said: {decision.reason}",
        Layer.HUMAN, decision.tier, escalated=True, raw=decision.raw,
    )
