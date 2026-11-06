from judging_agent.guardian.provenance import ProvenanceTracker, Sighting

FOLDER = "f" * 28
FILE_A = "a" * 28
FILE_B = "b" * 28


def test_ids_in_the_task_are_trusted():
    tracker = ProvenanceTracker(f"List folder {FOLDER} please")
    assert tracker.best(FOLDER) == Sighting("task")
    assert tracker.best(FILE_A) is None


def test_listing_reveals_children():
    tracker = ProvenanceTracker("task")
    tracker.ingest("list", {"folder_id": FOLDER}, {"files": [{"id": FILE_A}]})
    assert tracker.best(FILE_A) == Sighting("listing", FOLDER)


def test_ids_inside_content_are_untrusted_and_exclude_the_file_itself():
    tracker = ProvenanceTracker("task")
    content = f"see https://docs.google.com/document/d/{FILE_B}/edit (this is {FILE_A})"
    tracker.ingest("read", {"file_id": FILE_A}, {"content": content})
    assert tracker.best(FILE_B) == Sighting("content", FILE_A)
    assert not tracker.best(FILE_B).trusted
    assert tracker.best(FILE_A) is None


def test_a_trusted_sighting_wins_over_content():
    tracker = ProvenanceTracker("task")
    tracker.ingest("read", {"file_id": FILE_A}, {"content": FILE_B})
    tracker.ingest("list", {"folder_id": FOLDER}, {"files": [{"id": FILE_B}]})
    assert tracker.best(FILE_B).source == "listing"


def test_created_files_are_trusted():
    tracker = ProvenanceTracker("task")
    tracker.ingest("write", {"folder_id": FOLDER}, {"id": "new-file", "created": True})
    assert tracker.best("new-file") == Sighting("created", FOLDER)
    assert tracker.best("new-file").trusted
