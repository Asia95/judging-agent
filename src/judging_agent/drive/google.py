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
from judging_agent.drive.base import FOLDER_MIME, GOOGLE_DOC_MIME, GOOGLE_SHEET_MIME, TEXT_MIME, ResourceMeta
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
        self._user_email: str | None = None

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
        """Children of a folder, following pages until max_results (the API allows 1000 per page)."""
        safe_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        files: list[dict] = []
        page_token = None
        while len(files) < max_results:
            resp = self._svc().files().list(
                q=f"'{safe_id}' in parents and trashed=false",
                pageSize=min(max_results - len(files), 1000),
                pageToken=page_token,
                fields="nextPageToken, files(id, name, mimeType)",
            ).execute()
            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return files[:max_results]

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

    def get_metadata(self, resource_id: str) -> ResourceMeta | None:
        from googleapiclient.errors import HttpError

        try:
            meta = self._svc().files().get(
                fileId=resource_id,
                fields="id,name,mimeType,parents,owners(emailAddress)",
            ).execute()
        except HttpError:
            return None
        owners = meta.get("owners") or [{}]
        path, ancestors = self._ancestry(meta.get("parents") or [])
        return ResourceMeta(
            id=meta["id"],
            name=meta["name"],
            path=path + "/" + meta["name"],
            owner=owners[0].get("emailAddress", "unknown"),
            mime_type=meta.get("mimeType", ""),
            is_folder=meta.get("mimeType") == FOLDER_MIME,
            ancestors=tuple(ancestors),
        )

    def user_email(self) -> str:
        if self._user_email is None:
            about = self._svc().about().get(fields="user(emailAddress)").execute()
            self._user_email = about.get("user", {}).get("emailAddress", "unknown")
        return self._user_email

    def _ancestry(self, parents: list[str]) -> tuple[str, list[str]]:
        """Return ('/A/B', [ancestor folder IDs, nearest first]) for the first parent chain.

        The "My Drive" root is in the IDs but not in the path. A parent folder the
        user can't see (common for files shared with them) ends the chain, and the
        path starts with "/(hidden)". Cached; capped to avoid cycles.
        """
        from googleapiclient.errors import HttpError

        names, ids = [], []
        current = parents[0] if parents else None
        for _ in range(20):
            if current is None:
                break
            if current not in self._folder_cache:
                try:
                    f = self._svc().files().get(fileId=current, fields="name,parents").execute()
                except HttpError:
                    names.append("(hidden)")
                    break
                self._folder_cache[current] = f
            folder = self._folder_cache[current]
            ids.append(current)
            if not folder.get("parents"):  # "My Drive" root — not part of the path
                break
            names.append(folder["name"])
            current = folder["parents"][0]
        return ("/" + "/".join(reversed(names)) if names else ""), ids


if __name__ == "__main__":
    # Run once to trigger the OAuth flow and save token.json
    print("Authenticating with Google Drive...")
    GoogleDrive()._svc()
    print(f"Success! token saved to {TOKEN_PATH}")
