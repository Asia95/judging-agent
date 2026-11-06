from judging_agent.drive.base import FOLDER_MIME, TEXT_MIME
from judging_agent.guardian.provenance import Sighting
from judging_agent.guardian.rules import check_resource, check_rules
from judging_agent.guardian.scope import TaskScope
from judging_agent.tools import TOOLS

READ_ONLY = TaskScope(intent="read things")
SEEN = Sighting("listing", "folder")


def test_unknown_tool_is_blocked():
    d = check_rules("drive_delete_file", {"file_id": "x"}, READ_ONLY, SEEN)
    assert d.outcome == "block" and "does not exist" in d.reason


def test_invalid_args_are_blocked():
    d = check_rules("drive_read_file", {"file_id": 5}, READ_ONLY, SEEN)
    assert d.outcome == "block" and "Invalid arguments" in d.reason


def test_write_in_read_only_scope_is_blocked():
    d = check_rules("drive_update_file", {"file_id": "x", "new_content": "y"}, READ_ONLY, SEEN)
    assert d.outcome == "block" and "not part of this task" in d.reason


def test_made_up_id_is_blocked():
    d = check_rules("drive_read_file", {"file_id": "x"}, READ_ONLY, None)
    assert d.outcome == "block" and "made it up" in d.reason


def test_a_valid_call_passes():
    assert check_rules("drive_read_file", {"file_id": "x"}, READ_ONLY, SEEN) is None


def _meta(name, mime, is_folder=False):
    return {"name": name, "mimeType": mime, "is_folder": is_folder}


def test_file_tool_on_a_folder_is_blocked():
    d = check_resource(TOOLS["drive_read_file"], _meta("Invoices", FOLDER_MIME, is_folder=True))
    assert d.outcome == "block" and "wrong tool" in d.reason


def test_update_on_a_pdf_is_blocked_but_text_is_fine():
    update = TOOLS["drive_update_file"]
    assert check_resource(update, _meta("inv.pdf", "application/pdf")).outcome == "block"
    assert check_resource(update, _meta("notes.txt", TEXT_MIME)) is None
