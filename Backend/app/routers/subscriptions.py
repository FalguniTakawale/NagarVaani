"""
"My Neighborhood" email alerts — subscribe an email address to a lat/lng +
radius, get a real email when a complaint is reported or resolved nearby.
Email only: there's no SMS provider wired into this app (see config.py),
so a phone-number field would be a promise the backend can't keep.

notify_nearby_subscribers() is called from complaints.py at the two moments
that matter — a new complaint saved with coordinates, and a status update
that lands on "resolved" — so alerts are sent as part of the same request
that caused them, not a separate poller.
"""
import math
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Complaint, NeighborhoodSubscription
from app.schemas.schemas import NeighborhoodSubscribeRequest
from app.services.email import send_neighborhood_alert_email, send_neighborhood_confirm_email
from app.services.rate_limit import check_rate_limit, client_ip, seconds_until_reset

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

SUB_LIMIT = 5
SUB_WINDOW = 60 * 60
MAX_RADIUS_KM = 10.0


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _unsubscribe_url(token: str) -> str:
    # Same-origin frontend serves the API too (see main.py) — a relative API
    # path here would need the frontend origin, which this backend-only
    # module doesn't know, so the link points straight at the API endpoint
    # below; it returns a plain confirmation page rather than JSON.
    from app.config import get_settings
    settings = get_settings()
    base = (settings.frontend_url.split(",")[0].strip().rstrip("/") if settings.frontend_url else "")
    return f"{base}/api/subscriptions/unsubscribe/{token}"


@router.post("/neighborhood")
async def subscribe_neighborhood(payload: NeighborhoodSubscribeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    if not check_rate_limit("neighborhood_sub", ip, SUB_LIMIT, SUB_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many subscription requests — try again later",
            headers={"Retry-After": str(seconds_until_reset("neighborhood_sub", ip, SUB_WINDOW))},
        )
    radius = min(max(payload.radius_km, 0.5), MAX_RADIUS_KM)
    token = secrets.token_urlsafe(24)

    sub = NeighborhoodSubscription(
        email=payload.email, latitude=payload.latitude, longitude=payload.longitude,
        radius_km=radius, label=payload.label, unsubscribe_token=token,
    )
    db.add(sub)
    await db.flush()

    emailed = await send_neighborhood_confirm_email(payload.email, payload.label, radius, _unsubscribe_url(token))
    return {"message": "Subscribed" if emailed else "Subscribed (email delivery isn't configured on this server — see server log)", "id": sub.id}


@router.get("/unsubscribe/{token}")
async def unsubscribe_neighborhood(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NeighborhoodSubscription).where(NeighborhoodSubscription.unsubscribe_token == token))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found or already removed")
    sub.is_active = False
    await db.flush()
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center;color:#1C1C1E'>"
        "<h2>Unsubscribed</h2><p>You won't get any more neighborhood alerts from NagarVaani.</p></body></html>"
    )


async def notify_nearby_subscribers(db: AsyncSession, complaint: Complaint, event: str) -> None:
    """event: 'reported' | 'resolved'. Best-effort — an email failure here
    must never fail the complaint submission/status-update request that
    triggered it, same fail-open rule as every other notification path."""
    if complaint.latitude is None or complaint.longitude is None:
        return

    result = await db.execute(select(NeighborhoodSubscription).where(NeighborhoodSubscription.is_active == True))
    subs = result.scalars().all()
    if not subs:
        return

    # complaint.category may still be a plain string here rather than the
    # ComplaintCategory enum — SQLAlchemy doesn't coerce an in-memory
    # assignment to the enum type until the row is reloaded from the DB,
    # and this is called right after the same request's own flush().
    raw_category = complaint.category
    category_value = raw_category.value if hasattr(raw_category, "value") else (raw_category or "other")
    category_label = category_value.replace("_", " ").title()
    title = complaint.text_translated or complaint.text_original or ""

    for sub in subs:
        d = _haversine_km(sub.latitude, sub.longitude, complaint.latitude, complaint.longitude)
        if d > sub.radius_km:
            continue
        await send_neighborhood_alert_email(
            sub.email, sub.label, event, category_label, title, d, complaint.id, _unsubscribe_url(sub.unsubscribe_token),
        )
