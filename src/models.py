import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, Integer, DateTime, Enum as SAEnum,
    ForeignKey, JSON, Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from src.database import Base


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LeadStatus(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"
    opted_out = "opted_out"


class LeadSource(str, enum.Enum):
    instagram_dm = "instagram_dm"
    instagram_comment = "instagram_comment"
    telegram = "telegram"


class Platform(str, enum.Enum):
    instagram = "instagram"
    telegram = "telegram"
    reel = "reel"
    whatsapp = "whatsapp"
    story = "story"
    carousel = "carousel"
    facebook = "facebook"


class PostStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    posted = "posted"
    failed = "failed"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    dead_letter = "dead_letter"


class SequenceStatus(str, enum.Enum):
    sent = "sent"
    failed = "failed"
    opted_out = "opted_out"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ig_handle: Mapped[str] = mapped_column(String, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[LeadStatus] = mapped_column(SAEnum(LeadStatus), default=LeadStatus.warm)
    source: Mapped[str] = mapped_column(SAEnum(LeadSource, name="leadsource"))
    # Tracks when the nurture sequence was triggered (Day 0 DM event).
    # Day 3/7/14 are scheduled relative to this timestamp.
    nurture_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Intent keywords that triggered the nurture (comma-separated, for context)
    intent_keywords: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    sequences: Mapped[list["WhatsappSequence"]] = relationship(back_populates="lead")
    trial: Mapped["AdaptiqTrial | None"] = relationship(back_populates="lead", uselist=False)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform))
    caption_a: Mapped[str] = mapped_column(Text)
    caption_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_variant: Mapped[str] = mapped_column(String, default="a")
    image_url: Mapped[str] = mapped_column(String)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PostStatus] = mapped_column(SAEnum(PostStatus), default=PostStatus.pending)
    ig_post_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Instagram media ID
    fb_post_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Facebook post ID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    analytics: Mapped[list["PostAnalytics"]] = relationship(back_populates="post")


class PostAnalytics(Base):
    __tablename__ = "post_analytics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("posts.id"))
    reach: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    dm_triggers: Mapped[int] = mapped_column(Integer, default=0)
    story_views: Mapped[int] = mapped_column(Integer, default=0)
    link_clicks: Mapped[int] = mapped_column(Integer, default=0)
    winner_variant: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    post: Mapped["Post"] = relationship(back_populates="analytics")


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    agent_name: Mapped[str] = mapped_column(String)
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), default=JobStatus.pending)
    payload: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WhatsappSequence(Base):
    __tablename__ = "whatsapp_sequences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"))
    day_number: Mapped[int] = mapped_column(Integer)  # 0, 1, 3, 7, or 14
    template_name: Mapped[str] = mapped_column(String)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    status: Mapped[SequenceStatus] = mapped_column(SAEnum(SequenceStatus))

    lead: Mapped["Lead"] = relationship(back_populates="sequences")


class Admission(Base):
    """Tracks real admissions for accurate revenue reporting."""
    __tablename__ = "admissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    student_name: Mapped[str] = mapped_column(String)
    course_type: Mapped[str] = mapped_column(String)  # full_batch, prelims, test_series, mentorship
    fee_paid: Mapped[int] = mapped_column(Integer)     # in INR
    payment_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # instagram, whatsapp, direct
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AdaptiqTrial(Base):
    __tablename__ = "adaptiq_trials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), unique=True)
    trial_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str | None] = mapped_column(String, nullable=True)
    # Enhanced tracking fields
    source_post_id: Mapped[str | None] = mapped_column(String, nullable=True)   # which post drove signup
    weak_subjects: Mapped[str | None] = mapped_column(String, nullable=True)    # comma-separated string
    improvement_pct: Mapped[int] = mapped_column(Integer, default=0)
    webinar_attended: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_initiated: Mapped[bool] = mapped_column(Boolean, default=False)
    day1_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    day3_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    day5_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    day7_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    lead: Mapped["Lead"] = relationship(back_populates="trial")
