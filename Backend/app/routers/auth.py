from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.models import EmailVerification, OfficialVerificationStatus, PasswordReset, User, UserRole
from app.schemas.schemas import (
    ForgotPasswordRequest, GoogleAuthRequest, GoogleConfigOut, RegisterOut, ResendOtpRequest,
    ResetPasswordRequest, TokenOut, UserCreate, UserLogin, VerifyEmailRequest,
)
from app.services.auth import (
    create_access_token, generate_otp, generate_temp_password, hash_password,
    is_personal_email_domain, require_user, validate_password, verify_password,
)
from app.services.email import send_otp_email, send_password_reset_email, send_welcome_email
from app.services.rate_limit import check_rate_limit, client_ip, seconds_until_reset
from app.routers.telegram import create_link_code
from app.services.telegram_client import get_bot_username

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

GOOGLE_LIMIT = 20
GOOGLE_WINDOW = 60 * 60

OTP_TTL = timedelta(minutes=15)
RESEND_LIMIT = 3
RESEND_WINDOW = 60 * 60
RESET_LIMIT = 3
RESET_WINDOW = 60 * 60

# Brute-force guards. A 6-digit OTP has only 1,000,000 values, and a correct one
# returns a login token, so guessing must be capped hard (per account AND per IP).
LOGIN_LIMIT, LOGIN_WINDOW = 10, 15 * 60          # per IP and per email
OTP_TRY_LIMIT, OTP_TRY_WINDOW = 5, 15 * 60       # wrong-or-right attempts per account


def _throttle(bucket: str, key: str, limit: int, window: int, detail: str) -> None:
    if not check_rate_limit(bucket, key, limit, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail,
            headers={"Retry-After": str(seconds_until_reset(bucket, key, window))},
        )


UNVERIFIED_MSG = "Please verify your email. Check your inbox for the OTP."


def _token_out(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role.value),
        id=user.id, role=user.role, official_level=user.official_level,
        official_status=user.official_status, is_admin=user.is_admin, name=user.name,
        email=user.email, ward=user.ward, city=user.city, state=user.state, area=user.area,
        telegram_chat_id=user.telegram_chat_id,
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


async def _skip_verification(db: AsyncSession, user: User, password: str | None = None) -> TokenOut:
    """Only reachable when REQUIRE_EMAIL_VERIFICATION=false (demo hosts with no
    working SMTP). If an old unverified account re-registers, the password must
    match the one it was created with, so nobody can claim someone else's address."""
    if password is not None and not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=409, detail="Email already registered — sign in instead")
    user.is_email_verified = True
    await db.flush()
    return _token_out(user)


