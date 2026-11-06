from judging_agent.guardian.decision import HIGH, LOW, MEDIUM
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.risk import risk_tier
from judging_agent.guardian.scope import TaskScope

SCOPE = TaskScope(
    intent="Summarise invoices",
    relevant_locations=("invoices",),
    out_of_bounds_hints=("payroll", "hr"),
)
LISTING = Sighting("listing", "folder")


def _meta(path, owner="me@company.com"):
    return {"path": path, "owner": owner}


def test_out_of_bounds_hint_is_high():
    tier, reason = risk_tier("read", _meta("/HR/Payroll/salaries.xlsx"), LISTING, SCOPE)
    assert tier == HIGH and "payroll" in reason


def test_hints_match_whole_words_only():
    tier, _ = risk_tier("read", _meta("/Projects/three_year_plan.txt"), LISTING, SCOPE)
    assert tier == MEDIUM


def test_id_seen_only_in_content_is_high():
    tier, reason = risk_tier("read", _meta("/Finance/Reports/q3.txt"), Sighting("content", "inv3"), SCOPE)
    assert tier == HIGH and "document content" in reason


def test_writes_are_at_least_medium():
    tier, _ = risk_tier("write", _meta("/Finance/Invoices/inv.txt"), Sighting("task"), SCOPE)
    assert tier == MEDIUM


def test_reads_named_in_task_or_in_relevant_location_are_low():
    assert risk_tier("read", _meta("/Anything/x.txt"), Sighting("task"), SCOPE)[0] == LOW
    assert risk_tier("read", _meta("/Finance/Invoices/inv.txt"), LISTING, SCOPE)[0] == LOW


def test_everything_else_is_medium():
    assert risk_tier("read", _meta("/Projects/roadmap.txt"), LISTING, SCOPE)[0] == MEDIUM
