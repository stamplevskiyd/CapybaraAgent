"""add chat_prefs table (per-user favorite/model for chainlit threads)

Revision ID: d1b0cafe000a
Revises: c9a0cafe0009
Create Date: 2026-07-10 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1b0cafe000a"
down_revision: str | Sequence[str] | None = "c9a0cafe0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the chat_prefs table (soft reference to chainlit threads by thread_id)."""
    op.create_table(
        "chat_prefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chat_prefs_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_prefs"),
        sa.UniqueConstraint("user_id", "thread_id", name="uq_chat_prefs_user_id_thread_id"),
    )


def downgrade() -> None:
    """Drop the chat_prefs table."""
    op.drop_table("chat_prefs")
