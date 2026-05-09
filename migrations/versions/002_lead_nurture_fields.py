"""Add nurture_enrolled_at and intent_keywords to leads

Revision ID: 002
Revises: 001
Create Date: 2026-05-09 00:00:00.000000

Adds two columns to the leads table to support the event-driven nurture
sequence:
  - nurture_enrolled_at: UTC timestamp of the DM that triggered the sequence.
    Day 3/7/14 Celery ETA tasks are scheduled relative to this.
  - intent_keywords: comma-separated keywords detected in the original DM
    (e.g. "fees,batch"). Passed to LeadNurtureAgent for personalised messages.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "nurture_enrolled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "intent_keywords",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("leads", "intent_keywords")
    op.drop_column("leads", "nurture_enrolled_at")
