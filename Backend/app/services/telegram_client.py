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


_SECRET_RE = None


async def register_webhook(public_base_url: str) -> str:
    """Point Telegram at this server's /api/telegram/webhook, so no manual
    `setWebhook` browser/curl step is needed after each deploy or token change.

    Idempotent (skips if already pointing here) and best-effort: returns a short
    status string for the log and never raises, so a Telegram outage can't stop the
    site from starting. The bot token is never logged."""
    import re
    global _SECRET_RE
    if not is_configured():
        return "skipped: TELEGRAM_BOT_TOKEN not set"
    secret = settings.telegram_webhook_secret
    if not secret:
        return "skipped: TELEGRAM_WEBHOOK_SECRET not set (the webhook would be unauthenticated)"
    _SECRET_RE = _SECRET_RE or re.compile(r"^[A-Za-z0-9_-]{1,256}$")
    if not _SECRET_RE.match(secret):
        return "skipped: TELEGRAM_WEBHOOK_SECRET may only contain letters, numbers, _ and - (Telegram's rule)"
    base = (public_base_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        return "skipped: no public https URL (set FRONTEND_URL)"
    target = f"{base}/api/telegram/webhook"
    api = TELEGRAM_API.format(token=settings.telegram_bot_token)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            info = (await client.get(f"{api}/getWebhookInfo")).json()
            if not info.get("ok"):
                return f"failed: Telegram rejected the token ({info.get('description', 'unknown error')})"
            if info.get("result", {}).get("url") == target:
                return f"already registered at {target}"
            r = (await client.post(f"{api}/setWebhook", data={
                "url": target, "secret_token": secret, "allowed_updates": '["message"]',
            })).json()
        return f"registered at {target}" if r.get("ok") else f"failed: {r.get('description', 'unknown error')}"
    except Exception as e:  # noqa: BLE001
        return f"failed: {type(e).__name__}"
