"""add facts table and users.memory_auto_capture

Revision ID: e5d0cafe0005
Revises: d4d0cafe0004
Create Date: 2026-07-05 12:00:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "e5d0cafe0005"
down_revision: str | Sequence[str] | None = "d4d0cafe0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector, add the auto-capture flag, and create the facts table."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "users",
        sa.Column(
            "memory_auto_capture",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('personal', 'project', 'preference')", name="ck_facts_category"
        ),
        sa.CheckConstraint("source IN ('manual', 'auto')", name="ck_facts_source"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_facts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_facts"),
    )
    op.create_index("ix_facts_user_id", "facts", ["user_id"])
    op.create_index("ix_facts_user_id_created_at", "facts", ["user_id", "created_at"])
    op.create_index(
        "ix_facts_embedding_hnsw",
        "facts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Drop the facts table and the auto-capture flag (leave the extension)."""
    op.drop_index("ix_facts_embedding_hnsw", table_name="facts")
    op.drop_index("ix_facts_user_id_created_at", table_name="facts")
    op.drop_index("ix_facts_user_id", table_name="facts")
    op.drop_table("facts")
    op.drop_column("users", "memory_auto_capture")
