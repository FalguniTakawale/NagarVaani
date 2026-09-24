"""
Speech-to-text.
Claude has no audio input, so voice notes (web mic recording or Telegram
voice messages) go through OpenAI's Whisper API before entering the normal
filter -> classify -> score pipeline in ai_engine.py.
"""

import io

from app.config import get_settings

settings = get_settings()


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> dict:
    """
    Returns: {text, language}
    Fails open (empty transcript) if no API key is configured or the call fails,
    matching the fail-open pattern already used in ai_engine.py.
    """
    if not settings.openai_api_key:
        return {"text": "", "language": None, "error": "STT unavailable — OPENAI_API_KEY not configured"}

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )
        return {"text": result.text, "language": getattr(result, "language", None)}
    except Exception as e:
        return {"text": "", "language": None, "error": str(e)}
