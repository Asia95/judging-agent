"""apps/ui/views/compare.py — the Guardian on vs off tab: one task, two runs, side by side."""

from typing import Callable

import streamlit as st

from apps.ui.comparison import Comparison, verdict
from apps.ui.runner import DemoRun, RunState
from apps.ui.views.components import answer_card, badge, esc, timeline

SPACE_ABOVE = {"feed_off": 275, "feed_on": 275}


def _heading(title: str, run: DemoRun) -> str:
    if not run.finished:
        return f"**{title}**"
    result = verdict(run)
    return f"**{title}** " + badge("LEAK" if result.leaked else "SAFE", "red" if result.leaked else "green") \
        + f" {esc(result.text)}"


def render(comparison: Comparison | None, action: tuple | None, on_start: Callable[[str], None], task: str,
           can_start: bool):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("Run both", key="compare_button", type="primary", icon=":material/compare_arrows:",
                  disabled=not can_start, on_click=on_start, args=(task,))
        st.caption("Runs the task on the left twice, on fresh fake Drives. "
                   "A simulated human answers escalations and denies HR and Payroll.")
    if comparison is None:
        return

    sides = []
    for column, title, run, key in zip(st.columns(2, gap="medium"), ("Guardian off", "Guardian on"),
                                       (comparison.off, comparison.on), ("feed_off", "feed_on")):
        heading = column.empty()
        feed = column.container(height=400, autoscroll=True, border=True, key=key)
        slot = feed.empty()
        sides.append((title, run, heading, slot, feed.container()))

    def draw(side, event=None):
        title, run, heading, slot, _ = side
        heading.markdown(_heading(title, run))
        with slot.container():
            timeline(run.events, run.taint)

    for side in sides:
        draw(side)
    if action:
        for side, go in zip(sides, (comparison.run_off, comparison.run_on)):
            side[1].on_event = lambda event, side=side: draw(side, event)
            with side[4], st.spinner("Running…"):
                go()
            draw(side)

    for title, run, heading, slot, end in sides:
        with end:
            if run.state == RunState.DONE:
                answer_card(run.answer)
            elif run.state in (RunState.FAILED, RunState.ABORTED):
                st.error(esc(run.error))
