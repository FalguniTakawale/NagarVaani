from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr

from app.models.models import ComplaintCategory, ComplaintStatus, OfficialLevel, UserRole


# ── COMPLAINTS ────────────────────────────────────────────────────────────────
class ImageIn(BaseModel):
    url: str
    caption: Optional[str] = None
    is_360: bool = False


class ComplaintCreate(BaseModel):
    text: str
    # Normally the classifier decides the category. The corruption page pins it
    # so a bribery report can't be filed under "other" by a hesitant model.
    category: Optional[ComplaintCategory] = None
    anonymous: bool = False  # drop author_id even when logged in
    location_text: Optional[str] = None
    ward: Optional[str] = None
    area: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    images: Optional[List[ImageIn]] = None


class ComplaintListItem(BaseModel):
    id: str
    text_original: str
    category: Optional[ComplaintCategory] = None
    priority_score: float
    status: ComplaintStatus
    vote_count: int = 0
    created_at: Optional[datetime] = None


class ComplaintOut(ComplaintListItem):
    text_translated: Optional[str] = None
    detected_language: Optional[str] = None
    score_breakdown: dict = {}
    is_safety_risk: bool = False
    official_brief: Optional[str] = None
    recommended_action: Optional[str] = None


# ── VOTES ─────────────────────────────────────────────────────────────────────
class VoteCreate(BaseModel):
    is_solidarity: Optional[bool] = None


class VoteOut(BaseModel):
    id: str
    complaint_id: str
    is_solidarity: bool
    created_at: Optional[datetime] = None


# ── COMMENTS ──────────────────────────────────────────────────────────────────
class CommentCreate(BaseModel):
    text: str
    author_name: Optional[str] = None
    author_area: Optional[str] = None


class CommentOut(BaseModel):
    id: str
    text: str
    author_name: Optional[str] = None
    author_area: Optional[str] = None
    detected_places: List[str] = []
    created_at: Optional[datetime] = None


# ── LINKED AREAS / STATUS ─────────────────────────────────────────────────────
class LinkAreaCreate(BaseModel):
    area_name: Optional[str] = None


class StatusUpdate(BaseModel):
    status: ComplaintStatus
    note: Optional[str] = None


class DisputeCreate(BaseModel):
    note: Optional[str] = None


# ── TRANSLATION ───────────────────────────────────────────────────────────────
class TranslateRequest(BaseModel):
    target_language: str = "en"


class TranslateResponse(BaseModel):
    original: str
    translated: str
    detected_language: Optional[str] = None


# ── AUTH ──────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.citizen
    official_level: Optional[OfficialLevel] = None  # only meaningful when role=official
    state: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    ward: Optional[str] = None
    preferred_language: Optional[str] = "en"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RegisterOut(BaseModel):
    message: str
    user_id: str
    email: EmailStr
    requires_verification: bool = True


class VerifyEmailRequest(BaseModel):
    user_id: str
    otp: str


class ResendOtpRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    id: str
    role: UserRole
    official_level: Optional[OfficialLevel] = None
    name: str
    ward: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    area: Optional[str] = None
