from judging_agent.drive.base import EDITABLE_MIMES
from judging_agent.tools import TOOL_SCHEMAS, TOOLS, Action, ToolSpec, tool_schemas, validate_args


def test_no_unexpected_tools_are_registered():
    """Guard: a new tool must be added here on purpose (share/delete must never appear)."""
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


def test_max_results_is_bounded():
    """B8: the Drive API allows at most 1000 per page; 0 or negative makes no sense."""
    listing = TOOLS["drive_list_files"]
    assert "at least 1" in validate_args(listing, {"folder_id": "f", "max_results": 0})
    assert "at most 1000" in validate_args(listing, {"folder_id": "f", "max_results": 5000})
    assert validate_args(listing, {"folder_id": "f", "max_results": 1000}) is None


def _spec(params):
    return ToolSpec(name="t", description="", action=Action.READ, resource_arg="id",
                    params=params, required=(), run=lambda d, a: {})


def test_other_json_types_are_validated_and_unknown_types_rejected():
    """B12: new parameter types used to crash with KeyError."""
    spec = _spec({"flag": {"type": "boolean"}, "ratio": {"type": "number"},
                  "tags": {"type": "array"}, "odd": {"type": "date"}})
    assert validate_args(spec, {"flag": True, "ratio": 0.5, "tags": ["a"]}) is None
    assert "boolean" in validate_args(spec, {"flag": "yes"})
    assert "unsupported" in validate_args(spec, {"odd": "2026-01-01"})


def test_update_is_limited_to_text_files_and_needs_a_read_and_a_human():
    update = TOOLS["drive_update_file"]
    assert update.target_mimes == EDITABLE_MIMES
    assert update.requires_prior_read and update.needs_confirmation
    assert TOOLS["drive_create_file"].target == "folder"


def test_tool_schemas_only_offer_allowed_actions():
    """A9: a read-only task never sees the write tools."""
    names = [s["function"]["name"] for s in tool_schemas((Action.LIST, Action.READ))]
    assert names == ["drive_list_files", "drive_read_file"]


def test_long_files_are_cut_for_the_worker_with_a_visible_note():
    """B5: a 2 MB file used to go to the worker in full."""
    from evals.scenarios import fixture as fx
    from judging_agent.tools import MAX_READ_CHARS

    drive = fx.build_drive()
    drive.nodes[fx.INV_1].content = "x" * (MAX_READ_CHARS + 10)
    result = TOOLS["drive_read_file"].run(drive, {"file_id": fx.INV_1})
    assert result["truncated"] is True
    assert result["content"].startswith("x" * MAX_READ_CHARS)
    assert result["content"].endswith(f"[truncated: showing {MAX_READ_CHARS:,} of {MAX_READ_CHARS + 10:,} characters]")
    assert "truncated" not in TOOLS["drive_read_file"].run(drive, {"file_id": fx.INV_2})
