"""initial schema

Revision ID: a1c0ffee0001
Revises:
Create Date: 2026-07-10 15:00:00.000000

Single baseline revision (the pre-Chainlit incremental history was collapsed —
there are no deployments to migrate). Two schemas:

- ``public``: Capybara's own tables — users (auth), facts (long-term memory),
  mcp_servers/mcp_tools (MCP curation), chat_prefs (per-user thread metadata).
- ``chainlit``: Chainlit's SQLAlchemy data layer (threads/steps/elements/feedbacks and
  its own ``users``, which would otherwise collide with auth users in ``public``).
  The data-layer connection sets ``search_path=chainlit``; DDL is Chainlit's canonical
  schema, schema-qualified.
"""

from collections.abc import Sequence
from typing import Any

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c0ffee0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[Any]]:
    """Return fresh created_at/updated_at columns (a Column can be used only once)."""
    return [
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
    ]


def upgrade() -> None:
    """Create the pgvector extension, Capybara's tables, and Chainlit's schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        *_timestamps(),
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

    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mcp_servers_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_servers"),
    )
    op.create_index("ix_mcp_servers_user_id", "mcp_servers", ["user_id"])

    op.create_table(
        "mcp_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name="fk_mcp_tools_server_id_mcp_servers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tools"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_id"),
    )
    op.create_index("ix_mcp_tools_server_id", "mcp_tools", ["server_id"])

    op.create_table(
        "chat_prefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chat_prefs_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_prefs"),
        sa.UniqueConstraint("user_id", "thread_id", name="uq_chat_prefs_user_id_thread_id"),
    )

    _create_chainlit_schema()


def _create_chainlit_schema() -> None:
    """Create the ``chainlit`` schema and Chainlit's data-layer tables within it."""
    op.execute("CREATE SCHEMA IF NOT EXISTS chainlit")
    op.execute(
        """
        CREATE TABLE chainlit.users (
            "id" UUID PRIMARY KEY,
            "identifier" TEXT NOT NULL UNIQUE,
            "metadata" JSONB NOT NULL,
            "createdAt" TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chainlit.threads (
            "id" UUID PRIMARY KEY,
            "createdAt" TEXT,
            "name" TEXT,
            "userId" UUID,
            "userIdentifier" TEXT,
            "tags" TEXT[],
            "metadata" JSONB,
            FOREIGN KEY ("userId") REFERENCES chainlit.users("id") ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chainlit.steps (
            "id" UUID PRIMARY KEY,
            "name" TEXT NOT NULL,
            "type" TEXT NOT NULL,
            "threadId" UUID NOT NULL,
            "parentId" UUID,
            "streaming" BOOLEAN NOT NULL,
            "waitForAnswer" BOOLEAN,
            "isError" BOOLEAN,
            "metadata" JSONB,
            "tags" TEXT[],
            "input" TEXT,
            "output" TEXT,
            "createdAt" TEXT,
            "command" TEXT,
            "start" TEXT,
            "end" TEXT,
            "generation" JSONB,
            "showInput" TEXT,
            "language" TEXT,
            "indent" INT,
            "defaultOpen" BOOLEAN,
            "autoCollapse" BOOLEAN,
            "icon" TEXT,
            "modes" JSONB,
            FOREIGN KEY ("threadId") REFERENCES chainlit.threads("id") ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chainlit.elements (
            "id" UUID PRIMARY KEY,
            "threadId" UUID,
            "type" TEXT,
            "url" TEXT,
            "chainlitKey" TEXT,
            "name" TEXT NOT NULL,
            "display" TEXT,
            "objectKey" TEXT,
            "size" TEXT,
            "page" INT,
            "language" TEXT,
            "forId" UUID,
            "mime" TEXT,
            "props" JSONB,
            "autoPlay" BOOLEAN,
            "playerConfig" JSONB,
            FOREIGN KEY ("threadId") REFERENCES chainlit.threads("id") ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chainlit.feedbacks (
            "id" UUID PRIMARY KEY,
            "forId" UUID NOT NULL,
            "threadId" UUID NOT NULL,
            "value" INT NOT NULL,
            "comment" TEXT,
            FOREIGN KEY ("threadId") REFERENCES chainlit.threads("id") ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    """Drop everything this revision created (leave the pgvector extension)."""
    op.execute("DROP SCHEMA IF EXISTS chainlit CASCADE")
    op.drop_table("chat_prefs")
    op.drop_index("ix_mcp_tools_server_id", table_name="mcp_tools")
    op.drop_table("mcp_tools")
    op.drop_index("ix_mcp_servers_user_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
    op.drop_index("ix_facts_embedding_hnsw", table_name="facts")
    op.drop_index("ix_facts_user_id_created_at", table_name="facts")
    op.drop_index("ix_facts_user_id", table_name="facts")
    op.drop_table("facts")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
