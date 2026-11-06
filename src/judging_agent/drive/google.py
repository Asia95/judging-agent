"""
drive/google.py — DriveBackend over the Google Drive v3 API.

Authentication (first run):
  1. Put your OAuth credentials.json from Google Cloud Console into credentials/
  2. Run `python -m judging_agent.drive.google`
  3. Later runs use credentials/token.json automatically.

Google Docs are exported as text/plain and Sheets as text/csv (first sheet
only); other files are downloaded and converted by drive.extract.
"""

import io

from judging_agent.config import CREDENTIALS_DIR
from judging_agent.drive.base import FOLDER_MIME, GOOGLE_DOC_MIME, GOOGLE_SHEET_MIME, TEXT_MIME
from judging_agent.drive.extract import extract_text

CREDENTIALS_PATH = CREDENTIALS_DIR / "credentials.json"
TOKEN_PATH = CREDENTIALS_DIR / "token.json"

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
            if TOKEN_PATH.exists():
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
        mime = meta.get("mimeType", "")

        # Google Workspace formats — export as plain text
        if mime == GOOGLE_DOC_MIME:
            data = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = data.decode("utf-8") if isinstance(data, bytes) else data
        elif mime == GOOGLE_SHEET_MIME:
            data = svc.files().export(fileId=file_id, mimeType="text/csv").execute()
            content = data.decode("utf-8") if isinstance(data, bytes) else data
        else:
            # Download the raw binary first
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = downloader.next_chunk()
            raw = buf.getvalue()
            content = extract_text(mime, meta["name"], raw)

        return {"id": file_id, "name": meta["name"], "content": content}

    def update_file(self, file_id: str, content: str) -> dict:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=TEXT_MIME)
        result = self._svc().files().update(fileId=file_id, media_body=media).execute()
        return {"id": file_id, "name": result.get("name"), "updated": True}

    def create_file(self, folder_id: str, name: str, content: str) -> dict:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=TEXT_MIME)
        created = self._svc().files().create(
            body={"name": name, "parents": [folder_id], "mimeType": TEXT_MIME},
            media_body=media,
            fields="id,name",
        ).execute()
        return {"id": created["id"], "name": created["name"], "created": True}

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


if __name__ == "__main__":
    # Run once to trigger the OAuth flow and save token.json
    print("Authenticating with Google Drive...")
    GoogleDrive()._svc()
    print(f"Success! token saved to {TOKEN_PATH}")
