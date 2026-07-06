"""add messages.tool_calls jsonb column

Revision ID: f6e0cafe0006
Revises: e5d0cafe0005
Create Date: 2026-07-05 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "f6e0cafe0006"
down_revision: str | Sequence[str] | None = "e5d0cafe0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable tool_calls JSONB column to messages."""
    op.add_column("messages", sa.Column("tool_calls", JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the tool_calls column from messages."""
    op.drop_column("messages", "tool_calls")
