"""The Streamlit app, driven headless with streamlit's AppTest and scripted models (no network)."""

import pytest

pytest.importorskip("streamlit")

from helpers import AllowJudge, ScriptedChatModel, answer, call, scenario, wants  # noqa: E402
from pathlib import Path  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

from apps.ui.runner import DemoRun, RunState  # noqa: E402
from evals.scenarios import fixture as fx  # noqa: E402
from judging_agent.guardian import StubJudge  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "apps" / "ui" / "app.py")


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30)


def _queue(at: AppTest, run: DemoRun):
    """What the Run button's callback does, with scripted models instead of watsonx."""
    at.session_state["run"] = run
    at.session_state["action"] = ("start",)


def _markdown(at):
    return "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [s.label for s in at.status])


def test_the_app_loads_with_presets_and_nothing_running():
    at = _app().run()
    assert not at.exception
    assert "Summarise invoices (injection)" in at.selectbox[0].options
    assert not at.sidebar.children          # the controls are on the page, not in a sidebar that can hide
    assert any("press **Run**" in i.value for i in at.info)


def test_a_held_write_is_shown_and_approved_from_the_page(tmp_path):
    drive = fx.build_drive()
    scn = scenario("7_save_summary")
    model = ScriptedChatModel(
        wants(call("drive_create_file", {"folder_id": fx.REPORTS, "name": "summary.txt", "new_content": "total 2480"})),
        answer("saved"))
    at = _app()
    _queue(at, DemoRun(task=scn.task, drive=drive, scope=scn.scope, judge=StubJudge(), worker_model=model,
                       audit_path=tmp_path / "audit.jsonl"))
    at.run()
    assert not at.exception
    run = at.session_state["run"]
    assert run.state == RunState.WAITING and drive.writes == []
    assert "total 2480" in "\n".join(c.value for c in at.code)      # the human sees the content
    assert {"Approve", "Deny"} <= {b.label for b in at.button}

    next(b for b in at.button if b.label == "Approve").click().run()
    assert not at.exception
    assert at.session_state["run"].state == RunState.DONE and len(drive.writes) == 1
    assert "saved" in _markdown(at)
    assert "Approve" not in [b.label for b in at.button]
    assert not _controls_locked(at)


def _controls_locked(at) -> bool:
    return at.button(key="run_button").disabled and at.radio(key="backend").disabled


def test_the_controls_are_unlocked_once_a_run_finishes_or_waits(tmp_path):
    """Regression: the controls were drawn locked for the page run that did the work, and stayed locked."""
    scn = scenario("7_save_summary")
    model = ScriptedChatModel(
        wants(call("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})),
        answer("done"))
    at = _app()
    _queue(at, DemoRun(task=scn.task, drive=fx.build_drive(), scope=scn.scope, judge=StubJudge(),
                       worker_model=model, audit_path=tmp_path / "audit.jsonl"))
    at.run()
    assert at.session_state["run"].state == RunState.WAITING and not _controls_locked(at)
    next(b for b in at.button if b.label == "Deny").click().run()
    assert at.session_state["run"].state == RunState.DONE and not _controls_locked(at)


def test_an_injected_file_name_is_shown_as_text_not_markdown(tmp_path):
    drive = fx.build_drive()
    drive.nodes[fx.INV_1].name = "[click me](https://evil.example) **now**.txt"
    model = ScriptedChatModel(wants(call("drive_list_files", {"folder_id": fx.INVOICES})),
                              wants(call("drive_read_file", {"file_id": fx.INV_1})), answer("ok"))
    at = _app()
    _queue(at, DemoRun(task=fx.INVOICES_TASK, drive=drive, scope=fx.INVOICES_SCOPE, judge=StubJudge(),
                       worker_model=model, audit_path=tmp_path / "audit.jsonl"))
    at.run()
    assert not at.exception
    page = _markdown(at)
    assert r"\[click me\]\(https\:" in page            # the name is on the page, escaped
    assert "](https://evil" not in page and "**now**" not in page


def test_the_answer_keeps_tables_but_loses_links_and_html():
    from apps.ui.views.components import safe_markdown

    out = safe_markdown("| a | b |\n|---|---|\n| **1** | [x](https://evil.example) ![i](http://t/p.png) <b>hi</b> :red[!] $x$ |")
    assert "| **1** |" in out
    assert "](" not in out                                   # links and images become their text
    assert r"\<b\>" in out and r"\:red[" in out and r"\$x\$" in out   # inert, shown literally


def _flat(node):
    found = []
    for child in getattr(node, "children", {}).values():
        found += [child, *_flat(child)]
    return found


def test_the_feed_tells_the_story_in_order(tmp_path):
    """Layout A: the banner follows the call that caused it, the question its call, the answer comes last."""
    scn = scenario("7_save_summary")
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES})),
        wants(call("drive_read_file", {"file_id": fx.INV_3})),
        wants(call("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})),
        answer("the end"))
    at = _app()
    _queue(at, DemoRun(task=scn.task, drive=fx.build_drive(), scope=scn.scope, judge=AllowJudge(),
                       worker_model=model, audit_path=tmp_path / "audit.jsonl"))
    at.run()

    def story():
        names = []
        for e in _flat(at.tabs[0]):
            kind = type(e).__name__
            if kind in ("Status", "Error"):
                names.append(kind)
            elif kind == "Button" and e.label == "Approve":
                names.append("Approve")
            elif kind == "Markdown" and e.value == "**Worker's answer**":
                names.append("Answer")
        return names

    assert story() == ["Status", "Status", "Error", "Status", "Approve"]
    next(b for b in at.button if b.label == "Approve").click().run()
    assert story() == ["Status", "Status", "Error", "Status", "Answer"]


def test_the_scope_stays_on_one_line_with_the_rest_counted():
    from apps.ui.views.components import scope_summary
    from judging_agent.guardian import TaskScope

    line = scope_summary(TaskScope(intent="x", actions=("list", "read"), relevant_locations=("invoices",),
                                   out_of_bounds_hints=("payroll", "hr", "salaries", "personal", "legal")))
    assert "invoices" in line and r"not: payroll, hr, salaries \+2" in line
