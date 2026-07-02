"""seed local user

Revision ID: a75744e6fd97
Revises: 1d1a12d143df
Create Date: 2026-07-02 17:07:06.510600

"""
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a75744e6fd97"
down_revision: str | Sequence[str] | None = "1d1a12d143df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid),
        sa.column("username", sa.String),
        sa.column("display_name", sa.String),
    )
    op.bulk_insert(
        users,
        [{"id": LOCAL_USER_ID, "username": "roman", "display_name": "Роман"}],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE username = 'roman'"))
