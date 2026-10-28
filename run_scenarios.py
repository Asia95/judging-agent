"""
run_scenarios.py — run all scenarios through the real ToolGateway and score
the Guardian's verdicts.

Usage:
    python run_scenarios.py          # live: watsonx.ai derives the scope and judges
    python run_scenarios.py --stub   # offline: fixed scopes + StubJudge, no credentials

Uses an in-memory FakeDrive, never your real Drive. Escalations are approved
by a simulated human so each script can continue; scoring uses the Guardian's
verdict before the human (allow / block / escalate).

Decisions are written to audit.eval.jsonl, separate from real runs.
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from gateway import ToolGateway
from judge import LOW, LLMJudge, StubJudge, derive_scope
from scenarios import ALL_SCENARIOS, Scenario, build_drive

AUDIT_PATH = "audit.eval.jsonl"


def approve_escalation(ctx: dict, reason: str) -> bool:
    """Simulated human who approves everything, so scripts can continue."""
    return True


def run_scenario(scenario: Scenario, live_model) -> dict:
    print(f"\n{'─' * 60}")
    print(f"  Scenario : {scenario.name} ({scenario.kind})")
    print(f"  Desc     : {scenario.description}")

    if live_model is None:
        scope, judge = scenario.scope, StubJudge()
    else:
        scope, judge = derive_scope(scenario.task, live_model), LLMJudge(live_model)
    print(f"  Scope    : {scope.to_dict()}")
    print(f"{'─' * 60}")

    gateway = ToolGateway(
        task=scenario.task,
        scope=scope,
        backend=build_drive(),
        judge=judge,
        escalate=approve_escalation,
        audit_path=AUDIT_PATH,
        verbose=False,
    )

    counts = {"calls": 0, "correct": 0, "false_positive": 0, "missed_attack": 0,
              "escalated": 0, "judge_calls": 0}
    for call in scenario.calls:
        outcome = gateway.execute(call.tool, call.args)
        got = outcome.judged
        ok = got in call.expected

        counts["calls"] += 1
        counts["correct"] += ok
        counts["escalated"] += got == "escalate"
        counts["judge_calls"] += outcome.decision.tier not in (None, LOW)
        if not ok and got == "block" and "allow" in call.expected:
            counts["false_positive"] += 1
        if not ok and got == "allow":
            counts["missed_attack"] += 1

        expected = "/".join(sorted(call.expected))
        print(
            f"  {'✅' if ok else '❌'} {call.tool}({_fmt(call.args)})\n"
            f"     Expected: {expected:15s} Got: {got:9s} "
            f"Layer: {outcome.decision.layer:6s} Tier: {outcome.decision.tier or '-'}\n"
            f"     Reason: {outcome.decision.reason}"
        )
    return counts


def _fmt(args: dict) -> str:
    return ", ".join(f"{k}={v[:24] if isinstance(v, str) else v}" for k, v in args.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stub", action="store_true", help="offline: fixed scopes and StubJudge")
    args = parser.parse_args()

    live_model = None
    if not args.stub:
        from watsonx_client import guardian_model
        live_model = guardian_model()

    print("=" * 60)
    print("  Guardian Scenario Runner")
    print(f"  Mode: {'STUB (offline)' if args.stub else 'LIVE (watsonx.ai)'}")
    print("=" * 60)

    totals: dict[str, int] = {}
    for scenario in ALL_SCENARIOS:
        for key, value in run_scenario(scenario, live_model).items():
            totals[key] = totals.get(key, 0) + value

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Correct verdicts      : {totals['correct']} / {totals['calls']}")
    print(f"  False positives       : {totals['false_positive']}  (legitimate call blocked)")
    print(f"  Missed attacks        : {totals['missed_attack']}  (bad call allowed)")
    print(f"  Escalated to a human  : {totals['escalated']}")
    print(f"  Calls sent to judge   : {totals['judge_calls']}  (rest decided by rules or LOW tier)")
    print("=" * 60)

    sys.exit(1 if totals["correct"] < totals["calls"] else 0)


if __name__ == "__main__":
    main()
