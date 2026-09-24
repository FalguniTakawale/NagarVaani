from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.ai_engine import translate_text

router = APIRouter(tags=["translate"])


class TranslateAnyRequest(BaseModel):
    text: str
    target_language: str = "en"


@router.post("/translate")
async def translate_any(payload: TranslateAnyRequest):
    """Translate arbitrary text (a comment, a snippet) — same Claude path as
    /complaints/{id}/translate but without needing a complaint id."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to translate")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Text too long to translate (max 4000 characters)")
    result = await translate_text(text, payload.target_language or "en")
    return {
        "translated": result.get("translated", text),
        "detected_language": result.get("detected_language"),
        "target_language": payload.target_language or "en",
    }
