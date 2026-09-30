"""
Speech-to-text.
Claude/Gemini have no audio input in this pipeline, so voice notes (web mic
recording or Telegram voice messages) go through a hosted Whisper model
before entering the normal filter -> classify -> score pipeline in
ai_engine.py.

The provider is chosen automatically from whichever key is configured, in this
order: GROQ_API_KEY (free, fastest, no cold starts — recommended for demos),
HUGGINGFACE_API_KEY (free, but cold starts of 10-20s), OPENAI_API_KEY. Set
STT_PROVIDER=groq|huggingface|openai to force one. With no key set, voice notes
return a clear error and everything else keeps working.
"""

import asyncio

import httpx

from app.config import get_settings

settings = get_settings()

def _pick_provider() -> str | None:
    forced = (getattr(settings, "stt_provider", "") or "").lower()
    keys = {"groq": settings.groq_api_key, "huggingface": settings.huggingface_api_key, "openai": settings.openai_api_key}
    if forced in keys and keys[forced]:
        return forced
    for name in ("groq", "huggingface", "openai"):
        if keys[name]:
            return name
    return None


HF_MODEL = "openai/whisper-large-v3"
GROQ_MODEL = "whisper-large-v3-turbo"
OPENAI_MODEL = "whisper-1"

# Python's stdlib mimetypes module gets these wrong for our purposes —
# .webm maps to "video/webm" (we only ever send audio-only blobs from the
# browser's MediaRecorder) and .wav maps to the nonstandard "audio/x-wav".
# HF's router needs the exact Content-Type to match the audio or it fails
# with a generic, unhelpful "Internal Error" — it does not sniff the bytes.
_AUDIO_CONTENT_TYPES = {
    ".ogg": "audio/ogg",    # Telegram voice notes (opus-in-ogg)
    ".webm": "audio/webm",  # web mic recording (MediaRecorder default)
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


def _guess_audio_content_type(filename: str) -> str:
    for ext, content_type in _AUDIO_CONTENT_TYPES.items():
        if filename.lower().endswith(ext):
            return content_type
    return "audio/wav"  # reasonable default; most callers pass a known extension anyway


async def _transcribe_huggingface(audio_bytes: bytes, filename: str) -> dict:
    if not settings.huggingface_api_key:
        return {"text": "", "language": None, "error": "STT unavailable — HUGGINGFACE_API_KEY not configured"}

    url = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"
    content_type = _guess_audio_content_type(filename)
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}", "Content-Type": content_type}

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(2):  # one retry for the free-tier cold-start case
            try:
                resp = await client.post(url, headers=headers, content=audio_bytes)
                data = resp.json()
            except Exception as e:
                return {"text": "", "language": None, "error": f"HF request failed: {e}"}

            if resp.status_code == 200 and isinstance(data, dict) and "text" in data:
                return {"text": data["text"].strip(), "language": None}

            # Model still loading on the free tier — wait the time HF tells us
            # (capped so one slow call can't hang the whole request) and retry once.
            if resp.status_code == 503 and attempt == 0:
                wait_s = min(float(data.get("estimated_time", 10)), 20)
                await asyncio.sleep(wait_s)
                continue

            return {"text": "", "language": None, "error": data.get("error", f"HF error {resp.status_code}")}

    return {"text": "", "language": None, "error": "HF model still loading — try again in a moment"}


async def _transcribe_openai_compatible(audio_bytes: bytes, filename: str, provider: str) -> dict:
    import io

    api_key = settings.groq_api_key if provider == "groq" else settings.openai_api_key
    if not api_key:
        provider_name = "GROQ_API_KEY" if provider == "groq" else "OPENAI_API_KEY"
        return {"text": "", "language": None, "error": f"STT unavailable — {provider_name} not configured"}

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1" if provider == "groq" else None,
        )
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        result = await client.audio.transcriptions.create(
            model=GROQ_MODEL if provider == "groq" else OPENAI_MODEL,
            file=audio_file,
        )
        return {"text": result.text, "language": getattr(result, "language", None)}
    except Exception as e:
        return {"text": "", "language": None, "error": str(e)}


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> dict:
    """
    Returns: {text, language}
    Fails open (empty transcript) if no API key is configured or the call fails,
    matching the fail-open pattern already used in ai_engine.py.
    """
    provider = _pick_provider()
    if provider is None:
        return {"text": "", "language": None,
                "error": "Voice notes are not set up on this server — add GROQ_API_KEY (free) or HUGGINGFACE_API_KEY"}
    if provider == "huggingface":
        return await _transcribe_huggingface(audio_bytes, filename)
    return await _transcribe_openai_compatible(audio_bytes, filename, provider)
