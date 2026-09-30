from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, status

from app.services.media_storage import upload_image
from app.services.stt import transcribe_audio
from app.services.rate_limit import check_rate_limit, client_ip, seconds_until_reset

router = APIRouter(tags=["media"])

# Both endpoints are reachable without login (anonymous complaints can carry
# a photo/voice note), so — same reasoning as /complaints and /chatbot — the
# only thing standing between this and a free way to burn Cloudinary/Whisper
# quota or memory-exhaust the process is a per-IP cap plus a hard size limit.
UPLOAD_LIMIT = 15           # per IP
UPLOAD_WINDOW = 60 * 60     # one hour

MAX_AUDIO_BYTES = 15 * 1024 * 1024   # 15MB — a few minutes of voice note
MAX_IMAGE_BYTES = 8 * 1024 * 1024    # 8MB — a phone photo, generously

_AUDIO_CONTENT_PREFIXES = ("audio/", "video/webm")  # browsers sometimes tag audio-only webm as video/webm


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Reads at most max_bytes+1 so an oversized upload is caught without
    ever holding more than that much of it in memory."""
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {max_bytes // (1024 * 1024)}MB)",
        )
    return data


@router.post("/stt")
async def speech_to_text(audio: UploadFile, request: Request, language: Optional[str] = Form(None)):
    """Shared STT path for the web mic-recording upload — same Whisper call the Telegram voice-note path uses."""
    ip = client_ip(request)
    if not check_rate_limit("media_upload", ip, UPLOAD_LIMIT, UPLOAD_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads, try again later",
            headers={"Retry-After": str(seconds_until_reset("media_upload", ip, UPLOAD_WINDOW))},
        )

    content_type = audio.content_type or ""
    if not content_type.startswith(_AUDIO_CONTENT_PREFIXES):
        raise HTTPException(status_code=400, detail="File doesn't look like an audio recording")

    audio_bytes = await _read_capped(audio, MAX_AUDIO_BYTES)
    result = await transcribe_audio(audio_bytes, filename=audio.filename or "voice.webm", language=language)
    return result


@router.post("/media/upload")
async def upload_photo(file: UploadFile, request: Request):
    """Uploads one complaint photo/360° image to Cloudinary. Called once per
    selected file from the submit form; the frontend collects the returned
    URLs (with captions + is_360 flag) into ComplaintCreate.images."""
    ip = client_ip(request)
    if not check_rate_limit("media_upload", ip, UPLOAD_LIMIT, UPLOAD_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads, try again later",
            headers={"Retry-After": str(seconds_until_reset("media_upload", ip, UPLOAD_WINDOW))},
        )

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File doesn't look like an image")

    file_bytes = await _read_capped(file, MAX_IMAGE_BYTES)
    result = await upload_image(file_bytes, filename=file.filename or "complaint.jpg")
    return result
