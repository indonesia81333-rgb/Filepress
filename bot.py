from __future__ import annotations

import asyncio
import html
import logging
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path

from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import settings
from database import UploadDatabase
from services.filepress import FilePressClient, FilePressError
from services.google_drive import GoogleDriveError, get_file_metadata, upload_file

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("filepress_bot")

app = Client(
    "filepress_telegram_bot",
    api_id=settings.api_id,
    api_hash=settings.api_hash,
    bot_token=settings.bot_token,
    workers=16,
    sleep_threshold=60,
    max_concurrent_transmissions=2,
)

database = UploadDatabase(settings.database_path)
filepress = FilePressClient(
    settings.filepress_api_url,
    settings.filepress_api_key,
    settings.filepress_base_url,
)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def get_media_details(message: Message) -> tuple[str, int]:
    media = (
        message.document
        or message.video
        or message.audio
        or message.animation
        or message.voice
        or message.video_note
        or message.sticker
        or message.photo
    )
    if not media:
        raise ValueError("No supported media was found in that message.")

    name = getattr(media, "file_name", None)
    if not name:
        mime = getattr(media, "mime_type", None) or "application/octet-stream"
        extension = mimetypes.guess_extension(mime) or ".bin"
        name = f"telegram_file_{message.id}{extension}"
    name = Path(name).name.replace("\x00", "")[:240]
    size = int(getattr(media, "file_size", 0) or 0)
    return name, size


async def edit_status(status: Message, text: str) -> None:
    try:
        await status.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as exc:
        LOGGER.debug("Progress edit skipped: %s", exc)


async def progress_callback(current: int, total: int, status: Message, state: dict) -> None:
    now = time.monotonic()
    if current < total and now - state.get("last", 0) < 2.0:
        return
    state["last"] = now
    percent = (current / total * 100) if total else 0
    bar_size = 12
    filled = int(bar_size * percent / 100)
    bar = "█" * filled + "░" * (bar_size - filled)
    await edit_status(
        status,
        f"<b>Downloading from Telegram</b>\n<code>{bar}</code> {percent:.1f}%\n"
        f"{human_size(current)} / {human_size(total)}",
    )


async def drive_progress_callback(status: Message, percent: float, state: dict) -> None:
    now = time.monotonic()
    if percent < 1 and now - state.get("last", 0) < 2.0:
        return
    state["last"] = now
    value = max(0, min(100, percent * 100))
    bar_size = 12
    filled = int(bar_size * value / 100)
    bar = "█" * filled + "░" * (bar_size - filled)
    await edit_status(status, f"<b>Uploading to Google Drive</b>\n<code>{bar}</code> {value:.1f}%")


async def publish_drive_id(user_id: int, drive_file_id: str, file_name: str, file_size: int) -> tuple[str, str | None]:
    link, filepress_id, _response = await filepress.publish_drive_file(drive_file_id)
    await asyncio.to_thread(
        database.add_upload,
        user_id,
        file_name,
        file_size,
        drive_file_id,
        filepress_id,
        link,
    )
    return link, filepress_id


@app.on_message(filters.private & filters.command(["start", "help"]))
async def start_handler(_client: Client, message: Message) -> None:
    text = (
        "<b>FilePress Telegram Uploader</b>\n\n"
        "Send me a document, video, audio, photo, animation, voice note or other Telegram media. "
        "I will transfer it to Google Drive, publish the Drive file through FilePress, and return a share link.\n\n"
        "<b>Commands</b>\n"
        "/start — Start the bot\n"
        "/help — Show help\n"
        "/publish_drive DRIVE_FILE_ID — Publish an existing Drive file\n"
        "/myuploads — Show your latest 10 links\n"
        "/status — Check bot status\n\n"
        "<b>4 GB note:</b> Telegram bot-side MTProto uploads are documented up to about 2000 MiB. "
        "For a 4 GB file, upload it directly to Google Drive first, then use /publish_drive."
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@app.on_message(filters.private & filters.command("status"))
async def status_handler(_client: Client, message: Message) -> None:
    await message.reply_text(
        "<b>Bot status:</b> Online\n"
        f"<b>Telegram file limit:</b> {human_size(settings.max_telegram_file_size)}\n"
        f"<b>FilePress API:</b> <code>{html.escape(settings.filepress_api_url)}</code>",
        parse_mode=ParseMode.HTML,
    )


@app.on_message(filters.private & filters.command("publish_drive"))
async def publish_drive_handler(_client: Client, message: Message) -> None:
    if len(message.command) < 2:
        await message.reply_text(
            "Usage: <code>/publish_drive DRIVE_FILE_ID</code>\n"
            "The Drive file must be accessible to FilePress. For service-account metadata checks, share it with the configured service-account email.",
            parse_mode=ParseMode.HTML,
        )
        return

    raw = message.command[1].strip()
    match = re.search(r"(?:/file/d/|id=)([A-Za-z0-9_-]{10,})", raw)
    drive_file_id = match.group(1) if match else raw
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", drive_file_id):
        await message.reply_text("That does not look like a valid Google Drive file ID or URL.")
        return

    status = await message.reply_text("Checking Google Drive file and publishing to FilePress…")
    try:
        metadata = await asyncio.to_thread(
            get_file_metadata,
            drive_file_id,
            settings.gdrive_service_account_file,
        )
        file_name = str(metadata.get("name") or f"GoogleDrive_{drive_file_id}")
        file_size = int(metadata.get("size") or 0)
        link, _ = await publish_drive_id(message.from_user.id, drive_file_id, file_name, file_size)
        await status.edit_text(
            f"<b>Published successfully</b>\n\n"
            f"<b>File:</b> {html.escape(file_name)}\n"
            f"<b>Size:</b> {human_size(file_size)}\n\n"
            f"<b>Share link:</b> {html.escape(link)}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open FilePress link", url=link)]]),
            disable_web_page_preview=True,
        )
    except (GoogleDriveError, FilePressError) as exc:
        await status.edit_text(f"<b>Publish failed</b>\n{html.escape(str(exc))}", parse_mode=ParseMode.HTML)
    except Exception:
        LOGGER.exception("Drive publish command failed")
        await status.edit_text("Something went wrong while publishing. Check the server log.")


