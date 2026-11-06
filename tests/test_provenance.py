from judging_agent.guardian.provenance import ProvenanceTracker, Sighting

FOLDER = "1UeTJ6TPqmMgKmLmpwwwb1ZF-qeIElXxd"      # realistic Drive IDs: letters + digits
FILE_A = "1QEt27fYutqDgElC50kGIxFFBdHz3sVjp"
FILE_B = "1RwtIdM_s-cpV0z_fNz30rUHubcqW2PRC"


def test_ids_in_the_task_are_trusted():
    tracker = ProvenanceTracker(f"List folder {FOLDER} please")
    assert tracker.best(FOLDER) == Sighting("task")
    assert tracker.best(FILE_A) is None


def test_listing_reveals_children():
    tracker = ProvenanceTracker(f"task {FOLDER}")
    tracker.ingest(FOLDER, {"files": [{"id": FILE_A}]})
    assert tracker.best(FILE_A) == Sighting("listing", FOLDER)


def test_a_read_is_tracked_and_ids_inside_content_are_untrusted():
    tracker = ProvenanceTracker("task")
    linked = tracker.ingest(FILE_A, {"content": f"see .../d/{FILE_B}/edit (this file is {FILE_A})"})
    assert linked == {FILE_B}
    assert tracker.read_ids == {FILE_A}
    assert tracker.best(FILE_B) == Sighting("content", FILE_A)
    assert not tracker.best(FILE_B).trusted
    assert tracker.best(FILE_A) is None          # its own ID doesn't count


def test_a_trusted_sighting_wins_over_content():
    tracker = ProvenanceTracker(f"task {FOLDER}")
    tracker.ingest(FILE_A, {"content": FILE_B})
    tracker.ingest(FOLDER, {"files": [{"id": FILE_B}]})
    assert tracker.best(FILE_B).source == "listing"


def test_created_files_are_trusted():
    tracker = ProvenanceTracker(f"task {FOLDER}")
    tracker.ingest(FOLDER, {"id": "new-file", "created": True})
    assert tracker.best("new-file") == Sighting("created", FOLDER)
    assert tracker.best("new-file").trusted


def test_files_inside_an_untrusted_folder_stay_untrusted():
    """B5: approving one listing of a folder found in content used to launder its children."""
    tracker = ProvenanceTracker("task")
    tracker.ingest(FILE_A, {"content": f"see folder {FOLDER}"})
    tracker.ingest(FOLDER, {"files": [{"id": FILE_B}]})
    child = tracker.best(FILE_B)
    assert child.source == "listing" and child.inherited_untrusted and not child.trusted
    assert "only found in document content" in child.describe()


def test_taint_reasons_are_not_duplicated():
    tracker = ProvenanceTracker("task")
    tracker.mark_tainted("x")
    tracker.mark_tainted("x")
    assert tracker.taint == ["x"]


def test_url_slugs_are_not_drive_ids_but_drive_urls_are():
    """B4: ordinary web links used to taint the session."""
    from judging_agent.guardian.provenance import extract_ids

    assert extract_ids("https://example.com/guides/getting-started-with-invoices") == set()
    assert extract_ids(f"https://docs.google.com/document/d/{FILE_A}/edit") == {FILE_A}
    assert extract_ids("https://drive.google.com/drive/folders/AbCdEfGhIjKlMnOp") == {"AbCdEfGhIjKlMnOp"}
    assert extract_ids("open?id=XyZ123abcDEF456") == {"XyZ123abcDEF456"}
    assert extract_ids(f"bare id {FILE_B} in text") == {FILE_B}
