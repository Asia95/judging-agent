"""ToolGateway: the human step, execution, recording, audit and events."""

import json
from types import SimpleNamespace

from helpers import SpyDrive, scenario

from evals.scenarios import fixture as fx
from judging_agent.drive import DryRunDrive
from judging_agent.guardian import PENDING, StubJudge, TaskScope
from judging_agent.guardian.rules import Budget
from judging_agent.tools import Action


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ── Audit (B10, B11, C9) ──────────────────────────────────────────────────────

def test_every_decision_is_audited_with_scope_and_judge(gateway_for, tmp_path):
    gw = gateway_for()
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_delete_file", {"file_id": fx.INV_1})
    records = _records(tmp_path / "audit.jsonl")
    assert [r["tool"] for r in records] == ["drive_list_files", "drive_delete_file"]
    assert [r["status"] for r in records] == ["approved", "blocked"]
    assert records[0]["judge"] == "allow-all"
    assert records[0]["scope"]["intent"] == fx.INVOICES_SCOPE.intent
    assert records[0]["call_id"] != records[1]["call_id"]


def test_no_audit_record_means_no_action(gateway_for, tmp_path):
    """B10: the tool used to run first and be audited afterwards."""
    drive = fx.build_drive()
    gw = gateway_for(scenario("7_save_summary"), backend=drive, audit_path=tmp_path / "not-a-dir" / "x")
    (tmp_path / "not-a-dir").write_text("a file where the audit folder should be")
    outcome = gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    assert outcome.status == "blocked" and "Audit log could not be written" in outcome.decision.reason
    assert drive.writes == []


def test_a_failing_tool_is_recorded(gateway_for, tmp_path):
    gw = gateway_for(backend=SpyDrive(fail={"list_folder"}))
    outcome = gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    assert outcome.status == "failed" and "network down" in outcome.result["error"]
    assert [r["status"] for r in _records(tmp_path / "audit.jsonl")] == ["approved", "failed"]


# ── Pending approvals (A8) ────────────────────────────────────────────────────

def test_a_pending_call_runs_only_after_a_human_approves(gateway_for, tmp_path):
    drive = fx.build_drive()
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), backend=drive,
                     escalate=lambda ctx, reason: PENDING)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_1})
    held = gw.execute("drive_update_file", {"file_id": fx.INV_1, "new_content": "Status: PAID"})
    assert held.status == "pending" and drive.writes == []
    assert list(gw.pending) == [held.call_id]

    done = gw.resolve(held.call_id, approved=True)
    assert done.status == "executed" and done.judged == "escalate"
    assert drive.writes == [(fx.INV_1, "Status: PAID")]
    assert gw.pending == {}
    assert [r["status"] for r in _records(tmp_path / "audit.jsonl")][-2:] == ["pending", "approved"]


def test_a_pending_call_can_be_denied(gateway_for):
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), escalate=lambda ctx, reason: PENDING)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_1})
    held = gw.execute("drive_update_file", {"file_id": fx.INV_1, "new_content": "x"})
    assert gw.resolve(held.call_id, approved=False).status == "blocked"


# ── Events (A6) ───────────────────────────────────────────────────────────────

def test_listeners_see_every_outcome_and_a_broken_one_changes_nothing(gateway_for):
    seen = []

    def broken(outcome, ctx):
        raise RuntimeError("UI crashed")

    gw = gateway_for(listeners=[lambda outcome, ctx: seen.append((outcome.status, ctx is not None)), broken])
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_delete_file", {"file_id": fx.INV_1})
    assert seen == [("executed", True), ("blocked", False)]


# ── Phase 1 behaviour, end to end ─────────────────────────────────────────────

def test_overwrites_always_go_to_a_human_even_if_the_judge_allows(gateway_for):
    drive = fx.build_drive()
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), backend=drive)   # human says no
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_1})
    outcome = gw.execute("drive_update_file", {"file_id": fx.INV_1, "new_content": "Status: PAID"})
    assert outcome.judged == "escalate" and outcome.status == "blocked"
    assert drive.writes == []


def test_after_an_injected_document_even_an_allowing_judge_cannot_write(gateway_for, tmp_path):
    gw = gateway_for(scenario("8_injection_then_write"))
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_3})
    outcome = gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    assert outcome.decision.tier == "high" and outcome.judged == "escalate" and outcome.status == "blocked"
    assert "invoice_003" in _records(tmp_path / "audit.jsonl")[-1]["session_taint"][0]


def test_a_human_approved_sensitive_read_still_taints_later_writes(gateway_for):
    task = SimpleNamespace(
        task=f"Tidy the reports in {fx.REPORTS}; payroll is in {fx.PAYROLL}",
        scope=TaskScope(intent="tidy reports", actions=(Action.LIST, Action.READ, Action.WRITE),
                        relevant_locations=("reports",), out_of_bounds_hints=("salaries",)),
    )
    gw = gateway_for(task, escalate=lambda ctx, reason: True)
    gw.execute("drive_list_files", {"folder_id": fx.PAYROLL})
    read = gw.execute("drive_read_file", {"file_id": fx.SALARIES})
    assert read.judged == "escalate" and read.status == "executed"      # HIGH, approved by the human
    assert any("sensitive" in t for t in gw.provenance.taint)
    write = gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    assert write.decision.tier == "high"


def test_call_budget_stops_a_looping_worker(gateway_for):
    gw = gateway_for(budget=Budget(max_calls=3))
    verdicts = [gw.execute("drive_list_files", {"folder_id": fx.INVOICES}).judged for _ in range(5)]
    assert verdicts == ["allow", "allow", "allow", "block", "block"]


def test_dry_run_records_writes_without_changing_the_drive(gateway_for):
    drive = fx.build_drive()
    dry = DryRunDrive(drive)
    gw = gateway_for(scenario("7_save_summary"), judge=StubJudge(), escalate=lambda ctx, reason: True, backend=dry)
    gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    assert len(dry.writes) == 1 and drive.writes == []


def test_dry_run_update_reports_the_file_name():
    """B14"""
    result = DryRunDrive(fx.build_drive()).update_file(fx.INV_1, "x")
    assert result["name"] == "invoice_001.txt" and result["dry_run"]


# ── Regression tests (code review 2) ──────────────────────────────────────────

def test_held_writes_cannot_exceed_the_write_budget_when_approved(gateway_for):
    """B3: five held writes with max_writes=3 used to all run after approval."""
    drive = fx.build_drive()
    gw = gateway_for(scenario("7_save_summary"), judge=StubJudge(), backend=drive,
                     escalate=lambda ctx, reason: PENDING, budget=Budget(max_writes=3))
    held = [gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": f"n{i}.txt", "new_content": "x"})
            for i in range(5)]
    results = [gw.resolve(h.call_id, approved=True) for h in held]
    assert [r.status for r in results] == ["executed"] * 3 + ["blocked"] * 2
    assert "Approved by human, but session budget exceeded" in results[-1].decision.reason
    assert len(drive.writes) == 3


def test_resolving_an_unknown_or_answered_call_is_a_clear_error(gateway_for):
    """B7: used to be a bare KeyError (e.g. a double-click on Approve)."""
    import pytest

    gw = gateway_for(scenario("7_save_summary"), judge=StubJudge(), escalate=lambda ctx, reason: PENDING)
    held = gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    gw.resolve(held.call_id, approved=False)
    with pytest.raises(ValueError, match="already been answered"):
        gw.resolve(held.call_id, approved=True)
