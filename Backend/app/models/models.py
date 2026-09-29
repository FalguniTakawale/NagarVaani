from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, Enum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
import uuid
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    citizen = "citizen"
    official = "official"


class OfficialLevel(str, enum.Enum):
    """Jurisdiction level for role=official. Determines the dashboard's default
    scope, not what it can access — any official can still explore nationwide."""
    ward_officer = "ward_officer"    # jurisdiction: ward
    municipal = "municipal"          # jurisdiction: city
    district = "district"            # jurisdiction: city (no separate district field yet)
    state = "state"                  # jurisdiction: state
    central = "central"              # jurisdiction: nationwide


class OfficialVerificationStatus(str, enum.Enum):
    """There's no real government employee registry to check a signup
    against, so official access is gated two ways instead: the signup email
    can't be a personal-provider address, and an admin has to approve the
    account before it gets official-only access. Only meaningful when role=official."""
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ComplaintStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    disputed = "disputed"
    rejected = "rejected"


class ComplaintCategory(str, enum.Enum):
    drainage = "drainage"
    road = "road"
    garbage = "garbage"
    electricity = "electricity"
    tree_hazard = "tree_hazard"
    water_supply = "water_supply"
    corruption = "corruption"
    other = "other"


# ── USER ──────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.citizen, nullable=False)
    official_level = Column(Enum(OfficialLevel), nullable=True)  # only meaningful when role=official
    official_status = Column(Enum(OfficialVerificationStatus), nullable=True)  # only meaningful when role=official
    # The work email they applied with — kept around after approval replaces
    # `email` with a system-issued one, so admins can see who they're vetting.
    requested_email = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    # Google Sign-In. auth_provider stays "password" for accounts that have
    # ever set a real password (even if they later also link Google), so
    # "forgot password" keeps working for them either way. google_sub is
    # Google's own stable per-account id — matched first, ahead of email, so
    # a later email change on the Google side can't orphan the link.
    auth_provider = Column(String(20), default="password", nullable=False)
    google_sub = Column(String(255), nullable=True, unique=True, index=True)

    # Location
    state = Column(String(100))
    city = Column(String(100))
    area = Column(String(100))
    ward = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)

    preferred_language = Column(String(10), default="en")
    is_email_verified = Column(Boolean, default=False, nullable=False)
    telegram_chat_id = Column(String(50), nullable=True, index=True)
    notify_status_change = Column(Boolean, default=True)
    notify_linked = Column(Boolean, default=True)
    notify_digest = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    complaints = relationship("Complaint", back_populates="author")
    votes = relationship("Vote", back_populates="user")


# ── EMAIL VERIFICATION (signup OTP) ───────────────────
class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    otp_hash = Column(String, nullable=False)   # bcrypt of the 6-digit code — never the code itself
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── PASSWORD RESET (forgot-password OTP) ──────────────
class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    otp_hash = Column(String, nullable=False)   # bcrypt of the 6-digit code — never the code itself
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── DISTRICT / AREA ───────────────────────────────────
class District(Base):
    __tablename__ = "districts"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False, index=True)
    ward = Column(String(50))
    city = Column(String(100))
    state = Column(String(100))
    population = Column(Integer, default=10000)
    latitude = Column(Float)
    longitude = Column(Float)

    # Seasonal data — months 1-12 mapped to season labels
    # e.g. {"6": "monsoon", "7": "monsoon", "8": "monsoon", "12": "winter"}
    seasonal_data = Column(JSON, default={})


