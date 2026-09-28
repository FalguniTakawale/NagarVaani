from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import EmailVerification, PasswordReset, User
from app.schemas.schemas import (
    ForgotPasswordRequest, RegisterOut, ResendOtpRequest, ResetPasswordRequest,
    TokenOut, UserCreate, UserLogin, VerifyEmailRequest,
)
from app.services.auth import (
    create_access_token, generate_otp, hash_password, validate_password, verify_password,
)
from app.services.email import send_otp_email, send_password_reset_email, send_welcome_email
from app.services.rate_limit import check_rate_limit, seconds_until_reset

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL = timedelta(minutes=15)
RESEND_LIMIT = 3
RESEND_WINDOW = 60 * 60
RESET_LIMIT = 3
RESET_WINDOW = 60 * 60

UNVERIFIED_MSG = "Please verify your email. Check your inbox for the OTP."


def _token_out(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role.value),
        id=user.id, role=user.role, official_level=user.official_level, name=user.name,
        ward=user.ward, city=user.city, state=user.state, area=user.area,
    )


async def _issue_otp(db: AsyncSession, user: User) -> None:
    """Replace any outstanding code for this user with a fresh one and email it.
    Only the bcrypt hash is stored — a DB leak doesn't leak live codes."""
    await db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    otp = generate_otp()
    db.add(EmailVerification(
        user_id=user.id,
        otp_hash=hash_password(otp),
        expires_at=datetime.now(timezone.utc) + OTP_TTL,
    ))
    await db.flush()
    await send_otp_email(user.email, user.name, otp)


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    if error := validate_password(payload.password):
        raise HTTPException(status_code=400, detail=error)

    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        if not existing.is_email_verified:
            # Same person retrying after an abandoned signup — just send a new code.
            await _issue_otp(db, existing)
            return RegisterOut(message="OTP sent", user_id=existing.id, email=existing.email)
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        official_level=payload.official_level if payload.role.value == "official" else None,
        state=payload.state,
        city=payload.city,
        area=payload.area,
        ward=payload.ward,
        preferred_language=payload.preferred_language or "en",
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()
    await _issue_otp(db, user)
    return RegisterOut(message="OTP sent", user_id=user.id, email=user.email)


@router.post("/verify-email", response_model=TokenOut)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == payload.user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.is_email_verified:
        return _token_out(user)  # already done — harmless, just log them in

    record = (await db.execute(
        select(EmailVerification)
        .where(EmailVerification.user_id == user.id)
        .order_by(EmailVerification.created_at.desc())
    )).scalars().first()
    if not record:
        raise HTTPException(status_code=400, detail="No code on file — request a new one")

    expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="That code has expired — request a new one")
    if not verify_password(payload.otp.strip(), record.otp_hash):
        raise HTTPException(status_code=400, detail="Incorrect code")

    user.is_email_verified = True
    await db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    await db.flush()
    await send_welcome_email(user.email, user.name)
    return _token_out(user)


@router.post("/resend-otp")
async def resend_otp(payload: ResendOtpRequest, db: AsyncSession = Depends(get_db)):
    key = payload.email.lower()
    if not check_rate_limit("resend_otp", key, RESEND_LIMIT, RESEND_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many codes requested — try again later",
            headers={"Retry-After": str(seconds_until_reset("resend_otp", key, RESEND_WINDOW))},
        )

    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    # Don't reveal whether an email is registered.
    if user and not user.is_email_verified:
        await _issue_otp(db, user)
    return {"message": "If that email has a pending signup, a new code has been sent",
            "user_id": user.id if user and not user.is_email_verified else None}


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_email_verified:
        # Object detail so the frontend can jump straight to the OTP step.
        raise HTTPException(
            status_code=403,
            detail={"msg": UNVERIFIED_MSG, "requires_verification": True,
                    "user_id": user.id, "email": user.email},
        )

    return _token_out(user)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Always responds the same way regardless of whether the email is
    registered — same non-enumeration pattern as resend-otp."""
    key = payload.email.lower()
    if not check_rate_limit("forgot_password", key, RESET_LIMIT, RESET_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reset requests — try again later",
            headers={"Retry-After": str(seconds_until_reset("forgot_password", key, RESET_WINDOW))},
        )

    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user:
        await db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
        otp = generate_otp()
        db.add(PasswordReset(
            user_id=user.id,
            otp_hash=hash_password(otp),
            expires_at=datetime.now(timezone.utc) + OTP_TTL,
        ))
        await db.flush()
        await send_password_reset_email(user.email, user.name, otp)

    return {"message": "If that email has an account, a reset code has been sent"}


@router.post("/reset-password", response_model=TokenOut)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if error := validate_password(payload.new_password):
        raise HTTPException(status_code=400, detail=error)

    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect code")  # don't reveal the email doesn't exist

    record = (await db.execute(
        select(PasswordReset)
        .where(PasswordReset.user_id == user.id)
        .order_by(PasswordReset.created_at.desc())
    )).scalars().first()
    if not record:
        raise HTTPException(status_code=400, detail="No reset code on file — request a new one")

    expires_at = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="That code has expired — request a new one")
    if not verify_password(payload.otp.strip(), record.otp_hash):
        raise HTTPException(status_code=400, detail="Incorrect code")

    user.hashed_password = hash_password(payload.new_password)
    await db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    await db.flush()
    return _token_out(user)  # log them straight in, same as verify-email does
