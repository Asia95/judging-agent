"""GoogleDrive against a fake Drive API service: no network, no credentials."""

from googleapiclient.errors import HttpError

from judging_agent.drive.google import GoogleDrive


class _Resp(dict):
    status = 404
    reason = "Not Found"


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeService:
    """files().get / files().list / about().get over a small dict of files."""

    def __init__(self, files: dict, children: list[dict] | None = None, page_size_cap: int = 2):
        self._files = files
        self._children = children or []
        self._cap = page_size_cap
        self.list_calls = 0

    def files(self):
        return self

    def about(self):
        return self

    def get(self, fileId=None, fields=None):
        if fileId is None:                       # about().get
            return _Req(lambda: {"user": {"emailAddress": "me@company.com"}})

        def fetch():
            if fileId not in self._files:
                raise HttpError(_Resp(), b"File not found")
            return self._files[fileId]
        return _Req(fetch)

    def list(self, q, pageSize, pageToken, fields):
        self.list_calls += 1
        start = int(pageToken or 0)
        size = min(pageSize, self._cap)
        page = self._children[start:start + size]
        token = str(start + size) if start + size < len(self._children) else None
        return _Req(lambda: {"files": page, "nextPageToken": token})


def _drive(service) -> GoogleDrive:
    g = GoogleDrive()
    g._service = service
    return g


def test_a_shared_file_whose_parent_is_hidden_does_not_crash():
    """B3: get_metadata used to raise when a parent folder wasn't visible."""
    files = {"shared": {"id": "shared", "name": "notes.txt", "mimeType": "text/plain",
                        "parents": ["hidden-parent"], "owners": [{"emailAddress": "vendor@acme.com"}]}}
    meta = _drive(FakeService(files)).get_metadata("shared")
    assert meta.path == "/(hidden)/notes.txt"
    assert meta.ancestors == ()          # unknown, so a workspace boundary blocks it
    assert meta.owner == "vendor@acme.com"


def test_ancestry_for_a_normal_file():
    files = {
        "root": {"name": "My Drive"},
        "fin": {"name": "Finance", "parents": ["root"]},
        "inv": {"id": "inv", "name": "inv.pdf", "mimeType": "application/pdf", "parents": ["fin"],
                "owners": [{"emailAddress": "me@company.com"}]},
    }
    meta = _drive(FakeService(files)).get_metadata("inv")
    assert (meta.path, meta.ancestors) == ("/Finance/inv.pdf", ("fin", "root"))


def test_listing_follows_pages_up_to_max_results():
    """B8: only the first page used to be returned."""
    children = [{"id": f"f{i}", "name": f"file{i}", "mimeType": "text/plain"} for i in range(5)]
    service = FakeService({}, children, page_size_cap=2)
    drive = _drive(service)
    assert [f["id"] for f in drive.list_folder("folder", max_results=50)] == [f"f{i}" for i in range(5)]
    assert service.list_calls == 3
    assert len(drive.list_folder("folder", max_results=3)) == 3


def test_user_email_is_read_once():
    assert _drive(FakeService({})).user_email() == "me@company.com"
