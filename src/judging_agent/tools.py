"""
tools.py — the tool registry.

Each tool is defined exactly once as a ToolSpec. The JSON schemas sent to the
worker model and the action/resource info used by the Guardian both come from
TOOLS, so a tool that is not registered here cannot be called at all.

Writes only touch text: drive_update_file is limited to Google Docs and plain
text files (overwriting a PDF or XLSX with text would destroy it), and
drive_create_file always creates a plain text file.
"""

from dataclasses import dataclass
from typing import Callable

from judging_agent.drive.base import EDITABLE_MIMES, DriveBackend


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    action: str                 # "list" | "read" | "write"
    resource_arg: str           # the argument that names the Drive resource
    params: dict                # JSON-schema properties
    required: tuple[str, ...]
    run: Callable[[DriveBackend, dict], dict]
    target: str = "file"        # "file" | "folder": what resource_arg must point to
    target_mimes: frozenset[str] = frozenset()  # if set, the file must have one of these types

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


_JSON_TYPES = {"string": str, "integer": int}


def validate_args(spec: ToolSpec, args: dict) -> str | None:
    """Return an error message if args don't match the spec's schema, else None."""
    missing = [a for a in spec.required if a not in args]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    unknown = [a for a in args if a not in spec.params]
    if unknown:
        return f"unknown argument(s): {', '.join(unknown)}"
    for name, value in args.items():
        expected = _JSON_TYPES[spec.params[name]["type"]]
        if not isinstance(value, expected) or isinstance(value, bool):
            return f"argument '{name}' must be of type {spec.params[name]['type']}"
    return None


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="drive_list_files",
            description="List files inside a specific Google Drive folder.",
            action="list",
            resource_arg="folder_id",
            params={
                "folder_id": {"type": "string", "description": "The Google Drive folder ID to list."},
                "max_results": {"type": "integer", "description": "Max files to return (default 50)."},
            },
            required=("folder_id",),
            run=lambda d, a: {"files": d.list_folder(a["folder_id"], a.get("max_results", 50))},
            target="folder",
        ),
        ToolSpec(
            name="drive_read_file",
            description="Download and read the text content of a Google Drive file.",
            action="read",
            resource_arg="file_id",
            params={"file_id": {"type": "string", "description": "The Google Drive file ID to read."}},
            required=("file_id",),
            run=lambda d, a: d.read_file(a["file_id"]),
        ),
        ToolSpec(
            name="drive_update_file",
            description=(
                "Overwrite a Google Doc or plain-text file with new content. "
                "PDF, Word and Excel files cannot be updated."
            ),
            action="write",
            resource_arg="file_id",
            params={
                "file_id": {"type": "string", "description": "The file ID to update."},
                "new_content": {"type": "string", "description": "The full new text content to write."},
            },
            required=("file_id", "new_content"),
            run=lambda d, a: d.update_file(a["file_id"], a["new_content"]),
            target_mimes=EDITABLE_MIMES,
        ),
        ToolSpec(
            name="drive_create_file",
            description="Create a new plain-text file in a Google Drive folder.",
            action="write",
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
