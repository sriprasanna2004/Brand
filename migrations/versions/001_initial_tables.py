"""Initial tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    leadstatus = sa.Enum("hot", "warm", "cold", "opted_out", name="leadstatus")
    leadsource = sa.Enum("instagram_dm", "instagram_comment", "telegram", name="leadsource")
    platform = sa.Enum("instagram", "telegram", name="platform")
    poststatus = sa.Enum("pending", "approved", "posted", "failed", name="poststatus")
    jobstatus = sa.Enum("pending", "running", "success", "failed", "dead_letter", name="jobstatus")
    sequencestatus = sa.Enum("sent", "failed", "opted_out", name="sequencestatus")

    for e in (leadstatus, leadsource, platform, poststatus, jobstatus, sequencestatus):
        e.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ig_handle", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("status", sa.Enum("hot", "warm", "cold", "opted_out", name="leadstatus"), nullable=False),
        sa.Column("source", sa.Enum("instagram_dm", "instagram_comment", "telegram", name="leadsource"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ig_handle", name="uq_leads_ig_handle"),
    )
    op.create_index("ix_leads_ig_handle", "leads", ["ig_handle"], unique=True)

    op.create_table(
        "posts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.Enum("instagram", "telegram", name="platform"), nullable=False),
        sa.Column("caption_a", sa.Text(), nullable=False),
        sa.Column("caption_b", sa.Text(), nullable=True),
        sa.Column("active_variant", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Enum("pending", "approved", "posted", "failed", name="poststatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_posts_scheduled_at", "posts", ["scheduled_at"])

    op.create_table(
        "post_analytics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", UUID(as_uuid=True), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("reach", sa.Integer(), nullable=False),
        sa.Column("saves", sa.Integer(), nullable=False),
        sa.Column("dm_triggers", sa.Integer(), nullable=False),
        sa.Column("story_views", sa.Integer(), nullable=False),
        sa.Column("link_clicks", sa.Integer(), nullable=False),
        sa.Column("winner_variant", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agent_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "success", "failed", "dead_letter", name="jobstatus"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", name="uq_agent_jobs_job_id"),
    )
    op.create_index("ix_agent_jobs_job_id", "agent_jobs", ["job_id"], unique=True)

    op.create_table(
        "whatsapp_sequences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("template_name", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Enum("sent", "failed", "opted_out", name="sequencestatus"), nullable=False),
    )

    op.create_table(
        "adaptiq_trials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("trial_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan", sa.String(), nullable=True),
        sa.UniqueConstraint("lead_id", name="uq_adaptiq_trials_lead_id"),
    )


def downgrade() -> None:
    op.drop_table("adaptiq_trials")
    op.drop_table("whatsapp_sequences")
    op.drop_table("agent_jobs")
    op.drop_table("post_analytics")
    op.drop_table("posts")
    op.drop_table("leads")

    for name in ("sequencestatus", "jobstatus", "poststatus", "platform", "leadsource", "leadstatus"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
