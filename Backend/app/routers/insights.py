"""
Policy insights — turns complaints (+ any ingested external datasets) into a
ranked list of demand hotspots with a *suggested project type* for each.

What is real here: the aggregation (counts, severity sums, cross-area links) is
computed live from the complaints table. What is deliberately NOT here: cost
estimates or budget figures — there is no cost dataset, so none are invented.
"Suggested project" is a transparent rule (category → generic project type), not
a model output, and every row says which datasets it used and which are missing.
"""
import csv
import io
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Complaint, ComplaintCategory, ComplaintStatus, RegionIndicator, User
from app.services.auth import require_admin, require_official
from app.services.jurisdiction import apply_jurisdiction

router = APIRouter(prefix="/insights", tags=["insights"])

DEFAULT_POPULATION = 10000
MAX_ROWS = 5000

PROJECT_TYPES = {
    "drainage": "Storm-water drain desilting / capacity upgrade",
    "water_supply": "Water-supply pipeline repair or augmentation",
    "road": "Road resurfacing / pothole-repair programme",
    "electricity": "Feeder / transformer / street-lighting upgrade",
    "garbage": "Waste-collection route and bin-coverage improvement",
    "tree_hazard": "Tree-hazard survey and pruning drive",
    "other": "Field assessment by the ward office",
}


async def population_for(db: AsyncSession, city: str | None, state: str | None = None) -> int:
    """Real population from an ingested dataset if one covers this city, else the
    prototype default. Newest year wins."""
    if not city:
        return DEFAULT_POPULATION
    q = select(RegionIndicator.value).where(
        RegionIndicator.indicator == "population", func.lower(RegionIndicator.city) == city.strip().lower()
    ).order_by(RegionIndicator.year.desc().nullslast()).limit(1)
    val = (await db.execute(q)).scalar_one_or_none()
    return int(val) if val and val > 0 else DEFAULT_POPULATION


class IndicatorRow(BaseModel):
    country: str = Field(default="India", max_length=60)
    state: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    indicator: str = Field(pattern=r"^[a-z0-9_]{2,60}$")
    value: float
    year: int | None = Field(default=None, ge=1900, le=2100)
    source: str = Field(min_length=3, max_length=200)  # provenance is mandatory


class IndicatorUpload(BaseModel):
    rows: list[IndicatorRow] = Field(max_length=MAX_ROWS)


@router.post("/indicators")
async def upload_indicators(payload: IndicatorUpload, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin-only JSON ingestion of an external dataset (census population, infra
    index, planned investment …). Every row must name its source."""
    for r in payload.rows:
        db.add(RegionIndicator(**r.model_dump()))
    await db.flush()
    return {"inserted": len(payload.rows)}


@router.post("/indicators/csv")
async def upload_indicators_csv(file: UploadFile, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Same as above from a CSV: country,state,city,indicator,value,year,source (max 1 MB)."""
    raw = await file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV too large (max 1 MB)")
    rows = []
    try:
        for i, rec in enumerate(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))):
            if i >= MAX_ROWS:
                raise HTTPException(status_code=413, detail=f"Too many rows (max {MAX_ROWS})")
            rec = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in rec.items() if k}
            rec["year"] = int(rec["year"]) if rec.get("year") else None
            rec["country"] = rec.get("country") or "India"
            rows.append(IndicatorRow(**rec))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {str(e)[:200]}")
    for r in rows:
        db.add(RegionIndicator(**r.model_dump()))
    await db.flush()
    return {"inserted": len(rows)}


@router.get("/datasets")
async def dataset_status(db: AsyncSession = Depends(get_db), official: User = Depends(require_official)):
    """What external data is actually loaded — the honest 'data coverage' view."""
    rows = (await db.execute(
        select(RegionIndicator.country, RegionIndicator.indicator, func.count(RegionIndicator.id), func.max(RegionIndicator.year))
        .group_by(RegionIndicator.country, RegionIndicator.indicator)
    )).all()
    return [{"country": c, "indicator": i, "rows": n, "latest_year": y} for c, i, n, y in rows]


@router.get("/priority-projects")
async def priority_projects(limit: int = 15, db: AsyncSession = Depends(get_db), official: User = Depends(require_official)):
    """Ranked demand hotspots (city × category) inside the official's jurisdiction.

    demand_index = sum of priority scores of unresolved complaints — i.e. weighted
    by severity/season/pattern, NOT by vote count. If a population dataset covers
    the city, `reports_per_100k` is also given. No cost figures — none are invented."""
    limit = max(1, min(limit, 50))
    open_states = [ComplaintStatus.open, ComplaintStatus.in_progress, ComplaintStatus.disputed]
    q = apply_jurisdiction(
        select(Complaint).where(
            Complaint.is_ai_filtered == True, Complaint.status.in_(open_states),
            Complaint.category != ComplaintCategory.corruption, Complaint.city.isnot(None),
        ),
        official,
    )
    complaints = (await db.execute(q)).scalars().all()

    groups: dict[tuple, list[Complaint]] = defaultdict(list)
    for c in complaints:
        cat = c.category.value if hasattr(c.category, "value") else (c.category or "other")
        groups[(c.state or "", c.city, cat)].append(c)

    indicator_rows = (await db.execute(select(RegionIndicator))).scalars().all()
    by_city: dict[str, dict[str, float]] = defaultdict(dict)
    for r in sorted(indicator_rows, key=lambda r: r.year or 0):
        if r.city:
            by_city[r.city.lower()][r.indicator] = r.value

    out = []
    for (state, city, cat), items in groups.items():
        items.sort(key=lambda c: c.priority_score or 0, reverse=True)
        ind = by_city.get(city.lower(), {})
        pop = ind.get("population")
        n = len(items)
        critical = sum(1 for c in items if c.is_safety_risk or (c.priority_score or 0) >= 80)
        label = cat.replace("_", " ")
        out.append({
            "state": state or None, "city": city, "category": cat,
            "open_reports": n, "critical_reports": critical,
            "demand_index": round(sum(c.priority_score or 0 for c in items), 1),
            "avg_score": round(sum(c.priority_score or 0 for c in items) / n, 1),
            "linked_areas_total": sum(c.linked_area_count or 0 for c in items),
            "reports_per_100k": round(n / pop * 100000, 2) if pop else None,
            "suggested_project": PROJECT_TYPES.get(cat, PROJECT_TYPES["other"]),
            "rationale": (f"{n} unresolved {label} report(s) in {city}, {critical} safety-critical, "
                          f"reported across {sum(c.linked_area_count or 0 for c in items)} linked area(s)."),
            "evidence_complaint_ids": [c.id for c in items[:3]],
            "external_data_used": sorted(ind.keys()),
            "external_data_missing": [k for k in ("population", "infra_index", "planned_investment") if k not in ind],
            "cost_estimate": None,   # intentionally absent — no cost dataset
        })
    out.sort(key=lambda r: r["demand_index"], reverse=True)
    return {
        "generated_from": "live complaints table + region_indicators",
        "method": "rule-based ranking (sum of priority scores); suggested project is a category→project-type mapping, not a forecast",
        "hotspots": out[:limit],
    }
