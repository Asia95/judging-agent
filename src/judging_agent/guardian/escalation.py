"""
guardian/escalation.py — who decides when the Guardian escalates.

A handler gets the judge context and the Guardian's reason, and returns True
to approve the call. The gateway takes one as `escalate=`.
"""

from typing import Callable

EscalationHandler = Callable[[dict, str], bool]


def console_escalation(ctx: dict, reason: str) -> bool:
    """Ask a human operator on stdin. Returns True if approved."""
    print("\n" + "=" * 60)
    print("  ⚠️  HUMAN ESCALATION REQUIRED")
    print("=" * 60)
    print(f"  Tool     : {ctx['tool']}")
    print(f"  Resource : {ctx['metadata']['path']}  (owner: {ctx['metadata']['owner']})")
    print(f"  Found via: {ctx['sighting'].describe()}")
    print(f"  Reason   : {reason}")
    print("=" * 60)
    while True:
        answer = input("  Approve this tool call? [approve/deny]: ").strip().lower()
        if answer in ("approve", "a", "yes", "y"):
            return True
        if answer in ("deny", "d", "no", "n"):
            return False
        print("  Please enter 'approve' or 'deny'.")


def deny_escalation(ctx: dict, reason: str) -> bool:
    """Non-interactive handler: every escalation is denied."""
    return False


def approve_escalation(ctx: dict, reason: str) -> bool:
    """Simulated human who approves everything, so eval scripts can continue.
    Evals score the Guardian's verdict before this handler runs."""
    return True
