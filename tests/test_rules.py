from helpers import meta

from judging_agent.drive.base import FOLDER_MIME
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.rules import Budget, Usage, check_budget, check_resource, check_rules
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import TOOLS, Action

READ_ONLY = TaskScope(intent="read things")
WRITE_SCOPE = TaskScope(intent="edit things", actions=(Action.LIST, Action.READ, Action.WRITE))
SEEN = Sighting("listing", "folder")
UPDATE = {"file_id": "x", "new_content": "y"}


# ── check_rules ───────────────────────────────────────────────────────────────

def test_unknown_tool_is_blocked():
    d = check_rules("drive_delete_file", {"file_id": "x"}, READ_ONLY, SEEN)
    assert d.outcome == "block" and "does not exist" in d.reason


def test_invalid_args_are_blocked():
    d = check_rules("drive_read_file", {"file_id": 5}, READ_ONLY, SEEN)
    assert d.outcome == "block" and "Invalid arguments" in d.reason


def test_write_in_read_only_scope_is_blocked():
    d = check_rules("drive_update_file", UPDATE, READ_ONLY, SEEN)
    assert d.outcome == "block" and "not part of this task" in d.reason


def test_made_up_id_is_blocked():
    d = check_rules("drive_read_file", {"file_id": "x"}, READ_ONLY, None)
    assert d.outcome == "block" and "made it up" in d.reason


def test_a_valid_call_passes():
    assert check_rules("drive_read_file", {"file_id": "x"}, READ_ONLY, SEEN) is None


def test_overwrite_needs_a_prior_read_but_create_does_not():
    assert "wasn't read" in check_rules("drive_update_file", UPDATE, WRITE_SCOPE, SEEN, read_ids=set()).reason
    assert check_rules("drive_update_file", UPDATE, WRITE_SCOPE, SEEN, read_ids={"x"}) is None
    create = {"folder_id": "f", "name": "n.txt", "new_content": "y"}
    assert check_rules("drive_create_file", create, WRITE_SCOPE, SEEN, read_ids=set()) is None


# ── check_budget ──────────────────────────────────────────────────────────────

READ, CREATE = TOOLS["drive_read_file"], TOOLS["drive_create_file"]


def test_budget_caps_calls():
    budget = Budget(max_calls=5)
    assert check_budget(READ, {}, Usage(calls=4), budget) is None
    assert "5 tool calls" in check_budget(READ, {}, Usage(calls=5), budget).reason


def test_budget_caps_writes_and_total_characters():
    budget = Budget(max_writes=2, max_chars_written=10, max_chars_per_write=10)
    assert "2 writes" in check_budget(CREATE, {"new_content": "a"}, Usage(writes=2), budget).reason
    assert "characters written" in check_budget(CREATE, {"new_content": "a" * 6}, Usage(chars_written=5), budget).reason
    assert check_budget(CREATE, {"new_content": "a" * 5}, Usage(chars_written=5), budget) is None


def test_one_write_cannot_exceed_what_the_judge_reads():
    """B1: content past the judge's window used to go unjudged."""
    budget = Budget(max_chars_per_write=100)
    d = check_budget(CREATE, {"new_content": "a" * 101}, Usage(), budget)
    assert d.outcome == "block" and "limit the Guardian can review" in d.reason
    assert check_budget(CREATE, {"new_content": "a" * 100}, Usage(), budget) is None


def test_usage_counts_characters_not_bytes():
    """B13: the counter is named for what it counts."""
    assert hasattr(Usage(), "chars_written") and not hasattr(Usage(), "bytes_written")


# ── check_resource ────────────────────────────────────────────────────────────

def test_file_tool_on_a_folder_is_blocked():
    d = check_resource(READ, meta("/Invoices", is_folder=True, mime=FOLDER_MIME))
    assert d.outcome == "block" and "wrong tool" in d.reason


def test_update_on_a_pdf_is_blocked_but_text_is_fine():
    update = TOOLS["drive_update_file"]
    assert check_resource(update, meta("/inv.pdf", mime="application/pdf")).outcome == "block"
    assert check_resource(update, meta("/notes.txt")) is None


def test_workspace_boundary():
    inside = meta("/W/a.txt", ancestors=("w", "root"))
    outside = meta("/Other/a.txt", ancestors=("other", "root"))
    assert check_resource(READ, inside, workspace_root="w") is None
    assert "outside" in check_resource(READ, outside, workspace_root="w").reason
    assert check_resource(READ, outside, workspace_root=None) is None
    folder = meta("/W", is_folder=True, mime=FOLDER_MIME, id="w")
    assert check_resource(TOOLS["drive_list_files"], folder, workspace_root="w") is None
