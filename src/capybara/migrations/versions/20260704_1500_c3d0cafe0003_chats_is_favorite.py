"""add chats.is_favorite

Revision ID: c3d0cafe0003
Revises: b2d0cafe0002
Create Date: 2026-07-04 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d0cafe0003"
down_revision: str | Sequence[str] | None = "b2d0cafe0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the non-null is_favorite column defaulting to false."""
    op.add_column(
        "chats",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Drop the is_favorite column."""
    op.drop_column("chats", "is_favorite")
