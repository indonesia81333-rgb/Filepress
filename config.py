from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    filepress_api_key: str
    filepress_api_url: str
    filepress_base_url: str
    gdrive_service_account_file: str
    gdrive_folder_id: str
    download_dir: Path
    max_telegram_file_size: int
    port: int
    database_path: Path


settings = Settings(
    api_id=_int_env("API_ID", 0),
    api_hash=_required("API_HASH"),
    bot_token=_required("BOT_TOKEN"),
    filepress_api_key=_required("FILEPRESS_API_KEY"),
    filepress_api_url=os.getenv(
        "FILEPRESS_API_URL",
        "https://api.filebee.top/api/v1/file/add",
    ).strip().rstrip("/"),
    filepress_base_url=os.getenv("FILEPRESS_BASE_URL", "https://filepress.live").strip().rstrip("/"),
    gdrive_service_account_file=os.getenv("GDRIVE_SERVICE_ACCOUNT_FILE", "service-account.json").strip(),
    gdrive_folder_id=os.getenv("GDRIVE_FOLDER_ID", "").strip(),
    download_dir=Path(os.getenv("DOWNLOAD_DIR", "downloads")).resolve(),
    # Pyrogram/MTProto's documented bot-side ceiling is approximately 2000 MiB.
    max_telegram_file_size=_int_env("TELEGRAM_MAX_FILE_SIZE_BYTES", 2_097_152_000),
    port=_int_env("PORT", 8080),
    database_path=Path(os.getenv("DATABASE_PATH", "data/uploads.sqlite3")).resolve(),
)

settings.download_dir.mkdir(parents=True, exist_ok=True)
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
