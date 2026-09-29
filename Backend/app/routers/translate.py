from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.ai_engine import translate_text
from app.services.rate_limit import check_rate_limit, client_ip

router = APIRouter(tags=["translate"])


class TranslateAnyRequest(BaseModel):
    text: str
    target_language: str = "en"


@router.post("/translate")
async def translate_any(payload: TranslateAnyRequest, request: Request):
    """Translate arbitrary text (a comment, a snippet) — same Claude path as
    /complaints/{id}/translate but without needing a complaint id."""
    if not check_rate_limit("translate", client_ip(request), 30, 60 * 10):
        raise HTTPException(status_code=429, detail="Too many translations — slow down a little")
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to translate")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Text too long to translate (max 4000 characters)")
    result = await translate_text(text, payload.target_language or "en")
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail="Translation is temporarily unavailable — please try again shortly")
    return {
        "translated": result.get("translated", text),
        "detected_language": result.get("detected_language"),
        "romanized": bool(result.get("romanized")),
        "target_language": payload.target_language or "en",
    }
