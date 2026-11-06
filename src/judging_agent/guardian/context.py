"""
guardian/context.py — everything known about one tool call when it is judged.

Built by the PolicyEngine and passed to judges, escalation handlers, the audit
log and event listeners (e.g. a UI).
"""

from dataclasses import dataclass

from judging_agent.drive.base import ResourceMeta
from judging_agent.guardian.decision import Tier
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import Action


@dataclass(frozen=True)
class CallContext:
    task: str
    scope: TaskScope
    tool: str
    action: Action
    args: dict
    resource_arg: str               # which argument names the resource (the rest is worker-chosen)
    resource: ResourceMeta
    sighting: Sighting              # how the worker learned the resource's ID
    tier: Tier
    tier_reason: str
    history: tuple[dict, ...]       # earlier calls: {tool, resource, outcome}
    taint: tuple[str, ...]          # why the session is tainted; empty = clean

    @property
    def worker_args(self) -> dict:
        """Arguments the worker chose itself, i.e. everything except the resource ID."""
        return {k: v for k, v in self.args.items() if k != self.resource_arg}
