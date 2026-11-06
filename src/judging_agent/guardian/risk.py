"""
guardian/risk.py — risk tiers: a pure function over metadata + provenance.

  LOW    → allow without an LLM call
  MEDIUM → the judge decides
  HIGH   → the judge may block or escalate, never allow outright
"""

import re

from judging_agent.guardian.decision import HIGH, LOW, MEDIUM
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.scope import TaskScope


def _mentions(text: str, keyword: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def risk_tier(action: str, metadata: dict, sighting: Sighting, scope: TaskScope) -> tuple[str, str]:
    """Return (tier, reason) for a call that already passed the fixed rules."""
    path = metadata["path"].lower()
    high = []
    hits = [h for h in scope.out_of_bounds_hints if _mentions(f"{path} {metadata['owner'].lower()}", h)]
    if hits:
        high.append(f"resource matches out-of-bounds hint(s): {', '.join(hits)}")
    if not sighting.trusted:
        high.append(f"ID was only seen inside document content ({sighting.describe()})")
    if high:
        return HIGH, "; ".join(high)
    if action == "write":
        return MEDIUM, "writes always need a judgement"
    if sighting.source == "task":
        return LOW, "resource is named in the task"
    if any(_mentions(path, loc) for loc in scope.relevant_locations):
        return LOW, "resource is in a location the task points to"
    return MEDIUM, "no direct match with the task; judge whether the task plausibly needs it"
