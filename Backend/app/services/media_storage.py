"""
Image storage for complaint photos and 360° captures.
Uploaded straight to Cloudinary — no local filesystem writes, which matters
on Render where the filesystem isn't persistent across deploys.
"""

from app.config import get_settings

settings = get_settings()

_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return
    import cloudinary

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    _configured = True


async def upload_image(file_bytes: bytes, filename: str = "complaint.jpg") -> dict:
    """
    Returns: {url} on success, {error} on failure.
    Fails closed (unlike STT) — there's no sensible fallback for a missing
    image, so the caller drops it and tells the user, rather than silently
    submitting a broken image_url.
    """
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        return {"error": "Image upload unavailable — Cloudinary not configured on the server"}

    try:
        import cloudinary.uploader

        _ensure_configured()
        result = cloudinary.uploader.upload(
            file_bytes,
            folder="nagarvaani/complaints",
            resource_type="image",
        )
        return {"url": result["secure_url"]}
    except Exception as e:
        return {"error": f"Upload failed: {e}"}
