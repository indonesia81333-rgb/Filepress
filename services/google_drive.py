from __future__ import annotations

from pathlib import Path
from typing import Callable

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveError(RuntimeError):
    pass


def _service(credentials_file: str):
    path = Path(credentials_file)
    if not path.is_file():
        raise GoogleDriveError(
            f"Google service-account JSON was not found: {path}. "
            "Set GDRIVE_SERVICE_ACCOUNT_FILE and add that account to your Shared Drive."
        )
    credentials = service_account.Credentials.from_service_account_file(
        str(path), scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def upload_file(
    file_path: Path,
    file_name: str,
    credentials_file: str,
    folder_id: str = "",
    progress_callback: Callable[[float], None] | None = None,
) -> dict:
    """Upload a local file using Google's resumable upload protocol."""
    try:
        drive = _service(credentials_file)
        body = {"name": file_name}
        if folder_id:
            body["parents"] = [folder_id]

        media = MediaFileUpload(
            str(file_path),
            resumable=True,
            chunksize=8 * 1024 * 1024,
        )
        request = drive.files().create(
            body=body,
            media_body=media,
            fields="id,name,size,webViewLink",
            supportsAllDrives=True,
        )
        response = None
        while response is None:
            status, response = request.next_chunk(num_retries=5)
            if status and progress_callback:
                progress_callback(float(status.progress()))

        file_id = response.get("id")
        if not file_id:
            raise GoogleDriveError("Google Drive completed the upload but returned no file ID.")

        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
            supportsAllDrives=True,
        ).execute(num_retries=5)

        # Fetch canonical metadata after granting public-reader access.
        metadata = drive.files().get(
            fileId=file_id,
            fields="id,name,size,webViewLink",
            supportsAllDrives=True,
        ).execute(num_retries=5)
        return metadata
    except GoogleDriveError:
        raise
    except Exception as exc:
        raise GoogleDriveError(f"Google Drive upload failed: {exc}") from exc


def get_file_metadata(file_id: str, credentials_file: str) -> dict:
    """Read metadata for an existing Drive item accessible to the service account."""
    try:
        drive = _service(credentials_file)
        return drive.files().get(
            fileId=file_id,
            fields="id,name,size,webViewLink,mimeType",
            supportsAllDrives=True,
        ).execute(num_retries=3)
    except Exception as exc:
        raise GoogleDriveError(
            "Could not read that Google Drive file. Share it with the service-account "
            f"email or check the file ID. Details: {exc}"
        ) from exc
