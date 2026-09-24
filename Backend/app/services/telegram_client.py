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


async def send_message(chat_id: int | str, text: str) -> None:
    if not is_configured():
        return
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError:
            pass  # best-effort — a failed reply shouldn't fail the whole webhook


async def download_voice_file(file_id: str) -> bytes | None:
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
