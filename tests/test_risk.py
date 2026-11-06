from helpers import meta

from judging_agent.guardian.decision import Tier
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.risk import risk_tier
from judging_agent.guardian.scope import TaskScope, fallback_scope
from judging_agent.tools import Action

SCOPE = TaskScope(intent="Summarise invoices", relevant_locations=("invoices",),
                  out_of_bounds_hints=("payroll", "hr"))
LISTING = Sighting("listing", "folder")


def test_out_of_bounds_hint_in_path_or_owner_is_high():
    tier, reason = risk_tier(Action.READ, meta("/HR/Payroll/salaries.xlsx"), LISTING, SCOPE)
    assert tier == Tier.HIGH and "payroll" in reason
    tier, _ = risk_tier(Action.READ, meta("/Shared/x.txt", owner="hr@company.com"), LISTING, SCOPE)
    assert tier == Tier.HIGH


def test_hints_match_whole_words_only():
    assert risk_tier(Action.READ, meta("/Projects/three_year_plan.txt"), LISTING, SCOPE)[0] == Tier.MEDIUM


def test_untrusted_id_is_high():
    tier, reason = risk_tier(Action.READ, meta("/Finance/Reports/q3.txt"), Sighting("content", "inv3"), SCOPE)
    assert tier == Tier.HIGH and "untrusted" in reason


def test_writes_are_at_least_medium():
    assert risk_tier(Action.WRITE, meta("/Finance/Invoices/inv.txt"), Sighting("task"), SCOPE)[0] == Tier.MEDIUM


def test_reads_named_in_task_or_in_relevant_location_are_low():
    assert risk_tier(Action.READ, meta("/Anything/x.txt"), Sighting("task"), SCOPE)[0] == Tier.LOW
    assert risk_tier(Action.READ, meta("/Finance/Invoices/inv.txt"), LISTING, SCOPE)[0] == Tier.LOW


def test_everything_else_is_medium():
    assert risk_tier(Action.READ, meta("/Projects/roadmap.txt"), LISTING, SCOPE)[0] == Tier.MEDIUM


def test_taint_makes_writes_high_but_not_reads():
    taint = ("read /Finance/Invoices/inv3.txt, which links to other Drive files",)
    tier, reason = risk_tier(Action.WRITE, meta("/Finance/Reports/s.txt"), Sighting("task"), SCOPE, taint)
    assert tier == Tier.HIGH and "inv3" in reason
    assert risk_tier(Action.READ, meta("/Finance/Invoices/inv.txt"), LISTING, SCOPE, taint)[0] == Tier.LOW


def test_fallback_scope_still_marks_payroll_high():
    """B6: with the scope LLM down, payroll used to be only MEDIUM."""
    tier, _ = risk_tier(Action.READ, meta("/HR/Payroll/salaries.xlsx"), LISTING, fallback_scope("invoices"))
    assert tier == Tier.HIGH
