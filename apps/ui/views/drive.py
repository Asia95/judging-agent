"""apps/ui/views/drive.py — the Drive tab: the folder tree, marked with what the run did."""

import streamlit as st

from apps.ui.events import touched
from apps.ui.presets import known_injections
from apps.ui.runner import DemoRun
from apps.ui.tree import TreeRow
from apps.ui.views.components import badge, esc

SPACE_ABOVE = {"tree": 150}
MARK_COLORS = {"listed": "gray", "read": "green", "written": "blue", "blocked": "red", "pending": "orange",
               "failed": "red"}


def row_line(row: TreeRow, marks: dict, injected: set[str]) -> str:
    """One markdown list item. The file name is untrusted; the badges are our own labels."""
    icon = ":material/folder:" if row.is_folder else ":material/description:"
    mark = marks.get(row.id) or marks.get((row.parent, row.name))
    badges = [badge(mark, MARK_COLORS.get(mark, "gray"))] if mark else []
    if row.id in injected:
        badges.append(badge("prompt injection", "violet"))
    return "    " * row.depth + f"- {icon} {esc(row.name)} " + " ".join(badges)


def render(run: DemoRun | None, busy: bool):
    if run is None:
        st.info("Start a run to see its Drive here.", icon=":material/folder_open:")
        return
    if busy:
        st.caption("The tree appears when the run stops or waits for a human.")
        return
    if run.workspace_root is None:
        st.info("Set WORKSPACE_FOLDER_ID in .env to see the real Drive's tree.", icon=":material/folder_open:")
        return
    try:
        rows = run.tree()
    except Exception as exc:        # e.g. the Google token expired
        st.error(f"Could not read the folder tree: {esc(exc)}")
        return
    marks = touched(run.events)
    with st.container(height=400, border=True, key="tree"):
        st.markdown("\n".join(row_line(r, marks, known_injections()) for r in rows) or "The folder is empty.")
