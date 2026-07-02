"""add messages.seq

Revision ID: c2e9f8a31b05
Revises: a75744e6fd97
Create Date: 2026-07-02 17:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2e9f8a31b05"
down_revision: str | Sequence[str] | None = "a75744e6fd97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add seq identity column to messages for deterministic insertion-order sorting."""
    op.add_column(
        "messages",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
    )
    op.create_unique_constraint("uq_messages_seq", "messages", ["seq"])


def downgrade() -> None:
    """Remove seq column from messages."""
    op.drop_constraint("uq_messages_seq", "messages", type_="unique")
    op.drop_column("messages", "seq")
