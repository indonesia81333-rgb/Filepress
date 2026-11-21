# FilePress Telegram Uploader

An asynchronous Telegram file uploader built with **Pyrofork (Pyrogram-compatible MTProto)**. It downloads Telegram media with live progress, uploads it to Google Drive using resumable chunks, registers the Drive file ID with FilePress, and replies with a shareable FilePress link.

## Features

- Async Telegram handlers using Pyrofork / MTProto.
- Documents, videos, audio, photos, animations, voice notes, video notes and stickers.
- Live Telegram download progress and Google Drive upload progress.
- Google Drive resumable upload with public-reader link permission.
- FilePress API publishing and share-link generation.
- `/publish_drive` for an existing Google Drive file, including files larger than the Telegram bot transfer limit.
- `/myuploads` history stored in SQLite.
- `/health` endpoint for container/service health checks.
- Docker, Render worker and Procfile deployment files.

## Important: 4 GB support boundary

The FilePress API endpoint currently documented for this integration is a **registration/publishing endpoint** that accepts a Google Drive file ID and API key (`{"key": "...", "id": "..."}`). It is not documented as a raw multipart file-upload endpoint.

The Pyrogram/Pyrofork documentation describes MTProto bot uploads/downloads up to about **2000 MiB**. This project therefore rejects Telegram media above the configured Telegram bot-side limit instead of pretending that changing a variable enables 4 GB bot transfers.

For a 4 GB file, upload it directly to Google Drive first, make it accessible to FilePress (and to the configured service account if you use `/publish_drive` metadata lookup), then run:

```text
/publish_drive DRIVE_FILE_ID
```

This lets the bot publish a pre-existing large Drive file without routing the 4 GB bytes through Telegram. Actual availability and file-size limits remain subject to Google Drive and FilePress account/service limits.

## Requirements

- Python 3.10+ (Python 3.11 recommended)
- Telegram API ID and API hash from [my.telegram.org/apps](https://my.telegram.org/apps)
- Bot token from [@BotFather](https://t.me/BotFather)
- FilePress API key
- Google Cloud project with Google Drive API enabled
- Google service-account JSON credentials
- A Google Shared Drive (recommended) where the service account has permission to create files

## Google Drive setup

1. Enable **Google Drive API** in Google Cloud Console.
2. Create a service account and download its JSON key.
3. Put the JSON file beside `bot.py` as `service-account.json` (or change `GDRIVE_SERVICE_ACCOUNT_FILE`).
4. Create a Shared Drive and add the service-account email as a Content manager or equivalent role.
5. Set `GDRIVE_FOLDER_ID` to the destination folder ID if you want a specific folder. Leave it blank to use the service account's default Drive location.

The bot makes uploaded files publicly readable (`anyone` / `reader`) before publishing them. Do not use this on confidential files.

## Install and run

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, place `service-account.json` in the project directory, then run:

```bash
python bot.py
```

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `API_ID` | Yes | Telegram application ID |
| `API_HASH` | Yes | Telegram application hash |
| `BOT_TOKEN` | Yes | Bot token from BotFather |
| `FILEPRESS_API_KEY` | Yes | FilePress API key |
| `FILEPRESS_API_URL` | No | FilePress registration endpoint; default is `https://api.filebee.top/api/v1/file/add` |
| `FILEPRESS_BASE_URL` | No | Share-link base domain; default is `https://filepress.live` |
| `GDRIVE_SERVICE_ACCOUNT_FILE` | Yes for uploads | Path to Google service-account JSON |
| `GDRIVE_FOLDER_ID` | No | Drive destination folder ID |
| `TELEGRAM_MAX_FILE_SIZE_BYTES` | No | Bot-side Telegram cap; default 2,097,152,000 bytes |
| `DOWNLOAD_DIR` | No | Temporary download directory |
| `DATABASE_PATH` | No | SQLite database path |
| `PORT` | No | Health-check HTTP port; default 8080 |

## Bot commands

- `/start` or `/help` — usage instructions.
- `/status` — bot status and configured Telegram file limit.
- `/myuploads` — latest 10 published links for the current user.
- `/publish_drive DRIVE_FILE_ID` — publish an existing Google Drive file. A normal Drive file URL can also be passed.

To upload a normal Telegram file, simply send it to the bot. The bot will show download and cloud-upload progress, then return an **Open / Download** FilePress button.

## FilePress API compatibility

The known endpoint accepts a JSON body with the `key` and Google Drive `id` fields. FilePress domains can change; keep `FILEPRESS_API_URL` and `FILEPRESS_BASE_URL` configurable. If FilePress changes its endpoint or response schema, update `services/filepress.py` accordingly. The bot does not silently claim that a Drive-only upload is a FilePress-native binary upload.

## Deployment

### Docker

```bash
docker build -t filepress-telegram-bot .
docker run --env-file .env \\
  -v "$PWD/service-account.json:/app/service-account.json:ro" \\
  -v "$PWD/data:/app/data" \\
  -v "$PWD/downloads:/app/downloads" \\
  filepress-telegram-bot
```

### Render

Create a **Background Worker** from this repository using the included `render.yaml` / Dockerfile. Add the variables from `.env` in Render's Environment section, and make the Google service-account JSON available as a secret file at the configured path. Use a persistent disk for `/app/data` if you want upload history to survive restarts. Temporary downloads are deleted after each transfer.

### VPS / Termux

Run `pip install -r requirements.txt`, create `.env`, add the service-account JSON file, then run `python bot.py`. Use `tmux` or `systemd` on a VPS to keep the process alive.

## Security notes

- Never publish `.env`, `service-account.json`, or Pyrogram session files to GitHub.
- Rotate the bot token/API credentials immediately if they are exposed.
- This bot makes uploaded Drive files publicly readable to enable sharing. Do not upload private or copyrighted files unless you have permission to distribute them.
- Use HTTPS and restrict access to the host where the bot runs.
