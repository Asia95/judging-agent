"""apps/ui/runner.py: the demo run's state machine, with scripted models (no network)."""

import pytest
from helpers import AllowJudge, ScriptedChatModel, answer, call, scenario, wants

from apps.ui.events import touched
from apps.ui.runner import DemoRun, RunState
from evals.scenarios import fixture as fx
from judging_agent.guardian import StubJudge


def _run(model, scn=None, judge=None, tmp_path=None, **kw):
    task, scope = (scn.task, scn.scope) if scn else (fx.INVOICES_TASK, fx.INVOICES_SCOPE)
    return DemoRun(task=task, drive=kw.pop("drive", fx.build_drive()), scope=scope,
                   judge=judge or AllowJudge(), worker_model=model,
                   audit_path=tmp_path / "audit.jsonl", **kw)


def _save_run(tmp_path, **kw):
    """The worker wants to create a file in Reports; the stub judge escalates it (MEDIUM)."""
    model = ScriptedChatModel(
        wants(call("drive_create_file", {"folder_id": fx.REPORTS, "name": "summary.txt", "new_content": "total 2480"})),
        answer("saved"))
    return _run(model, scenario("7_save_summary"), StubJudge(), tmp_path, **kw)


def test_a_run_streams_events_and_finishes_with_the_answer(tmp_path):
    seen = []
    run = _run(ScriptedChatModel(wants(call("drive_list_files", {"folder_id": fx.INVOICES})), answer("3 invoices")),
               tmp_path=tmp_path, on_event=seen.append)
    run.start()
    assert run.state == RunState.DONE and run.finished and run.answer == "3 invoices"
    assert seen == run.events and run.events[0].status == "executed"


def test_a_held_call_waits_for_the_human_and_runs_when_approved(tmp_path):
    seen = []
    drive = fx.build_drive()
    run = _save_run(tmp_path, drive=drive, on_event=seen.append)
    run.start()
    assert run.state == RunState.WAITING and run.pending["tool"] == "drive_create_file"
    assert drive.writes == []

    run.answer_pending(True)
    assert run.state == RunState.DONE and run.answer == "saved" and run.pending is None
    [event] = run.events                                    # one card per call
    assert event.status == "executed" and event.by_human and event.index == 1
    assert [e.status for e in seen] == ["pending", "executed"]
    assert len(drive.writes) == 1


def test_a_denied_call_is_blocked_and_the_worker_carries_on(tmp_path):
    drive = fx.build_drive()
    run = _save_run(tmp_path, drive=drive)
    run.start()
    run.answer_pending(False)
    assert run.state == RunState.DONE and run.events[0].status == "blocked" and drive.writes == []


def test_answers_and_restarts_are_refused_in_the_wrong_state(tmp_path):
    run = _run(ScriptedChatModel(answer("nothing to do")), tmp_path=tmp_path)
    with pytest.raises(RuntimeError, match="Nothing is waiting"):
        run.answer_pending(True)
    run.start()
    with pytest.raises(RuntimeError, match="already started"):
        run.start()
    with pytest.raises(RuntimeError, match="Nothing is waiting"):
        run.answer_pending(True)                  # e.g. a double-click on Approve


def test_an_llm_error_fails_the_run_with_a_message(tmp_path):
    class Down(ScriptedChatModel):
        def invoke(self, messages):
            raise ConnectionError("watsonx unreachable")

    run = _run(Down(), tmp_path=tmp_path)
    run.start()
    assert run.state == RunState.FAILED and "watsonx unreachable" in run.error


def test_a_run_cut_off_by_a_page_rerun_is_aborted_not_resumed(tmp_path):
    """Streamlit stops a script with a BaseException (not Exception) when the user clicks mid-run."""
    class ScriptStopped(BaseException):
        pass

    def stop(event):
        raise ScriptStopped()

    run = _run(ScriptedChatModel(wants(call("drive_list_files", {"folder_id": fx.INVOICES})), answer("x")),
               tmp_path=tmp_path, on_event=stop)
    with pytest.raises(ScriptStopped):
        run.start()
    assert run.busy
    run.recover()                                   # the next page run
    assert run.state == RunState.ABORTED and run.finished and "reloaded" in run.error
    run.recover()
    assert run.state == RunState.ABORTED


def test_touched_and_taint_tell_the_injection_story(tmp_path):
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES})),
        wants(call("drive_read_file", {"file_id": fx.INV_3})),
        wants(call("drive_read_file", {"file_id": fx.SALARIES})),
        answer("total $430"))
    run = _run(model, tmp_path=tmp_path)
    assert run.taint == ()
    run.start()
    # HIGH: even a judge that allows everything can't allow it, so it goes to the human.
    assert run.state == RunState.WAITING
    assert touched(run.events)[fx.SALARIES] == "pending"
    run.answer_pending(False)
    assert touched(run.events) == {fx.INVOICES: "listed", fx.INV_3: "read", fx.SALARIES: "blocked"}
    assert run.taint and "invoice_003" in run.taint[0]
