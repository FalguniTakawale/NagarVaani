from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.models import ComplaintCategory, ComplaintStatus, OfficialLevel, OfficialVerificationStatus, UserRole


# ── COMPLAINTS ────────────────────────────────────────────────────────────────
class ImageIn(BaseModel):
    url: str = Field(..., max_length=2048)
    caption: Optional[str] = Field(None, max_length=300)
    is_360: bool = False

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("Image URL must be http(s)")
        return v


class ComplaintCreate(BaseModel):
    text: str = Field(..., min_length=3, max_length=5000)
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
    images: Optional[List[ImageIn]] = Field(None, max_length=10)


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
    text: str = Field(..., min_length=1, max_length=2000)
    author_name: Optional[str] = Field(None, max_length=100)
    author_area: Optional[str] = Field(None, max_length=100)


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
    password: str = Field(..., max_length=72)  # bcrypt limit
    role: UserRole = UserRole.citizen
    official_level: Optional[OfficialLevel] = None  # only meaningful when role=official
    state: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    ward: Optional[str] = None
    preferred_language: Optional[str] = "en"


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)  # bcrypt limit


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
    new_password: str = Field(..., max_length=72)


class GoogleAuthRequest(BaseModel):
    credential: str  # the ID token Google Identity Services hands back


class GoogleConfigOut(BaseModel):
    enabled: bool
    client_id: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    id: str
    role: UserRole
    official_level: Optional[OfficialLevel] = None
    official_status: Optional[OfficialVerificationStatus] = None
    is_admin: bool = False
    name: str
    email: Optional[EmailStr] = None
    ward: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    area: Optional[str] = None
    telegram_chat_id: Optional[str] = None


# ── ADMIN: OFFICIAL VERIFICATION ────────────────────────────────────────────
class PendingOfficialOut(BaseModel):
    id: str
    name: str
    requested_email: Optional[str] = None
    official_level: Optional[OfficialLevel] = None
    state: Optional[str] = None
    city: Optional[str] = None
    ward: Optional[str] = None
    created_at: Optional[datetime] = None


class ApproveOfficialOut(BaseModel):
    message: str
    new_email: str
    temporary_password: str
    emailed: bool


class RejectOfficialRequest(BaseModel):
    reason: Optional[str] = None


# ── NEIGHBORHOOD SUBSCRIPTION ────────────────────────────────────────────────
class NeighborhoodSubscribeRequest(BaseModel):
    email: EmailStr
    latitude: float
    longitude: float
    radius_km: float = 1.6
    label: Optional[str] = None
