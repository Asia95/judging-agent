"""The LangGraph worker, driven by a scripted fake chat model (no network)."""

import json

from helpers import ScriptedChatModel, SpyDrive, answer, call, scenario, wants
from langchain_core.messages import AIMessage

from evals.scenarios import fixture as fx
from judging_agent.guardian import PENDING, StubJudge
from judging_agent.guardian.provenance import Sighting
from judging_agent.worker import GraphWorker


def tool_results(model):
    return [json.loads(m.content) for m in model.seen[-1] if m.type == "tool"]


# ── Basics ────────────────────────────────────────────────────────────────────

def test_tool_calls_go_through_the_gateway_and_the_answer_comes_back(gateway_for):
    gw = gateway_for()
    model = ScriptedChatModel(wants(call("drive_list_files", {"folder_id": fx.INVOICES})), answer("3 invoices"))
    assert GraphWorker(gw, model=model).run(fx.INVOICES_TASK) == "3 invoices"
    assert [o.tool for o in gw.outcomes] == ["drive_list_files"]
    assert len(tool_results(model)[0]["files"]) == 3


def test_a_read_only_task_is_only_offered_read_tools(gateway_for):
    model = ScriptedChatModel(answer("done"))
    GraphWorker(gateway_for(), model=model).run(fx.INVOICES_TASK)
    assert model.offered == ["drive_list_files", "drive_read_file"]


def test_the_only_way_to_drive_is_through_the_gateway(gateway_for):
    """Every Drive access matches a call the gateway executed; blocked calls touch nothing."""
    drive = SpyDrive()
    gw = gateway_for(backend=drive)
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES}, "c1")),
        wants(call("drive_read_file", {"file_id": fx.INV_3}, "c2")),
        wants(call("drive_read_file", {"file_id": fx.SALARIES}, "c3"),          # injected link
              call("drive_delete_file", {"file_id": fx.INV_1}, "c4"),            # tool that doesn't exist
              call("drive_update_file", {"file_id": fx.INV_1, "new_content": "x"}, "c5")),  # not in scope
        answer("done"),
    )
    GraphWorker(gw, model=model).run(fx.INVOICES_TASK)
    executed = [(o.tool, o.resource) for o in gw.outcomes if o.status == "executed"]
    assert len(drive.touched) == len(executed) == 2
    assert all(rid != fx.SALARIES for _, rid in drive.touched)
    assert [o.status for o in gw.outcomes] == ["executed", "executed", "blocked", "blocked", "blocked"]


def test_invalid_tool_arguments_are_blocked_and_audited(gateway_for):
    gw = gateway_for()
    bad = AIMessage(content="", invalid_tool_calls=[
        {"name": "drive_read_file", "args": "{not json", "id": "c1", "error": None, "type": "invalid_tool_call"}])
    model = ScriptedChatModel(bad, answer("gave up"))
    GraphWorker(gw, model=model).run(fx.INVOICES_TASK)
    assert gw.outcomes[0].status == "blocked" and "valid JSON" in gw.outcomes[0].decision.reason
    assert tool_results(model)[0]["error"] == "blocked by guardian"


def test_the_run_stops_after_max_turns(gateway_for):
    loop = [wants(call("drive_list_files", {"folder_id": fx.INVOICES}, f"c{i}")) for i in range(10)]
    worker = GraphWorker(gateway_for(), model=ScriptedChatModel(*loop), max_turns=3)
    assert worker.run(fx.INVOICES_TASK) == "(stopped after 3 turns)"


# ── Human approval through interrupt() ────────────────────────────────────────

def _overwrite_setup(gateway_for, *extra_replies):
    drive = fx.build_drive()
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), backend=drive,
                     escalate=lambda ctx, reason: PENDING)
    update = call("drive_update_file", {"file_id": fx.INV_1, "new_content": "Status: PAID"}, "c3")
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES}, "c1")),
        wants(call("drive_read_file", {"file_id": fx.INV_1}, "c2")),
        wants(update), *extra_replies)
    return drive, gw, GraphWorker(gw, model=model)


