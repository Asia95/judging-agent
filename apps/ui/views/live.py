"""
apps/ui/views/live.py — the Live run tab: one story, top to bottom.

One line above the feed (the scope and the counts), then a single feed in the
order things happened: the task, one step per call, a banner where the session
became tainted, the human's question right under the call it is about, and the
worker's answer at the end. The feed scrolls inside and follows the newest item,
so the page itself never scrolls.

If the page run carries an action (start, or a human's answer), it is carried
out here, after the existing steps are drawn, so new steps appear live below them.
"""

from typing import Callable

import streamlit as st

from apps.ui.events import CallEvent
from apps.ui.runner import DemoRun, RunState
from apps.ui.views.components import answer_card, esc, pending_panel, scope_line, status_line, timeline

# The feed is sized to the window: its height minus this many pixels for the
# top bar, the tab label, the line above the feed and the page padding.
# (height= below is the fallback until that style applies.)
SPACE_ABOVE = {"calls": 215}


def render(run: DemoRun | None, action: tuple | None, on_answer: Callable[[bool], None], watch_for: str = ""):
    if run is None:
        st.info("Pick a task on the left and press **Run**.", icon=":material/arrow_back:")
        return

    scope_col, status_col = st.columns([3, 2], vertical_alignment="center")
    scope_slot = scope_col.empty()
    status_slot = status_col.empty()

    feed = st.container(height=500, autoscroll=True, border=True, key="calls")
    note = f"  \n👀 *{esc(watch_for)}*" if watch_for else ""
    feed.markdown(f"**Task:** {esc(run.task)}{note}")
    # One slot for the whole timeline, redrawn on each event: steps must be direct
    # siblings to share the connector line (a slot per step would break it).
    steps = feed.empty()
    outcome = feed.container()

    def draw_scope(scope):
        with scope_slot.container():
            scope_line(scope)

    def draw_feed(event: CallEvent | None = None):
        with steps.container():
            timeline(run.events, run.taint)
        with status_slot.container():
            status_line(run.events)

    if run.scope:
        draw_scope(run.scope)
    draw_feed()

    if action:
        run.on_scope, run.on_event = draw_scope, draw_feed
        with outcome, st.spinner("The worker is running. Every tool call goes through the Guardian…"):
            if action[0] == "start":
                run.start()
            else:
                run.answer_pending(action[1])
        draw_feed()

    with outcome:
        if run.state == RunState.WAITING:
            pending_panel(run.pending, on_answer)
        elif run.state == RunState.DONE:
            answer_card(run.answer)
            if not run.events:
                st.caption("The worker answered without calling any tool.")
        elif run.state in (RunState.FAILED, RunState.ABORTED):
            st.error(esc(run.error))
