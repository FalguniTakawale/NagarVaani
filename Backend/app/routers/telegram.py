"""
Telegram ingestion channel — text or voice note in, scored complaint out,
using the exact same filter/classify/score pipeline as the web form.
Chosen over WhatsApp Cloud API for the hackathon build: no Meta Business
verification queue, a bot token from @BotFather works immediately.
"""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.models import Complaint, ComplaintStatus, User
from app.services.ai_engine import process_complaint_pipeline
from app.services.stt import transcribe_audio
from app.services.telegram_client import download_voice_file, send_message

router = APIRouter(prefix="/telegram", tags=["telegram"])
settings = get_settings()


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


@router.post("/webhook")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    _verify_webhook_secret(request)
    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}  # ignore non-message updates (edits, reactions, etc.)

    chat_id = message["chat"]["id"]

    # Resolve the sender's account, if their Telegram is already linked
    result = await db.execute(select(User).where(User.telegram_chat_id == str(chat_id)))
    user = result.scalar_one_or_none()

    text = None
    if "voice" in message:
        await send_message(chat_id, "Got your voice note — transcribing…")
        audio_bytes = await download_voice_file(message["voice"]["file_id"])
        if audio_bytes is None:
            await send_message(chat_id, "Couldn't download that voice note. Please try again.")
            return {"ok": True}
        stt_result = await transcribe_audio(audio_bytes, filename="voice.ogg")
        text = stt_result.get("text", "")
        if not text:
            await send_message(
                chat_id,
                "Sorry, I couldn't transcribe that voice note "
                f"({stt_result.get('error', 'unknown error')}). Try sending it as text instead.",
            )
            return {"ok": True}
    elif "text" in message:
        text = message["text"]

    if not text:
        await send_message(chat_id, "Send a text message or a voice note describing the civic issue.")
        return {"ok": True}

    ai_result = await process_complaint_pipeline(
        text=text,
        location="",
        population=10000,
        vote_count=0,
        linked_area_count=0,
    )

    if not ai_result.get("passed"):
        reply = f"This couldn't be published: {ai_result.get('filter_reason')}"
        if ai_result.get("suggested_rephrasing"):
            reply += f"\n\nTry rephrasing: \"{ai_result['suggested_rephrasing']}\""
        await send_message(chat_id, reply)
        return {"ok": True}

    complaint = Complaint(
        author_id=user.id if user else None,
        text_original=text,
        text_translated=ai_result.get("text_translated"),
        detected_language=ai_result.get("detected_language"),
        category=ai_result.get("category"),
        location_text=ai_result.get("location_hint"),
        ward=user.ward if user else None,
        area=user.area if user else None,
        city=user.city if user else None,
        state=user.state if user else None,
        priority_score=ai_result.get("priority_score", 0),
        score_breakdown=ai_result.get("score_breakdown", {}),
        is_safety_risk=ai_result.get("is_safety_risk", False),
        seasonal_multiplier=ai_result.get("seasonal_multiplier", 1.0),
        source_channel="telegram",
        status=ComplaintStatus.open,
        is_ai_filtered=True,
        official_brief=ai_result.get("official_brief"),
        recommended_action=ai_result.get("recommended_action"),
    )
    db.add(complaint)
    await db.flush()

    reply = (
        f"✓ Complaint recorded — priority score {ai_result['priority_score']}/100 "
        f"({ai_result.get('category', 'other')}).\n"
        f"Complaint ID: {complaint.id[:8]}"
    )
    if not user:
        reply += "\n\nLink your Telegram to a NagarVaani account on the website to track status updates here."
    await send_message(chat_id, reply)

    return {"ok": True}