def test_an_overwrite_pauses_the_graph_until_a_human_answers(gateway_for):
    drive, gw, worker = _overwrite_setup(gateway_for, answer("marked as paid"))
    step = worker.start("mark invoice_001 as paid")
    assert not step.done and step.pending["tool"] == "drive_update_file"
    assert drive.writes == []
    step = worker.resume(approved=True)
    assert step.answer == "marked as paid"
    assert drive.writes == [(fx.INV_1, "Status: PAID")]
    assert [o.status for o in gw.outcomes] == ["executed", "executed", "pending", "executed"]


def test_a_denied_overwrite_never_runs(gateway_for):
    drive, gw, worker = _overwrite_setup(gateway_for, answer("ok, not changed"))
    assert worker.run("mark invoice_001 as paid", approve=lambda pending: False) == "ok, not changed"
    assert drive.writes == []
    assert gw.outcomes[-1].status == "blocked"


def test_calls_before_a_paused_one_are_not_run_twice_on_resume(gateway_for):
    """LangGraph re-runs the paused node from the top; finished calls must be reused, not repeated."""
    drive = SpyDrive()
    gw = gateway_for(judge=StubJudge(), backend=drive, escalate=lambda ctx, reason: PENDING)
    gw.session.provenance.add(fx.REPORTS, Sighting("listing", fx.FINANCE))     # MEDIUM: stub escalates
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES}, "c1"),
              call("drive_list_files", {"folder_id": fx.REPORTS}, "c2")),
        answer("done"))
    worker = GraphWorker(gw, model=model)
    assert not worker.start(fx.INVOICES_TASK).done
    assert worker.resume(approved=True).answer == "done"
    assert drive.touched == [("list_folder", fx.INVOICES), ("list_folder", fx.REPORTS)]


# ── Regression tests (code review 2) ──────────────────────────────────────────

def test_two_approvals_in_one_turn_each_get_their_own_answer(gateway_for):
    """B1: approving the first and denying the second used to write both."""
    drive = fx.build_drive()
    gw = gateway_for(scenario("7_save_summary"), judge=StubJudge(), backend=drive,
                     escalate=lambda ctx, reason: PENDING)          # stub escalates MEDIUM writes
    model = ScriptedChatModel(
        wants(call("drive_create_file", {"folder_id": fx.REPORTS, "name": "a.txt", "new_content": "A"}, "c1"),
              call("drive_create_file", {"folder_id": fx.REPORTS, "name": "b.txt", "new_content": "B"}, "c2")),
        answer("done"))
    GraphWorker(gw, model=model).run("save two files", approve=lambda pending: pending["args"]["name"] == "a.txt")
    assert sorted(drive.nodes[file_id].name for file_id, _ in drive.writes) == ["a.txt"]
    assert [o.status for o in gw.outcomes] == ["pending", "executed", "pending", "blocked"]


def test_a_model_that_reuses_tool_call_ids_still_gets_every_call_run(gateway_for):
    """B2: the second turn's call used to get the first turn's cached result."""
    gw = gateway_for()
    model = ScriptedChatModel(
        wants(call("drive_list_files", {"folder_id": fx.INVOICES}, "call_0")),
        wants(call("drive_read_file", {"file_id": fx.INV_1}, "call_0")),
        answer("done"))
    GraphWorker(gw, model=model).run(fx.INVOICES_TASK)
    assert [o.tool for o in gw.outcomes] == ["drive_list_files", "drive_read_file"]
    assert "Acme" in tool_results(model)[-1]["content"]


def test_an_answer_made_of_content_blocks_is_returned_as_text(gateway_for):
    """B6"""
    model = ScriptedChatModel(AIMessage(content=[{"type": "text", "text": "3 invoices"}]))
    assert GraphWorker(gateway_for(), model=model).run(fx.INVOICES_TASK) == "3 invoices"


def test_a_worker_runs_one_task(gateway_for):
    """B8: a second start() used to continue the first task's conversation."""
    import pytest

    worker = GraphWorker(gateway_for(), model=ScriptedChatModel(answer("one"), answer("two")))
    worker.start("task one")
    with pytest.raises(RuntimeError, match="one task"):
        worker.start("task two")
