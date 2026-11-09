"""
apps/ui/runner.py — one demo run: scope → gateway → worker, as a state machine (no Streamlit).

    IDLE → RUNNING → (WAITING ⇄ RUNNING)* → DONE | FAILED
                └──────────── ABORTED (the page was re-run in the middle of a call)

There are no threads. start() and answer_pending() run the worker until it
finishes or a human must decide (GraphWorker pauses at LangGraph interrupts),
so a click on Approve is just the next Streamlit script run calling
answer_pending(). Every Guardian decision is turned into a CallEvent and
handed to on_event as it happens, which is how the page updates live.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable

from apps.ui.events import CallEvent, from_outcome, remember_names
from apps.ui.tree import TreeRow, walk
from apps.ui.unguarded import UnguardedGateway
from judging_agent.config import RUNS_DIR
from judging_agent.drive.base import DriveBackend
from judging_agent.guardian import Judge, LLMJudge, TaskScope, ToolGateway, derive_scope, pending_escalation
from judging_agent.worker import GraphWorker, WorkerStep

UI_AUDIT_PATH = RUNS_DIR / "audit.ui.jsonl"


class RunState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting_for_human"
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class DemoRun:
    task: str
    drive: DriveBackend
    workspace_root: str | None = None
    on_event: Callable[[CallEvent], None] = lambda event: None    # the live renderer
    on_scope: Callable[[TaskScope], None] = lambda scope: None    # called once, before the worker starts
    # Injected for tests; by default the watsonx models from judging_agent.llm.
    guardian_llm: object = None             # derives the scope and backs the LLM judge
    worker_model: object = None             # a LangChain chat model
    judge: Judge | None = None              # default: LLMJudge(guardian_llm)
    scope: TaskScope | None = None          # default: derived from the task
    audit_path: str | Path = UI_AUDIT_PATH
    guardian: bool = True                   # False: no checks at all, fake Drive only

    state: RunState = RunState.IDLE
    events: list[CallEvent] = field(default_factory=list)
    pending: dict | None = None             # what the human is asked, while WAITING
    answer: str | None = None
    error: str | None = None

    def __post_init__(self):
        self.gateway: ToolGateway | None = None
        self._worker: GraphWorker | None = None
        self._names: dict[str, str] = {}
        self._tree: tuple[int, list[TreeRow]] | None = None

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        if self.state != RunState.IDLE:
            raise RuntimeError(f"This run has already started ({self.state}); create a new DemoRun.")
        self.state = RunState.RUNNING
        self._step(self._begin)

    def answer_pending(self, approved: bool):
        if self.state != RunState.WAITING:
            raise RuntimeError(f"Nothing is waiting for a human (the run is {self.state}).")
        self.state, self.pending = RunState.RUNNING, None
        self._step(lambda: self._worker.resume(approved))

    def recover(self):
        """Call at the start of every page run: a run still RUNNING was cut off mid-call."""
        if self.state == RunState.RUNNING:
            self.state = RunState.ABORTED
            self.error = "The page was reloaded while the run was in progress. Start a new run."

    @property
    def busy(self) -> bool:
        return self.state == RunState.RUNNING

    @property
    def finished(self) -> bool:
        return self.state in (RunState.DONE, RunState.FAILED, RunState.ABORTED)

    @property
    def taint(self) -> tuple[str, ...]:
        """Why the session is tainted right now; empty = clean."""
        return tuple(self.gateway.provenance.taint) if self.gateway else ()

    def tree(self) -> list[TreeRow]:
        """The workspace's folder tree. Read once, and again only after a write changed it."""
        writes = sum(e.status == "executed" and e.tool in ("drive_update_file", "drive_create_file")
                     for e in self.events)
        if self._tree is None or self._tree[0] != writes:
            self._tree = (writes, walk(self.drive, self.workspace_root))
        return self._tree[1]

    # ── internals ─────────────────────────────────────────────────────────────

    def _begin(self) -> WorkerStep:
        self.gateway = self._guarded_gateway() if self.guardian else self._unguarded_gateway()
        self._worker = GraphWorker(self.gateway, model=self.worker_model)
        return self._worker.start(self.task)

    def _guarded_gateway(self) -> ToolGateway:
        if self.guardian_llm is None and (self.scope is None or self.judge is None):
            from judging_agent.llm import guardian_model
            self.guardian_llm = guardian_model()
        if self.scope is None:
            self.scope = derive_scope(self.task, self.guardian_llm)
        self.on_scope(self.scope)
        return ToolGateway(
            task=self.task, scope=self.scope, backend=self.drive,
            judge=self.judge or LLMJudge(self.guardian_llm), escalate=pending_escalation,
            audit_path=self.audit_path, workspace_root=self.workspace_root,
            verbose=False, listeners=[self._listen],
        )

    def _unguarded_gateway(self) -> UnguardedGateway:
        gateway = UnguardedGateway(self.task, self.drive, listeners=[self._listen])  # refuses a real Drive
        self.scope = gateway.scope
        return gateway

    def _step(self, advance: Callable[[], WorkerStep]):
        try:
            step = advance()
        except Exception as exc:            # watsonx down, Drive auth expired, ...
            self.state, self.error = RunState.FAILED, f"{type(exc).__name__}: {exc}"
            return
        if step.done:
            self.state, self.answer = RunState.DONE, step.answer
        else:
            self.state, self.pending = RunState.WAITING, step.pending

    def _listen(self, outcome, ctx):
        """A held call's answer replaces its pending event (one card per call, like replay)."""
        remember_names(self._names, outcome, ctx)
        held = next((i for i, e in enumerate(self.events) if e.call_id == outcome.call_id), None)
        index = len(self.events) + 1 if held is None else self.events[held].index
        event = from_outcome(outcome, ctx, index, self._names)
        if held is None:
            self.events.append(event)
        else:
            self.events[held] = event
        self.on_event(event)
