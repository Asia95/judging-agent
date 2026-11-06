"""
worker/graph.py — the Worker as a LangGraph agent.

    START → agent ─(tool calls?)─→ tools → agent → … → END

  agent  the worker model (ChatWatsonx), offered only the tool schemas the
         task's scope allows. It never holds a tool object.
  tools  OUR node, not LangGraph's ToolNode: it hands every call to
         gateway.execute() and nothing else, so the only way from the graph to
         Drive is through the Guardian. Calls run one at a time (the gateway
         keeps per-session state), and invalid or invented tool calls are sent
         to the gateway too, so they are blocked and audited like any other.

Human approval. If the gateway's escalation handler returns PENDING, the tools
node pauses the graph with LangGraph's interrupt(); the caller shows the
question to a human and continues with resume(approved), which calls
gateway.resolve(). With a handler that answers right away (console), the graph
never pauses.

LangGraph re-runs a paused node from the top when it resumes, and hands each
interrupt() call its answer by POSITION (the first interrupt() in the node gets
the first answer, and so on). So within one model turn the node remembers, per
call position, which calls already finished (reused, never executed twice),
which one is waiting for a human, and which ones were answered by a human
(they call interrupt() again on every re-run, so later answers keep their
positions). The memory is reset when a new model turn starts.

One GraphWorker runs one task, like its gateway.

The Guardian (scope derivation, gateway, judge) stays outside the graph: the
scope is derived from the task before the graph starts and handed in.
"""

import json
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt

from judging_agent.guardian.gateway import ToolGateway
from judging_agent.tools import tool_schemas

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to Google Drive tools. "
    "Complete the task given by the user using only the tools available to you. "
    "Do not attempt to access files or folders that are not relevant to the task."
)


@dataclass
class WorkerStep:
    """Where a run stands: finished with an answer, or waiting for a human."""
    answer: str | None = None       # the final answer, once the worker is done
    pending: dict | None = None     # {call_id, tool, args, reason} while a human must decide

    @property
    def done(self) -> bool:
        return self.pending is None


@dataclass
class GraphWorker:
    gateway: ToolGateway
    model: object = None            # a LangChain chat model; default: worker_chat_model()
    max_turns: int = 20             # model turns before the run is stopped
    thread_id: str = field(default="")

    def __post_init__(self):
        if self.model is None:
            from judging_agent.llm import worker_chat_model
            self.model = worker_chat_model()
        self.thread_id = self.thread_id or self.gateway.run_id
        self.tools = tool_schemas(self.gateway.scope.actions)
        self.graph = self._build()
        self._started = False
        # Memory for the current model turn, keyed by the call's position in the message:
        self._turn: str | None = None           # id of the model message these calls belong to
        self._finished: dict[int, dict] = {}    # position -> result (reused on re-runs)
        self._waiting: dict[int, str] = {}      # position -> gateway call_id awaiting a human
        self._answered: set[int] = set()        # positions a human answered (re-call interrupt())

    # ── public API ────────────────────────────────────────────────────────────

    def start(self, task: str) -> WorkerStep:
        if self._started:
            raise RuntimeError("A GraphWorker runs one task; create a new worker (and gateway) for the next.")
        self._started = True
        return self._invoke({"messages": [("user", task)]})

    def resume(self, approved: bool) -> WorkerStep:
        """Answer the pending question and continue."""
        return self._invoke(Command(resume=approved))

    def run(self, task: str, approve: Callable[[dict], bool] = lambda pending: False) -> str:
        """Run to the end, asking approve(pending) whenever a human must decide."""
        step = self.start(task)
        while not step.done:
            step = self.resume(approve(step.pending))
        return step.answer

    # ── the graph ─────────────────────────────────────────────────────────────

    def _build(self):
        model = self.model.bind_tools(self.tools)

        def agent(state: MessagesState):
            return {"messages": [model.invoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])]}

        def route(state: MessagesState):
            last = state["messages"][-1]
            wants_tools = isinstance(last, AIMessage) and (last.tool_calls or last.invalid_tool_calls)
            return "tools" if wants_tools else END

        graph = StateGraph(MessagesState)
        graph.add_node("agent", agent)
        graph.add_node("tools", self._tools_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", route, ["tools", END])
        graph.add_edge("tools", "agent")
        return graph.compile(checkpointer=InMemorySaver())

    def _tools_node(self, state: MessagesState):
        last: AIMessage = state["messages"][-1]
        if last.id != self._turn:                   # a new model turn: forget the previous one's calls
            self._turn, self._finished, self._waiting, self._answered = last.id, {}, {}, set()
        calls = [(c["id"], c["name"], c["args"]) for c in last.tool_calls]
        # Arguments that weren't valid JSON: the gateway blocks and audits them.
        calls += [(c["id"], c["name"] or "", {"_unparsed": c["args"] or ""}) for c in last.invalid_tool_calls]
        messages = []
        for position, (call_id, name, args) in enumerate(calls):
            result = self._call(position, name, args)
            messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call_id, name=name))
        return {"messages": messages}

    def _call(self, position: int, name: str, args: dict) -> dict:
        """One tool call through the gateway; pauses the graph if a human must decide."""
        if position in self._finished:              # re-run after resume: never execute twice
            if position in self._answered:
                interrupt(None)                     # consume this call's answer so later ones keep their position
            return self._finished[position]
        if position in self._waiting:               # the human has answered this one
            approved = interrupt(None)              # on resume this returns the human's answer
            self._answered.add(position)
            outcome = self.gateway.resolve(self._waiting.pop(position), approved=bool(approved))
        else:
            outcome = self.gateway.execute(name, args)
            if outcome.status == "pending":
                self._waiting[position] = outcome.call_id
                interrupt({"call_id": outcome.call_id, "tool": name, "args": args,
                           "resource": outcome.resource, "reason": outcome.decision.reason})
        self._finished[position] = outcome.result
        return outcome.result

    def _invoke(self, payload) -> WorkerStep:
        config = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": 2 * self.max_turns + 1}
        try:
            state = self.graph.invoke(payload, config)
        except GraphRecursionError:
            return WorkerStep(answer=f"(stopped after {self.max_turns} turns)")
        if state.get("__interrupt__"):
            return WorkerStep(pending=state["__interrupt__"][0].value)
        text = str(state["messages"][-1].text).strip()   # .text also joins content blocks
        return WorkerStep(answer=text or "(no text response)")
