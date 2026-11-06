"""
drive/base.py — the interface every Drive backend implements, its metadata type,
and MIME types.

Backends only talk to storage; they know nothing about the Guardian.
"""

from dataclasses import dataclass
from typing import Protocol

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
TEXT_MIME = "text/plain"
EDITABLE_MIMES = frozenset({GOOGLE_DOC_MIME, TEXT_MIME})


@dataclass(frozen=True)
class ResourceMeta:
    """What the Guardian knows about a file or folder before touching it."""
    id: str
    name: str
    path: str                       # "/Finance/Invoices/inv.pdf"; the Drive root is not included
    owner: str                      # owner's email address, or "unknown"
    mime_type: str
    is_folder: bool
    ancestors: tuple[str, ...] = ()  # IDs of the folders above it, nearest first


class DriveBackend(Protocol):
    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        """Return [{id, name, mimeType}] for the direct children of a folder."""

    def read_file(self, file_id: str) -> dict:
        """Return {id, name, content} with the file's text content."""

    def update_file(self, file_id: str, content: str) -> dict:
        """Overwrite a text file. Return {id, name, updated}."""

    def create_file(self, folder_id: str, name: str, content: str) -> dict:
        """Create a plain text file in a folder. Return {id, name, created}."""

    def get_metadata(self, resource_id: str) -> ResourceMeta | None:
        """Return the resource's metadata, or None if it doesn't exist or isn't visible."""

    def user_email(self) -> str:
        """The email address of the account the agent acts for."""
