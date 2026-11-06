import json

from evals.scenarios import fixture as fx
from judging_agent.drive import DryRunDrive
from judging_agent.guardian import StubJudge, ToolGateway, deny_escalation


def _gateway(tmp_path, backend=None, scope=fx._INVOICES_SCOPE, task=fx._INVOICES_TASK):
    return ToolGateway(
        task=task,
        scope=scope,
        backend=backend or fx.build_drive(),
        judge=StubJudge(),
        escalate=deny_escalation,
        audit_path=tmp_path / "audit.jsonl",
        verbose=False,
    )


def test_injected_link_is_blocked_and_never_executed(tmp_path):
    gw = _gateway(tmp_path)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_3})
    outcome = gw.execute("drive_read_file", {"file_id": fx.SALARIES})
    assert outcome.judged == "block"
    assert outcome.result["error"] == "blocked by guardian"
    assert "content" not in outcome.result


def test_every_call_is_audited(tmp_path):
    gw = _gateway(tmp_path)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_delete_file", {"file_id": fx.INV_1})
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [r["tool"] for r in records] == ["drive_list_files", "drive_delete_file"]
    assert [r["executed"] for r in records] == [True, False]


def test_unparseable_arguments_are_blocked(tmp_path):
    outcome = _gateway(tmp_path).execute("drive_read_file", {"_unparsed": "{oops"})
    assert outcome.judged == "block"


def test_dry_run_records_writes_without_changing_the_drive(tmp_path):
    drive = fx.build_drive()
    dry = DryRunDrive(drive)
    scope = fx.ALL_SCENARIOS[-1].scope            # 7_save_summary: write allowed
    gw = ToolGateway(task=fx.ALL_SCENARIOS[-1].task, scope=scope, backend=dry, judge=StubJudge(),
                     escalate=lambda ctx, reason: True, audit_path=tmp_path / "a.jsonl", verbose=False)
    gw.execute("drive_create_file", {"folder_id": fx.REPORTS, "name": "s.txt", "new_content": "x"})
    assert len(dry.writes) == 1
    assert drive.writes == []
