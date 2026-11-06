"""
guardian/rules.py — fixed rules. No LLM can override them.

check_rules runs before the metadata lookup (it only needs the call itself);
check_resource runs after it (it needs to know what the resource is).
"""

from judging_agent.guardian.decision import Decision
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import TOOLS, ToolSpec, validate_args


def check_rules(
    tool_name: str,
    args: dict,
    scope: TaskScope,
    sighting: Sighting | None,
) -> Decision | None:
    """Return a blocking Decision if a fixed rule is violated, else None."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        return Decision("block", f"Tool '{tool_name}' does not exist or is never allowed.", "rule")
    error = validate_args(spec, args)
    if error:
        return Decision("block", f"Invalid arguments for {tool_name}: {error}.", "rule")
    if spec.action not in scope.actions:
        return Decision("block", f"Action '{spec.action}' is not part of this task.", "rule")
    if sighting is None:
        return Decision(
            "block",
            f"ID '{args[spec.resource_arg]}' was never seen in the task or any tool "
            "result — the worker made it up.",
            "rule",
        )
    return None


def check_resource(spec: ToolSpec, metadata: dict) -> Decision | None:
    """Return a blocking Decision if the tool can't be used on this resource, else None."""
    if metadata["is_folder"] != (spec.target == "folder"):
        kind = "a folder" if metadata["is_folder"] else "a file"
        return Decision("block", f"'{metadata['name']}' is {kind}; wrong tool for it.", "rule")
    if spec.target_mimes and metadata["mimeType"] not in spec.target_mimes:
        return Decision(
            "block", f"{spec.name} can't be used on '{metadata['name']}' ({metadata['mimeType']}).", "rule",
        )
    return None
