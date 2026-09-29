import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, or_, false
from sqlalchemy.orm import selectinload
from typing import Optional, List
from app.database import get_db
from app.models.models import (
    Complaint, Vote, Comment, LinkedArea, StatusLog, ComplaintFlag,
    ComplaintStatus, ComplaintCategory, User, OfficialLevel
)
from app.schemas.schemas import (
    ComplaintCreate, ComplaintOut, ComplaintListItem,
    VoteCreate, VoteOut, CommentCreate, CommentOut,
    LinkAreaCreate, StatusUpdate, FlagCreate, DisputeCreate, TranslateRequest, TranslateResponse
)
from app.models.models import UserRole
from app.services.auth import get_current_user, require_user, require_official
from app.services.jurisdiction import apply_jurisdiction
from app.services.rate_limit import check_rate_limit, client_ip, seconds_until_reset
from app.services.telegram_client import send_message as tg_send
from app.services.email import send_status_update_email
from app.routers.subscriptions import notify_nearby_subscribers
from app.routers.insights import population_for
from app.services.ai_engine import (
    process_complaint_pipeline,
    detect_places_in_comment,
    translate_text
)

router = APIRouter(prefix="/complaints", tags=["complaints"])

SUBMIT_LIMIT = 5            # per IP
SUBMIT_WINDOW = 60 * 60     # one hour


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── SUBMIT COMPLAINT ──────────────────────────────────────────────────────────
@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_complaint(
    payload: ComplaintCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    # Each submission costs 3-4 Claude calls — cap per IP so a script can't
    # burn through the API credit.
    ip = client_ip(request)
    if not check_rate_limit("submit", ip, SUBMIT_LIMIT, SUBMIT_WINDOW):
        retry_in = seconds_until_reset("submit", ip, SUBMIT_WINDOW)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions, try again later",
            headers={"Retry-After": str(retry_in)},
        )

    # Location is required for a normal civic complaint — a report with no
    # location is useless to an official trying to act on it. The corruption
    # form is exempt (location can be sensitive/unknown there, e.g. "which
    # office" isn't always a place a citizen can safely name).
    is_corruption = payload.category is not None and payload.category.value == "corruption"
    if not is_corruption and not (payload.location_text and payload.location_text.strip()):
        raise HTTPException(status_code=400, detail="Location is required")

    # City and state are what actually populate ward/city/state-scoped views,
    # hotspot maps, and state-level dashboards — "Location" alone is just a
    # free-text hint an official reads, it isn't queryable. An anonymous
    # submitter or an account with no city/state on file has no other source
    # for this, so the frontend asks explicitly; enforce it here too so it
    # can't be skipped by calling the API directly.
    resolved_city = payload.city or (current_user.city if current_user else None)
    resolved_state = payload.state or (current_user.state if current_user else None)
    if not is_corruption and not resolved_city:
        raise HTTPException(status_code=400, detail="City is required")
    if not is_corruption and not resolved_state:
        raise HTTPException(status_code=400, detail="State is required")

    location_str = payload.location_text or payload.area or payload.city or ""

    # Real population if an external dataset (region_indicators) covers this
    # city, else the prototype default of 10,000.
    population = await population_for(db, resolved_city, resolved_state)

    # Run the full AI pipeline
    ai_result = await process_complaint_pipeline(
        text=payload.text,
        location=location_str,
        population=population,
        vote_count=0,
        linked_area_count=0,
    )

    if not ai_result.get("passed"):
        # Rejected — return 422 with the reason + rephrasing suggestion
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "rejected": True,
                "reason": ai_result.get("filter_reason"),
                "suggested_rephrasing": ai_result.get("suggested_rephrasing"),
            }
        )

    # Caller-pinned category (corruption page) overrides the classifier; the
    # score is recomputed with it so the breakdown stays honest.
    if payload.category and payload.category.value != ai_result.get("category"):
        from app.services.ai_engine import score_complaint
        rescored = await score_complaint(
            text=payload.text, category=payload.category.value,
            is_safety_risk=ai_result.get("is_safety_risk", False),
            population=population, linked_area_count=0, vote_count=0,
        )
        ai_result["category"] = payload.category.value
        ai_result["priority_score"] = rescored["score"]
        ai_result["score_breakdown"] = rescored["breakdown"]
        ai_result["seasonal_multiplier"] = rescored["breakdown"]["l2_seasonal_multiplier"]

    complaint = Complaint(
        author_id=None if payload.anonymous else (current_user.id if current_user else None),
        text_original=payload.text,
        text_translated=ai_result.get("text_translated"),
        detected_language=ai_result.get("detected_language"),
        category=ai_result.get("category"),
        location_text=payload.location_text,
        ward=payload.ward or (current_user.ward if current_user else None),
        area=payload.area or ai_result.get("location_hint") or (current_user.area if current_user else None),
        city=payload.city or (current_user.city if current_user else None),
        state=payload.state or (current_user.state if current_user else None),
        latitude=payload.latitude,
        longitude=payload.longitude,
        priority_score=ai_result.get("priority_score", 0),
        score_breakdown=ai_result.get("score_breakdown", {}),
        is_safety_risk=ai_result.get("is_safety_risk", False),
        seasonal_multiplier=ai_result.get("seasonal_multiplier", 1.0),
        image_urls=[img.model_dump() for img in (payload.images or [])],
        status=ComplaintStatus.open,
        is_ai_filtered=True,
        official_brief=ai_result.get("official_brief"),
        recommended_action=ai_result.get("recommended_action"),
    )

    db.add(complaint)
    await db.flush()

    # Cross-channel notification: whoever actually submitted this (regardless
    # of the anonymous flag, which only affects public attribution) gets a
    # receipt on Telegram if they've linked it — the "your order has been
    # placed" moment, same idea as the bot's own in-chat confirmation.
    if current_user and current_user.telegram_chat_id:
        await tg_send(
            current_user.telegram_chat_id,
            f"✓ Your complaint was registered on NagarVaani.\n"
            f"Category: {complaint.category} · Priority score: {complaint.priority_score}/100\n"
            f"Complaint ID: {complaint.id[:8]}\n\n"
            f"We'll message you here when its status changes.",
        )

    # "My Neighborhood" alerts — never for corruption reports, same rule as
    # every other public-facing surface in the app.
    if complaint.category != ComplaintCategory.corruption:
        await notify_nearby_subscribers(db, complaint, "reported")

    return {
        "id": complaint.id,
        "priority_score": complaint.priority_score,
        "score_breakdown": complaint.score_breakdown,
        "category": complaint.category,
        "is_safety_risk": complaint.is_safety_risk,
        "status": complaint.status,
        "message": "Complaint submitted and scored successfully",
    }


