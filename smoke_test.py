from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory

from database import UploadDatabase
from services.filepress import _find_filepress_id, _find_url


def main() -> None:
    assert _find_filepress_id({"data": {"_id": "file123456789"}}) == "file123456789"
    assert _find_filepress_id({"id": "file123456789"}) == "file123456789"
    assert _find_url({"data": {"url": "https://filepress.live/file/demo"}}) == "https://filepress.live/file/demo"

    with TemporaryDirectory() as tmp:
        db = UploadDatabase(Path(tmp) / "test.sqlite3")
        db.add_upload(10, "demo.mp4", 1234, "drive_id_123", "fp_id_456", "https://filepress.live/file/fp_id_456")
        rows = db.list_uploads(10)
        assert len(rows) == 1
        assert rows[0]["file_name"] == "demo.mp4"
        assert rows[0]["share_url"].endswith("fp_id_456")

    print("Smoke tests passed")


if __name__ == "__main__":
    main()
