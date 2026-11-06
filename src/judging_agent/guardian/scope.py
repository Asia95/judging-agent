"""
guardian/scope.py — what the task allows, derived before the worker starts.

An LLM turns the task text into a soft TaskScope: intended actions, locations
the task points to, and hints of data it clearly doesn't need. Only `actions`
is a hard limit. The scope is frozen before the worker reads anything.

If the LLM fails, the fallback is read-only and uses a fixed list of sensitive
keywords, so a broken scope LLM makes the Guardian stricter, never looser.
`source` records which happened, and is written to every audit record.
"""

from dataclasses import asdict, dataclass

from judging_agent.guardian.prompts import SCOPE_SYSTEM_PROMPT
from judging_agent.llm import chat_json
from judging_agent.tools import Action

# Used when the scope LLM is unavailable: a code-level floor for "out of bounds".
DEFAULT_SENSITIVE_HINTS = ("payroll", "salary", "salaries", "hr", "personal", "confidential")


@dataclass(frozen=True)
class TaskScope:
    intent: str
    actions: tuple[Action, ...] = (Action.LIST, Action.READ)
    relevant_locations: tuple[str, ...] = ()
    out_of_bounds_hints: tuple[str, ...] = ()
    source: str = "manual"          # "llm" | "fallback" | "manual" (written by hand, e.g. in evals)

    def to_dict(self) -> dict:
        return asdict(self)


def fallback_scope(task: str) -> TaskScope:
    return TaskScope(intent=task, out_of_bounds_hints=DEFAULT_SENSITIVE_HINTS, source="fallback")


def derive_scope(task: str, model) -> TaskScope:
    """Ask the LLM for a TaskScope. Falls back to fallback_scope() on any failure."""
    try:
        data, _ = chat_json(model, SCOPE_SYSTEM_PROMPT, task)
    except Exception:
        return fallback_scope(task)
    if data is None:
        return fallback_scope(task)

    def str_list(key: str) -> tuple[str, ...]:
        values = data.get(key)
        if not isinstance(values, (list, tuple)):   # a bare string would be split into letters
            return ()
        return tuple(str(v).strip().lower() for v in values if str(v).strip())[:5]

    actions = {Action(a) for a in str_list("actions") if a in tuple(Action)}
    # Writing needs reading (an overwrite requires a prior read), and reading needs
    # listing (it's how the worker finds files), so the LLM can't leave them out.
    if Action.WRITE in actions:
        actions.add(Action.READ)
    if Action.READ in actions:
        actions.add(Action.LIST)
    if not actions:
        return fallback_scope(task)
    return TaskScope(
        intent=str(data.get("intent") or task),
        actions=tuple(a for a in Action if a in actions),
        relevant_locations=str_list("relevant_locations"),
        out_of_bounds_hints=str_list("out_of_bounds_hints"),
        source="llm",
    )
