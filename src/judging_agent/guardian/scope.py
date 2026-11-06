"""
guardian/scope.py — what the task allows, derived before the worker starts.

An LLM turns the task text into a soft TaskScope: intended actions, locations
the task points to, and hints of data it clearly doesn't need. Only `actions`
is a hard limit. The scope is frozen before the worker reads anything.
"""

from dataclasses import asdict, dataclass

from judging_agent.guardian.prompts import SCOPE_SYSTEM_PROMPT
from judging_agent.llm import chat_json


@dataclass(frozen=True)
class TaskScope:
    intent: str
    actions: tuple[str, ...] = ("list", "read")
    relevant_locations: tuple[str, ...] = ()
    out_of_bounds_hints: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def derive_scope(task: str, model) -> TaskScope:
    """Ask the LLM for a TaskScope. Falls back to a read-only scope on any failure."""
    fallback = TaskScope(intent=task)
    try:
        data, _ = chat_json(model, SCOPE_SYSTEM_PROMPT, task)
    except Exception:
        return fallback
    if data is None:
        return fallback

    def str_list(key: str) -> tuple[str, ...]:
        values = data.get(key) or []
        return tuple(str(v).strip().lower() for v in values if str(v).strip())[:5]

    actions = tuple(a for a in str_list("actions") if a in ("list", "read", "write"))
    return TaskScope(
        intent=str(data.get("intent") or task),
        actions=actions or fallback.actions,
        relevant_locations=str_list("relevant_locations"),
        out_of_bounds_hints=str_list("out_of_bounds_hints"),
    )
