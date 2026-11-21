from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class UploadDatabase:
    def __init__(self, path: Path):
        self.path = path
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    drive_file_id TEXT NOT NULL,
                    filepress_id TEXT,
                    share_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, id DESC)")

    def add_upload(
        self,
        user_id: int,
        file_name: str,
        file_size: int,
        drive_file_id: str,
        filepress_id: str | None,
        share_url: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO uploads
                (user_id, file_name, file_size, drive_file_id, filepress_id, share_url)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, file_name, file_size, drive_file_id, filepress_id, share_url),
            )

    def list_uploads(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM uploads WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


# Database writes are small local transactions; each call opens its own connection.