# ── COMPLAINT ─────────────────────────────────────────
class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String, primary_key=True, default=gen_uuid)
    author_id = Column(String, ForeignKey("users.id"), nullable=True)  # nullable = anonymous

    # Content
    text_original = Column(Text, nullable=False)
    text_translated = Column(Text)           # AI-translated to English
    detected_language = Column(String(10))

    # Classification (set by AI)
    category = Column(Enum(ComplaintCategory), nullable=True)
    category_confidence = Column(Float, default=0.0)

    # Location
    location_text = Column(String(255))      # user typed
    ward = Column(String(50))
    area = Column(String(100))
    city = Column(String(100))
    state = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)

    # AI scoring
    priority_score = Column(Float, default=0.0)
    score_breakdown = Column(JSON, default={})   # {l1, l2, l3, l4, l5, l6, multiplier}
    is_safety_risk = Column(Boolean, default=False)
    seasonal_multiplier = Column(Float, default=1.0)

    # Media
    image_urls = Column(JSON, default=[])        # [{url, caption, is_360}]
    audio_url = Column(String(500))              # voice note (web mic or Telegram), if any

    # Ingestion channel
    source_channel = Column(String(20), default="web")  # web | telegram | whatsapp

    # Status
    status = Column(Enum(ComplaintStatus), default=ComplaintStatus.open)
    is_ai_filtered = Column(Boolean, default=False)  # True = passed AI filter
    filter_reason = Column(Text)                     # if rejected

    # Cross-district
    linked_area_count = Column(Integer, default=0)

    # AI-generated brief for officials
    official_brief = Column(Text)
    recommended_action = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    author = relationship("User", back_populates="complaints")
    votes = relationship("Vote", back_populates="complaint", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="complaint", cascade="all, delete-orphan")
    status_logs = relationship("StatusLog", back_populates="complaint", cascade="all, delete-orphan")
    linked_areas = relationship("LinkedArea", back_populates="complaint", cascade="all, delete-orphan")

    @property
    def vote_count(self):
        return len(self.votes) if self.votes else 0


# ── VOTE ──────────────────────────────────────────────
class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True, default=gen_uuid)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    is_solidarity = Column(Boolean, default=False)  # True = voter from different area
    voter_area = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    complaint = relationship("Complaint", back_populates="votes")
    user = relationship("User", back_populates="votes")


# ── COMMENT ───────────────────────────────────────────
class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=gen_uuid)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)
    author_id = Column(String, ForeignKey("users.id"), nullable=True)
    author_name = Column(String(100))          # display name
    author_area = Column(String(100))          # for display

    text = Column(Text, nullable=False)
    detected_places = Column(JSON, default=[]) # places NLP found in this comment
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    complaint = relationship("Complaint", back_populates="comments")


# ── LINKED AREA ───────────────────────────────────────
class LinkedArea(Base):
    __tablename__ = "linked_areas"

    id = Column(String, primary_key=True, default=gen_uuid)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)
    area_name = Column(String(100), nullable=False)
    link_type = Column(String(20), default="button")  # "button" or "nlp"
    complaint_count = Column(Integer, default=1)
    linked_at = Column(DateTime(timezone=True), server_default=func.now())

    complaint = relationship("Complaint", back_populates="linked_areas")


# ── STATUS LOG ────────────────────────────────────────
class StatusLog(Base):
    __tablename__ = "status_log"

    id = Column(String, primary_key=True, default=gen_uuid)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False)
    old_status = Column(Enum(ComplaintStatus))
    new_status = Column(Enum(ComplaintStatus), nullable=False)
    updated_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    complaint = relationship("Complaint", back_populates="status_logs")


# ── NEIGHBORHOOD SUBSCRIPTION ─────────────────────────
class NeighborhoodSubscription(Base):
    """"My Neighborhood" email alerts — a real Brevo-sent email (see
    email.py) whenever a complaint is reported or resolved within
    `radius_km` of this point. No phone/SMS field on purpose: there's no SMS
    provider wired into this app, so offering one would be a UI promise the
    backend can't keep."""
    __tablename__ = "neighborhood_subscriptions"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String(255), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_km = Column(Float, default=1.6)  # ~1 mile
    label = Column(String(150), nullable=True)  # e.g. "Shivaji Nagar, Pune" — for the confirmation email
    is_active = Column(Boolean, default=True, nullable=False)
    unsubscribe_token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── CITIZEN REPORT (the "⚑ Flag" button on a complaint) ──
class ComplaintReport(Base):
    """A citizen flagging a complaint as spam / fake / abusive / duplicate.
    Goes to the admin review queue (GET /api/admin/reports) — it does NOT
    hide the complaint automatically, so it can't be used to silence one.
    One report per signed-in user or per IP per complaint."""
    __tablename__ = "complaint_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    complaint_id = Column(String, ForeignKey("complaints.id"), nullable=False, index=True)
    reporter_id = Column(String, ForeignKey("users.id"), nullable=True)
    reporter_key = Column(String(80), nullable=False)  # "u:<user id>" or "ip:<addr>" — dedupe key
    reason = Column(String(30), nullable=False)        # spam | fake | abusive | duplicate | other
    note = Column(String(500), nullable=True)
    resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
