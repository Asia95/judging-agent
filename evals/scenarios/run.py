"""
evals/scenarios/run.py — run the fake-Drive scenarios through the real
ToolGateway and score the Guardian's verdicts.

Usage (from the project root):
    python -m evals.scenarios.run          # live: watsonx.ai derives the scope and judges
    python -m evals.scenarios.run --stub   # offline: fixed scopes + StubJudge, no credentials

Uses an in-memory FakeDrive, never your real Drive.
"""

import argparse
import sys

from evals.scenarios.fixture import ALL_SCENARIOS, build_drive
from evals.scripted import print_summary, run_all
from judging_agent.config import RUNS_DIR

AUDIT_PATH = RUNS_DIR / "audit.eval.jsonl"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stub", action="store_true", help="offline: fixed scopes and StubJudge")
    args = parser.parse_args()

    live_model = None
    if not args.stub:
        from judging_agent.llm import guardian_model
        live_model = guardian_model()

    print("=" * 60)
    print("  Guardian Scenario Runner")
    print(f"  Mode: {'STUB (offline)' if args.stub else 'LIVE (watsonx.ai)'}")
    print("=" * 60)

    totals = run_all(ALL_SCENARIOS, build_drive, live_model, AUDIT_PATH)
    print_summary(totals, AUDIT_PATH)
    sys.exit(1 if totals["correct"] < totals["calls"] else 0)


if __name__ == "__main__":
    main()
