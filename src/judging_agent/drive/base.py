"""
drive/base.py — the interface every Drive backend implements, and MIME types.

Backends only talk to storage; they know nothing about the Guardian.
"""

from typing import Protocol

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
TEXT_MIME = "text/plain"
EDITABLE_MIMES = frozenset({GOOGLE_DOC_MIME, TEXT_MIME})


class DriveBackend(Protocol):
    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        """Return [{id, name, mimeType}] for the direct children of a folder."""

    def read_file(self, file_id: str) -> dict:
        """Return {id, name, content} with the file's text content."""

    def update_file(self, file_id: str, content: str) -> dict:
        """Overwrite a text file. Return {id, name, updated}."""

    def create_file(self, folder_id: str, name: str, content: str) -> dict:
        """Create a plain text file in a folder. Return {id, name, created}."""

    def get_metadata(self, resource_id: str) -> dict | None:
        """Return {id, name, path, owner, mimeType, is_folder}, or None if not found."""