@app.on_message(filters.private & filters.command("myuploads"))
async def myuploads_handler(_client: Client, message: Message) -> None:
    rows = await asyncio.to_thread(database.list_uploads, message.from_user.id, 10)
    if not rows:
        await message.reply_text("You do not have any published uploads yet.")
        return
    lines = ["<b>Your latest uploads</b>"]
    buttons = []
    for index, item in enumerate(rows, 1):
        name = html.escape(item["file_name"])
        size = human_size(int(item["file_size"] or 0))
        url = item["share_url"]
        lines.append(f"{index}. <b>{name}</b> — {size}\n{html.escape(url)}")
        buttons.append([InlineKeyboardButton(f"{index}. Open {item['file_name'][:35]}", url=url)])
    await message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


@app.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.photo
        | filters.animation
        | filters.voice
        | filters.video_note
        | filters.sticker
    )
)
async def media_handler(_client: Client, message: Message) -> None:
    try:
        file_name, file_size = get_media_details(message)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return

    if file_size and file_size > settings.max_telegram_file_size:
        await message.reply_text(
            "<b>This file is larger than the Telegram bot transfer limit.</b>\n\n"
            f"File size: {human_size(file_size)}\n"
            f"Bot-side limit: {human_size(settings.max_telegram_file_size)}\n\n"
            "For files up to 4 GB, upload the file to Google Drive directly, share it with the configured service-account email, "
            "then send <code>/publish_drive DRIVE_FILE_ID</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    service_account_path = Path(settings.gdrive_service_account_file)
    if not service_account_path.is_file():
        await message.reply_text(
            "Google Drive storage is not configured. Add your service-account JSON file and set "
            "<code>GDRIVE_SERVICE_ACCOUNT_FILE</code> in the environment.",
            parse_mode=ParseMode.HTML,
        )
        return

    status = await message.reply_text(
        f"<b>Preparing upload</b>\n{html.escape(file_name)}\n{human_size(file_size)}"
    )
    file_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="fp_upload_",
            suffix=Path(file_name).suffix,
            dir=settings.download_dir,
            delete=False,
        ) as temp_file:
            file_path = Path(temp_file.name)

        download_state = {"last": 0.0}

        async def download_progress(current: int, total: int) -> None:
            await progress_callback(current, total, status, download_state)

        await app.download_media(
            message,
            file_name=str(file_path),
            progress=download_progress,
        )

        if not file_path.exists() or file_path.stat().st_size == 0:
            raise RuntimeError("Telegram download completed without creating a file.")
        actual_size = file_path.stat().st_size
        if actual_size > settings.max_telegram_file_size:
            raise RuntimeError(
                f"Downloaded file exceeded the configured Telegram limit ({human_size(actual_size)})."
            )

        await edit_status(status, "<b>Telegram download complete.</b> Starting resumable Google Drive upload…")
        loop = asyncio.get_running_loop()
        drive_state = {"last": 0.0}

        def drive_progress(percent: float) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(drive_progress_callback(status, percent, drive_state))
            )

        metadata = await asyncio.to_thread(
            upload_file,
            file_path,
            file_name,
            settings.gdrive_service_account_file,
            settings.gdrive_folder_id,
            drive_progress,
        )
        drive_file_id = str(metadata["id"])
        uploaded_size = int(metadata.get("size") or actual_size)

        await edit_status(status, "<b>Google Drive upload complete.</b> Publishing share link through FilePress…")
        link, filepress_id = await publish_drive_id(
            message.from_user.id,
            drive_file_id,
            file_name,
            uploaded_size,
        )

        await status.edit_text(
            "<b>Upload complete!</b>\n\n"
            f"<b>File:</b> {html.escape(file_name)}\n"
            f"<b>Size:</b> {human_size(uploaded_size)}\n"
            "<b>Storage:</b> Google Drive → FilePress\n\n"
            f"<b>Share link:</b> {html.escape(link)}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Open / Download", url=link)]]
            ),
            disable_web_page_preview=True,
        )
    except (GoogleDriveError, FilePressError) as exc:
        LOGGER.warning("Upload service error: %s", exc)
        await edit_status(status, f"<b>Upload failed</b>\n{html.escape(str(exc))}")
    except Exception as exc:
        LOGGER.exception("Media upload failed")
        await edit_status(status, f"<b>Upload failed</b>\n{html.escape(str(exc)[:900])}")
    finally:
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                LOGGER.warning("Could not remove temporary file: %s", file_path)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "filepress-telegram-bot"})


async def main() -> None:
    runner = web.AppRunner(web.Application())
    runner.app.router.add_get("/health", health)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.port)
    await site.start()

    await app.start()
    me = await app.get_me()
    LOGGER.info("Bot started as @%s (id=%s)", me.username, me.id)
    try:
        await idle()
    finally:
        await app.stop()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("Bot stopped")
