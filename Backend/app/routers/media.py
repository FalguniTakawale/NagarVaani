from fastapi import APIRouter, UploadFile

from app.services.media_storage import upload_image
from app.services.stt import transcribe_audio

router = APIRouter(tags=["media"])


@router.post("/stt")
async def speech_to_text(audio: UploadFile):
    """Shared STT path for the web mic-recording upload — same Whisper call the Telegram voice-note path uses."""
    audio_bytes = await audio.read()
    result = await transcribe_audio(audio_bytes, filename=audio.filename or "voice.webm")
    return result


@router.post("/media/upload")
async def upload_photo(file: UploadFile):
    """Uploads one complaint photo/360° image to Cloudinary. Called once per
    selected file from the submit form; the frontend collects the returned
    URLs (with captions + is_360 flag) into ComplaintCreate.images."""
    file_bytes = await file.read()
    result = await upload_image(file_bytes, filename=file.filename or "complaint.jpg")
    return result
