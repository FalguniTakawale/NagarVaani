"""Optional first-admin bootstrap from environment variables.

Render's free tier has no Shell, so there's no way to run a script against the
deployed database. Instead: set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD in
the service's Environment tab and redeploy — on startup this creates (or resets) one
pre-approved, email-verified central official who is also an admin (so they can
approve other officials from the portal).

Nothing is hardcoded: with the variables unset this does nothing. The password must
meet the normal password rules. REMOVE both variables after testing, and delete the
account if it was only for a demo — removing the variables does not delete it.
"""
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.models import OfficialLevel, OfficialVerificationStatus, User, UserRole
from app.services.auth import hash_password, validate_password


async def bootstrap_admin() -> None:
    s = get_settings()
    email = (s.bootstrap_admin_email or "").strip().lower()
    password = s.bootstrap_admin_password or ""
    if not email or not password:
        return
    if err := validate_password(password):
        print(f"[bootstrap] BOOTSTRAP_ADMIN_PASSWORD rejected: {err}")
        return
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            user = User(email=email, name="Admin", hashed_password=hash_password(password), role=UserRole.official)
            db.add(user)
        user.hashed_password = hash_password(password)
        user.role = UserRole.official
        user.official_level = OfficialLevel.central
        user.official_status = OfficialVerificationStatus.approved
        user.is_admin = True
        user.is_email_verified = True
        await db.commit()
    print(f"[bootstrap] admin account ready: {email} (remove the BOOTSTRAP_* variables once you've tested)")
