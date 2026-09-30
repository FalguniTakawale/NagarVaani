"""
Telegram ingestion channel — text or voice note in, scored complaint out,
using the exact same filter/classify/score pipeline as the web form, but
as a short back-and-forth rather than a single message: if the sender isn't
a linked account with a known area, the bot asks which area this is about,
then whether they'd like to attach a photo, before finalizing.

State: an in-memory dict of "what are we waiting for from this chat" keyed
by chat_id. Simple and enough for a hackathon build — it resets if the
process restarts (which --reload does on every code change in dev), but a
half-finished draft losing state on redeploy is an acceptable trade-off
here; nothing is written to the DB until the draft is actually finalized.
"""

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.models import Complaint, ComplaintStatus, User
from app.services.ai_engine import (
    classify_complaint, filter_complaint, generate_official_brief, score_complaint,
)
from app.services.media_storage import upload_image
from app.services.stt import transcribe_audio
from app.services.telegram_client import download_telegram_file, send_message

router = APIRouter(prefix="/telegram", tags=["telegram"])
settings = get_settings()

# chat_id (str) -> draft dict. See _finalize_complaint for the shape once complete.
_pending: dict[str, dict] = {}

# Account-linking codes: code -> {"user_id": str, "expires_at": datetime}.
# Same in-memory, restart-loses-it trade-off as _pending above — a code is
# single-use and short-lived, so losing one just means generating a new one.
_link_codes: dict[str, dict] = {}
LINK_CODE_TTL = timedelta(minutes=10)


def create_link_code(user_id: str) -> str:
    """Called from the auth router when a logged-in user asks to link
    Telegram. Returns a short code they send the bot as /start <code>."""
    code = secrets.token_urlsafe(6)
    _link_codes[code] = {"user_id": user_id, "expires_at": datetime.now(timezone.utc) + LINK_CODE_TTL}
    return code


def _verify_webhook_secret(request: Request) -> None:
    """Telegram echoes the secret_token given to setWebhook in this header.
    Reject anything else with a bare 403 — no hint about what was expected."""
    expected = settings.telegram_webhook_secret
    if not expected:
        if settings.environment.lower() == "development":
            return  # unsecured local testing (e.g. curl) is fine
        raise HTTPException(status_code=403)
    provided = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403)


async def _finalize_complaint(db: AsyncSession, chat_id, user: User | None, draft: dict) -> None:
    """Score, brief, and save a draft that now has everything it needs (area
    resolved, photo step answered one way or another), then reply."""
    score_result = await score_complaint(
        text=draft["text"], category=draft["category"], is_safety_risk=draft["is_safety_risk"],
        population=10000, linked_area_count=0, vote_count=0,
    )
    area_text = draft.get("area")
    brief_result = await generate_official_brief(
        text_original=draft["text"], text_translated=draft.get("translated", draft["text"]),
        category=draft["category"], score=score_result["score"], score_breakdown=score_result["breakdown"],
        location=area_text or "Unknown location", linked_area_count=0,
    )

    complaint = Complaint(
        author_id=user.id if user else None,
        text_original=draft["text"],
        text_translated=draft.get("translated"),
        detected_language=draft.get("language"),
        category=draft["category"],
        location_text=area_text,
        ward=user.ward if user else None,
        area=(user.area if user and user.area else area_text),
        city=user.city if user else None,
        state=user.state if user else None,
        priority_score=score_result["score"],
        score_breakdown=score_result["breakdown"],
        is_safety_risk=draft["is_safety_risk"],
        seasonal_multiplier=score_result["breakdown"]["l2_seasonal_multiplier"],
        image_urls=draft.get("images") or [],
        source_channel="telegram",
        status=ComplaintStatus.open,
        is_ai_filtered=True,
        official_brief=brief_result.get("brief"),
        recommended_action=brief_result.get("recommended_action"),
    )
    db.add(complaint)
    await db.flush()

    reply = (
        f"✓ Complaint recorded — priority score {score_result['score']}/100 "
        f"({draft['category']}).\n"
        f"Complaint ID: {complaint.id}"
    )
    if area_text:
        reply += f"\n📍 Area: {area_text}"
    if draft.get("images"):
        reply += f"\n📸 {len(draft['images'])} photo(s) attached"
    if user:
        reply += "\n\nYou'll find this in \"My complaints\" on the website too."
    else:
        reply += (
            "\n\nYou're not linked to a NagarVaani account, so save this ID — it's the only way to "
            "check on this complaint later. Search it on the website's \"Track a complaint\" page."
        )
    await send_message(chat_id, reply)


