"""
Thin wrapper over the Telegram Bot API. No third-party bot framework needed —
just three HTTP calls: send a reply, resolve a file_id to a path, download it.
No approval step, unlike WhatsApp Cloud API — a bot token from @BotFather is
enough to receive text and voice messages immediately.
"""

import httpx

from app.config import get_settings

settings = get_settings()

TELEGRAM_API = "https://api.telegram.org/bot{token}"
TELEGRAM_FILE_API = "https://api.telegram.org/file/bot{token}"


def is_configured() -> bool:
    return bool(settings.telegram_bot_token)


_bot_username: str | None = None  # cached after the first getMe call


async def get_bot_username() -> str | None:
    """Fetched from Telegram rather than hardcoded/config'd, so a bot swap
    doesn't need a code change — just re-links naturally on next call."""
    global _bot_username
    if _bot_username or not is_configured():
        return _bot_username
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/getMe"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            _bot_username = resp.json()["result"]["username"]
        except httpx.HTTPError:
            return None
    return _bot_username


async def send_message(chat_id: int | str, text: str) -> None:
    if not is_configured():
        return
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError:
            pass  # best-effort — a failed reply shouldn't fail the whole webhook


async def download_telegram_file(file_id: str) -> bytes | None:
    """Generic file_id -> bytes fetch. Works for voice notes, photos, or
    anything else Telegram hands us a file_id for — the getFile/download
    dance is identical regardless of media type."""
    if not is_configured():
        return None
    base = TELEGRAM_API.format(token=settings.telegram_bot_token)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{base}/getFile", params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        file_url = f"{TELEGRAM_FILE_API.format(token=settings.telegram_bot_token)}/{file_path}"
        file_resp = await client.get(file_url)
        file_resp.raise_for_status()
        return file_resp.content


# Old name kept as an alias — telegram.py's voice-note path already calls this.
download_voice_file = download_telegram_file
