from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Comment, Complaint, ComplaintStatus, User
from app.services.auth import require_official
from app.services.jurisdiction import apply_jurisdiction, jurisdiction_label

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/ward")
async def ward_stats(ward: str = Query(...), db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count(Complaint.id)).where(Complaint.ward == ward))
    critical = await db.execute(
        select(func.count(Complaint.id)).where(Complaint.ward == ward, Complaint.is_safety_risk == True)
    )
    resolved = await db.execute(
        select(func.count(Complaint.id)).where(Complaint.ward == ward, Complaint.status == ComplaintStatus.resolved)
    )
    in_progress = await db.execute(
        select(func.count(Complaint.id)).where(Complaint.ward == ward, Complaint.status == ComplaintStatus.in_progress)
    )

    return {
        "ward": ward,
        "open": total.scalar() or 0,
        "critical": critical.scalar() or 0,
        "resolved": resolved.scalar() or 0,
        "in_progress": in_progress.scalar() or 0,
    }


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


@router.get("/nationwide")
async def nationwide_stats(db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count(Complaint.id)))
    critical = await db.execute(select(func.count(Complaint.id)).where(Complaint.is_safety_risk == True))
    resolved = await db.execute(select(func.count(Complaint.id)).where(Complaint.status == ComplaintStatus.resolved))

    by_state = await db.execute(
        select(Complaint.state, func.count(Complaint.id), func.avg(Complaint.priority_score))
        .where(Complaint.state.isnot(None))
        .group_by(Complaint.state)
        .order_by(func.avg(Complaint.priority_score).desc())
    )

    return {
        "total": total.scalar() or 0,
        "critical": critical.scalar() or 0,
        "resolved": resolved.scalar() or 0,
        "hotspots_by_state": [
            {"state": state, "complaint_count": count, "avg_score": round(avg_score or 0, 1)}
            for state, count, avg_score in by_state.all()
        ],
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
