"""
evals/results.py — each eval's latest numbers, for the demo UI's Results tab.

Every runner saves one small JSON file in runs/results/. The UI only reads
these files: it never starts an eval, because evals are slow and cost tokens.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from judging_agent.config import RUNS_DIR
from judging_agent.guardian.prompts import PROMPT_VERSION

RESULTS_DIR = RUNS_DIR / "results"


def save_result(name: str, title: str, metrics: dict, model: str, results_dir: Path = RESULTS_DIR) -> None:
    """Replace the latest result of one eval. `name` is the file name; include the mode (stub or live)."""
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{name}.json").write_text(json.dumps({
        "name": name,
        "title": title,
        "metrics": metrics,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")


def load_results(results_dir: Path = RESULTS_DIR) -> list[dict]:
    """Every saved result, sorted by name. A file that can't be read is skipped."""
    results = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and {"title", "metrics", "model", "timestamp"} <= record.keys():
            results.append(record)
    return results
