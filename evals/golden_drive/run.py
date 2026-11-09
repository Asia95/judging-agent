"""
evals/golden_drive/run.py — the scripted scenarios on the real-Drive golden dataset.

Usage (from the project root):
    python -m evals.golden_drive.run           # live: watsonx.ai derives scope and judges
    python -m evals.golden_drive.run --stub    # offline judge: fixed scopes + StubJudge

Requires:
  - credentials/token.json  (run `python -m judging_agent.drive.google` once)
  - evals/golden_drive/ids.json  (run `python -m evals.golden_drive.setup` once)

Reads go to the real Drive; writes go through DryRunDrive, so they are judged
as usual but never change Drive.
"""

import argparse
import sys

from evals.golden_drive.dataset import build_scenarios, load_ids
from evals.results import save_result
from evals.scripted import print_summary, result_metrics, run_all
from judging_agent.config import RUNS_DIR, settings
from judging_agent.drive import DryRunDrive, GoogleDrive

AUDIT_PATH = RUNS_DIR / "audit.golden.jsonl"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stub", action="store_true",
                        help="offline judge: fixed scopes and StubJudge (real Drive is still read)")
    args = parser.parse_args()

    live_model = None
    if not args.stub:
        from judging_agent.llm import guardian_model
        live_model = guardian_model()

    print("=" * 60)
    print("  Guardian Golden Drive Runner")
    print(f"  Mode   : {'STUB (offline judge)' if args.stub else 'LIVE (watsonx.ai)'}")
    print("  Backend: real Google Drive (writes are dry-run)")
    print("=" * 60)

    scenarios = build_scenarios(load_ids())
    drive = GoogleDrive()   # one OAuth session; each scenario gets its own dry-run wrapper
    totals = run_all(scenarios, lambda: DryRunDrive(drive), live_model, AUDIT_PATH)
    print_summary(totals, AUDIT_PATH)
    save_result("golden-drive-stub" if args.stub else "golden-drive",
                f"Scripted scenarios, real Drive ({'stub judge' if args.stub else 'live judge'})",
                result_metrics(totals), "stub" if args.stub else settings().guardian_model_id)
    sys.exit(1 if totals["correct"] < totals["calls"] else 0)


if __name__ == "__main__":
    main()
