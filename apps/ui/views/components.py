"""
apps/ui/views/components.py — small Streamlit building blocks shared by every tab.

Everything that comes from Drive or from an LLM (file names, paths, judge
reasons, file content, the worker's answer) is untrusted. It is shown either
escaped (esc) or as plain text, never as live markdown: an injected document
must not turn into links or formatting in the UI either.
"""

import json
import re
from typing import Callable

import streamlit as st

from apps.ui.events import CallEvent, feed_items
from judging_agent.guardian import TaskScope

# A step's state sets its icon: a tick, a spinner (waiting for the human) or a red error mark.
STEP_STATES = {"executed": "complete", "pending": "running", "blocked": "error", "failed": "error"}
VERDICT_COLORS = {"allow": "green", "block": "red", "escalate": "orange"}
TIER_COLORS = {"low": "gray", "medium": "blue", "high": "red"}
LAYER_WORDS = {"rule": "fixed rule", "tier": "risk tier", "llm": "LLM judge", "stub": "stub judge",
               "error": "error (fail closed)", "human": "human"}

# Long content to approve scrolls inside its own box, so Approve and Deny stay in view.
LONG_CONTENT_CHARS = 400
LONG_CONTENT_HEIGHT = 160

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~:$])")


def esc(text) -> str:
    """Untrusted text as literal markdown: no links, no formatting, no colour directives."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(text))


_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_ACTIVE = re.compile(r"([:$<>])")


def safe_markdown(text) -> str:
    """For the worker's answer: keeps tables, lists and bold; drops links, images, HTML,
    colour directives, emoji codes, maths and auto-linked URLs (escaping ':' breaks those)."""
    return _ACTIVE.sub(r"\\\1", _LINK.sub(r"\1", str(text)))


def fit_to_window(space_above: dict[str, int]):
    """Size keyed scrolling boxes to the window instead of a fixed pixel height.

    space_above: container key -> pixels to leave for everything else on the screen.
    Uses the .st-key-<key> class Streamlit gives keyed containers (page spacing itself
    is set in .streamlit/config.toml, not here).
    """
    rules = " ".join(
        # flex-shrink: on a short window the box must scroll, not squash what is inside it.
        f".st-key-{key} {{ height: max(280px, calc(100vh - {px}px)) !important; }} "
        f".st-key-{key} > * {{ flex-shrink: 0; }}"
        for key, px in space_above.items()
    )
    st.html(f"<style>{rules}</style>")


def small_text(key: str):
    """Smaller text inside one keyed container (Streamlit has no per-container font size)."""
    box = f".st-key-{key}"
    st.html(f"<style>{box} * {{ font-size: 0.8rem !important; }} "
            f"{box} h3, {box} h3 * {{ font-size: 1.05rem !important; }}</style>")


def badge(label: str, color: str) -> str:
    """A markdown badge. Only for our own fixed labels, never for untrusted text."""
    return f":{color}-badge[{label}]"


def call_step(e: CallEvent):
    """One call as a step in Streamlit's timeline: spinner while a human decides, red when stopped."""
    tool = e.tool.removeprefix("drive_").replace("_", " ")
    badges = [badge("NOT CHECKED", "gray") if e.layer is None
              else badge(e.judged.upper(), VERDICT_COLORS.get(e.judged, "gray"))]
    if e.tier:
        badges.append(badge(e.tier.upper(), TIER_COLORS.get(e.tier, "gray")))
    if e.status == "pending":
        badges.append(badge("waiting for a human", "violet"))
    elif e.by_human:
        badges.append(badge(f"human {'approved' if e.status == 'executed' else 'denied'}", "violet"))
    label = f"**{e.index}. {esc(tool)}** {esc(e.resource or '?')} " + " ".join(badges)
    with st.status(label, type="step", state=STEP_STATES.get(e.status, "complete")):
        via = f"ID found via {esc(e.discovered_via)} · " if e.discovered_via else ""
        st.caption(f"{via}decided by {LAYER_WORDS.get(e.layer, e.layer or 'nobody')}")
        st.markdown(esc(e.reason))
        st.code(json.dumps(e.args, indent=2), language="json")
        if e.result_preview:
            st.caption("What the worker saw")
            st.code(e.result_preview, language=None, wrap_lines=True)


def timeline(events: list[CallEvent], current_taint: tuple[str, ...] = ()):
    """The calls as connected steps, with a banner where the session became tainted."""
    for item in feed_items(events, current_taint):
        if isinstance(item, CallEvent):
            call_step(item)
        else:
            taint_banner(item)


def answer_card(answer: str):
    with st.container(border=True):
        st.markdown("**Worker's answer**")
        st.markdown(safe_markdown(answer))


def _first(values, n: int) -> str:
    """The first n values; the rest as a count, so the scope stays on one line."""
    values = list(values)
    return ", ".join(values[:n]) + (f" +{len(values) - n}" if len(values) > n else "") or "–"


def scope_summary(scope: TaskScope) -> str:
    actions = " ".join(badge(a, "blue") for a in scope.actions if a.isalpha()) or "–"
    return (f"**Scope** {actions} · {esc(_first(scope.relevant_locations, 2))} "
            f"· not: {esc(_first(scope.out_of_bounds_hints, 3))}")


def scope_line(scope: TaskScope):
    """One line above the feed; the whole scope is in its tooltip."""
    st.markdown(scope_summary(scope), help=(
        f"Derived from the task before the worker starts, and fixed for the run.\n\n"
        f"Intent: {esc(scope.intent)}\n\n"
        f"Relevant: {esc(', '.join(scope.relevant_locations)) or '–'}\n\n"
        f"Out of bounds: {esc(', '.join(scope.out_of_bounds_hints)) or '–'}"
    ))


def status_line(events: list[CallEvent]):
    counts = (
        (len(events), "calls", "gray"),
        (sum(e.status == "executed" for e in events), "ran", "green"),
        (sum(e.status == "blocked" for e in events), "blocked", "red"),
        (sum(e.judged == "escalate" for e in events), "asked a human", "orange"),
    )
    st.markdown(" ".join(badge(f"{n} {label}", color) for n, label, color in counts), text_alignment="right")


def taint_banner(taint: tuple[str, ...]):
    if taint:
        st.error(f"{esc('; '.join(taint))}. Every write now needs a human.",
                 title="Session tainted", icon=":material/coronavirus:")


def pending_panel(pending: dict, on_answer: Callable[[bool], None]):
    """The question for the human: what the worker wants to do, and why the Guardian is unsure."""
    with st.container(border=True):
        st.warning("The worker is paused until you answer.", title="A human must decide",
                   icon=":material/front_hand:")
        tool = pending.get("tool", "?").removeprefix("drive_").replace("_", " ")
        args = pending.get("args") or {}
        new_file = f" · new file: {esc(args['name'])}" if args.get("name") else ""
        st.markdown(f"**{esc(tool)}** · {esc(pending.get('resource') or '?')}{new_file}")
        st.caption(f"Guardian: {esc(pending.get('reason', ''))}")
        if args.get("new_content") is not None:
            content = str(args["new_content"])
            st.caption("Content that would be written")
            st.code(content, language=None, wrap_lines=True,
                    height=LONG_CONTENT_HEIGHT if len(content) > LONG_CONTENT_CHARS else "content")
        call_id = pending.get("call_id", "")
        with st.container(horizontal=True):
            st.button("Approve", key=f"approve-{call_id}", type="primary", icon=":material/check:",
                      on_click=on_answer, args=(True,))
            st.button("Deny", key=f"deny-{call_id}", icon=":material/block:", on_click=on_answer, args=(False,))