# ── LIST COMPLAINTS ───────────────────────────────────────────────────────────
@router.get("", response_model=List[dict])
async def list_complaints(
    scope: str = Query("ward", description="ward | trending | nearby | mine | voted | jurisdiction | corruption"),
    ward: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    sort: str = Query("priority", description="priority | votes | recent | distance (nearby only)"),
    category: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    # Strings, not floats — a frontend bug elsewhere already sent literal
    # "null" here once (JS `null` stringified by URLSearchParams), which a
    # float-typed Query rejects with a raw 422 no matter what fixes it on
    # the client side. Parsed defensively below instead, so any client
    # (present or future) sending "null"/""/garbage degrades to "no
    # coordinates" rather than a hard error.
    lat: Optional[str] = Query(None),
    lng: Optional[str] = Query(None),
    radius_km: float = Query(5.0, ge=0.1, le=100),
    near_text: Optional[str] = Query(None, description="nearby without GPS: match area / city / location text"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    def _parse_coord(raw: Optional[str]) -> Optional[float]:
        if raw is None or raw.strip().lower() in ("", "null", "undefined", "nan"):
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    lat = _parse_coord(lat)
    lng = _parse_coord(lng)

    q = select(Complaint).where(Complaint.is_ai_filtered == True)

    # Corruption reports live in their own section — never mixed into the
    # public feeds, and the corruption scope shows nothing else. Unlike every
    # other scope, this one requires an account: these can name the official
    # being accused, so "public feed" here means "any signed-in citizen",
    # not "anyone with curl and no login".
    if scope == "corruption":
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required to view corruption reports")
        q = q.where(Complaint.category == ComplaintCategory.corruption)
    elif scope in ("ward", "trending", "nearby") and category != "corruption":
        q = q.where(Complaint.category != ComplaintCategory.corruption)

    # Scope filtering
    if scope == "ward":
        # Use logged-in user's ward if not explicitly passed
        ward_filter = ward or (current_user.ward if current_user else None)
        if ward_filter:
            q = q.where(Complaint.ward == ward_filter)
        elif city:
            q = q.where(Complaint.city == city)
        else:
            # No ward and no city to scope to (a guest with no account, or a
            # logged-in user who never set a location) — this must NOT fall
            # through to an unfiltered, nationwide query. "Issues in your
            # ward" showing every ward in the country is a real bug, not a
            # helpful fallback. Return nothing rather than mislead.
            q = q.where(false())
    elif scope == "trending":
        # Nationwide by default; near_text narrows it to a specific area/ward/city
        # without needing GPS — same free-text match "nearby" uses without a fix.
        if near_text:
            like = f"%{near_text.strip()}%"
            q = q.where(or_(Complaint.area.ilike(like), Complaint.city.ilike(like),
                            Complaint.location_text.ilike(like), Complaint.ward.ilike(like)))
    elif scope == "nearby":
        if lat is not None and lng is not None:
            # Cheap bounding box in SQL (SQLite has no trig functions); the exact
            # haversine cut + distance sort happen in Python below.
            dlat = radius_km / 111.0
            dlng = radius_km / max(111.0 * math.cos(math.radians(lat)), 1e-6)
            q = q.where(
                Complaint.latitude.isnot(None), Complaint.longitude.isnot(None),
                Complaint.latitude.between(lat - dlat, lat + dlat),
                Complaint.longitude.between(lng - dlng, lng + dlng),
            )
        elif near_text:
            like = f"%{near_text.strip()}%"
            q = q.where(or_(Complaint.area.ilike(like), Complaint.city.ilike(like),
                            Complaint.location_text.ilike(like), Complaint.ward.ilike(like)))
        elif city:
            q = q.where(Complaint.city == city)
    elif scope == "mine":
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required to view your complaints")
        q = q.where(Complaint.author_id == current_user.id)
    elif scope == "voted":
        if not current_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required to view your votes")
        voted_ids = select(Vote.complaint_id).where(Vote.user_id == current_user.id)
        q = q.where(Complaint.id.in_(voted_ids))
    elif scope == "jurisdiction":
        # Default dashboard scope for officials — Tier 1: their jurisdiction only.
        # This is a *default view*, not an access restriction — any official can
        # still request scope=trending to explore nationwide.
        if not current_user or current_user.role != "official":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Official access required")
        level = current_user.official_level
        if level == OfficialLevel.ward_officer and current_user.ward:
            q = q.where(Complaint.ward == current_user.ward)
        elif level in (OfficialLevel.municipal, OfficialLevel.district) and current_user.city:
            q = q.where(Complaint.city == current_user.city)
        elif level == OfficialLevel.state and current_user.state:
            q = q.where(Complaint.state == current_user.state)
        # level == central (or unset): nationwide, no filter

    # Home ("ward") and Trending are "what needs attention" feeds — a
    # resolved issue has nothing left to act on there, so it doesn't belong
    # once it's fixed. Only skip this when the caller explicitly asked for a
    # specific status (so e.g. a future "show resolved too" toggle can still
    # request it) — it never applies to "My complaints", where seeing your
    # own resolved items is the whole point.
    if scope in ("ward", "trending") and not status_filter:
        q = q.where(Complaint.status != ComplaintStatus.resolved)

    # Category filter
    if category:
        q = q.where(Complaint.category == category)

    # Status filter
    if status_filter:
        q = q.where(Complaint.status == status_filter)

    # Sorting
    if sort == "priority":
        q = q.order_by(desc(Complaint.priority_score))
    elif sort == "votes":
        # Subquery for vote count
        vote_count_sub = (
            select(Vote.complaint_id, func.count(Vote.id).label("vc"))
            .group_by(Vote.complaint_id)
            .subquery()
        )
        q = q.outerjoin(vote_count_sub, Complaint.id == vote_count_sub.c.complaint_id)
        q = q.order_by(desc(func.coalesce(vote_count_sub.c.vc, 0)))
    elif sort == "recent":
        q = q.order_by(desc(Complaint.created_at))

    geo = scope == "nearby" and lat is not None and lng is not None
    q = q.options(selectinload(Complaint.votes), selectinload(Complaint.comments))
    offset = (page - 1) * per_page

    if geo:
        # Exact radius + distance need Python, so paginate after the cut.
        rows = (await db.execute(q)).scalars().all()
        with_dist = []
        for c in rows:
            d = haversine_km(lat, lng, c.latitude, c.longitude)
            if d <= radius_km:
                with_dist.append((d, c))
        if sort == "distance":
            with_dist.sort(key=lambda t: t[0])
        complaints = [c for _, c in with_dist[offset: offset + per_page]]
        distance_of = {c.id: round(d, 2) for d, c in with_dist}
    else:
        q = q.offset(offset).limit(per_page)
        complaints = (await db.execute(q)).scalars().all()
        distance_of = {}

    return [
        {
            "id": c.id,
            "latitude": c.latitude,
            "longitude": c.longitude,
            **({"distance_km": distance_of.get(c.id)} if geo else {}),
            "text_original": c.text_original,
            "text_translated": c.text_translated,
            "detected_language": c.detected_language,
            "category": c.category,
            "location_text": c.location_text,
            "ward": c.ward,
            "area": c.area,
            "city": c.city,
            "priority_score": c.priority_score,
            "is_safety_risk": c.is_safety_risk,
            "status": c.status,
            "vote_count": len(c.votes),
            "comment_count": len(c.comments),
            "linked_area_count": c.linked_area_count,
            "image_count": len(c.image_urls) if c.image_urls else 0,
            "score_breakdown": c.score_breakdown,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in complaints
    ]


# ── INVESTMENT FLAGS (officials) ──────────────────────────────────────────────
# Declared before /{complaint_id} so the literal path isn't swallowed by it.
@router.get("/flagged")
async def flagged_complaints(
    db: AsyncSession = Depends(get_db),
    official: User = Depends(require_official),
):
    """Complaints an official flagged for investment review — i.e. that carry a
    comment starting with "[OFFICIAL FLAG]". Latest flag per complaint."""
    q = (
        select(Complaint, Comment)
        .join(Comment, Comment.complaint_id == Complaint.id)
        .where(Comment.text.like("[OFFICIAL FLAG]%"))
        .order_by(desc(Comment.created_at))
    )
    q = apply_jurisdiction(q, official)
    rows = (await db.execute(q)).all()

    seen, out = set(), []
    for complaint, flag in rows:
        if complaint.id in seen:
            continue
        seen.add(complaint.id)
        out.append({
            "id": complaint.id,
            "title": (complaint.text_translated or complaint.text_original)[:120],
            "priority_score": complaint.priority_score,
            "category": complaint.category,
            "status": complaint.status,
            "ward": complaint.ward,
            "city": complaint.city,
            "recommended_action": complaint.recommended_action,
            "linked_area_count": complaint.linked_area_count,
            "flagged_by": flag.author_name,
            "flagged_at": flag.created_at.isoformat() if flag.created_at else None,
            "flag_note": flag.text.replace("[OFFICIAL FLAG]", "", 1).strip(),
        })
    return out


# ── CITIZEN FLAGS ("report this post") ────────────────────────────────────────
FLAG_REASON_LABELS = {
    "spam": "Spam", "misleading": "Misleading / false", "duplicate": "Duplicate",
    "abusive": "Abusive / hateful", "wrong_location": "Wrong location", "other": "Other",
}


@router.get("/citizen-flags")
async def citizen_flags(
    db: AsyncSession = Depends(get_db),
    official: User = Depends(require_official),
):
    """Moderation queue for officials: complaints signed-in citizens reported,
    scoped to the official's jurisdiction. Declared before /{complaint_id}."""
    q = (
        select(Complaint, func.count(ComplaintFlag.id), func.max(ComplaintFlag.created_at))
        .join(ComplaintFlag, ComplaintFlag.complaint_id == Complaint.id)
        .group_by(Complaint.id)
        .order_by(desc(func.count(ComplaintFlag.id)))
        .limit(100)
    )
    q = apply_jurisdiction(q, official)
    out = []
    for complaint, n, last in (await db.execute(q)).all():
        reasons = (await db.execute(
            select(ComplaintFlag.reason, ComplaintFlag.note).where(ComplaintFlag.complaint_id == complaint.id)
            .order_by(desc(ComplaintFlag.created_at)).limit(5)
        )).all()
        out.append({
            "id": complaint.id,
            "title": (complaint.text_translated or complaint.text_original)[:120],
            "priority_score": complaint.priority_score,
            "status": complaint.status,
            "flag_count": n,
            "last_flagged_at": last.isoformat() if last else None,
            "reasons": [{"reason": FLAG_REASON_LABELS.get(r, r), "note": note} for r, note in reasons],
        })
    return out


@router.post("/{complaint_id}/flag", response_model=dict, status_code=status.HTTP_201_CREATED)
async def flag_complaint(
    complaint_id: str,
    payload: FlagCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """A signed-in citizen reports a complaint (spam, misleading, duplicate,
    abusive, wrong location). It lands in the officials' moderation queue
    (GET /complaints/citizen-flags → Investment Flags page). It does NOT hide
    or re-score the complaint automatically — a human decides."""
    if not check_rate_limit("flag", current_user.id, 20, 60 * 60):
        raise HTTPException(status_code=429, detail="Too many reports — try again later")
    complaint = (await db.execute(select(Complaint).where(Complaint.id == complaint_id))).scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.author_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't report your own complaint")
    existing = (await db.execute(
        select(ComplaintFlag).where(ComplaintFlag.complaint_id == complaint_id, ComplaintFlag.user_id == current_user.id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="You've already reported this complaint")
    db.add(ComplaintFlag(complaint_id=complaint_id, user_id=current_user.id, reason=payload.reason, note=payload.note))
    await db.flush()
    return {"flagged": True, "message": "Thanks — an official will review this report."}


# ── RELATED COMPLAINTS (Tier 2 + Tier 3) ──────────────────────────────────────
@router.get("/{complaint_id}/related")
async def get_related_complaints(
    complaint_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Tier 2 — "similar issues in your area": same category, same geography.
    Tier 3 — simplified stand-in for market-basket / associative-rule mining:
    other complaints located in one of this complaint's linked areas, any
    category. A real co-occurrence mining engine (Amazon's "people also
    bought" model) is the documented V2 direction — this is a same-shape
    query that produces the same dashboard experience for the prototype.
    """
    result = await db.execute(
        select(Complaint).where(Complaint.id == complaint_id).options(selectinload(Complaint.linked_areas))
    )
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Tier 2 — same category, same city/ward, excluding self
    similar_q = select(Complaint).where(
        Complaint.id != complaint_id,
        Complaint.category == complaint.category,
        Complaint.is_ai_filtered == True,
    )
    if complaint.ward:
        similar_q = similar_q.where(Complaint.ward == complaint.ward)
    elif complaint.city:
        similar_q = similar_q.where(Complaint.city == complaint.city)
    similar_q = similar_q.order_by(desc(Complaint.priority_score)).limit(5)
    similar = (await db.execute(similar_q)).scalars().all()

    # Tier 3 — any complaint located in one of this complaint's linked areas
    linked_names = [la.area_name for la in complaint.linked_areas]
    cross_pattern = []
    if linked_names:
        cross_q = (
            select(Complaint)
            .where(
                Complaint.id != complaint_id,
                Complaint.is_ai_filtered == True,
                (Complaint.area.in_(linked_names)) | (Complaint.city.in_(linked_names)) | (Complaint.ward.in_(linked_names)),
            )
            .order_by(desc(Complaint.priority_score))
            .limit(5)
        )
        cross_pattern = (await db.execute(cross_q)).scalars().all()

    def brief(c):
        return {
            "id": c.id,
            "text": (c.text_translated or c.text_original)[:100],
            "category": c.category,
            "priority_score": c.priority_score,
            "ward": c.ward,
            "city": c.city,
        }

    return {
        "similar_in_area": [brief(c) for c in similar],
        "cross_pattern": [brief(c) for c in cross_pattern],
    }


# ── GET SINGLE COMPLAINT ──────────────────────────────────────────────────────
@router.get("/{complaint_id}")
async def get_complaint(
    complaint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    result = await db.execute(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .options(
            selectinload(Complaint.votes),
            selectinload(Complaint.comments),
            selectinload(Complaint.linked_areas),
            selectinload(Complaint.status_logs),
        )
    )
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    # Same login requirement as scope=corruption on the list endpoint — a
    # complaint id alone (e.g. shared via a link) shouldn't bypass it.
    if complaint.category == ComplaintCategory.corruption and not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required to view this report")

    return {
        "id": complaint.id,
        # Never expose the author's user id publicly — the client only needs to
        # know whether *it* is the author (to show the dispute button).
        "is_author": bool(current_user and complaint.author_id and complaint.author_id == current_user.id),
        "text_original": complaint.text_original,
        "text_translated": complaint.text_translated,
        "detected_language": complaint.detected_language,
        "category": complaint.category,
        "location_text": complaint.location_text,
        "ward": complaint.ward,
        "area": complaint.area,
        "city": complaint.city,
        "state": complaint.state,
        "priority_score": complaint.priority_score,
        "score_breakdown": complaint.score_breakdown,
        "is_safety_risk": complaint.is_safety_risk,
        "seasonal_multiplier": complaint.seasonal_multiplier,
        "image_urls": complaint.image_urls,
        "status": complaint.status,
        "official_brief": complaint.official_brief,
        "recommended_action": complaint.recommended_action,
        "vote_count": len(complaint.votes),
        "comment_count": len(complaint.comments),
        "linked_area_count": complaint.linked_area_count,
        "linked_areas": [
            {
                "area_name": la.area_name,
                "link_type": la.link_type,
                "complaint_count": la.complaint_count,
                "linked_at": la.linked_at.isoformat() if la.linked_at else None,
            }
            for la in complaint.linked_areas
        ],
        "comments": [
            {
                "id": c.id,
                "author_name": c.author_name,
                "author_area": c.author_area,
                "text": c.text,
                "detected_places": c.detected_places,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in sorted(complaint.comments, key=lambda x: x.created_at or 0)
        ],
        "status_log": [
            {
                "old_status": sl.old_status,
                "new_status": sl.new_status,
                "note": sl.note,
                "created_at": sl.created_at.isoformat() if sl.created_at else None,
            }
            for sl in complaint.status_logs
        ],
        "created_at": complaint.created_at.isoformat() if complaint.created_at else None,
    }


# ── VOTE ──────────────────────────────────────────────────────────────────────
@router.post("/{complaint_id}/vote", response_model=dict)
async def vote(
    complaint_id: str,
    payload: VoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # Check complaint exists
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Check not already voted
    existing = await db.execute(
        select(Vote).where(Vote.complaint_id == complaint_id, Vote.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You have already voted on this complaint")

    # Determine solidarity
    is_solidarity = payload.is_solidarity or (
        current_user.ward != complaint.ward and bool(complaint.ward)
    )

    vote = Vote(
        complaint_id=complaint_id,
        user_id=current_user.id,
        is_solidarity=is_solidarity,
        voter_area=current_user.area,
    )
    db.add(vote)
    await db.flush()

    # Recalculate score with new vote count
    vote_count_result = await db.execute(
        select(func.count(Vote.id)).where(Vote.complaint_id == complaint_id)
    )
    new_vote_count = vote_count_result.scalar()

    # Re-score (only L6 changes)
    from app.services.ai_engine import score_complaint
    new_score = await score_complaint(
        text=complaint.text_original,
        category=str(complaint.category.value if complaint.category else "other"),
        is_safety_risk=complaint.is_safety_risk,
        population=await population_for(db, complaint.city, complaint.state),
        linked_area_count=complaint.linked_area_count,
        vote_count=new_vote_count,
    )
    complaint.priority_score = new_score["score"]
    complaint.score_breakdown = new_score["breakdown"]

    return {
        "voted": True,
        "is_solidarity": is_solidarity,
        "new_vote_count": new_vote_count,
        "new_score": new_score["score"],
    }


# ── COMMENT ───────────────────────────────────────────────────────────────────
@router.post("/{complaint_id}/comments", response_model=dict)
async def add_comment(
    complaint_id: str,
    payload: CommentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    # Every comment triggers an LLM place-scan, and anonymous commenting is
    # allowed — cap per IP so it can't be used to burn API credit.
    if not check_rate_limit("comment", client_ip(request), 30, 60 * 60):
        raise HTTPException(status_code=429, detail="Too many comments — try again later")

    # "[OFFICIAL FLAG]" is a reserved marker that feeds the Investment Flags
    # list — only a verified official may write it, otherwise anyone could
    # forge a flag by typing the prefix.
    is_official = bool(current_user and current_user.role == UserRole.official)
    if payload.text.lstrip().upper().startswith("[OFFICIAL FLAG]") and not is_official:
        raise HTTPException(status_code=403, detail="That prefix is reserved for officials")

    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # NLP scan for place names
    detected_places = await detect_places_in_comment(
        comment_text=payload.text,
        complaint_city=complaint.city or ""
    )

    comment = Comment(
        complaint_id=complaint_id,
        author_id=current_user.id if current_user else None,
        # Signed-in users always post under their own account name; only
        # anonymous commenters may pick a display name (so nobody can post
        # "as" an official or another user).
        author_name=(current_user.name if current_user else (payload.author_name or "Anonymous")),
        author_area=payload.author_area or (current_user.area if current_user else None),
        text=payload.text,
        detected_places=detected_places,
    )
    db.add(comment)
    await db.flush()

    # Auto-link detected places as linked areas (NLP type)
    newly_linked = []
    for place in detected_places:
        # Check if already linked
        existing_link = await db.execute(
            select(LinkedArea).where(
                LinkedArea.complaint_id == complaint_id,
                LinkedArea.area_name == place,
            )
        )
        existing = existing_link.scalar_one_or_none()
        if existing:
            existing.complaint_count += 1
        else:
            linked_area = LinkedArea(
                complaint_id=complaint_id,
                area_name=place,
                link_type="nlp",
                complaint_count=1,
            )
            db.add(linked_area)
            complaint.linked_area_count = (complaint.linked_area_count or 0) + 1
            newly_linked.append(place)

    return {
        "id": comment.id,
        "text": comment.text,
        "author_name": comment.author_name,
        "author_area": comment.author_area,
        "detected_places": detected_places,
        "newly_linked_areas": newly_linked,
        "message": f"Comment posted. {len(newly_linked)} new area(s) auto-linked via NLP." if newly_linked else "Comment posted.",
    }


# ── LINK AREA (button) ────────────────────────────────────────────────────────
@router.post("/{complaint_id}/link-area", response_model=dict)
async def link_area(
    complaint_id: str,
    payload: LinkAreaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not check_rate_limit("link_area", client_ip(request), 30, 60 * 60):
        raise HTTPException(status_code=429, detail="Too many requests — try again later")
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    area_name = payload.area_name or (current_user.area if current_user else "Unknown area")

    existing = await db.execute(
        select(LinkedArea).where(
            LinkedArea.complaint_id == complaint_id,
            LinkedArea.area_name == area_name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This area is already linked to this complaint")

    linked = LinkedArea(
        complaint_id=complaint_id,
        area_name=area_name,
        link_type="button",
        complaint_count=1,
    )
    db.add(linked)
    complaint.linked_area_count = (complaint.linked_area_count or 0) + 1

    # Recalculate score with new linked count
    from app.services.ai_engine import score_complaint
    vote_count_result = await db.execute(
        select(func.count(Vote.id)).where(Vote.complaint_id == complaint_id)
    )
    vote_count = vote_count_result.scalar()

    new_score = await score_complaint(
        text=complaint.text_original,
        category=str(complaint.category.value if complaint.category else "other"),
        is_safety_risk=complaint.is_safety_risk,
        population=await population_for(db, complaint.city, complaint.state),
        linked_area_count=complaint.linked_area_count,
        vote_count=vote_count,
    )
    complaint.priority_score = new_score["score"]
    complaint.score_breakdown = new_score["breakdown"]

    return {
        "linked": True,
        "area_name": area_name,
        "new_linked_count": complaint.linked_area_count,
        "new_score": new_score["score"],
    }


# ── STATUS UPDATE (officials only) ────────────────────────────────────────────
@router.patch("/{complaint_id}/status", response_model=dict)
async def update_status(
    complaint_id: str,
    payload: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    official: User = Depends(require_official),
):
    # Officials may only change complaints inside their own jurisdiction
    # (ward / city / state; central = nationwide) — reading is open to all
    # officials, writing is not.
    result = await db.execute(apply_jurisdiction(select(Complaint).where(Complaint.id == complaint_id), official))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found in your jurisdiction")

    old_status = complaint.status
    complaint.status = payload.status

    log = StatusLog(
        complaint_id=complaint_id,
        old_status=old_status,
        new_status=payload.status,
        updated_by_id=official.id,
        note=payload.note,
    )
    db.add(log)

    # Notify the citizen — on Telegram if linked, and always by email too
    # (every account has one; Telegram is opt-in extra, not a replacement).
    # Both respect the same notify_status_change preference.
    if complaint.author_id and old_status != payload.status:
        author = (await db.execute(select(User).where(User.id == complaint.author_id))).scalar_one_or_none()
        if author and author.notify_status_change:
            status_labels = {
                "open": "Open", "in_progress": "In progress",
                "resolved": "Resolved ✓", "disputed": "Disputed", "rejected": "Rejected",
            }
            status_value = payload.status.value if hasattr(payload.status, "value") else str(payload.status)
            new_label = status_labels.get(status_value, status_value)

            if author.telegram_chat_id:
                text = (
                    f"📋 Update on your complaint (ID {complaint_id[:8]}):\n"
                    f"Status is now: {new_label}"
                )
                if payload.note:
                    text += f"\nNote from {official.name}: {payload.note}"
                if payload.status == ComplaintStatus.resolved:
                    text += "\n\nNot actually fixed? You can dispute this on the website."
                await tg_send(author.telegram_chat_id, text)

            complaint_title = (complaint.text_translated or complaint.text_original or "")[:80]
            await send_status_update_email(
                author.email, author.name, complaint_id, complaint_title,
                status_value, payload.note, official.name,
            )

    # Map reactivity + "My Neighborhood" alerts both key off this: a resolved
    # complaint drops off /stats/map (default status_filter="open") and
    # nearby subscribers get told it's fixed, in the same request that
    # resolved it rather than on a delay.
    if payload.status == ComplaintStatus.resolved and old_status != ComplaintStatus.resolved and complaint.category != ComplaintCategory.corruption:
        await notify_nearby_subscribers(db, complaint, "resolved")

    return {
        "complaint_id": complaint_id,
        "old_status": old_status,
        "new_status": payload.status,
        "updated_by": official.name,
    }


# ── DISPUTE (citizen — only the original author, only on a resolved complaint) ─
@router.post("/{complaint_id}/dispute", response_model=dict)
async def dispute_complaint(
    complaint_id: str,
    payload: DisputeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if complaint.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the original complainant can dispute this resolution")

    if complaint.status != ComplaintStatus.resolved:
        raise HTTPException(
            status_code=400,
            detail=f"Only a resolved complaint can be disputed (current status: {complaint.status.value})",
        )

    old_status = complaint.status
    complaint.status = ComplaintStatus.disputed

    log = StatusLog(
        complaint_id=complaint_id,
        old_status=old_status,
        new_status=ComplaintStatus.disputed,
        updated_by_id=current_user.id,
        note=payload.note or "Citizen disputed this resolution — marked not actually fixed.",
    )
    db.add(log)

    return {
        "complaint_id": complaint_id,
        "old_status": old_status,
        "new_status": ComplaintStatus.disputed,
        "disputed_by": current_user.name,
    }


# ── TRANSLATE ─────────────────────────────────────────────────────────────────
@router.post("/{complaint_id}/translate", response_model=dict)
async def translate_complaint(
    complaint_id: str,
    payload: TranslateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not check_rate_limit("translate", client_ip(request), 60, 60 * 60):
        raise HTTPException(status_code=429, detail="Too many translations — try again later")
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    text_to_translate = complaint.text_original
    translation = await translate_text(text_to_translate, payload.target_language)
    if not translation.get("ok"):
        raise HTTPException(status_code=503, detail="Translation service is unavailable right now — please try again")

    return {
        "original": text_to_translate,
        "translated": translation.get("translated"),
        "detected_language": translation.get("detected_language"),
        "target_language": payload.target_language,
    }
