"""add updated_at to users and messages

Revision ID: b23789cc3517
Revises: c2e9f8a31b05
Create Date: 2026-07-03 11:31:15.678983

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b23789cc3517"
down_revision: str | Sequence[str] | None = "c2e9f8a31b05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add updated_at column to users and messages tables."""
    op.add_column(
        "messages",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove updated_at column from users and messages tables."""
    op.drop_column("users", "updated_at")
    op.drop_column("messages", "updated_at")
