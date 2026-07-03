"""add_password_hash

Revision ID: 436abea5145d
Revises: b23789cc3517
Create Date: 2026-07-03 12:43:14.578973

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "436abea5145d"
down_revision: str | Sequence[str] | None = "b23789cc3517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    """Delete the seeded local user and add the password_hash column."""
    op.execute(sa.text("DELETE FROM users WHERE username = 'roman'"))
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=False),
    )


def downgrade() -> None:
    """Remove the password_hash column and restore the seeded local user."""
    op.drop_column("users", "password_hash")
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid),
        sa.column("username", sa.String),
        sa.column("display_name", sa.String),
    )
    op.bulk_insert(
        users,
        [{"id": _SEED_USER_ID, "username": "roman", "display_name": "Роман"}],
    )
