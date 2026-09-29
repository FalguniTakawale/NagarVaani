from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Comment, Complaint, ComplaintCategory, ComplaintStatus, StatusLog, User
from app.services.auth import require_official, require_user
from app.services.jurisdiction import apply_jurisdiction, jurisdiction_label

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/ward")
async def ward_stats(
    ward: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Real counts for a location — ward if given, else city, else nationwide.
    Used by both the official portal's stat tiles and the citizen right-panel
    dashboard, so the scope fallback here matters to both."""
    if ward:
        scope_cond = Complaint.ward == ward
        label = f"Ward {ward}"
    elif city:
        scope_cond = Complaint.city == city
        label = city
    else:
        scope_cond = true()
        label = "Nationwide"

    async def count(*extra):
        q = select(func.count(Complaint.id)).where(scope_cond, Complaint.is_ai_filtered == True, *extra)
        return (await db.execute(q)).scalar() or 0

    open_count = await count(Complaint.status == ComplaintStatus.open)
    in_progress = await count(Complaint.status == ComplaintStatus.in_progress)
    resolved = await count(Complaint.status == ComplaintStatus.resolved)
    # Same "critical" definition already used for officials' jurisdiction
    # stats — high-priority and not yet closed out.
    critical = await count(Complaint.priority_score >= 80, Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.disputed]))
    total = await count()
    resolved_pct = round(resolved / total * 100) if total else 0

    return {
        "ward": ward,
        "label": label,
        "open": open_count,
        "critical": critical,
        "resolved": resolved,
        "in_progress": in_progress,
        "total": total,
        "resolved_pct": resolved_pct,
    }


@router.get("/recent-updates")
async def recent_updates(
    ward: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    limit: int = Query(3, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Real recent official status changes for the right-panel "Govt updates"
    widget — same ward/city/nationwide fallback as /stats/ward. Genuinely
    empty (not padded with fake rows) when nothing has changed status yet in
    scope, which is honest given how little seed data exists right now."""
    q = (
        select(StatusLog, Complaint)
        .join(Complaint, StatusLog.complaint_id == Complaint.id)
        .where(Complaint.is_ai_filtered == True)
    )
    if ward:
        q = q.where(Complaint.ward == ward)
    elif city:
        q = q.where(Complaint.city == city)
    q = q.order_by(desc(StatusLog.created_at)).limit(limit)
    rows = (await db.execute(q)).all()

    return [
        {
            "complaint_id": complaint.id,
            "title": (complaint.text_translated or complaint.text_original)[:60],
            "status": log.new_status,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log, complaint in rows
    ]


@router.get("/my-updates")
async def my_updates(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Real status changes on complaints THIS user filed — what the
    notification bell shows. Anonymous complaints have no author_id, so
    they never appear here (correctly — there's no account to notify)."""
    q = (
        select(StatusLog, Complaint)
        .join(Complaint, StatusLog.complaint_id == Complaint.id)
        .where(Complaint.author_id == current_user.id)
        .order_by(desc(StatusLog.created_at))
        .limit(limit)
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "complaint_id": complaint.id,
            "title": (complaint.text_translated or complaint.text_original)[:60],
            "status": log.new_status,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log, complaint in rows
    ]


@router.get("/jurisdiction")
async def jurisdiction_stats(db: AsyncSession = Depends(get_db), official: User = Depends(require_official)):
    """Stat tiles + sidebar badges for the official portal, scoped to the
    official's own jurisdiction (ward / city / state / nationwide by level)."""
    async def count(*conds):
        q = apply_jurisdiction(select(func.count(Complaint.id)).where(Complaint.is_ai_filtered == True, *conds), official)
        return (await db.execute(q)).scalar() or 0

    flagged_q = apply_jurisdiction(
        select(func.count(func.distinct(Complaint.id)))
        .join(Comment, Comment.complaint_id == Complaint.id)
        .where(Comment.text.like("[OFFICIAL FLAG]%")),
        official,
    )
    return {
        "jurisdiction": jurisdiction_label(official),
        "level": official.official_level.value if official.official_level else None,
        "open": await count(Complaint.status == ComplaintStatus.open),
        "in_progress": await count(Complaint.status == ComplaintStatus.in_progress),
        "resolved": await count(Complaint.status == ComplaintStatus.resolved),
        "disputed": await count(Complaint.status == ComplaintStatus.disputed),
        "critical": await count(Complaint.priority_score >= 80, Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.disputed])),
        "total": await count(),
        "flagged": (await db.execute(flagged_q)).scalar() or 0,
    }


@router.get("/resolved-this-week")
async def resolved_this_week(db: AsyncSession = Depends(get_db)):
    """Real counts, not a marketing number — how many complaints actually got
    marked resolved (via StatusLog, so it's the true resolution moment, not
    just current status) in the last 7 days, broken down by category. Used
    for the "X issues fixed this week" widget. Genuinely 0 when nothing's
    been resolved yet, same "don't pad with fake rows" rule as
    /stats/recent-updates."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    q = (
        select(Complaint.category, func.count(func.distinct(Complaint.id)))
        .join(StatusLog, StatusLog.complaint_id == Complaint.id)
        .where(
            StatusLog.new_status == ComplaintStatus.resolved,
            StatusLog.created_at >= since,
            Complaint.is_ai_filtered == True,
            Complaint.category != ComplaintCategory.corruption,
        )
        .group_by(Complaint.category)
    )
    rows = (await db.execute(q)).all()
    breakdown = sorted(
        [{"category": cat.value if cat else "other", "count": n} for cat, n in rows if n],
        key=lambda x: -x["count"],
    )
    return {"total": sum(b["count"] for b in breakdown), "breakdown": breakdown, "days": 7}


@router.get("/nationwide")
async def nationwide_stats(db: AsyncSession = Depends(get_db)):
    async def count(*conds):
        q = select(func.count(Complaint.id)).where(Complaint.is_ai_filtered == True, *conds)
        return (await db.execute(q)).scalar() or 0

    total = await count()
    resolved = await count(Complaint.status == ComplaintStatus.resolved)
    still_open = (Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.disputed]),)
    # Same "critical" definition used everywhere else in this app: high
    # priority score, not yet closed out.
    critical = await count(Complaint.priority_score >= 80, *still_open)
    moderate = await count(Complaint.priority_score >= 55, Complaint.priority_score < 80, *still_open)
    # A real, computable stand-in for "needs coordinated investment": a
    # complaint whose priority score itself already factors in how many
    # other areas report the same problem (L5 cross-district pattern bonus).
    linked_clusters = await count(Complaint.linked_area_count >= 2)

    by_state = await db.execute(
        select(Complaint.state, func.count(Complaint.id), func.avg(Complaint.priority_score))
        .where(Complaint.state.isnot(None), Complaint.is_ai_filtered == True)
        .group_by(Complaint.state)
        .order_by(func.avg(Complaint.priority_score).desc())
    )
    hotspots = [
        {"state": state, "complaint_count": c, "avg_score": round(avg_score or 0, 1)}
        for state, c, avg_score in by_state.all()
    ]
    # "Systemic pattern" = more than one report from that state — a genuine,
    # if simple, threshold rather than an invented number.
    states_with_patterns = sum(1 for h in hotspots if h["complaint_count"] > 1)

    return {
        "total": total,
        "critical": critical,
        "moderate": moderate,
        "resolved": resolved,
        "linked_clusters": linked_clusters,
        "states_with_patterns": states_with_patterns,
        "hotspots_by_state": hotspots,
    }


@router.get("/map")
async def map_points(
    scope: str = Query("national", description="national | ward | city | state"),
    ward: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    status_filter: Optional[str] = Query("open"),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Points for the Leaflet hotspot layer — one per complaint with known coordinates."""
    q = select(Complaint).where(
        Complaint.latitude.isnot(None),
        Complaint.longitude.isnot(None),
        Complaint.is_ai_filtered == True,
        # Same rule as the complaints list: corruption reports are never in a
        # public feed, and this map has no login gate — so their pins,
        # which can effectively mark where an accusation was filed, must
        # never appear on it either.
        Complaint.category != ComplaintCategory.corruption,
    )

    if status_filter:
        q = q.where(Complaint.status == status_filter)

    if scope == "ward" and ward:
        q = q.where(Complaint.ward == ward)
    elif scope == "city" and city:
        q = q.where(Complaint.city == city)
    elif scope == "state" and state:
        q = q.where(Complaint.state == state)
    # scope == "national" (default): no geography filter

    q = q.order_by(desc(Complaint.priority_score)).limit(limit)
    result = await db.execute(q)
    complaints = result.scalars().all()

    return [
        {
            "id": c.id,
            "lat": c.latitude,
            "lng": c.longitude,
            "score": c.priority_score,
            "category": c.category,
            "label": (c.text_translated or c.text_original)[:90],
            "linked_area_count": c.linked_area_count,
            "ward": c.ward,
            "city": c.city,
            "state": c.state,
        }
        for c in complaints
    ]


# ── DATA-DRIVEN PROJECT PRIORITIES ────────────────────────────────────────────
# Real, public inputs only: Census of India 2011 state populations (millions)
# and the real central schemes that fund each problem type. No invented costs.
CENSUS_2011_MILLIONS = {
    "Uttar Pradesh": 199.8, "Maharashtra": 112.4, "Bihar": 104.1, "West Bengal": 91.3,
    "Madhya Pradesh": 72.6, "Tamil Nadu": 72.1, "Rajasthan": 68.5, "Karnataka": 61.1,
    "Gujarat": 60.4, "Andhra Pradesh": 49.6, "Odisha": 42.0, "Telangana": 35.0,
    "Kerala": 33.4, "Jharkhand": 33.0, "Assam": 31.2, "Punjab": 27.7,
    "Chhattisgarh": 25.5, "Haryana": 25.4, "Delhi": 16.8, "Uttarakhand": 10.1,
    "Himachal Pradesh": 6.9, "Goa": 1.46,
}
SCHEME_FOR_CATEGORY = {
    "drainage": "AMRUT 2.0 (urban drainage & water)",
    "water_supply": "Jal Jeevan Mission / AMRUT 2.0",
    "garbage": "Swachh Bharat Mission (Urban)",
    "electricity": "Saubhagya / state DISCOM upgrade",
    "road": "PMGSY (rural) / Smart Cities Mission (urban)",
    "tree_hazard": "Municipal horticulture / disaster-management budget",
    "corruption": "Vigilance referral (not an investment item)",
    "other": "Ward-level budget",
}


@router.get("/priorities")
async def project_priorities(
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    official: User = Depends(require_official),
):
    """Ranks (state, problem-type) pairs by unresolved complaint demand, joins
    Census-2011 population for a per-million demand rate, and maps each to the
    real central scheme that would fund it. priority_index is transparent:
    avg severity score × (1 + ln(open complaints)). It is a *triage aid* for
    planners, not a costed project plan."""
    import math
    rows = (await db.execute(
        select(Complaint.state, Complaint.category, func.count(Complaint.id),
               func.avg(Complaint.priority_score), func.sum(Complaint.linked_area_count))
        .where(Complaint.is_ai_filtered == True, Complaint.state.isnot(None),  # noqa: E712
               Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.disputed, ComplaintStatus.in_progress]))
        .group_by(Complaint.state, Complaint.category)
    )).all()
    out = []
    for state, cat, n, avg, linked in rows:
        cat_key = cat.value if hasattr(cat, "value") else str(cat)
        pop = CENSUS_2011_MILLIONS.get(state)
        avg = float(avg or 0)
        out.append({
            "state": state, "category": cat_key, "open_complaints": n,
            "avg_severity": round(avg, 1),
            "population_millions_2011": pop,
            "complaints_per_million": round(n / pop, 3) if pop else None,
            "priority_index": round(avg * (1 + math.log(n)), 1),
            "suggested_funding_scheme": SCHEME_FOR_CATEGORY.get(cat_key, "Ward-level budget"),
        })
    out.sort(key=lambda r: r["priority_index"], reverse=True)
    return {"method": "avg severity × (1 + ln(open complaints)); population = Census 2011",
            "items": out[:limit]}
