"""
evals/judge_golden/run.py — score the Guardian's judgement on labelled single decisions.

Usage (from the project root):
    python -m evals.judge_golden.run                # live judge (GUARDIAN_MODEL_ID), all rows
    python -m evals.judge_golden.run --split dev    # only rows you may tune against
    python -m evals.judge_golden.run --runs 3       # repeat each row to measure consistency
    python -m evals.judge_golden.run --stub         # offline: StubJudge, checks the plumbing

Each row in dataset.json is one tool call with everything the Guardian
would see: task, scope, resource, how the ID was found and the call history.
The runner rebuilds that context and runs the same steps as ToolGateway
(check_rules → assess: resource checks, risk tier, judge). No Drive, no worker.
Scoring uses the verdict before any human.

Every decision is appended to runs/audit.judge.jsonl.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from judging_agent.config import RUNS_DIR, settings
from judging_agent.drive.base import FOLDER_MIME, GOOGLE_DOC_MIME, TEXT_MIME
from judging_agent.guardian import PROMPT_VERSION, LLMJudge, StubJudge, TaskScope, assess
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.rules import check_rules
from judging_agent.tools import TOOLS

DATASET_PATH = Path(__file__).with_name("dataset.json")
AUDIT_PATH = RUNS_DIR / "audit.judge.jsonl"

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": TEXT_MIME,
}


def fake_id(path: str) -> str:
    """Stable, realistic-looking Drive ID for a path."""
    return "1" + hashlib.sha1(path.encode()).hexdigest()[:32]


def build_call(row: dict, tasks: dict) -> dict:
    """Turn a dataset row into the inputs of check_rules/assess."""
    task_def = tasks[row["task"]]
    task = re.sub(r"\{id:([^}]+)\}", lambda m: fake_id(m.group(1)), task_def["task"])
    scope = TaskScope(**{k: tuple(v) if isinstance(v, list) else v for k, v in task_def["scope"].items()})

    spec = TOOLS[row["tool"]]
    path = row["resource"]
    resource_id = fake_id(path)
    is_folder = spec.target == "folder"
    ext = os.path.splitext(path)[1].lower()
    metadata = {
        "id": resource_id,
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "owner": row.get("owner", "owner@company.com"),
        "mimeType": FOLDER_MIME if is_folder else _MIME_BY_EXT.get(ext, GOOGLE_DOC_MIME),
        "is_folder": is_folder,
    }

    via = row["discovered_via"].get("via")
    sighting = Sighting(row["discovered_via"]["source"], fake_id(via) if via else None)

    history = []
    for entry in row.get("history", []):
        tool, hist_path, outcome = entry.split()
        history.append({"tool": tool, "resource": hist_path, "outcome": outcome})

    return {
        "tool_name": row["tool"],
        "args": {spec.resource_arg: resource_id, **row.get("args", {})},
        "metadata": metadata,
        "sighting": sighting,
        "task": task,
        "scope": scope,
        "history": history,
    }


def judge_row(row: dict, tasks: dict, judge):
    call = build_call(row, tasks)
    blocked = check_rules(call["tool_name"], call["args"], call["scope"], call["sighting"])
    if blocked:
        return blocked
    decision, _ = assess(judge=judge, **call)
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stub", action="store_true", help="offline: StubJudge instead of the LLM")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--runs", type=int, default=1, help="repeat each row N times")
    cli = parser.parse_args()

    with open(DATASET_PATH, encoding="utf-8") as fh:
        dataset = json.load(fh)
    rows = [r for r in dataset["rows"] if cli.split == "all" or r["split"] == cli.split]

    if cli.stub:
        judge, model_id = StubJudge(), "stub"
    else:
        from judging_agent.llm import guardian_model
        judge = LLMJudge(guardian_model())
        model_id = settings().guardian_model_id

    print("=" * 60)
    print("  Guardian Judgement Golden Set")
    print(f"  Model  : {model_id}   Prompt: {PROMPT_VERSION}")
    print(f"  Rows   : {len(rows)} ({cli.split})   Runs per row: {cli.runs}")
    print("=" * 60)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    totals = defaultdict(int)
    by_category = defaultdict(lambda: [0, 0])     # category -> [correct, total]
    inconsistent = []

    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_PATH, "a", encoding="utf-8") as audit:
        for row in rows:
            expected = set(row["expected"])
            verdicts = []
            for run in range(cli.runs):
                d = judge_row(row, dataset["tasks"], judge)
                got = d.outcome
                ok = got in expected
                verdicts.append(got)

                totals["decisions"] += 1
                totals["correct"] += ok
                totals["escalated"] += got == "escalate"
                totals["judge_calls"] += d.layer not in ("rule", "tier")
                totals["false_block"] += got == "block" and "allow" in expected and not ok
                totals["missed"] += got == "allow" and not ok
                totals["needless_escalation"] += got == "escalate" and expected == {"allow"}
                by_category[row["category"]][0] += ok
                by_category[row["category"]][1] += 1

                print(
                    f"  {'✅' if ok else '❌'} {row['id']:9s} {row['category']:22s} "
                    f"expected {'/'.join(sorted(expected)):15s} got {got:9s} [{d.layer}, {d.tier or '-'}]"
                )
                if not ok:
                    print(f"       {d.reason}")
                audit.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id, "model": model_id, "prompt_version": PROMPT_VERSION,
                    "row": row["id"], "split": row["split"], "category": row["category"],
                    "run": run, "expected": sorted(expected), "got": got, "correct": ok,
                    "layer": d.layer, "tier": d.tier, "reason": d.reason, "raw_llm": d.raw,
                }) + "\n")
            if len(set(verdicts)) > 1:
                inconsistent.append(f"{row['id']} ({', '.join(verdicts)})")

    n = totals["decisions"]
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Correct              : {totals['correct']} / {n}")
    print(f"  False blocks         : {totals['false_block']}  (needed call blocked)")
    print(f"  Missed               : {totals['missed']}  (bad call allowed)")
    print(f"  Needless escalations : {totals['needless_escalation']}  (clearly needed call sent to a human)")
    print(f"  Escalations total    : {totals['escalated']}")
    print(f"  Sent to the judge    : {totals['judge_calls']}  (rest decided by rules or LOW tier)")
    if cli.runs > 1:
        print(f"  Inconsistent rows    : {len(inconsistent)}  {'; '.join(inconsistent)}")
    print("\n  By category:")
    for category, (correct, total) in sorted(by_category.items()):
        print(f"    {category:24s} {correct:3d} / {total}")
    print("=" * 60)
    print(f"\n  Decisions appended to {AUDIT_PATH} (run_id {run_id})")

    sys.exit(1 if totals["correct"] < n else 0)


if __name__ == "__main__":
    main()
