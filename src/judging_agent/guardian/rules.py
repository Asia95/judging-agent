"""
guardian/rules.py — fixed rules. No LLM can override them.

check_rules    runs first and only needs the call and what the session has seen
check_budget   stops a looping or hijacked worker, and keeps every write small
               enough for the judge to read in full
check_resource runs after the metadata lookup (it needs to know what the resource is)
"""

from dataclasses import dataclass

from judging_agent.drive.base import ResourceMeta
from judging_agent.guardian.decision import Decision
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import TOOLS, Action, ToolSpec, validate_args


@dataclass(frozen=True)
class Budget:
    """Per-session limits. Every attempted call counts; writes only once executed."""
    max_calls: int = 30
    max_writes: int = 3
    max_chars_written: int = 20_000
    # The judge reads a write's content in full, so no single write may be longer.
    max_chars_per_write: int = 4_000


@dataclass
class Usage:
    calls: int = 0
    writes: int = 0
    chars_written: int = 0


def check_rules(
    tool_name: str,
    args: dict,
    scope: TaskScope,
    sighting: Sighting | None,
    read_ids: set[str] | frozenset[str] = frozenset(),
) -> Decision | None:
    """Return a blocking Decision if a fixed rule is violated, else None."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        return Decision.block(f"Tool '{tool_name}' does not exist or is never allowed.")
    error = validate_args(spec, args)
    if error:
        return Decision.block(f"Invalid arguments for {tool_name}: {error}.")
    if spec.action not in scope.actions:
        return Decision.block(f"Action '{spec.action}' is not part of this task.")
    resource_id = args[spec.resource_arg]
    if sighting is None:
        return Decision.block(
            f"ID '{resource_id}' was never seen in the task or any tool result — the worker made it up."
        )
    if spec.requires_prior_read and resource_id not in read_ids:
        return Decision.block(
            f"{tool_name} on a file that wasn't read in this session; overwriting it "
            "could destroy content the worker hasn't seen."
        )
    return None


def check_budget(spec: ToolSpec, args: dict, usage: Usage, budget: Budget) -> Decision | None:
    """Return a blocking Decision if this call would exceed the session budget, else None."""
    if usage.calls >= budget.max_calls:
        return Decision.block(f"Session budget exceeded: {budget.max_calls} tool calls.")
    return check_write_budget(spec, args, usage, budget)


def check_write_budget(spec: ToolSpec, args: dict, usage: Usage, budget: Budget) -> Decision | None:
    """The write limits alone. Also checked again when a human approves a held call,
    since other writes may have run while it was waiting."""
    if spec.action != Action.WRITE:
        return None
    size = len(args.get("new_content", ""))
    if size > budget.max_chars_per_write:
        return Decision.block(
            f"Write of {size} characters is over the {budget.max_chars_per_write}-character "
            "limit the Guardian can review."
        )
    if usage.writes >= budget.max_writes:
        return Decision.block(f"Session budget exceeded: {budget.max_writes} writes.")
    if usage.chars_written + size > budget.max_chars_written:
        return Decision.block(f"Session budget exceeded: {budget.max_chars_written} characters written.")
    return None


def check_resource(spec: ToolSpec, resource: ResourceMeta, workspace_root: str | None = None) -> Decision | None:
    """Return a blocking Decision if the tool can't be used on this resource, else None.

    workspace_root: if set, only this folder and what is inside it can be touched.
    """
    if workspace_root and workspace_root != resource.id and workspace_root not in resource.ancestors:
        return Decision.block(f"'{resource.path}' is outside the agent's workspace folder.")
    if resource.is_folder != (spec.target == "folder"):
        kind = "a folder" if resource.is_folder else "a file"
        return Decision.block(f"'{resource.name}' is {kind}; wrong tool for it.")
    if spec.target_mimes and resource.mime_type not in spec.target_mimes:
        return Decision.block(f"{spec.name} can't be used on '{resource.name}' ({resource.mime_type}).")
    return None
