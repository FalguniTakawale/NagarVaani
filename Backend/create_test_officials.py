"""Create (or reset) dummy official accounts for testing the official portal.

    python create_test_officials.py                       # local / dev
    python create_test_officials.py --allow-production    # on a deployed DB (Render Shell)
    python create_test_officials.py --remove              # delete them again

Creates three pre-approved, email-verified accounts:
  admin.test@nagarvaani.gov.in   central official + ADMIN (can approve other officials)
  ward.test@nagarvaani.gov.in    ward officer, Ward 12, Pune, Maharashtra
  state.test@nagarvaani.gov.in   state officer, Maharashtra

Passwords are random and printed ONCE (re-running resets them) — nothing is hardcoded,
because a fixed admin password in a public repo would be a backdoor on any deployment.
To choose your own, set TEST_OFFICIAL_PASSWORD (must meet the password rules).
DELETE THESE ACCOUNTS (--remove) after testing on a public site.
"""
import asyncio
import os
import sys

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal, create_tables
from app.models.models import (
    EmailVerification, OfficialLevel, OfficialVerificationStatus, PasswordReset, User, UserRole,
)
from app.services.auth import generate_temp_password, hash_password, validate_password

ACCOUNTS = [
    dict(email="admin.test@nagarvaani.gov.in", name="Test Admin", level=OfficialLevel.central, admin=True),
    dict(email="ward.test@nagarvaani.gov.in", name="Test Ward Officer", level=OfficialLevel.ward_officer,
         ward="12", city="Pune", state="Maharashtra", area="Shivaji Nagar"),
    dict(email="state.test@nagarvaani.gov.in", name="Test State Officer", level=OfficialLevel.state, state="Maharashtra"),
]


async def main(remove: bool, allow_prod: bool):
    settings = get_settings()
    if settings.environment.lower() != "development" and not (allow_prod or remove):
        sys.exit("ENVIRONMENT is not 'development' — re-run with --allow-production if you really mean it, "
                 "and run with --remove when you're done testing.")
    await create_tables()
    fixed = os.environ.get("TEST_OFFICIAL_PASSWORD")
    if fixed and (err := validate_password(fixed)):
        sys.exit(err)
    async with AsyncSessionLocal() as s:
        if remove:
            emails = [a["email"] for a in ACCOUNTS]
            ids = [u.id for u in (await s.execute(select(User).where(User.email.in_(emails)))).scalars()]
            if ids:
                await s.execute(delete(EmailVerification).where(EmailVerification.user_id.in_(ids)))
                await s.execute(delete(PasswordReset).where(PasswordReset.user_id.in_(ids)))
                await s.execute(delete(User).where(User.id.in_(ids)))
            await s.commit()
            print(f"Removed {len(ids)} test account(s).")
            return
        print("Test official accounts (passwords shown once):\n")
        for a in ACCOUNTS:
            pw = fixed or generate_temp_password()
            u = (await s.execute(select(User).where(User.email == a["email"]))).scalar_one_or_none()
            if not u:
                u = User(email=a["email"], hashed_password=hash_password(pw), name=a["name"], role=UserRole.official)
                s.add(u)
            u.hashed_password = hash_password(pw)
            u.role = UserRole.official
            u.official_level = a["level"]
            u.official_status = OfficialVerificationStatus.approved
            u.is_admin = bool(a.get("admin"))
            u.is_email_verified = True
            for f in ("ward", "city", "state", "area"):
                setattr(u, f, a.get(f))
            print(f"  {a['email']:34} {pw}   ({a['level'].value}{', ADMIN' if a.get('admin') else ''})")
        await s.commit()
    print("\nSign in on the site with these. Remove them after testing: python create_test_officials.py --remove")

if __name__ == "__main__":
    asyncio.run(main("--remove" in sys.argv, "--allow-production" in sys.argv))
