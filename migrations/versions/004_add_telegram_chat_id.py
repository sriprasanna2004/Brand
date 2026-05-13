"""Add telegram_chat_id to leads table

Revision ID: 004
Revises: 003
Create Date: 2026-05-13 00:00:00.000000

Adds telegram_chat_id column to leads so nurture messages can be sent
directly to leads via Telegram bot when they message the bot.
Priority: Telegram > WhatsApp (no restrictions, no approval needed).
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("telegram_chat_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "telegram_chat_id")
