import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import OfficialVerificationStatus, User, UserRole
from app.schemas.schemas import ApproveOfficialOut, PendingOfficialOut, RejectOfficialRequest
from app.services.auth import generate_temp_password, hash_password, require_admin
from app.services.email import send_official_approved_email, send_official_rejected_email

router = APIRouter(prefix="/admin", tags=["admin"])


def _slug(value: str | None, fallback: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower()) or fallback


async def _generate_official_email(db: AsyncSession, user: User) -> str:
    """A system-issued login identifier — not necessarily a real inbox.
    Notifications (including this account's own credentials) go to
    `requested_email`, the work address they applied with."""
    base = f"{_slug(user.official_level.value if user.official_level else None, 'official')}." \
           f"{_slug(user.ward or user.city or user.state, 'in')}"
    domain = "@nagarvaani.gov.in"
    candidate = f"{base}{domain}"
    n = 1
    while (await db.execute(select(User).where(User.email == candidate))).scalar_one_or_none():
        n += 1
        candidate = f"{base}{n}{domain}"
    return candidate


@router.get("/pending-officials", response_model=list[PendingOfficialOut])
async def list_pending_officials(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    result = await db.execute(
        select(User).where(User.role == UserRole.official, User.official_status == OfficialVerificationStatus.pending)
        .order_by(User.created_at)
    )
    return result.scalars().all()


@router.post("/officials/{user_id}/approve", response_model=ApproveOfficialOut)
async def approve_official(user_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or user.role != UserRole.official:
        raise HTTPException(status_code=404, detail="Official application not found")
    if user.official_status == OfficialVerificationStatus.approved:
        raise HTTPException(status_code=409, detail="Already approved")

    new_email = await _generate_official_email(db, user)
    temp_password = generate_temp_password()

    notify_to = user.requested_email or user.email
    user.email = new_email
    user.hashed_password = hash_password(temp_password)
    user.official_status = OfficialVerificationStatus.approved
    await db.flush()

    emailed = await send_official_approved_email(notify_to, user.name, new_email, temp_password)
    return ApproveOfficialOut(
        message=f"Approved. Credentials sent to {notify_to}" if emailed else "Approved. SMTP isn't configured — relay these credentials yourself.",
        new_email=new_email, temporary_password=temp_password, emailed=emailed,
    )


@router.post("/officials/{user_id}/reject")
async def reject_official(user_id: str, payload: RejectOfficialRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or user.role != UserRole.official:
        raise HTTPException(status_code=404, detail="Official application not found")
    if user.official_status == OfficialVerificationStatus.approved:
        raise HTTPException(status_code=409, detail="Already approved — can't reject")

    user.official_status = OfficialVerificationStatus.rejected
    await db.flush()
    emailed = await send_official_rejected_email(user.requested_email or user.email, user.name, payload.reason)
    return {"message": "Rejected", "emailed": emailed}
