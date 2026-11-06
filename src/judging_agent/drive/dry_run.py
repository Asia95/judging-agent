"""
drive/dry_run.py — a wrapper for evaluations on a real Drive.
"""

from judging_agent.drive.base import DriveBackend


class DryRunDrive:
    """Wraps a backend for evaluations: reads go through, writes are only recorded.

    Lets eval runs on the real Drive exercise write tools without changing the
    fixture files. A file "created" here doesn't exist in the inner backend.
    """

    def __init__(self, inner: DriveBackend):
        self.inner = inner
        self.writes: list[tuple[str, str]] = []

    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        return self.inner.list_folder(folder_id, max_results)

    def read_file(self, file_id: str) -> dict:
        return self.inner.read_file(file_id)

    def get_metadata(self, resource_id: str) -> dict | None:
        return self.inner.get_metadata(resource_id)

    def update_file(self, file_id: str, content: str) -> dict:
        self.writes.append((file_id, content))
        return {"id": file_id, "updated": True, "dry_run": True}

    def create_file(self, folder_id: str, name: str, content: str) -> dict:
        file_id = f"dry-run-{len(self.writes)}"
        self.writes.append((f"{folder_id}/{name}", content))
        return {"id": file_id, "name": name, "created": True, "dry_run": True}
