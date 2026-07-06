"""add chat/message composite indexes

Revision ID: d4d0cafe0004
Revises: c3d0cafe0003
Create Date: 2026-07-04 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4d0cafe0004"
down_revision: str | Sequence[str] | None = "c3d0cafe0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add composite indexes for the hot chat/message list queries."""
    op.create_index("ix_chats_user_id_updated_at", "chats", ["user_id", "updated_at"])
    op.create_index("ix_messages_chat_id_seq", "messages", ["chat_id", "seq"])


def downgrade() -> None:
    """Drop the composite chat/message indexes."""
    op.drop_index("ix_messages_chat_id_seq", table_name="messages")
    op.drop_index("ix_chats_user_id_updated_at", table_name="chats")
