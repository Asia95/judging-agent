"""apps/ui/views/replay.py — the Replay tab: an earlier run from its audit log, with no LLM calls."""

from pathlib import Path

import streamlit as st

from apps.ui.events import AuditRun, from_audit, load_runs
from apps.ui.views.components import esc, scope_line, status_line, timeline
from judging_agent.config import RUNS_DIR
from judging_agent.guardian import TaskScope

SPACE_ABOVE = {"replay": 310}


@st.cache_data(max_entries=32, show_spinner=False)
def _runs(path: str, modified: float) -> list[AuditRun]:
    """`modified` is part of the cache key, so a log that grew is read again."""
    return load_runs(Path(path))


def _scope(saved: dict) -> TaskScope | None:
    try:
        return TaskScope(intent=saved["intent"], actions=tuple(saved["actions"]),
                         relevant_locations=tuple(saved["relevant_locations"]),
                         out_of_bounds_hints=tuple(saved["out_of_bounds_hints"]), source=saved.get("source", ""))
    except (KeyError, TypeError):       # a log from before scopes were recorded
        return None


def render(locked: bool):
    files = sorted(RUNS_DIR.glob("audit*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    logs = {f.name: runs for f in files if (runs := _runs(str(f), f.stat().st_mtime))}
    if not logs:
        st.info("No runs to replay yet. Each run is saved in the runs/ folder.", icon=":material/history:")
        return

    file_col, run_col = st.columns([1, 3])
    name = file_col.selectbox("Audit log", list(logs), disabled=locked, key="replay_file")
    runs = logs[name]
    index = run_col.selectbox("Run", range(len(runs)), format_func=lambda i: runs[i].label, disabled=locked,
                              key=f"replay_run:{name}")
    run = runs[index]
    events = from_audit(run.records)

    scope_col, status_col = st.columns([3, 2], vertical_alignment="center")
    if scope := _scope(run.scope):
        with scope_col:
            scope_line(scope)
    with status_col:
        status_line(events)
    with st.container(height=400, border=True, key="replay"):
        st.markdown(f"**Task:** {esc(run.task)}")
        timeline(events)
