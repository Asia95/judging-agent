"""
apps/ui/unguarded.py — the Guardian switched OFF, for the side-by-side comparison only.

Has the parts of ToolGateway that GraphWorker and DemoRun use, but runs every
call without checking it. It refuses any backend except the in-memory fake
Drive, so it can never touch real files, and it writes no audit log.
"""

import itertools
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

from judging_agent.drive import FakeDrive
from judging_agent.guardian import Decision, TaskScope, ToolOutcome, Verdict
from judging_agent.guardian.gateway import Listener
from judging_agent.tools import TOOLS, Action, validate_args

NOT_CHECKED = Decision(Verdict.ALLOW, "Guardian off: this call was not checked.", layer=None)


@dataclass
class UnguardedGateway:
    task: str
    backend: FakeDrive
    listeners: list[Listener] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.backend, FakeDrive):
            raise ValueError("The Guardian can only be switched off on the fake Drive.")
        self.scope = TaskScope(intent=self.task, actions=tuple(Action), source="guardian off")
        self.run_id = uuid.uuid4().hex[:8]
        self.provenance = SimpleNamespace(taint=[])     # nothing tracks it with the Guardian off
        self._ids = itertools.count(1)

    def execute(self, tool_name: str, args: dict) -> ToolOutcome:
        call_id = f"{self.run_id}-{next(self._ids)}"
        spec = TOOLS.get(tool_name)
        problem = f"Unknown tool {tool_name!r}." if spec is None else validate_args(spec, args)
        try:
            if problem:
                raise ValueError(problem)
            result, status = spec.run(self.backend, args), "executed"
        except Exception as exc:
            result, status = {"error": f"Tool failed: {exc}"}, "failed"
        target = args.get(spec.resource_arg) if spec else None
        meta = self.backend.get_metadata(target) if isinstance(target, str) else None
        outcome = ToolOutcome(call_id, tool_name, args, NOT_CHECKED, result, status, meta.path if meta else target)
        for listener in self.listeners:
            listener(outcome, None)
        return outcome
