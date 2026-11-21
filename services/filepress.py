from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import aiohttp


class FilePressError(RuntimeError):
    pass


def _find_filepress_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for container in (payload.get("data"), payload):
        if isinstance(container, dict):
            for key in ("_id", "file_id", "id"):
                value = container.get(key)
                if value:
                    return str(value)
    return None


def _find_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for container in (payload.get("data"), payload):
        if isinstance(container, dict):
            for key in ("url", "link", "file_url", "download_url"):
                value = container.get(key)
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    return value
    return None


class FilePressClient:
    def __init__(self, api_url: str, api_key: str, base_url: str):
        self.api_url = api_url
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def publish_drive_file(self, drive_file_id: str) -> tuple[str, str | None, dict]:
        """Register an existing Google Drive file with FilePress.

        The currently documented FilePress endpoint accepts a Drive file ID and API key;
        it is a publishing/registration API, not a multipart binary upload endpoint.
        """
        timeout = aiohttp.ClientTimeout(total=90, connect=20, sock_read=60)
        payload = {"key": self.api_key, "id": drive_file_id}
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, json=payload) as response:
                    raw_text = await response.text()
                    try:
                        data = await response.json(content_type=None)
                    except Exception:
                        data = None
                    if response.status not in (200, 201, 202):
                        detail = raw_text[:500] or f"HTTP {response.status}"
                        raise FilePressError(f"FilePress API returned HTTP {response.status}: {detail}")
                    if isinstance(data, dict):
                        message = str(data.get("message", "")).lower()
                        if data.get("success") is False or "file not found" in message:
                            raise FilePressError(str(data.get("message") or "FilePress could not find this Drive file."))
                    filepress_id = _find_filepress_id(data)
                    direct_url = _find_url(data)
                    if direct_url:
                        parsed = urlparse(direct_url)
                        if parsed.scheme not in {"http", "https"}:
                            direct_url = None
                    if not direct_url and filepress_id:
                        direct_url = f"{self.base_url}/file/{filepress_id}"
                    if not direct_url:
                        raise FilePressError(
                            "FilePress accepted the request but returned no usable file ID or URL. "
                            f"Response: {raw_text[:500]}"
                        )
                    return direct_url, filepress_id, data if isinstance(data, dict) else {"raw": raw_text[:500]}
        except FilePressError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise FilePressError(
                f"Could not connect to FilePress API ({self.api_url}). "
                f"Check FILEPRESS_API_URL because FilePress domains may change. Details: {exc}"
            ) from exc
