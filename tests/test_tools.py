from judging_agent.drive.base import EDITABLE_MIMES
from judging_agent.tools import TOOL_SCHEMAS, TOOLS, validate_args


def test_registry_has_only_the_four_drive_tools():
    assert set(TOOLS) == {"drive_list_files", "drive_read_file", "drive_update_file", "drive_create_file"}
    assert [s["function"]["name"] for s in TOOL_SCHEMAS] == list(TOOLS)


def test_valid_args_pass():
    assert validate_args(TOOLS["drive_read_file"], {"file_id": "abc"}) is None


def test_missing_unknown_and_wrong_type_args_are_reported():
    read = TOOLS["drive_read_file"]
    assert "missing" in validate_args(read, {})
    assert "unknown" in validate_args(read, {"file_id": "abc", "email": "x@y.z"})
    assert "type string" in validate_args(read, {"file_id": 123})


def test_bool_is_not_accepted_as_integer():
    error = validate_args(TOOLS["drive_list_files"], {"folder_id": "abc", "max_results": True})
    assert error and "integer" in error


def test_update_is_limited_to_text_files_and_create_targets_folders():
    assert TOOLS["drive_update_file"].target_mimes == EDITABLE_MIMES
    assert TOOLS["drive_create_file"].target == "folder"
    assert TOOLS["drive_list_files"].target == "folder"