@router.post("/register", response_model=RegisterOut | TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    _throttle("register_ip", client_ip(request), 10, 60 * 60, "Too many sign-ups from this network — try again later")
    if error := validate_password(payload.password):
        raise HTTPException(status_code=400, detail=error)

    is_official = payload.role.value == "official"
    if is_official and is_personal_email_domain(payload.email):
        raise HTTPException(
            status_code=400,
            detail="Please register with your official/work email address — personal email providers (Gmail, Yahoo, etc.) aren't accepted for official accounts.",
        )

    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        if not existing.is_email_verified:
            # Same person retrying after an abandoned signup — just send a new code.
            if not settings.require_email_verification:
                return await _skip_verification(db, existing, payload.password)
            await _issue_otp(db, existing)
            return RegisterOut(message="OTP sent", user_id=existing.id, email=existing.email)
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        official_level=payload.official_level if is_official else None,
        # An official account can't do anything official-only until an admin
        # approves it (see require_official) — the work-email check above is
        # just a soft filter, not identity proof.
        official_status=OfficialVerificationStatus.pending if is_official else None,
        requested_email=payload.email if is_official else None,
        state=payload.state,
        city=payload.city,
        area=payload.area,
        ward=payload.ward,
        preferred_language=payload.preferred_language or "en",
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()
    if not settings.require_email_verification:
        return await _skip_verification(db, user)
    await _issue_otp(db, user)
    return RegisterOut(message="OTP sent", user_id=user.id, email=user.email)


@router.post("/verify-email", response_model=TokenOut)
async def verify_email(payload: VerifyEmailRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _throttle("verify_otp", payload.user_id, OTP_TRY_LIMIT, OTP_TRY_WINDOW, "Too many attempts — request a new code and try again later")
    _throttle("verify_otp_ip", client_ip(request), 30, OTP_TRY_WINDOW, "Too many attempts — try again later")
    user = (await db.execute(select(User).where(User.id == payload.user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.is_email_verified:
        # Never hand out a token here: this endpoint takes only a user_id + OTP,
        # so returning one for an already-verified account would let anyone who
        # learns a user_id log in as them. They must use /auth/login.
        raise HTTPException(status_code=400, detail="This email is already verified — please sign in with your password")

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
async def login(payload: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    _throttle("login_ip", client_ip(request), LOGIN_LIMIT * 3, LOGIN_WINDOW, "Too many sign-in attempts — try again later")
    _throttle("login_email", payload.email.lower(), LOGIN_LIMIT, LOGIN_WINDOW, "Too many sign-in attempts for this account — try again later")
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_email_verified and not settings.require_email_verification:
        user.is_email_verified = True   # password already checked above
        await db.flush()

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
async def reset_password(payload: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _throttle("reset_try", payload.email.lower(), OTP_TRY_LIMIT, OTP_TRY_WINDOW, "Too many attempts — request a new code and try again later")
    _throttle("reset_try_ip", client_ip(request), 30, OTP_TRY_WINDOW, "Too many attempts — try again later")
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


@router.get("/me", response_model=TokenOut)
async def me(current_user: User = Depends(require_user)):
    """Refresh the client's cached profile (e.g. after linking Telegram)
    without a full re-login. Also extends the session, harmlessly."""
    return _token_out(current_user)


@router.post("/telegram-link-code")
async def telegram_link_code(current_user: User = Depends(require_user)):
    bot_username = await get_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram isn't configured on this server right now")
    code = create_link_code(current_user.id)
    return {
        "code": code,
        "bot_username": bot_username,
        "deep_link": f"https://t.me/{bot_username}?start={code}",
        "expires_in_minutes": 10,
    }


@router.get("/google-config", response_model=GoogleConfigOut)
async def google_config():
    """The frontend only renders the "Continue with Google" button once it
    knows a real Client ID is set — same "fails clearly, not silently" pattern
    as Telegram/Cloudinary/SMTP when their keys are missing."""
    return GoogleConfigOut(enabled=bool(settings.google_client_id), client_id=settings.google_client_id)


@router.post("/google", response_model=TokenOut)
async def google_auth(payload: GoogleAuthRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Verifies the ID token Google Identity Services returned client-side,
    then logs in (matching by Google's own stable subject id first, falling
    back to email) or creates a new citizen account. Google has already
    verified the email, so there's no OTP step here — unlike password signup.

    Deliberately citizen-only: an official account still has to go through
    the work-email + admin-approval flow, so someone can't get official access
    just by having a Gmail account Google will vouch for."""
    key = client_ip(request)
    if not check_rate_limit("google_auth", key, GOOGLE_LIMIT, GOOGLE_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts — try again later",
            headers={"Retry-After": str(seconds_until_reset("google_auth", key, GOOGLE_WINDOW))},
        )
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in isn't configured on this server")

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = await run_in_threadpool(
            google_id_token.verify_oauth2_token,
            payload.credential, google_requests.Request(), settings.google_client_id,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired Google sign-in — please try again")

    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="That Google account's email isn't verified")

    email = claims["email"]
    sub = claims["sub"]
    name = claims.get("name") or email.split("@", 1)[0]

    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if not user:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user and user.role != UserRole.citizen:
            raise HTTPException(
                status_code=400,
                detail="This email belongs to an official account — sign in with your official credentials instead.",
            )

    if user:
        user.google_sub = sub
        if not user.is_email_verified:
            user.is_email_verified = True  # Google already verified it
    else:
        user = User(
            name=name,
            email=email,
            # Nobody can ever type this — it just satisfies the NOT NULL
            # column. "Forgot password" gives them a real one later if they
            # ever want to sign in without Google.
            hashed_password=hash_password(generate_temp_password()),
            role=UserRole.citizen,
            auth_provider="google",
            google_sub=sub,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        await send_welcome_email(user.email, user.name)

    await db.flush()
    return _token_out(user)
