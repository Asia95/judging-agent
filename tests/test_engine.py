"""PolicyEngine: the Guardian's decision on its own, with no tools run."""

from helpers import AllowJudge, meta

from judging_agent.drive.base import FOLDER_MIME
from judging_agent.guardian import PolicyEngine, Session, StubJudge, TaskScope
from judging_agent.guardian.decision import Layer, Tier, Verdict
from judging_agent.guardian.provenance import Sighting
from judging_agent.tools import Action

FILE = "1QEt27fYutqDgElC50kGIxFFBdHz3sVjp"      # realistic Drive IDs: letters + digits
FOLDER = "1UeTJ6TPqmMgKmLmpwwwb1ZF-qeIElXxd"
WRITE_SCOPE = TaskScope(intent="t", actions=(Action.LIST, Action.READ, Action.WRITE))


def _session(*known, source="listing"):
    session = Session("task")
    for rid in known:
        session.provenance.add(rid, Sighting(source, "parent"))
    return session


def test_low_tier_is_allowed_without_asking_the_judge():
    judge = AllowJudge()
    engine = PolicyEngine(f"read {FILE}", TaskScope(intent="t"), judge)
    session = Session(f"read {FILE}")
    decision, ctx = engine.evaluate("drive_read_file", {"file_id": FILE}, session, lambda rid: meta(id=FILE))
    assert (decision.outcome, decision.layer, judge.calls) == (Verdict.ALLOW, Layer.TIER, 0)
    assert ctx.tier == Tier.LOW


def test_a_lookup_error_blocks_instead_of_crashing():
    """B3: a Drive timeout or a hidden parent folder used to crash the whole run."""
    def broken(rid):
        raise TimeoutError("Drive API timed out")
    engine = PolicyEngine("t", TaskScope(intent="t"), AllowJudge())
    decision, ctx = engine.evaluate("drive_read_file", {"file_id": FILE}, _session(FILE), broken)
    assert decision.outcome == Verdict.BLOCK and "Could not verify" in decision.reason and ctx is None


def test_a_missing_resource_is_blocked():
    engine = PolicyEngine("t", TaskScope(intent="t"), AllowJudge())
    decision, _ = engine.evaluate("drive_read_file", {"file_id": FILE}, _session(FILE), lambda rid: None)
    assert decision.outcome == Verdict.BLOCK and "does not exist" in decision.reason


def test_a_judge_can_never_allow_a_high_call():
    """Enforced in the engine, so it holds for any judge, not just LLMJudge."""
    engine = PolicyEngine("t", TaskScope(intent="t"), AllowJudge())
    session = _session(FILE, source="content")
    decision, ctx = engine.evaluate("drive_read_file", {"file_id": FILE}, session, lambda rid: meta(id=FILE))
    assert ctx.tier == Tier.HIGH and decision.outcome == Verdict.ESCALATE


def test_an_allowed_overwrite_still_needs_a_human():
    engine = PolicyEngine("t", WRITE_SCOPE, AllowJudge())
    session = _session(FILE)
    session.provenance.read_ids.add(FILE)
    decision, _ = engine.evaluate("drive_update_file", {"file_id": FILE, "new_content": "x"}, session,
                                  lambda rid: meta(id=FILE))
    assert decision.outcome == Verdict.ESCALATE and "human confirmation" in decision.reason


def test_an_allowed_create_needs_no_human():
    engine = PolicyEngine("t", WRITE_SCOPE, AllowJudge())
    folder = meta("/Reports", is_folder=True, mime=FOLDER_MIME, id=FOLDER)
    decision, _ = engine.evaluate("drive_create_file", {"folder_id": FOLDER, "name": "s.txt", "new_content": "x"},
                                  _session(FOLDER), lambda rid: folder)
    assert decision.outcome == Verdict.ALLOW


def test_a_write_too_long_for_the_judge_is_blocked_before_it():
    """B1"""
    judge = AllowJudge()
    engine = PolicyEngine("t", WRITE_SCOPE, judge)
    folder = meta("/Reports", is_folder=True, mime=FOLDER_MIME, id=FOLDER)
    args = {"folder_id": FOLDER, "name": "s.txt", "new_content": "x" * 5000}
    decision, _ = engine.evaluate("drive_create_file", args, _session(FOLDER), lambda rid: folder)
    assert decision.outcome == Verdict.BLOCK and judge.calls == 0


def test_stub_judge_through_the_engine():
    engine = PolicyEngine("t", TaskScope(intent="t"), StubJudge())
    decision, _ = engine.evaluate("drive_read_file", {"file_id": FILE}, _session(FILE),
                                  lambda rid: meta("/Projects/roadmap.txt", id=FILE))
    assert (decision.outcome, decision.layer) == (Verdict.ESCALATE, Layer.STUB)
