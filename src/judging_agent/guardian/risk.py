"""
guardian/risk.py — risk tiers: a pure function over metadata, provenance and taint.

  LOW    → allow without an LLM call
  MEDIUM → the judge decides
  HIGH   → the judge may block or escalate, never allow outright

Why LOW still uses the task's location keywords and not folder ancestry: a task
often names the top folder ("somewhere in my Drive, root ID …"), and "inside a
folder named in the task" would then make the whole Drive LOW and skip the judge.
"""

import re

from judging_agent.drive.base import ResourceMeta
from judging_agent.guardian.decision import Tier
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import Action


def _mentions(text: str, keyword: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def hint_matches(resource: ResourceMeta, scope: TaskScope) -> list[str]:
    """The out-of-bounds hints that the resource's path or owner matches."""
    text = f"{resource.path} {resource.owner}".lower()
    return [h for h in scope.out_of_bounds_hints if _mentions(text, h)]


def risk_tier(
    action: Action,
    resource: ResourceMeta,
    sighting: Sighting,
    scope: TaskScope,
    taint: tuple[str, ...] = (),
) -> tuple[Tier, str]:
    """Return (tier, reason) for a call that already passed the fixed rules.

    taint: reasons the session is tainted (see provenance.py); it makes writes HIGH.
    """
    high = []
    hits = hint_matches(resource, scope)
    if hits:
        high.append(f"resource matches out-of-bounds hint(s): {', '.join(hits)}")
    if not sighting.trusted:
        high.append(f"ID is untrusted ({sighting.describe()})")
    if action == Action.WRITE and taint:
        high.append(f"write after the session was exposed to risky content ({'; '.join(taint)})")
    if high:
        return Tier.HIGH, "; ".join(high)
    if action == Action.WRITE:
        return Tier.MEDIUM, "writes always need a judgement"
    if sighting.source == "task":
        return Tier.LOW, "resource is named in the task"
    if any(_mentions(resource.path.lower(), loc) for loc in scope.relevant_locations):
        return Tier.LOW, "resource is in a location the task points to"
    return Tier.MEDIUM, "no direct match with the task; judge whether the task plausibly needs it"
