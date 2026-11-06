"""
guardian/escalation.py — who decides when the Guardian escalates.

A handler gets the call context and the Guardian's reason, and returns:
  True / False — approved / denied right away (console, scripts)
  PENDING      — "a human will decide later": the gateway holds the call and
                 runs it when someone calls gateway.resolve(call_id, approved).
                 This is what a UI button or a LangGraph interrupt() needs.
"""

from typing import Callable, Final

from judging_agent.guardian.context import CallContext


class _Pending:
    def __repr__(self) -> str:
        return "PENDING"


PENDING: Final = _Pending()

EscalationHandler = Callable[[CallContext, str], "bool | _Pending"]


def console_escalation(ctx: CallContext, reason: str) -> bool:
    """Ask a human operator on stdin. Returns True if approved."""
    print("\n" + "=" * 60)
    print("  ⚠️  HUMAN ESCALATION REQUIRED")
    print("=" * 60)
    print(f"  Tool     : {ctx.tool}")
    print(f"  Resource : {ctx.resource.path}  (owner: {ctx.resource.owner})")
    print(f"  Found via: {ctx.sighting.describe()}")
    print(f"  Reason   : {reason}")
    print("=" * 60)
    while True:
        answer = input("  Approve this tool call? [approve/deny]: ").strip().lower()
        if answer in ("approve", "a", "yes", "y"):
            return True
        if answer in ("deny", "d", "no", "n"):
            return False
        print("  Please enter 'approve' or 'deny'.")


def deny_escalation(ctx: CallContext, reason: str) -> bool:
    """Non-interactive handler: every escalation is denied."""
    return False


def approve_escalation(ctx: CallContext, reason: str) -> bool:
    """Simulated human who approves everything, so eval scripts can continue.
    Evals score the Guardian's verdict before this handler runs."""
    return True


def pending_escalation(ctx: CallContext, reason: str) -> _Pending:
    """Hold every escalated call until gateway.resolve() is called (UI, LangGraph)."""
    return PENDING
