import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.models import User, UserRole, OfficialVerificationStatus

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# There's no real government employee registry to check a signup against, so
# this is a soft gate: block the free/personal email providers people already
# have, so an official at least has to use a work-looking address. It's not
# proof of identity — the admin approval step (require_official below) is
# what actually gates official-only access.
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "rediffmail.com", "protonmail.com", "aol.com", "live.com", "yandex.com",
}


def is_personal_email_domain(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in PERSONAL_EMAIL_DOMAINS


PASSWORD_RULES = [
    (re.compile(r".{8,}"), "at least 8 characters"),
    (re.compile(r"[A-Z]"), "an uppercase letter"),
    (re.compile(r"[a-z]"), "a lowercase letter"),
    (re.compile(r"\d"), "a digit"),
    (re.compile(r"[^A-Za-z0-9]"), "a special character (e.g. @ # ! $)"),
]


def validate_password(password: str) -> Optional[str]:
    """Returns a human-readable error listing what's missing, or None if the password is acceptable.
    Mirrors the frontend check in auth.js — the frontend is a convenience, this is the guarantee."""
    missing = [label for pattern, label in PASSWORD_RULES if not pattern.search(password or "")]
    if not missing:
        return None
    return "Password needs " + ", ".join(missing) + "."


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_temp_password() -> str:
    """A random password that already satisfies validate_password's rules,
    so an approved official can log in immediately and change it whenever."""
    import string
    specials = "!@#$%*"
    required = [
        secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits), secrets.choice(specials),
    ]
    pool = string.ascii_letters + string.digits
    required += [secrets.choice(pool) for _ in range(6)]
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Optional auth — returns None instead of raising, so citizens can browse/post anonymously."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
    except JWTError:
        return None
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def require_user(current_user: Optional[User] = Depends(get_current_user)) -> User:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return current_user


async def require_official(current_user: Optional[User] = Depends(get_current_user)) -> User:
    if not current_user or current_user.role != UserRole.official:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Official access required")
    if current_user.official_status != OfficialVerificationStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your official account is still pending admin approval",
        )
    return current_user


async def require_admin(current_user: Optional[User] = Depends(get_current_user)) -> User:
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
