"""Fix AdaptiqTrial column types — Integer booleans to Boolean, improvement_pct nullable to default 0

Revision ID: 003
Revises: 002
Create Date: 2026-05-10 00:00:00.000000

Changes:
  - webinar_attended, demo_booked, payment_initiated, day1-7_sent: INTEGER -> BOOLEAN
  - improvement_pct: nullable INTEGER -> INTEGER DEFAULT 0
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOOL_COLS = [
    "webinar_attended",
    "demo_booked",
    "payment_initiated",
    "day1_sent",
    "day3_sent",
    "day5_sent",
    "day7_sent",
]


def upgrade() -> None:
    # Convert Integer 0/1 columns to proper Boolean
    for col in BOOL_COLS:
        op.execute(f"ALTER TABLE adaptiq_trials ALTER COLUMN {col} TYPE BOOLEAN USING {col}::boolean")
        op.execute(f"ALTER TABLE adaptiq_trials ALTER COLUMN {col} SET DEFAULT FALSE")
        op.execute(f"ALTER TABLE adaptiq_trials ALTER COLUMN {col} SET NOT NULL")

    # Fix improvement_pct — set default 0 and make not nullable
    op.execute("UPDATE adaptiq_trials SET improvement_pct = 0 WHERE improvement_pct IS NULL")
    op.execute("ALTER TABLE adaptiq_trials ALTER COLUMN improvement_pct SET DEFAULT 0")
    op.execute("ALTER TABLE adaptiq_trials ALTER COLUMN improvement_pct SET NOT NULL")


def downgrade() -> None:
    for col in BOOL_COLS:
        op.execute(f"ALTER TABLE adaptiq_trials ALTER COLUMN {col} TYPE INTEGER USING {col}::integer")
        op.execute(f"ALTER TABLE adaptiq_trials ALTER COLUMN {col} SET DEFAULT 0")

    op.execute("ALTER TABLE adaptiq_trials ALTER COLUMN improvement_pct DROP NOT NULL")
