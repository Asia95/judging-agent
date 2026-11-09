"""apps/ui/events.py: Guardian outcomes and audit records become the same CallEvents."""

import json

from helpers import SpyDrive, scenario

from apps.ui.events import from_audit, from_outcome, preview, remember_names
from evals.scenarios import fixture as fx
from judging_agent.guardian import PENDING


def _live(gw):
    """Attach a listener like the UI's; returns the list it fills."""
    events, names = [], {}

    def listen(outcome, ctx):
        remember_names(names, outcome, ctx)
        events.append(from_outcome(outcome, ctx, len(events) + 1, names))

    gw.listeners.append(listen)
    return events


def _audit(tmp_path):
    return [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


def _injection_run(gateway_for):
    gw = gateway_for()
    events = _live(gw)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_3})
    gw.execute("drive_read_file", {"file_id": fx.SALARIES})     # the injected goal
    gw.execute("drive_delete_file", {"file_id": fx.INV_1})      # not a tool: blocked before any context
    return gw, events


def test_live_events_say_what_happened_and_how_the_id_was_found(gateway_for):
    _, events = _injection_run(gateway_for)
    listing, read, injected, unknown = events

    assert [e.index for e in events] == [1, 2, 3, 4]
    assert listing.status == "executed" and listing.discovered_via == "task"
    assert listing.result_preview == "invoice_001.txt, invoice_002.pdf, invoice_003.txt"
    assert read.discovered_via == "listing of Invoices"
    assert "NOTE TO AI ASSISTANT" in read.result_preview

    assert injected.status == "blocked" and injected.tier == "high"
    assert injected.resource == "/HR/Payroll/salaries_2026.txt"
    assert injected.discovered_via == "content of invoice_003.txt"
    assert injected.taint and "invoice_003" in injected.taint[0]

    assert unknown.status == "blocked" and unknown.layer == "rule"
    assert unknown.discovered_via is None and unknown.tier is None


def test_pending_and_human_answers_are_events(gateway_for):
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), escalate=lambda ctx, reason: PENDING)
    events = _live(gw)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_1})
    held = gw.execute("drive_update_file", {"file_id": fx.INV_1, "new_content": "Status: PAID"})
    gw.resolve(held.call_id, approved=True)

    pending, done = events[-2:]
    assert pending.status == "pending" and pending.judged == "escalate"
    assert pending.args == {"file_id": fx.INV_1, "new_content": "<12 chars>"}   # content is not shown
    assert done.call_id == pending.call_id and done.status == "executed" and done.by_human


def test_failed_tools_are_events(gateway_for):
    events = _live(gw := gateway_for(backend=SpyDrive(fail={"list_folder"})))
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    assert events[0].status == "failed" and "network down" in events[0].result_preview


def test_replay_from_the_audit_log_matches_the_live_events(gateway_for, tmp_path):
    _, live = _injection_run(gateway_for)
    replayed = from_audit(_audit(tmp_path))
    shared = ("index", "call_id", "tool", "status", "judged", "layer", "tier", "reason", "discovered_via", "taint")
    assert [[getattr(e, f) for f in shared] for e in replayed] == [[getattr(e, f) for f in shared] for e in live]
    assert all(e.result_preview is None for e in replayed)       # the audit log keeps no results


def test_replay_folds_a_call_into_one_event(gateway_for, tmp_path):
    """pending + approved is one call; approved + failed is one call."""
    gw = gateway_for(scenario("9_overwrite_needs_read_and_human"), escalate=lambda ctx, reason: PENDING)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_1})
    held = gw.execute("drive_update_file", {"file_id": fx.INV_1, "new_content": "x"})
    gw.resolve(held.call_id, approved=False)
    events = from_audit(_audit(tmp_path))
    assert [e.status for e in events] == ["executed", "executed", "blocked"]
    assert events[-1].judged == "escalate" and events[-1].layer == "human"

    failing = gateway_for(backend=SpyDrive(fail={"list_folder"}), audit_path=tmp_path / "f.jsonl")
    failing.execute("drive_list_files", {"folder_id": fx.INVOICES})
    records = [json.loads(line) for line in (tmp_path / "f.jsonl").read_text(encoding="utf-8").splitlines()]
    [event] = from_audit(records)
    assert event.status == "failed" and "network down" in event.reason


def test_long_content_is_shortened_in_the_preview():
    assert preview({"content": "x" * 1000}).endswith(" …")
    assert len(preview({"content": "x" * 1000})) < 310
    assert preview({"files": []}) == "(empty folder)"


def test_a_taint_reason_appears_once_right_after_the_call_that_caused_it(gateway_for):
    from apps.ui.events import feed_items

    _, events = _injection_run(gateway_for)         # list, read invoice_003, read salaries, unknown tool
    items = feed_items(events)
    assert [type(i).__name__ for i in items] == ["CallEvent", "CallEvent", "tuple", "CallEvent", "CallEvent"]
    assert "invoice_003" in items[2][0]


def test_the_tainting_call_can_be_the_latest_one(gateway_for):
    from apps.ui.events import feed_items

    gw = gateway_for()
    events = _live(gw)
    gw.execute("drive_list_files", {"folder_id": fx.INVOICES})
    gw.execute("drive_read_file", {"file_id": fx.INV_3})
    assert feed_items(events, tuple(gw.provenance.taint))[-1] == tuple(gw.provenance.taint)
    assert feed_items([], ()) == []
