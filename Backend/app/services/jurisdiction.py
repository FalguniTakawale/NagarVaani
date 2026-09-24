"""Jurisdiction scoping for officials. Same rules as scope=jurisdiction in the
complaints list: a *default view* by level, never an access restriction."""

from app.models.models import Complaint, OfficialLevel, User


def apply_jurisdiction(q, official: User):
    level = official.official_level
    if level == OfficialLevel.ward_officer and official.ward:
        return q.where(Complaint.ward == official.ward)
    if level in (OfficialLevel.municipal, OfficialLevel.district) and official.city:
        return q.where(Complaint.city == official.city)
    if level == OfficialLevel.state and official.state:
        return q.where(Complaint.state == official.state)
    return q  # central / unset: nationwide


def jurisdiction_label(official: User) -> str:
    level = official.official_level
    if level == OfficialLevel.ward_officer and official.ward:
        return f"Ward {official.ward}" + (f" · {official.city}" if official.city else "")
    if level in (OfficialLevel.municipal, OfficialLevel.district) and official.city:
        return official.city
    if level == OfficialLevel.state and official.state:
        return official.state
    return "Nationwide"
