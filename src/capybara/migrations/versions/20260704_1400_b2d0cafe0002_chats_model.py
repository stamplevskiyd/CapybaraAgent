"""add chats.model

Revision ID: b2d0cafe0002
Revises: a1c0ffee0001
Create Date: 2026-07-04 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d0cafe0002"
down_revision: str | Sequence[str] | None = "a1c0ffee0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable model column to chats."""
    op.add_column("chats", sa.Column("model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Drop the model column from chats."""
    op.drop_column("chats", "model")
