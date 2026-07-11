"""add chat_prefs.mode (fast/smart agent mode)

Revision ID: b2c0cafe000b
Revises: a1c0ffee0001
Create Date: 2026-07-11 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c0cafe000b"
down_revision: str | Sequence[str] | None = "a1c0ffee0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the mode column (default 'fast') and its CHECK constraint."""
    op.add_column(
        "chat_prefs",
        sa.Column("mode", sa.String(length=8), nullable=False, server_default="fast"),
    )
    op.create_check_constraint(
        "mode", "chat_prefs", "mode IN ('fast', 'smart')"
    )


def downgrade() -> None:
    """Drop the mode column and its constraint."""
    op.drop_constraint("mode", "chat_prefs", type_="check")
    op.drop_column("chat_prefs", "mode")
