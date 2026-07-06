"""add messages.memory_saves jsonb column

Revision ID: a7f0cafe0007
Revises: f6e0cafe0006
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a7f0cafe0007"
down_revision: str | Sequence[str] | None = "f6e0cafe0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable memory_saves JSONB column to messages."""
    op.add_column("messages", sa.Column("memory_saves", JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the memory_saves column from messages."""
    op.drop_column("messages", "memory_saves")
