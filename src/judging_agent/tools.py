"""
tools.py — the tool registry.

Each tool is defined exactly once as a ToolSpec. The JSON schemas sent to the
worker model and the action/resource info used by the Guardian both come from
TOOLS, so a tool that is not registered here cannot be called at all.

Every tool acts on exactly one Drive resource, named by its `resource_arg`.
A tool with no resource (search) or several (move) would need the Guardian's
sighting and metadata checks to handle a list of resources first.

Writes only touch text: drive_update_file is limited to Google Docs and plain
text files (overwriting a PDF or XLSX with text would destroy it), and
drive_create_file always creates a plain text file.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Literal

from judging_agent.drive.base import EDITABLE_MIMES, DriveBackend


class Action(StrEnum):
    LIST = "list"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    action: Action
    resource_arg: str           # the argument that names the Drive resource
    params: dict                # JSON-schema properties
    required: tuple[str, ...]
    run: Callable[[DriveBackend, dict], dict]
    target: Literal["file", "folder"] = "file"      # what resource_arg must point to
    target_mimes: frozenset[str] = frozenset()      # if set, the file must have one of these types
    requires_prior_read: bool = False   # the file must have been read earlier in the session
    needs_confirmation: bool = False    # a human confirms every call the Guardian allows

    def schema(self) -> dict:
        """OpenAI-style tool schema passed to the worker model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": list(self.required),
                },
            },
        }


_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_args(spec: ToolSpec, args: dict) -> str | None:
    """Return an error message if args don't match the spec's schema, else None."""
    missing = [a for a in spec.required if a not in args]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    unknown = [a for a in args if a not in spec.params]
    if unknown:
        return f"unknown argument(s): {', '.join(unknown)}"
    for name, value in args.items():
        schema = spec.params[name]
        expected = _JSON_TYPES.get(schema.get("type"))
        if expected is None:
            return f"argument '{name}' has an unsupported schema type '{schema.get('type')}'"
        # bool is a subclass of int in Python; only "boolean" accepts it.
        if not isinstance(value, expected) or (isinstance(value, bool) and schema["type"] != "boolean"):
            return f"argument '{name}' must be of type {schema['type']}"
        if "minimum" in schema and value < schema["minimum"]:
            return f"argument '{name}' must be at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"argument '{name}' must be at most {schema['maximum']}"
    return None


# A read returns at most this much text to the worker: protects its context (and
# cost) from huge files. IDs past the cut are invisible to the worker and the
# Guardian alike, so provenance stays consistent with what the worker saw.
MAX_READ_CHARS = 50_000


def _read(drive: DriveBackend, args: dict) -> dict:
    result = drive.read_file(args["file_id"])
    content = result.get("content", "")
    if len(content) > MAX_READ_CHARS:
        result = {**result, "truncated": True, "content": content[:MAX_READ_CHARS]
                  + f"\n[truncated: showing {MAX_READ_CHARS:,} of {len(content):,} characters]"}
    return result


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="drive_list_files",
            description="List files inside a specific Google Drive folder.",
            action=Action.LIST,
            resource_arg="folder_id",
            params={
                "folder_id": {"type": "string", "description": "The Google Drive folder ID to list."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000,
                                "description": "Max files to return (default 50, at most 1000)."},
            },
            required=("folder_id",),
            run=lambda d, a: {"files": d.list_folder(a["folder_id"], a.get("max_results", 50))},
            target="folder",
        ),
        ToolSpec(
            name="drive_read_file",
            description="Download and read the text content of a Google Drive file.",
            action=Action.READ,
            resource_arg="file_id",
            params={"file_id": {"type": "string", "description": "The Google Drive file ID to read."}},
            required=("file_id",),
            run=_read,
        ),
        ToolSpec(
            name="drive_update_file",
            description=(
                "Overwrite a Google Doc or plain-text file with new content. "
                "Read the file first: overwriting a file you haven't read is refused. "
                "PDF, Word and Excel files cannot be updated."
            ),
            action=Action.WRITE,
            resource_arg="file_id",
            params={
                "file_id": {"type": "string", "description": "The file ID to update."},
                "new_content": {"type": "string", "description": "The full new text content to write."},
            },
            required=("file_id", "new_content"),
            run=lambda d, a: d.update_file(a["file_id"], a["new_content"]),
            target_mimes=EDITABLE_MIMES,
            requires_prior_read=True,       # never overwrite content the worker hasn't seen
            needs_confirmation=True,        # an overwrite can't be undone
        ),
        ToolSpec(
            name="drive_create_file",
            description="Create a new plain-text file in a Google Drive folder.",
            action=Action.WRITE,
            resource_arg="folder_id",
            params={
                "folder_id": {"type": "string", "description": "The folder ID to create the file in."},
                "name": {"type": "string", "description": "The new file's name, e.g. 'summary.txt'."},
                "new_content": {"type": "string", "description": "The text content of the new file."},
            },
            required=("folder_id", "name", "new_content"),
            run=lambda d, a: d.create_file(a["folder_id"], a["name"], a["new_content"]),
            target="folder",
        ),
    ]
}

TOOL_SCHEMAS: list[dict] = [spec.schema() for spec in TOOLS.values()]


def tool_schemas(actions) -> list[dict]:
    """Schemas for only the tools whose action is allowed (least privilege for the worker)."""
    return [spec.schema() for spec in TOOLS.values() if spec.action in actions]
