"""
guardian/session.py — everything the Guardian remembers during one task.

The PolicyEngine reads it to decide; the gateway updates it with record()
after a tool really ran. Keeping it separate lets evals build a session by
hand (e.g. "these files were already read") without running any tools.
"""

from dataclasses import dataclass, field

from judging_agent.drive.base import ResourceMeta
from judging_agent.guardian.provenance import ProvenanceTracker
from judging_agent.guardian.risk import hint_matches
from judging_agent.guardian.rules import Usage
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import Action, ToolSpec


@dataclass
class Session:
    task: str
    provenance: ProvenanceTracker = None    # type: ignore[assignment]  # built from task
    usage: Usage = field(default_factory=Usage)
    history: list[dict] = field(default_factory=list)   # {tool, resource, outcome}, for the judge

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = ProvenanceTracker(self.task)

    def record(
        self, spec: ToolSpec, args: dict, result: dict, resource: ResourceMeta, scope: TaskScope, user_email: str,
    ):
        """Update provenance, taint and usage after a tool ran successfully.

        A read taints the session (every later write becomes HIGH) when the file:
          - links to other Drive files (how injections redirect the agent),
          - matches an out-of-bounds hint (sensitive data is now in context), or
          - isn't owned by the user (someone else wrote it, so it may carry
            instructions; this also catches injections without any link).
        """
        linked = self.provenance.ingest(resource.id, result)
        if spec.action == Action.READ:
            if linked:
                self.provenance.mark_tainted(f"read {resource.path}, which links to other Drive files")
            if hint_matches(resource, scope):
                self.provenance.mark_tainted(f"read sensitive file {resource.path}")
            if resource.owner.lower() != user_email.lower():
                self.provenance.mark_tainted(f"read {resource.path}, owned by {resource.owner}, not by you")
        if spec.action == Action.WRITE:
            self.usage.writes += 1
            self.usage.chars_written += len(args.get("new_content", ""))
