"""
apps/ui/tree.py — the folder tree shown in the Drive tab (no Streamlit).

The UI reads this for the person watching the demo. It is never shown to the
worker, so it doesn't go through the Guardian.
"""

from dataclasses import dataclass

from judging_agent.drive.base import FOLDER_MIME, DriveBackend

MAX_ROWS = 200
MAX_DEPTH = 8


@dataclass(frozen=True)
class TreeRow:
    id: str
    parent: str
    name: str
    depth: int
    is_folder: bool


def walk(drive: DriveBackend, root_id: str) -> list[TreeRow]:
    """Everything under root_id, folders first, cut off at MAX_ROWS."""
    rows: list[TreeRow] = []

    def visit(folder_id: str, depth: int):
        children = drive.list_folder(folder_id, MAX_ROWS)
        for item in sorted(children, key=lambda c: (c["mimeType"] != FOLDER_MIME, c["name"].lower())):
            if len(rows) >= MAX_ROWS:
                return
            is_folder = item["mimeType"] == FOLDER_MIME
            rows.append(TreeRow(item["id"], folder_id, item["name"], depth, is_folder))
            if is_folder and depth < MAX_DEPTH:
                visit(item["id"], depth + 1)

    visit(root_id, 0)
    return rows
