"""
tools.py — tool registry and Drive backends.

Each tool is defined exactly once as a ToolSpec. The JSON schemas sent to the
worker model and the action/resource info used by the Guardian both come from
TOOLS, so a tool that is not registered here cannot be called at all.

Two backends implement the same DriveBackend interface:
  GoogleDrive — the real Google Drive API (OAuth, see README)
  FakeDrive   — an in-memory Drive used by the scenario runner (no credentials)

Authentication flow for GoogleDrive (first run):
  1. Put your OAuth credentials.json from Google Cloud Console into credentials/
  2. Run this file directly: `python tools.py`
  3. Subsequent runs use credentials/token.json automatically.
"""

import io
import os
from dataclasses import dataclass, field
from typing import Callable, Protocol

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


# ── Backend interface ─────────────────────────────────────────────────────────

class DriveBackend(Protocol):
    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        """Return [{id, name, mimeType}] for the direct children of a folder."""

    def read_file(self, file_id: str) -> dict:
        """Return {id, name, content} with the file's text content."""

    def update_file(self, file_id: str, content: str) -> dict:
        """Overwrite a text file. Return {id, name, updated}."""

    def get_metadata(self, resource_id: str) -> dict | None:
        """Return {id, name, path, owner, mimeType, is_folder}, or None if not found."""


# ── Real Google Drive ─────────────────────────────────────────────────────────

_CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials")
CREDENTIALS_PATH = os.path.join(_CREDENTIALS_DIR, "credentials.json")
TOKEN_PATH = os.path.join(_CREDENTIALS_DIR, "token.json")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",  # allows updating files the app created/opened
]


class GoogleDrive:
    """DriveBackend over the Google Drive v3 API."""

    def __init__(self):
        self._service = None
        self._folder_cache: dict[str, dict] = {}  # folder id -> {name, parents}

    def _svc(self):
        if self._service is None:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(TOKEN_PATH):
                creds = Credentials.from_authorized_user_file(TOKEN_PATH, GOOGLE_SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, GOOGLE_SCOPES)
                    creds = flow.run_local_server(port=0)
                with open(TOKEN_PATH, "w") as fh:
                    fh.write(creds.to_json())
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        safe_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        resp = self._svc().files().list(
            q=f"'{safe_id}' in parents and trashed=false",
            pageSize=max_results,
            fields="files(id, name, mimeType)",
        ).execute()
        return resp.get("files", [])

    def read_file(self, file_id: str) -> dict:
        from googleapiclient.http import MediaIoBaseDownload

        svc = self._svc()
        meta = svc.files().get(fileId=file_id, fields="name,mimeType").execute()
        if meta.get("mimeType") == GOOGLE_DOC_MIME:
            data = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = data.decode("utf-8") if isinstance(data, bytes) else data
        else:
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = buf.getvalue().decode("utf-8", errors="replace")
        return {"id": file_id, "name": meta["name"], "content": content}

    def update_file(self, file_id: str, content: str) -> dict:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="text/plain")
        result = self._svc().files().update(fileId=file_id, media_body=media).execute()
        return {"id": file_id, "name": result.get("name"), "updated": True}

    def get_metadata(self, resource_id: str) -> dict | None:
        from googleapiclient.errors import HttpError

        try:
            meta = self._svc().files().get(
                fileId=resource_id,
                fields="id,name,mimeType,parents,owners(emailAddress)",
            ).execute()
        except HttpError:
            return None
        owners = meta.get("owners") or [{}]
        return {
            "id": meta["id"],
            "name": meta["name"],
            "path": self._path(meta.get("parents") or []) + "/" + meta["name"],
            "owner": owners[0].get("emailAddress", "unknown"),
            "mimeType": meta.get("mimeType", ""),
            "is_folder": meta.get("mimeType") == FOLDER_MIME,
        }

    def _path(self, parents: list[str]) -> str:
        """Build '/A/B' for the first parent chain (cached; capped to avoid cycles)."""
        names = []
        current = parents[0] if parents else None
        for _ in range(20):
            if current is None:
                break
            if current not in self._folder_cache:
                f = self._svc().files().get(fileId=current, fields="name,parents").execute()
                self._folder_cache[current] = f
            folder = self._folder_cache[current]
            if not folder.get("parents"):  # "My Drive" root — don't include it
                break
            names.append(folder["name"])
            current = folder["parents"][0]
        return "/" + "/".join(reversed(names)) if names else ""


# ── In-memory Drive for scenarios ─────────────────────────────────────────────

