"""add chainlit data-layer tables in a dedicated schema

Revision ID: c9a0cafe0009
Revises: b8f0cafe0008
Create Date: 2026-07-10 12:00:00.000000

Chainlit's SQLAlchemy data layer persists threads/steps/elements/feedbacks and its own
``users`` table. That ``users`` name collides with Capybara's auth users, so Chainlit's
tables live in a dedicated ``chainlit`` Postgres schema (the data-layer connection sets
``search_path=chainlit``). The DDL is Chainlit's canonical schema, schema-qualified.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9a0cafe0009"
down_revision: str | Sequence[str] | None = "b8f0cafe0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    """Drop the ``chainlit`` schema and everything in it."""
    op.execute("DROP SCHEMA IF EXISTS chainlit CASCADE")