@router.post("/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    _verify_webhook_secret(request)
    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}  # ignore non-message updates (edits, reactions, etc.)

    chat_id = message["chat"]["id"]
    chat_key = str(chat_id)

    # Resolve the sender's account, if their Telegram is already linked
    result = await db.execute(select(User).where(User.telegram_chat_id == chat_key))
    user = result.scalar_one_or_none()

    incoming_text = (message.get("text") or "").strip()

    # ── ACCOUNT LINKING — /start <code> from the website's deep link ────────
    if incoming_text.startswith("/start"):
        parts = incoming_text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else None
        if not code:
            await send_message(
                chat_id,
                "👋 Welcome to NagarVaani! Send a message describing a civic issue to report it.\n\n"
                "To link this chat to your NagarVaani account (so complaints use your registered "
                "area and you get status updates here), generate a link code from the website's "
                "\"Link Telegram\" option and tap that link instead.",
            )
            return {"ok": True}

        record = _link_codes.get(code)
        if not record or datetime.now(timezone.utc) > record["expires_at"]:
            _link_codes.pop(code, None)
            await send_message(chat_id, "That link code is invalid or expired — generate a new one from the website and try again.")
            return {"ok": True}

        link_user = (await db.execute(select(User).where(User.id == record["user_id"]))).scalar_one_or_none()
        if not link_user:
            await send_message(chat_id, "Couldn't find that account anymore — generate a new link code and try again.")
            del _link_codes[code]
            return {"ok": True}

        link_user.telegram_chat_id = chat_key
        del _link_codes[code]
        await db.flush()
        await send_message(
            chat_id,
            f"✓ Linked! This chat is now connected to {link_user.name}'s NagarVaani account.\n\n"
            "Complaints you send here will use your registered area automatically, and you'll "
            "get status updates on ones you submit from the website too.",
        )
        return {"ok": True}

    if incoming_text.lower() == "cancel" and chat_key in _pending:
        del _pending[chat_key]
        await send_message(chat_id, "Cancelled — nothing was saved.")
        return {"ok": True}

    pending = _pending.get(chat_key)

    # ── CONTINUING AN IN-PROGRESS DRAFT ──────────────────────────────────────
    if pending:
        if pending["step"] == "area":
            if not incoming_text:
                await send_message(chat_id, "Please reply with just the area/locality name as text (e.g. \"Baner, Pune\").")
                return {"ok": True}
            pending["area"] = incoming_text
            pending["step"] = "photo"
            await send_message(chat_id, "Got it. Want to add a photo of it? Send one now, or reply \"skip\".")
            return {"ok": True}

        if pending["step"] == "photo":
            if "photo" in message:
                largest = message["photo"][-1]  # Telegram lists smallest → largest
                photo_bytes = await download_telegram_file(largest["file_id"])
                if photo_bytes:
                    upload_result = await upload_image(photo_bytes, filename="telegram.jpg")
                    if upload_result.get("url"):
                        pending.setdefault("images", []).append(
                            {"url": upload_result["url"], "caption": None, "is_360": False}
                        )
                    else:
                        await send_message(chat_id, "Couldn't save that photo, continuing without it.")
            # A photo, "skip", or anything else here all finalize the complaint.
            draft = _pending.pop(chat_key)
            await _finalize_complaint(db, chat_id, user, draft)
            return {"ok": True}

    # ── NEW MESSAGE — START A COMPLAINT ──────────────────────────────────────
    text = incoming_text or None
    if "voice" in message:
        await send_message(chat_id, "Got your voice note — transcribing…")
        audio_bytes = await download_telegram_file(message["voice"]["file_id"])
        if audio_bytes is None:
            await send_message(chat_id, "Couldn't download that voice note. Please try again.")
            return {"ok": True}
        stt_result = await transcribe_audio(
            audio_bytes, filename="voice.ogg",
            language=getattr(user, "preferred_language", None) if user else None,
        )
        text = stt_result.get("text", "")
        if not text:
            await send_message(
                chat_id,
                "Sorry, I couldn't transcribe that voice note "
                f"({stt_result.get('error', 'unknown error')}). Try sending it as text instead.",
            )
            return {"ok": True}

    if not text:
        await send_message(chat_id, "Send a text message or a voice note describing the civic issue.")
        return {"ok": True}

    filter_result = await filter_complaint(text)
    if not filter_result.get("passed", True):
        reply = f"This couldn't be published: {filter_result.get('reason')}"
        if filter_result.get("suggested_rephrasing"):
            reply += f"\n\nTry rephrasing: \"{filter_result['suggested_rephrasing']}\""
        await send_message(chat_id, reply)
        return {"ok": True}

    classify_result = await classify_complaint(text)
    draft = {
        "text": text,
        "translated": classify_result.get("translated_text", text),
        "language": classify_result.get("detected_language", "en"),
        "category": classify_result.get("category", "other"),
        "is_safety_risk": classify_result.get("is_safety_risk", False),
        "images": [],
    }

    # A linked account with a known area skips the question entirely — we
    # already know where they are.
    known_area = user and (user.area or user.ward or user.city) if user else None
    if user and known_area:
        draft["area"] = user.area or (f"Ward {user.ward}" if user.ward else None) or user.city
        draft["step"] = "photo"
        _pending[chat_key] = draft
        await send_message(
            chat_id,
            f"Got it — using your registered area ({draft['area']}). "
            "Want to add a photo of it? Send one now, or reply \"skip\".",
        )
        return {"ok": True}

    draft["step"] = "area"
    _pending[chat_key] = draft
    prefix = "" if user else "You're not linked to a NagarVaani account, so I don't know your area yet. "
    await send_message(chat_id, f"{prefix}Which area/locality is this in? (e.g. \"Baner, Pune\")")
    return {"ok": True}