@dataclass
class FakeNode:
    name: str
    parent: str | None
    is_folder: bool = False
    content: str = ""
    owner: str = "owner@company.com"


@dataclass
class FakeDrive:
    """DriveBackend over a dict of {id: FakeNode}. Tracks writes for assertions."""
    nodes: dict[str, FakeNode]
    writes: list[tuple[str, str]] = field(default_factory=list)

    def _node(self, resource_id: str) -> FakeNode:
        if resource_id not in self.nodes:
            raise FileNotFoundError(f"File not found: {resource_id}")
        return self.nodes[resource_id]

    def list_folder(self, folder_id: str, max_results: int = 50) -> list[dict]:
        self._node(folder_id)
        children = [
            {"id": nid, "name": n.name, "mimeType": FOLDER_MIME if n.is_folder else "text/plain"}
            for nid, n in self.nodes.items() if n.parent == folder_id
        ]
        return children[:max_results]

    def read_file(self, file_id: str) -> dict:
        node = self._node(file_id)
        return {"id": file_id, "name": node.name, "content": node.content}

    def update_file(self, file_id: str, content: str) -> dict:
        node = self._node(file_id)
        node.content = content
        self.writes.append((file_id, content))
        return {"id": file_id, "name": node.name, "updated": True}

    def get_metadata(self, resource_id: str) -> dict | None:
        node = self.nodes.get(resource_id)
        if node is None:
            return None
        # Like Google Drive, the root folder ("My Drive") is not part of the path.
        names, current = [node.name], node.parent
        while current is not None and self.nodes[current].parent is not None:
            names.append(self.nodes[current].name)
            current = self.nodes[current].parent
        return {
            "id": resource_id,
            "name": node.name,
            "path": "/" + "/".join(reversed(names)),
            "owner": node.owner,
            "mimeType": FOLDER_MIME if node.is_folder else "text/plain",
            "is_folder": node.is_folder,
        }


# ── Tool registry ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    action: str                 # "list" | "read" | "write"
    resource_arg: str           # the argument that names the Drive resource
    params: dict                # JSON-schema properties
    required: tuple[str, ...]
    run: Callable[[DriveBackend, dict], dict]

    def schema(self) -> dict:
        """OpenAI-style tool schema passed to the worker model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.params,
                    "required": list(self.required),
                },
            },
        }


_JSON_TYPES = {"string": str, "integer": int}


def validate_args(spec: ToolSpec, args: dict) -> str | None:
    """Return an error message if args don't match the spec's schema, else None."""
    missing = [a for a in spec.required if a not in args]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    unknown = [a for a in args if a not in spec.params]
    if unknown:
        return f"unknown argument(s): {', '.join(unknown)}"
    for name, value in args.items():
        expected = _JSON_TYPES[spec.params[name]["type"]]
        if not isinstance(value, expected) or isinstance(value, bool):
            return f"argument '{name}' must be of type {spec.params[name]['type']}"
    return None


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="drive_list_files",
            description="List files inside a specific Google Drive folder.",
            action="list",
            resource_arg="folder_id",
            params={
                "folder_id": {"type": "string", "description": "The Google Drive folder ID to list."},
                "max_results": {"type": "integer", "description": "Max files to return (default 50)."},
            },
            required=("folder_id",),
            run=lambda d, a: {"files": d.list_folder(a["folder_id"], a.get("max_results", 50))},
        ),
        ToolSpec(
            name="drive_read_file",
            description="Download and read the text content of a Google Drive file.",
            action="read",
            resource_arg="file_id",
            params={"file_id": {"type": "string", "description": "The Google Drive file ID to read."}},
            required=("file_id",),
            run=lambda d, a: d.read_file(a["file_id"]),
        ),
        ToolSpec(
            name="drive_update_file",
            description="Overwrite a plain-text Google Drive file with new content.",
            action="write",
            resource_arg="file_id",
            params={
                "file_id": {"type": "string", "description": "The file ID to update."},
                "new_content": {"type": "string", "description": "The full new text content to write."},
            },
            required=("file_id", "new_content"),
            run=lambda d, a: d.update_file(a["file_id"], a["new_content"]),
        ),
    ]
}

TOOL_SCHEMAS: list[dict] = [spec.schema() for spec in TOOLS.values()]


if __name__ == "__main__":
    # Run this file directly once to trigger the OAuth flow and save token.json
    print("Authenticating with Google Drive...")
    GoogleDrive()._svc()
    print(f"Success! token saved to {TOKEN_PATH}")
