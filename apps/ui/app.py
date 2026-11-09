"""
apps/ui/app.py — the demo UI. From the project root:

    pip install -e ".[ui]"
    streamlit run apps/ui/app.py

Only page layout and session state live here: runner.py does the work and
views/ draw it. Streamlit re-runs this script on every click, so a click never
does work itself; its callback records an action, and the page run that
follows carries it out, with every input disabled until it is finished.

session_state:
  run        the current DemoRun (or None)
  comparison the current Guardian on vs off Comparison (or None)
  action     ("start",), ("answer", approved) or ("compare",): what this page run must do
  watch_for  the preset's note for the audience
"""

import sys
from pathlib import Path

# `streamlit run` puts only this file's folder on sys.path; the app imports apps.* and evals.*.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from apps.ui.comparison import Comparison  # noqa: E402
from apps.ui.presets import Backend, make_drive, presets_for  # noqa: E402
from apps.ui.runner import DemoRun  # noqa: E402
from apps.ui.views import compare, drive, live, replay, results  # noqa: E402
from apps.ui.views.components import fit_to_window, small_text  # noqa: E402
from judging_agent.config import settings  # noqa: E402

CUSTOM = "Custom task…"

# Layout target: a 13-inch laptop, about 650px of browser height.
CONTROLS_SPACE = 90         # px the control box leaves for the top bar and page padding
TASK_BOX_HEIGHT = 150       # px; a preset's text is 5-6 lines at the control box's width


# ── callbacks: record what to do; the next page run does it ───────────────────

def start_run(task: str, backend: Backend, watch_for: str):
    try:
        drive, workspace_root = make_drive(backend)
    except Exception as exc:          # e.g. no Google token yet
        st.session_state.setup_error = f"Could not open {backend}: {exc}"
        return
    st.session_state.run = DemoRun(task=task.strip(), drive=drive, workspace_root=workspace_root)
    st.session_state.watch_for = watch_for
    st.session_state.action = ("start",)


def answer(approved: bool):
    st.session_state.action = ("answer", approved)


def start_comparison(task: str):
    st.session_state.comparison = Comparison.build(task.strip())
    st.session_state.action = ("compare",)


def reset():
    st.session_state.run = None
    st.session_state.comparison = None
    st.session_state.watch_for = ""


# ── page ──────────────────────────────────────────────────────────────────────

def controls(locked: bool):
    """The control box on the left. Not st.sidebar: the controls must always be visible."""
    with st.container(height=500, border=True, key="controls"):
        st.subheader(":material/shield: Judging agent")

        backend = Backend(st.radio("Drive", list(Backend), disabled=locked, key="backend"))
        if backend == Backend.REAL_LIVE:
            st.warning("Writes will really change your Drive.", icon=":material/warning:")
        presets = presets_for(backend)
        if backend.real and not presets:
            st.caption("No real-Drive presets: run `python -m evals.golden_drive.setup` first.")
        labels = [p.label for p in presets] + [CUSTOM]
        label = st.selectbox("Task", labels, disabled=locked, key=f"preset:{backend}")
        preset = next((p for p in presets if p.label == label), None)
        task = st.text_area("Task text", value=preset.task if preset else "", height=TASK_BOX_HEIGHT,
                            key=f"task:{backend}:{label}", disabled=locked, label_visibility="collapsed")

        left, right = st.columns(2)
        left.button("Run", key="run_button", type="primary", width="stretch", icon=":material/play_arrow:", disabled=locked or not task.strip(),
                    on_click=start_run, args=(task, backend, preset.watch_for if preset else ""))
        right.button("Reset", key="reset_button", width="stretch", icon=":material/restart_alt:", disabled=locked, on_click=reset)

        # Everything optional goes below the buttons, so it can never push Run off the screen.
        if preset:
            st.caption(preset.watch_for)
        s = settings()
        st.caption(f"Worker: `{s.worker_model_id}`  \nGuardian: `{s.guardian_model_id}`")
    return task, backend


def main():
    st.set_page_config(page_title="Judging agent", page_icon=":material/shield:", layout="wide")
    fit_to_window(live.SPACE_ABOVE | drive.SPACE_ABOVE | compare.SPACE_ABOVE | replay.SPACE_ABOVE
                  | {"controls": CONTROLS_SPACE})
    small_text("controls")
    run: DemoRun | None = st.session_state.get("run")
    comparison: Comparison | None = st.session_state.get("comparison")
    for started in (run, comparison):
        if started:
            started.recover()           # cut off by a click mid-run → aborted
    action = st.session_state.pop("action", None)
    busy = action is not None

    left, main_area = st.columns([1, 3.2], gap="medium")
    with left:
        task, backend = controls(locked=busy)
    with main_area:
        if error := st.session_state.pop("setup_error", None):
            st.error(error)
        live_tab, drive_tab, compare_tab, replay_tab, results_tab = st.tabs(
            ["Live run", "Drive", "Guardian on vs off", "Replay", "Results"])
        # The quick tabs first, so they are on the page while a run below takes its time.
        with drive_tab:
            drive.render(run, busy)
        with replay_tab:
            replay.render(busy)
        with results_tab:
            results.render()
        comparing = busy and action[0] == "compare"
        with live_tab:
            live.render(run, None if comparing else action, on_answer=answer,
                        watch_for=st.session_state.get("watch_for", ""))
        with compare_tab:
            compare.render(comparison, action if comparing else None, on_start=start_comparison, task=task,
                           can_start=not busy and backend == Backend.FAKE and bool(task.strip()))

    if action is not None:
        # The controls were drawn locked before the action ran; draw the page again to unlock them.
        st.rerun()


main()
