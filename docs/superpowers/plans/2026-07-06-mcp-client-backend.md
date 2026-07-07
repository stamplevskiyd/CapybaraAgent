# MCP Client — Backend Core (Sub-slice A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user attach a remote (HTTP/SSE) MCP server, discover and curate its tools, and have the enabled tools offered to the chat agent — surfaced through the existing tool-call streaming UI.

**Architecture:** Follows the project's `api → services → repositories → db` layering. Two new tables (`mcp_servers`, `mcp_tools`) hold config + discovered tool metadata (per-user, like `facts`). A thin `agent/mcp.py` adapter localises every pydantic-ai MCP call behind our own stable interface (`discover`, `build_toolset`). `McpService` orchestrates attach/refresh/CRUD/curation and builds per-turn toolsets. `stream_reply` gains a `toolsets=` parameter; `ChatService` threads MCP toolsets in next to the existing `recall` tool, so MCP tool calls flow through the existing `StreamedToolCall`/`ToolResult` → SSE → `ToolCallCard` path unchanged.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic-ai 2.5 (native MCP client: `pydantic_ai.mcp.MCPToolset` + `StreamableHttpTransport`), PostgreSQL, testcontainers, uv.

## Global Constraints

- **Python 3.12+, fully type-annotated; strict mypy** (`uv run mypy src`).
- **ruff lint + format**, pydocstyle `select = D` google convention — **every module/class/function/method needs a docstring** (tests exempt).
- **TDD**: write the failing test first; test repos/services/API against real Postgres (testcontainers, per-test transactional isolation via the `session` fixture); mock the MCP boundary (never reach a real MCP server).
- **All Python/pytest commands run via `uv run`.** Postgres image is `pgvector/pgvector:pg16`.
- **Remote transport only** (HTTP/SSE). No stdio, no subprocess spawning.
- **Auth = arbitrary HTTP headers** (key→value map); bearer is just an `Authorization` header.
- **Secrets stored as plain JSON — NOT encrypted at rest. This is a known limitation / TODO for a dedicated follow-up slice.** Do not add encryption in this slice; do keep the docstring/limitation note.
- **Per-user scoping**: servers carry `user_id` FK → `users` (`ondelete="CASCADE"`).
- **Fail-open at turn time**: an MCP server unreachable during a chat turn is skipped (logged), never breaks the reply. `attach`/`refresh` are explicit actions → loud, actionable errors.
- Layering is strict: **no DB queries in routers or services outside repositories**; MCP tool naming is namespaced to avoid collisions.
- Spec: `docs/superpowers/specs/2026-07-06-mcp-client-backend-design.md`.

---

## File Structure

**Create:**
- `src/capybara/db/models/mcp.py` — `McpServer`, `McpTool` ORM models.
- `src/capybara/migrations/versions/20260706_1900_b8f0cafe0008_mcp_servers_and_tools.py` — migration.
- `src/capybara/repositories/mcp_repo.py` — `McpServerRepo`, `McpToolRepo`.
- `src/capybara/agent/mcp.py` — pydantic-ai MCP adapter (`DiscoveredTool`, errors, `discover`, `build_toolset`).
- `src/capybara/services/mcp_service.py` — `McpService`.
- `src/capybara/api/routers/mcp.py` — `/mcp` router.
- `tests/test_mcp_models.py`, `tests/test_mcp_repo.py`, `tests/test_mcp_adapter.py`, `tests/test_mcp_service.py`, `tests/test_mcp_api.py`.

**Modify:**
- `src/capybara/db/models/__init__.py` — export the new models.
- `src/capybara/agent/base.py` — add `toolsets=` to `stream_reply`.
- `src/capybara/services/chat_service.py` — thread MCP toolsets; add `mcp_service` to the constructor.
- `src/capybara/api/schemas.py` — MCP request/response schemas.
- `src/capybara/api/dependencies.py` — `get_mcp_service`; inject it into `get_chat_service`.
- `src/capybara/main.py` — include the mcp router.
- `tests/support.py` — add `toolsets=()` to fake-agent `stream_reply` overrides.
- `tests/test_migrations.py` — assert the new tables exist.

---

## Task 1: MCP ORM models

**Files:**
- Create: `src/capybara/db/models/mcp.py`
- Modify: `src/capybara/db/models/__init__.py`
- Test: `tests/test_mcp_models.py`

**Interfaces:**
- Produces: `McpServer` (cols: `id: UUID`, `user_id: UUID`, `name: str`, `url: str`, `headers: dict[str, str]`, `enabled: bool`, `last_connected_at: datetime | None`, `last_error: str | None`, `created_at`/`updated_at`), `McpTool` (cols: `id: UUID`, `server_id: UUID`, `name: str`, `description: str | None`, `input_schema: dict[str, Any] | None`, `enabled: bool`, timestamps). Unique `(server_id, name)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_models.py`:

```python
"""Tests for the MCP ORM models' table shape."""

from capybara.db.base import Base
from capybara.db.models import McpServer, McpTool


def test_mcp_tables_registered_with_expected_columns() -> None:
    """Both MCP tables are on the metadata with their key columns."""
    tables = Base.metadata.tables
    assert "mcp_servers" in tables
    assert "mcp_tools" in tables

    server_cols = set(tables["mcp_servers"].columns.keys())
    assert {
        "id", "user_id", "name", "url", "headers", "enabled",
        "last_connected_at", "last_error", "created_at", "updated_at",
    } <= server_cols

    tool_cols = set(tables["mcp_tools"].columns.keys())
    assert {
        "id", "server_id", "name", "description", "input_schema",
        "enabled", "created_at", "updated_at",
    } <= tool_cols


def test_mcp_tool_has_unique_server_name() -> None:
    """A (server_id, name) uniqueness constraint prevents duplicate tools per server."""
    uniques = {
        tuple(c.name for c in con.columns)
        for con in McpTool.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("server_id", "name") in uniques
    assert McpServer.__tablename__ == "mcp_servers"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'McpServer'`.

- [ ] **Step 3: Write the models**

Create `src/capybara/db/models/mcp.py`:

```python
"""SQLAlchemy ORM models for MCP servers and their discovered tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin


class McpServer(Base, TimestampMixin):
    """A remote (HTTP/SSE) MCP server config owned by a user.

    ``headers`` holds arbitrary HTTP headers (auth lives here, e.g. ``Authorization``).
    NOTE: headers are stored as plain JSON and are NOT encrypted at rest — a known
    limitation tracked for a dedicated follow-up slice.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class McpTool(Base, TimestampMixin):
    """A single tool discovered from an MCP server, with a per-tool ``enabled`` flag.

    ``enabled`` is the curation control: only enabled tools of enabled servers are ever
    offered to the chat agent, so a large server (e.g. Home Assistant) can be trimmed to
    the tools a local model handles well.
    """

    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "name"),
        Index("ix_mcp_tools_server_id", "server_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    server_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

Modify `src/capybara/db/models/__init__.py` to export them:

```python
"""ORM model exports: User, Chat, Message, Fact, McpServer, McpTool."""

from capybara.db.models.chat import Chat
from capybara.db.models.fact import Fact
from capybara.db.models.mcp import McpServer, McpTool
from capybara.db.models.message import Message
from capybara.db.models.user import User

__all__ = ["Chat", "Fact", "McpServer", "McpTool", "Message", "User"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/capybara/db/models/mcp.py tests/test_mcp_models.py && uv run mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/db/models/mcp.py src/capybara/db/models/__init__.py tests/test_mcp_models.py
git commit -m "feat(mcp): add McpServer and McpTool ORM models"
```

---

## Task 2: Alembic migration

**Files:**
- Create: `src/capybara/migrations/versions/20260706_1900_b8f0cafe0008_mcp_servers_and_tools.py`
- Test: `tests/test_migrations.py` (extend)

**Interfaces:**
- Consumes: models from Task 1. Current head revision is `a7f0cafe0007`.
- Produces: tables `mcp_servers`, `mcp_tools` at head.

- [ ] **Step 1: Write the failing test — extend `tests/test_migrations.py`**

Add this test to the end of `tests/test_migrations.py`:

```python
async def test_migrations_create_mcp_tables(migrated_engine: AsyncEngine) -> None:
    """The MCP migration creates mcp_servers and mcp_tools at head."""
    async with migrated_engine.connect() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"mcp_servers", "mcp_tools"} <= set(tables)

        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'mcp_servers'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"headers", "enabled", "last_connected_at", "last_error"} <= set(cols)
```

Note: `inspect` is already imported in this file; `text` and `AsyncEngine` are already imported.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_migrations_create_mcp_tables -v`
Expected: FAIL — the assertion on `{"mcp_servers", "mcp_tools"}` fails (tables absent).

- [ ] **Step 3: Write the migration**

Create `src/capybara/migrations/versions/20260706_1900_b8f0cafe0008_mcp_servers_and_tools.py`:

```python
"""add mcp_servers and mcp_tools tables

Revision ID: b8f0cafe0008
Revises: a7f0cafe0007
Create Date: 2026-07-06 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8f0cafe0008"
down_revision: str | Sequence[str] | None = "a7f0cafe0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the mcp_servers and mcp_tools tables."""
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["mcp_servers.id"], name="fk_mcp_tools_server_id_mcp_servers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tools"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_id"),
    )
    op.create_index("ix_mcp_tools_server_id", "mcp_tools", ["server_id"])


def downgrade() -> None:
    """Drop the mcp_tools and mcp_servers tables."""
    op.drop_index("ix_mcp_tools_server_id", table_name="mcp_tools")
    op.drop_table("mcp_tools")
    op.drop_index("ix_mcp_servers_user_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: PASS (all migration tests).

- [ ] **Step 5: Verify metadata matches migration (no drift)**

Run: `uv run alembic check` if available, else confirm the `engine` fixture's `create_all` and the migration agree by running the whole DB suite: `uv run pytest tests/test_mcp_models.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/migrations/versions/20260706_1900_b8f0cafe0008_mcp_servers_and_tools.py tests/test_migrations.py
git commit -m "feat(mcp): migration for mcp_servers and mcp_tools"
```

---

## Task 3: MCP repositories

**Files:**
- Create: `src/capybara/repositories/mcp_repo.py`
- Test: `tests/test_mcp_repo.py`

**Interfaces:**
- Consumes: `McpServer`, `McpTool`; `BaseRepository` (`get`, `list`, `create`, `update`, `delete`); `FieldEquals` from `capybara.filters`.
- Produces: `McpServerRepo(session)` with `list(*filters)`; `McpToolRepo(session)` with `list_for_server(server_id: UUID) -> list[McpTool]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_repo.py`:

```python
"""Tests for the MCP repositories against a real Postgres session."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import McpServer
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo

pytestmark = pytest.mark.asyncio


async def test_server_and_tools_roundtrip(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    """Create a server with tools; list_for_server returns them; user filter scopes."""
    user = await make_user(session)
    servers = McpServerRepo(session)
    tools = McpToolRepo(session)

    server = await servers.create(
        user_id=user.id, name="home", url="http://ha/mcp", headers={"Authorization": "Bearer x"}
    )
    await tools.create(server_id=server.id, name="turn_on", description="d", input_schema={})
    await tools.create(server_id=server.id, name="turn_off", description=None, input_schema=None)

    listed = await servers.list(FieldEquals(McpServer.user_id, user.id))
    assert [s.name for s in listed] == ["home"]
    assert listed[0].headers == {"Authorization": "Bearer x"}

    server_tools = await tools.list_for_server(server.id)
    assert {t.name for t in server_tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in server_tools)  # default enabled


async def test_list_for_server_empty_for_unknown(session: AsyncSession) -> None:
    """list_for_server returns [] for a server id with no tools."""
    assert await McpToolRepo(session).list_for_server(uuid4()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.repositories.mcp_repo`.

- [ ] **Step 3: Write the repositories**

Create `src/capybara/repositories/mcp_repo.py`:

```python
"""Repositories for MCP servers and their discovered tools."""

from uuid import UUID

from capybara.db.models import McpServer, McpTool
from capybara.filters import FieldEquals
from capybara.repositories.base import BaseRepository


class McpServerRepo(BaseRepository[McpServer]):
    """Repository for MCP server rows (inherited CRUD only)."""

    model = McpServer


class McpToolRepo(BaseRepository[McpTool]):
    """Repository for MCP tool rows, with a per-server listing helper."""

    model = McpTool

    async def list_for_server(self, server_id: UUID) -> list[McpTool]:
        """Return all tools for *server_id*, in creation order."""
        return await self.list(FieldEquals(McpTool.server_id, server_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_repo.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/capybara/repositories/mcp_repo.py tests/test_mcp_repo.py && uv run mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/repositories/mcp_repo.py tests/test_mcp_repo.py
git commit -m "feat(mcp): McpServerRepo and McpToolRepo"
```

---

## Task 4: MCP adapter (pydantic-ai boundary)

**Files:**
- Create: `src/capybara/agent/mcp.py`
- Test: `tests/test_mcp_adapter.py`

**Interfaces:**
- Consumes: `pydantic_ai.mcp.MCPToolset`, `pydantic_ai.mcp.StreamableHttpTransport`, `pydantic_ai.toolsets.AbstractToolset`.
- Produces:
  - `@dataclass(frozen=True) class DiscoveredTool: name: str; description: str | None; input_schema: dict[str, Any] | None`
  - `class McpUnreachableError(Exception)` — server could not be reached.
  - `class McpProtocolError(Exception)` — reached, but handshake/`tools/list` failed.
  - `async def discover(url: str, headers: dict[str, str]) -> list[DiscoveredTool]`
  - `def build_toolset(url: str, headers: dict[str, str], enabled_tools: set[str], prefix: str) -> AbstractToolset[None]` — a pydantic-ai toolset filtered to `enabled_tools` (matched on the server's original tool names) and prefixed with `prefix` (so tools reach the model as `{prefix}_{tool}`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_adapter.py`. The tests monkeypatch `MCPToolset` inside the adapter module so no real server is contacted:

```python
"""Tests for the pydantic-ai MCP adapter, with MCPToolset mocked out."""

import httpx
import pytest

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import (
    DiscoveredTool,
    McpProtocolError,
    McpUnreachableError,
    build_toolset,
    discover,
)


class _FakeTool:
    def __init__(self, name: str, description: str | None, input_schema: dict | None) -> None:
        self.name = name
        self.description = description
        self.inputSchema = input_schema  # noqa: N815 — mirrors the MCP wire field name


class _FakeToolset:
    """Stand-in for pydantic-ai's MCPToolset: records construction, yields fake tools."""

    last_kwargs: dict = {}

    def __init__(self, transport, *, id=None, init_timeout=None):  # type: ignore[no-untyped-def]
        _FakeToolset.last_kwargs = {"transport": transport, "id": id}
        self._tools = [_FakeTool("turn_on", "Turn on", {"type": "object"}), _FakeTool("turn_off", None, None)]
        self.filtered_with = None
        self.prefixed_with = None

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        return False

    async def list_tools(self):  # type: ignore[no-untyped-def]
        return self._tools

    def filtered(self, fn):  # type: ignore[no-untyped-def]
        self.filtered_with = fn
        return self

    def prefixed(self, prefix):  # type: ignore[no-untyped-def]
        self.prefixed_with = prefix
        return self


@pytest.mark.asyncio
async def test_discover_maps_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """discover returns DiscoveredTool objects mapping name/description/input_schema."""
    monkeypatch.setattr(mcp_adapter, "MCPToolset", _FakeToolset)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    tools = await discover("http://ha/mcp", {"Authorization": "Bearer x"})

    assert tools == [
        DiscoveredTool(name="turn_on", description="Turn on", input_schema={"type": "object"}),
        DiscoveredTool(name="turn_off", description=None, input_schema=None),
    ]
    # Headers are threaded into the transport.
    assert _FakeToolset.last_kwargs["transport"] == {
        "url": "http://ha/mcp",
        "headers": {"Authorization": "Bearer x"},
    }


@pytest.mark.asyncio
async def test_discover_connection_error_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection failure surfaces as McpUnreachableError."""

    class _Boom(_FakeToolset):
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_other_error_is_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-connection failure surfaces as McpProtocolError."""

    class _Boom(_FakeToolset):
        async def list_tools(self):  # type: ignore[no-untyped-def]
            raise ValueError("bad handshake")

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpProtocolError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_flattens_exception_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error wrapped in an ExceptionGroup is still McpUnreachableError."""

    class _Boom(_FakeToolset):
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise BaseExceptionGroup("grp", [httpx.ConnectError("refused")])

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})


def test_build_toolset_filters_and_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_toolset filters to enabled tool names (pre-prefix) and applies the prefix."""
    monkeypatch.setattr(mcp_adapter, "MCPToolset", _FakeToolset)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    ts = build_toolset("http://ha/mcp", {}, enabled_tools={"turn_on"}, prefix="home")

    # The filter keeps only enabled original names.
    class _Def:
        def __init__(self, name: str) -> None:
            self.name = name

    assert ts.filtered_with(None, _Def("turn_on")) is True
    assert ts.filtered_with(None, _Def("turn_off")) is False
    assert ts.prefixed_with == "home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.agent.mcp`.

- [ ] **Step 3: Write the adapter**

Create `src/capybara/agent/mcp.py`:

```python
"""Thin adapter over pydantic-ai's MCP client (remote HTTP/SSE transport only).

Every pydantic-ai MCP call is localised here so the rest of the app depends on this
small, stable interface rather than the library's evolving API. Remote transport only —
no stdio/subprocess in this slice.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic_ai.mcp import MCPToolset, StreamableHttpTransport
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

#: Bound the connect/handshake so a dead server can't hang attach/refresh/turns.
_INIT_TIMEOUT_SECONDS = 10.0

#: Exception types that mean "the server could not be reached" (vs. a protocol error).
_UNREACHABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, ConnectionError, TimeoutError)


@dataclass(frozen=True)
class DiscoveredTool:
    """A tool reported by an MCP server's ``tools/list``."""

    name: str
    description: str | None
    input_schema: dict[str, Any] | None


class McpUnreachableError(Exception):
    """Raised when an MCP server cannot be reached (connection refused/timeout)."""


class McpProtocolError(Exception):
    """Raised when a server answered but the handshake or ``tools/list`` failed.

    This covers a wrong URL, a non-MCP endpoint, or rejected auth — an actionable
    configuration problem rather than an outage.
    """


def _flatten(exc: BaseException) -> Iterator[BaseException]:
    """Yield leaf exceptions, descending into ExceptionGroups (anyio wraps errors)."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _flatten(sub)
    else:
        yield exc


def _classify(exc: BaseException) -> Exception:
    """Map a raw pydantic-ai/MCP failure to an unreachable- or protocol-error."""
    if any(isinstance(leaf, _UNREACHABLE) for leaf in _flatten(exc)):
        return McpUnreachableError(str(exc))
    return McpProtocolError(str(exc))


def _raw_toolset(url: str, headers: dict[str, str], *, prefix_id: str | None = None) -> MCPToolset:
    """Build an unfiltered MCPToolset for *url*/*headers* (headers omitted when empty)."""
    transport = StreamableHttpTransport(url=url, headers=headers or None)
    return MCPToolset(transport, id=prefix_id, init_timeout=_INIT_TIMEOUT_SECONDS)


async def discover(url: str, headers: dict[str, str]) -> list[DiscoveredTool]:
    """Connect to the MCP server and return its advertised tools.

    Opens a session only for the duration of the call (handshake + ``tools/list``), then
    closes it.

    Raises:
        McpUnreachableError: If the server cannot be reached.
        McpProtocolError: If the server answered but the handshake/list failed.
    """
    toolset = _raw_toolset(url, headers)
    try:
        async with toolset:
            raw = await toolset.list_tools()
    except Exception as exc:  # noqa: BLE001 — re-raised as a classified adapter error
        raise _classify(exc) from exc
    return [
        DiscoveredTool(
            name=tool.name,
            description=getattr(tool, "description", None),
            input_schema=getattr(tool, "inputSchema", None),
        )
        for tool in raw
    ]


def build_toolset(
    url: str, headers: dict[str, str], enabled_tools: set[str], prefix: str
) -> AbstractToolset[None]:
    """Return an agent-ready toolset exposing only *enabled_tools*, namespaced by *prefix*.

    The filter matches on the server's original tool names (applied before prefixing);
    pydantic-ai then exposes each kept tool to the model as ``{prefix}_{tool}`` so names
    never collide across servers or with built-in tools. The MCP session is opened lazily
    by pydantic-ai for the duration of the agent run, not here.
    """
    enabled = set(enabled_tools)

    def _keep(_ctx: object, tool_def: ToolDefinition) -> bool:
        return tool_def.name in enabled

    toolset = _raw_toolset(url, headers, prefix_id=prefix)
    return toolset.filtered(_keep).prefixed(prefix)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_adapter.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/capybara/agent/mcp.py tests/test_mcp_adapter.py && uv run mypy src`
Expected: clean. (If mypy objects to `filtered`/`prefixed` return typing, annotate the return as `AbstractToolset[None]` — already done — and use `# type: ignore[return-value]` only if strictly necessary.)

- [ ] **Step 6: Commit**

```bash
git add src/capybara/agent/mcp.py tests/test_mcp_adapter.py
git commit -m "feat(mcp): pydantic-ai MCP adapter (discover + build_toolset)"
```

---

## Task 5: McpService

**Files:**
- Create: `src/capybara/services/mcp_service.py`
- Test: `tests/test_mcp_service.py`

**Interfaces:**
- Consumes: `McpServerRepo`, `McpToolRepo`, `FieldEquals`; the adapter (`discover`, `build_toolset`, `McpUnreachableError`, `McpProtocolError`); `async_sessionmaker`.
- Produces `McpService(sessionmaker)` with:
  - `async def list_servers(user_id) -> list[tuple[McpServer, list[McpTool]]]`
  - `async def attach(user_id, name, url, headers) -> tuple[McpServer, list[McpTool]]`
  - `async def get_server(user_id, server_id) -> tuple[McpServer, list[McpTool]] | None`
  - `async def update_server(user_id, server_id, *, name=None, url=None, headers=None, enabled=None) -> tuple[McpServer, list[McpTool]] | None`
  - `async def delete_server(user_id, server_id) -> bool`
  - `async def refresh(user_id, server_id) -> tuple[McpServer, list[McpTool]] | None`
  - `async def set_tool_enabled(user_id, server_id, tool_id, enabled) -> McpTool | None`
  - `async def build_toolsets(user_id) -> list[AbstractToolset[None]]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_service.py`. The adapter is monkeypatched so no server is contacted; the DB is real:

```python
"""Tests for McpService against real Postgres, with the MCP adapter mocked."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import DiscoveredTool, McpUnreachableError
from capybara.services.mcp_service import McpService

pytestmark = pytest.mark.asyncio


def _maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker that always hands back the test's transactional session."""
    from contextlib import asynccontextmanager

    class _Maker:
        def __call__(self):  # type: ignore[no-untyped-def]
            @asynccontextmanager
            async def _cm():  # type: ignore[no-untyped-def]
                yield session

            return _cm()

    return _Maker()  # type: ignore[return-value]


async def test_attach_persists_server_and_tools(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """attach discovers tools and stores the server + enabled tools."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    service = McpService(_maker(session))

    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {"X-Api-Key": "k"})

    assert server.name == "home"
    assert server.last_connected_at is not None
    assert {t.name for t in tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in tools)


async def test_attach_unreachable_persists_nothing(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """A failed attach raises and writes no server row."""
    user = await make_user(session)

    async def boom(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("refused")

    monkeypatch.setattr(mcp_adapter, "discover", boom)
    service = McpService(_maker(session))

    with pytest.raises(McpUnreachableError):
        await service.attach(user.id, "home", "http://ha/mcp", {})
    assert await service.list_servers(user.id) == []


async def test_set_tool_enabled_and_build_toolsets(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """Disabling a tool drops it; build_toolsets includes only reachable enabled servers."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    built: list = []

    def fake_build(url, headers, enabled_tools, prefix):  # type: ignore[no-untyped-def]
        built.append((prefix, set(enabled_tools)))
        return object()

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    monkeypatch.setattr(mcp_adapter, "build_toolset", fake_build)
    service = McpService(_maker(session))

    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {})
    off = next(t for t in tools if t.name == "turn_off")
    await service.set_tool_enabled(user.id, server.id, off.id, enabled=False)

    toolsets = await service.build_toolsets(user.id)

    assert len(toolsets) == 1
    assert built == [("home", {"turn_on"})]  # only the enabled tool


async def test_build_toolsets_skips_unreachable(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """A server unreachable at turn time is skipped (fail-open), not raised."""
    user = await make_user(session)

    async def fake_discover_ok(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {})]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover_ok)
    service = McpService(_maker(session))
    await service.attach(user.id, "home", "http://ha/mcp", {})

    async def now_unreachable(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("gone")

    monkeypatch.setattr(mcp_adapter, "discover", now_unreachable)

    toolsets = await service.build_toolsets(user.id)
    assert toolsets == []  # skipped, no exception


async def test_refresh_preserves_enabled_flags(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """refresh keeps a tool's enabled flag by name and adds/removes tools."""
    user = await make_user(session)

    async def discover_v1(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v1)
    service = McpService(_maker(session))
    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {})
    off = next(t for t in tools if t.name == "turn_off")
    await service.set_tool_enabled(user.id, server.id, off.id, enabled=False)

    async def discover_v2(url, headers):  # type: ignore[no-untyped-def]
        # turn_on stays, turn_off stays (disabled must persist), lock is new
        return [
            DiscoveredTool("turn_on", "d", {}),
            DiscoveredTool("turn_off", None, None),
            DiscoveredTool("lock", "new", {}),
        ]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v2)
    refreshed = await service.refresh(user.id, server.id)
    assert refreshed is not None
    _server, refreshed_tools = refreshed
    by_name = {t.name: t for t in refreshed_tools}
    assert set(by_name) == {"turn_on", "turn_off", "lock"}
    assert by_name["turn_off"].enabled is False  # preserved
    assert by_name["lock"].enabled is True  # new default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_service.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.services.mcp_service`.

- [ ] **Step 3: Write the service**

Create `src/capybara/services/mcp_service.py`:

```python
"""MCP service: attach/refresh/CRUD/curation of servers, and per-turn toolset assembly."""

import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.db.models import McpServer, McpTool
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Derive a tool-name prefix from a server name (lowercase alnum, ``_``-joined)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "mcp"


class McpService:
    """Orchestrate MCP servers: discovery, persistence, curation, and toolset assembly.

    Owns short-lived sessions from the app-wide sessionmaker (never borrows a request
    session), so it is safe to use from both routes and a chat turn.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the app-wide sessionmaker."""
        self._sessionmaker = sessionmaker

    async def _load(
        self, session: AsyncSession, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Return a user-owned server and its tools, or None if not found/owned."""
        server = await McpServerRepo(session).get(server_id)
        if server is None or server.user_id != user_id:
            return None
        tools = await McpToolRepo(session).list_for_server(server_id)
        return server, tools

    async def list_servers(self, user_id: UUID) -> list[tuple[McpServer, list[McpTool]]]:
        """Return the user's servers, each paired with its tools."""
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).list(FieldEquals(McpServer.user_id, user_id))
            trepo = McpToolRepo(session)
            return [(s, await trepo.list_for_server(s.id)) for s in servers]

    async def get_server(
        self, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Return a user-owned server and its tools, or None."""
        async with self._sessionmaker() as session:
            return await self._load(session, user_id, server_id)

    async def attach(
        self, user_id: UUID, name: str, url: str, headers: dict[str, str]
    ) -> tuple[McpServer, list[McpTool]]:
        """Discover *url*'s tools and persist the server + tools (all enabled).

        Raises:
            McpUnreachableError: If the server cannot be reached.
            McpProtocolError: If the handshake/list failed.
        """
        discovered = await mcp_adapter.discover(url, headers)  # raises → route maps to HTTP
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            trepo = McpToolRepo(session)
            server = await repo.create(
                user_id=user_id,
                name=name,
                url=url,
                headers=headers,
                enabled=True,
                last_connected_at=datetime.now(UTC),
                last_error=None,
            )
            tools = [
                await trepo.create(
                    server_id=server.id,
                    name=d.name,
                    description=d.description,
                    input_schema=d.input_schema,
                    enabled=True,
                )
                for d in discovered
            ]
            await session.commit()
            await session.refresh(server)
            for tool in tools:
                await session.refresh(tool)
            return server, tools

    async def update_server(
        self,
        user_id: UUID,
        server_id: UUID,
        *,
        name: str | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Update mutable server fields; return the server+tools, or None if not owned."""
        fields: dict[str, object] = {}
        if name is not None:
            fields["name"] = name
        if url is not None:
            fields["url"] = url
        if headers is not None:
            fields["headers"] = headers
        if enabled is not None:
            fields["enabled"] = enabled
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            server = await repo.get(server_id)
            if server is None or server.user_id != user_id:
                return None
            if fields:
                await repo.update(server, **fields)
                await session.commit()
            return await self._load(session, user_id, server_id)

    async def delete_server(self, user_id: UUID, server_id: UUID) -> bool:
        """Delete a user-owned server (cascades its tools); return whether it existed."""
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            server = await repo.get(server_id)
            if server is None or server.user_id != user_id:
                return False
            await repo.delete(server)
            await session.commit()
            return True

    async def refresh(
        self, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Re-discover a server's tools, preserving each tool's enabled flag by name.

        Returns None if the server is not owned. On a discovery failure, records
        ``last_error`` and re-raises (an explicit action → actionable HTTP error).
        """
        async with self._sessionmaker() as session:
            loaded = await self._load(session, user_id, server_id)
            if loaded is None:
                return None
            server, _ = loaded
            url, headers = server.url, dict(server.headers)
        try:
            discovered = await mcp_adapter.discover(url, headers)
        except (McpUnreachableError, McpProtocolError) as exc:
            async with self._sessionmaker() as session:
                repo = McpServerRepo(session)
                server = await repo.get(server_id)
                if server is not None:
                    await repo.update(server, last_error=str(exc))
                    await session.commit()
            raise
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            trepo = McpToolRepo(session)
            existing = {t.name: t for t in await trepo.list_for_server(server_id)}
            new_names = {d.name for d in discovered}
            for name, tool in existing.items():
                if name not in new_names:
                    await trepo.delete(tool)
            for d in discovered:
                if d.name in existing:
                    await trepo.update(
                        existing[d.name], description=d.description, input_schema=d.input_schema
                    )
                else:
                    await trepo.create(
                        server_id=server_id,
                        name=d.name,
                        description=d.description,
                        input_schema=d.input_schema,
                        enabled=True,
                    )
            server = await repo.get(server_id)
            assert server is not None  # loaded above under the same ownership check
            await repo.update(server, last_connected_at=datetime.now(UTC), last_error=None)
            await session.commit()
            return await self._load(session, user_id, server_id)

    async def set_tool_enabled(
        self, user_id: UUID, server_id: UUID, tool_id: UUID, *, enabled: bool
    ) -> McpTool | None:
        """Toggle a tool's enabled flag; return the tool, or None if not owned/found."""
        async with self._sessionmaker() as session:
            server = await McpServerRepo(session).get(server_id)
            if server is None or server.user_id != user_id:
                return None
            trepo = McpToolRepo(session)
            tool = await trepo.get(tool_id)
            if tool is None or tool.server_id != server_id:
                return None
            tool = await trepo.update(tool, enabled=enabled)
            await session.commit()
            await session.refresh(tool)
            return tool

    async def build_toolsets(self, user_id: UUID) -> list[AbstractToolset[None]]:
        """Build agent-ready toolsets for the user's enabled servers (enabled tools only).

        Fail-open: each enabled server is reachability-checked via ``discover``; an
        unreachable server is logged and skipped so a dead server never breaks the turn.

        NOTE (known slice-A inefficiency): this reachability check opens a session, and
        pydantic-ai opens another when the agent actually runs the toolset — two
        handshakes per server per turn. A persistent connection pool is a later slice.
        """
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).list(
                FieldEquals(McpServer.user_id, user_id), FieldEquals(McpServer.enabled, True)
            )
            trepo = McpToolRepo(session)
            specs = [
                (
                    s.name,
                    s.url,
                    dict(s.headers),
                    {t.name for t in await trepo.list_for_server(s.id) if t.enabled},
                )
                for s in servers
            ]
        toolsets: list[AbstractToolset[None]] = []
        for name, url, headers, enabled_names in specs:
            if not enabled_names:
                continue
            try:
                await mcp_adapter.discover(url, headers)
            except (McpUnreachableError, McpProtocolError):
                logger.warning("MCP server %r unreachable this turn; skipping its tools", name)
                continue
            toolsets.append(mcp_adapter.build_toolset(url, headers, enabled_names, _slug(name)))
        return toolsets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_service.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check src/capybara/services/mcp_service.py tests/test_mcp_service.py && uv run mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/services/mcp_service.py tests/test_mcp_service.py
git commit -m "feat(mcp): McpService — attach, refresh, curation, build_toolsets"
```

---

## Task 6: `stream_reply` gains a `toolsets` parameter

**Files:**
- Modify: `src/capybara/agent/base.py` (the `stream_reply` method)
- Modify: `tests/support.py` (add `toolsets=()` to fake `stream_reply` overrides)
- Test: `tests/test_agent_tool_stream.py` (add a toolset case)

**Interfaces:**
- Consumes: `pydantic_ai.toolsets.AbstractToolset`, existing `stream_reply` internals.
- Produces: `stream_reply(model_name, user_content, history, acc, tools=(), toolsets=())` — toolsets threaded into the pydantic-ai `Agent(..., toolsets=)`; the chat system prompt is set when either tools OR toolsets are present.

- [ ] **Step 1: Write the failing test — add to `tests/test_agent_tool_stream.py`**

Append:

```python
async def test_stream_reply_surfaces_toolset_tool(settings: Settings) -> None:
    """A tool provided via a toolset is called and surfaces as tool-call/result events."""
    from pydantic_ai.toolsets import FunctionToolset

    from capybara.agent.base import StreamedToolCall, StreamedToolResult

    def weather(city: str) -> str:
        """Return the weather for a city."""
        return "sunny in " + city

    agent = ToolCallingFakeAgent(settings, "Готово")
    toolset = FunctionToolset([weather]).prefixed("home")

    acc = ReplyAccumulator()
    events = [
        e
        async for e in agent.stream_reply(
            "test-model", "погода?", [], acc, toolsets=[toolset]
        )
    ]

    call_names = {e.name for e in events if isinstance(e, StreamedToolCall)}
    results = [e for e in events if isinstance(e, StreamedToolResult)]
    assert "home_weather" in call_names  # prefixed name reaches the model
    assert any("sunny" in r.result for r in results)
```

(`ReplyAccumulator` and `ToolCallingFakeAgent` are already imported in this file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_tool_stream.py::test_stream_reply_surfaces_toolset_tool -v`
Expected: FAIL — `TypeError: stream_reply() got an unexpected keyword argument 'toolsets'`.

- [ ] **Step 3: Add the `toolsets` parameter in `src/capybara/agent/base.py`**

In `BaseAgent.stream_reply`, update the signature and the `Agent(...)` construction. Change the signature from:

```python
    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools: Sequence[Tool[None]] = (),
    ) -> AsyncIterator[AgentStreamEvent]:
```

to:

```python
    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools: Sequence[Tool[None]] = (),
        toolsets: Sequence[AbstractToolset[None]] = (),
    ) -> AsyncIterator[AgentStreamEvent]:
```

Update the docstring's tools sentence to add: "MCP-backed tools are supplied via *toolsets*; text/tool-event handling is identical." Then change the agent construction from:

```python
        tool_list = list(tools)
        agent: Agent[None, str] = Agent(
            self._build_model(model_name),
            system_prompt=CHAT_SYSTEM_PROMPT if tool_list else (),
            tools=tool_list,
        )
```

to:

```python
        tool_list = list(tools)
        toolset_list = list(toolsets)
        agent: Agent[None, str] = Agent(
            self._build_model(model_name),
            system_prompt=CHAT_SYSTEM_PROMPT if (tool_list or toolset_list) else (),
            tools=tool_list,
            toolsets=toolset_list,
        )
```

Add the import near the other pydantic-ai imports at the top of `base.py`:

```python
from pydantic_ai.toolsets import AbstractToolset
```

- [ ] **Step 4: Update `tests/support.py` fake overrides**

Every fake agent in `tests/support.py` that OVERRIDES `stream_reply` must accept the new keyword (otherwise `ChatService` passing `toolsets=` in Task 7 breaks them). Add `toolsets=()` after `tools=()` in the `stream_reply` signature of each of these classes: `RaisingAgent`, `PartialThenFailAgent`, `PartialThenHangAgent`, `SlowStreamAgent`, `EmptyReplyAgent`, `ScriptedToolAgent`. For example, in `RaisingAgent.stream_reply`:

```python
    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
        toolsets=(),  # type: ignore[no-untyped-def]
    ) -> AsyncIterator[StreamedText]:
```

Apply the identical `toolsets=()` addition to each of the six overrides listed above.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tool_stream.py -v`
Expected: PASS (all, including the new toolset test).

- [ ] **Step 6: Run the full agent + chat suite to catch regressions**

Run: `uv run pytest tests/test_agent_stream.py tests/test_chat_service.py tests/test_chats_api.py -v`
Expected: PASS (the `support.py` signature change keeps existing overrides compatible).

- [ ] **Step 7: Lint + type-check**

Run: `uv run ruff check src/capybara/agent/base.py tests/support.py tests/test_agent_tool_stream.py && uv run mypy src`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/agent/base.py tests/support.py tests/test_agent_tool_stream.py
git commit -m "feat(agent): stream_reply accepts toolsets alongside tools"
```

---

## Task 7: Thread MCP toolsets through ChatService

**Files:**
- Modify: `src/capybara/services/chat_service.py`
- Modify: `src/capybara/api/dependencies.py`
- Test: `tests/test_chat_service.py` (add a toolset-integration test)

**Interfaces:**
- Consumes: `McpService.build_toolsets(user_id)` (Task 5); `stream_reply(..., toolsets=)` (Task 6).
- Produces: `ChatService(sessionmaker, agent, memory_service=None, turn_locks=None, mcp_service=None)`; `stream_turn` passes MCP toolsets (empty when `mcp_service` is None or `user_id` is None). `get_chat_service` injects a `McpService` via new `get_mcp_service`.

- [ ] **Step 1: Write the failing test — add to `tests/test_chat_service.py`**

This test uses a real `FunctionToolset` returned by a fake `McpService`, with the tool-calling fake agent, and asserts the MCP tool surfaces through `stream_turn`'s `ToolCall`/`ToolResult` events:

```python
async def test_stream_turn_surfaces_mcp_toolset_tool(settings, session, make_user) -> None:  # type: ignore[no-untyped-def]
    """An MCP toolset from McpService.build_toolsets surfaces as ToolCall/ToolResult events."""
    from pydantic_ai.toolsets import FunctionToolset

    from capybara.db.models import Chat, Message
    from capybara.services.events import ToolCall, ToolResult
    from support import ToolCallingFakeAgent

    user = await make_user(session)
    chat = Chat(user_id=user.id, title="t", model="test-model")
    session.add(chat)
    await session.flush()
    session.add(Message(chat_id=chat.id, role="user", content="погода?"))
    await session.commit()

    def weather(city: str) -> str:
        """Return the weather for a city."""
        return "sunny in " + city

    class _FakeMcp:
        async def build_toolsets(self, user_id):  # type: ignore[no-untyped-def]
            return [FunctionToolset([weather]).prefixed("home")]

    maker = create_sessionmaker(engine_from(session))  # see note below
    service = ChatService(
        maker, ToolCallingFakeAgent(settings, "Готово"), mcp_service=_FakeMcp()
    )

    events = [
        e
        async for e in service.stream_turn(
            chat.id, "test-model", "погода?", [], user_id=user.id
        )
    ]

    assert any(isinstance(e, ToolCall) and e.name == "home_weather" for e in events)
    assert any(isinstance(e, ToolResult) and "sunny" in e.result for e in events)
```

**Implementation note for the engineer:** match how the *existing* `tests/test_chat_service.py` builds a `ChatService` with a sessionmaker over the test engine (there is already a helper/fixture pattern in that file — reuse it instead of the `engine_from`/`create_sessionmaker` placeholder above, which is illustrative). If the file constructs `ChatService(maker, agent, memory_service=...)` elsewhere, follow that exact construction and just add `mcp_service=_FakeMcp()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_service.py::test_stream_turn_surfaces_mcp_toolset_tool -v`
Expected: FAIL — `TypeError: ChatService.__init__() got an unexpected keyword argument 'mcp_service'`.

- [ ] **Step 3: Add `mcp_service` to `ChatService` and thread toolsets**

In `src/capybara/services/chat_service.py`, add the import:

```python
from capybara.services.mcp_service import McpService
```

Extend `ChatService.__init__` to accept and store `mcp_service`:

```python
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent: BaseAgent,
        memory_service: MemoryService | None = None,
        turn_locks: ChatTurnLocks | None = None,
        mcp_service: McpService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._memory_service = memory_service
        self._turn_locks = turn_locks or ChatTurnLocks()
        self._mcp_service = mcp_service
```

In `stream_turn`, build toolsets right after the `tools` list is assembled and pass them to `stream_reply`. Change:

```python
        tools: list[Tool[None]] = []
        if user_id is not None and self._memory_service is not None:
            tools.append(make_recall_tool(self._memory_service, user_id))
        acc = ReplyAccumulator()
```

to:

```python
        tools: list[Tool[None]] = []
        if user_id is not None and self._memory_service is not None:
            tools.append(make_recall_tool(self._memory_service, user_id))
        toolsets: list[AbstractToolset[None]] = []
        if user_id is not None and self._mcp_service is not None:
            toolsets = await self._mcp_service.build_toolsets(user_id)
        acc = ReplyAccumulator()
```

and change the `stream_reply` call from:

```python
            async for event in self._agent.stream_reply(
                model_name, user_content, history, acc, tools=tools
            ):
```

to:

```python
            async for event in self._agent.stream_reply(
                model_name, user_content, history, acc, tools=tools, toolsets=toolsets
            ):
```

Add the import at the top of `chat_service.py`:

```python
from pydantic_ai.toolsets import AbstractToolset
```

- [ ] **Step 4: Wire the dependency in `src/capybara/api/dependencies.py`**

Add the import:

```python
from capybara.services.mcp_service import McpService
```

Add a `get_mcp_service` dependency (place it next to `get_memory_service`):

```python
def get_mcp_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> McpService:
    """Return an McpService that owns short-lived sessions from the app sessionmaker."""
    return McpService(sessionmaker)
```

Update `get_chat_service` to inject it:

```python
def get_chat_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    turn_locks: Annotated[ChatTurnLocks, Depends(get_chat_turn_locks)],
    mcp_service: Annotated[McpService, Depends(get_mcp_service)],
) -> ChatService:
    """Return a ChatService wired with recall, MCP toolsets, and the shared turn locks."""
    return ChatService(
        sessionmaker, agent, memory_service, turn_locks, mcp_service=mcp_service
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_service.py tests/test_chats_api.py -v`
Expected: PASS (existing tests unaffected — `mcp_service` defaults to None; new test passes).

- [ ] **Step 6: Lint + type-check**

Run: `uv run ruff check src/capybara/services/chat_service.py src/capybara/api/dependencies.py tests/test_chat_service.py && uv run mypy src`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/capybara/services/chat_service.py src/capybara/api/dependencies.py tests/test_chat_service.py
git commit -m "feat(mcp): thread MCP toolsets through ChatService turns"
```

---

## Task 8: `/mcp` API — schemas, router, wiring

**Files:**
- Modify: `src/capybara/api/schemas.py`
- Create: `src/capybara/api/routers/mcp.py`
- Modify: `src/capybara/main.py`
- Test: `tests/test_mcp_api.py`

**Interfaces:**
- Consumes: `McpService` via `get_mcp_service`; `get_current_user`; adapter errors for HTTP mapping.
- Produces routes under prefix `/mcp`: `GET /mcp/servers`, `POST /mcp/servers`, `GET /mcp/servers/{id}`, `PATCH /mcp/servers/{id}`, `DELETE /mcp/servers/{id}`, `POST /mcp/servers/{id}/refresh`, `PATCH /mcp/servers/{id}/tools/{tool_id}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_api.py`. Mirror the auth/client setup used by `tests/test_mcp_api`'s sibling `tests/test_memory_api.py` (build an app, override `get_current_user`/app state, issue a bearer token). The adapter is monkeypatched so no server is contacted:

```python
"""API tests for the /mcp router, with the MCP adapter mocked."""

import pytest

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import DiscoveredTool, McpUnreachableError

pytestmark = pytest.mark.asyncio


async def test_attach_list_and_toggle_tool(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Attach a server, list it with tools, then disable one tool."""

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)

    resp = await mcp_client.post(
        "/mcp/servers",
        json={"name": "home", "url": "http://ha/mcp", "headers": {"X-Api-Key": "k"}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "home"
    assert {t["name"] for t in body["tools"]} == {"turn_on", "turn_off"}
    server_id = body["id"]
    tool_id = next(t["id"] for t in body["tools"] if t["name"] == "turn_off")

    listed = await mcp_client.get("/mcp/servers")
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()] == ["home"]

    toggled = await mcp_client.patch(
        f"/mcp/servers/{server_id}/tools/{tool_id}", json={"enabled": False}
    )
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False


async def test_attach_unreachable_returns_502(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A server that can't be reached returns 502 with an actionable message."""

    async def boom(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("connection refused")

    monkeypatch.setattr(mcp_adapter, "discover", boom)
    resp = await mcp_client.post(
        "/mcp/servers", json={"name": "home", "url": "http://ha/mcp", "headers": {}}
    )
    assert resp.status_code == 502
    assert "refused" in resp.json()["detail"]


async def test_delete_server(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Deleting a server returns 204 and removes it from the list."""

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {})]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    created = await mcp_client.post(
        "/mcp/servers", json={"name": "home", "url": "http://ha/mcp", "headers": {}}
    )
    server_id = created.json()["id"]
    deleted = await mcp_client.delete(f"/mcp/servers/{server_id}")
    assert deleted.status_code == 204
    assert (await mcp_client.get("/mcp/servers")).json() == []
```

Add an `mcp_client` fixture to `tests/test_mcp_api.py` modelled exactly on the authenticated-client fixture in `tests/test_memory_api.py` (same app construction, app-state wiring for `sessionmaker`/`agent`/`settings`, `get_current_user` override or real token). Use the `FakeAgent` from `support.py` for `app.state.agent`. Reuse the `migrated_engine`/`settings`/`make_user` fixtures from `conftest.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_api.py -v`
Expected: FAIL — the router does not exist yet (404s / import error).

- [ ] **Step 3: Add schemas to `src/capybara/api/schemas.py`**

Append (the file already imports `BaseModel`, `ConfigDict`, `Field`, `UUID`, `datetime`):

```python
class McpServerCreate(BaseModel):
    """Payload to attach an MCP server."""

    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


class McpServerUpdate(BaseModel):
    """Partial update for an MCP server. At least one field must be provided."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1)
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _require_one(self) -> "McpServerUpdate":
        """Reject an empty patch."""
        if self.name is None and self.url is None and self.headers is None and self.enabled is None:
            raise ValueError("at least one field must be provided")
        return self


class McpToolUpdate(BaseModel):
    """Payload to toggle a tool's enabled flag."""

    enabled: bool


class McpToolOut(BaseModel):
    """Response schema for a single discovered MCP tool."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    enabled: bool


class McpServerOut(BaseModel):
    """Response schema for an MCP server with its tools."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    enabled: bool
    last_connected_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    tools: list[McpToolOut]
```

Note: `McpServerOut` deliberately omits `headers` from responses — secrets are write-only over the API (never echoed back). `model_validator` is already imported in this file (used by `FactUpdate`).

- [ ] **Step 4: Create the router `src/capybara/api/routers/mcp.py`**

```python
"""Router for MCP server management and per-tool curation."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.api.dependencies import get_current_user, get_mcp_service
from capybara.api.schemas import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpToolOut,
    McpToolUpdate,
)
from capybara.db.models import McpServer, McpTool, User
from capybara.services.mcp_service import McpService

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _server_out(server: McpServer, tools: list[McpTool]) -> McpServerOut:
    """Assemble a server + its tools into the response schema."""
    return McpServerOut(
        id=server.id,
        name=server.name,
        url=server.url,
        enabled=server.enabled,
        last_connected_at=server.last_connected_at,
        last_error=server.last_error,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=[McpToolOut.model_validate(t) for t in tools],
    )


def _raise_for_mcp_error(exc: McpUnreachableError | McpProtocolError) -> NoReturn:
    """Translate an MCP connection failure into an actionable HTTP error.

    Unreachable → 502 (upstream outage); protocol/handshake failure → 400 (bad config).
    """
    if isinstance(exc, McpUnreachableError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> list[McpServerOut]:
    """Return the current user's MCP servers with their tools."""
    return [_server_out(s, tools) for s, tools in await service.list_servers(user.id)]


@router.post("/servers", status_code=status.HTTP_201_CREATED, response_model=McpServerOut)
async def attach_server(
    payload: McpServerCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Attach an MCP server: validate the connection and persist it with its tools."""
    try:
        server, tools = await service.attach(user.id, payload.name, payload.url, payload.headers)
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    return _server_out(server, tools)


@router.get("/servers/{server_id}", response_model=McpServerOut)
async def get_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Return a single MCP server with its tools (404 if not owned)."""
    loaded = await service.get_server(user.id, server_id)
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.patch("/servers/{server_id}", response_model=McpServerOut)
async def update_server(
    server_id: UUID,
    payload: McpServerUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Update a server's name/url/headers/enabled (404 if not owned)."""
    loaded = await service.update_server(
        user.id,
        server_id,
        name=payload.name,
        url=payload.url,
        headers=payload.headers,
        enabled=payload.enabled,
    )
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> None:
    """Delete an MCP server and its tools (404 if not owned)."""
    if not await service.delete_server(user.id, server_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")


@router.post("/servers/{server_id}/refresh", response_model=McpServerOut)
async def refresh_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Re-discover a server's tools, preserving enabled flags (404 if not owned)."""
    try:
        loaded = await service.refresh(user.id, server_id)
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.patch("/servers/{server_id}/tools/{tool_id}", response_model=McpToolOut)
async def update_tool(
    server_id: UUID,
    tool_id: UUID,
    payload: McpToolUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpToolOut:
    """Toggle a tool's enabled flag (curation); 404 if the server/tool is not owned."""
    tool = await service.set_tool_enabled(user.id, server_id, tool_id, enabled=payload.enabled)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP tool not found")
    return McpToolOut.model_validate(tool)
```

- [ ] **Step 5: Wire the router in `src/capybara/main.py`**

Add `mcp` to the routers import and include it alongside the others:

```python
    from capybara.api.routers import auth, chats, events, health, mcp, memory, models, users
    ...
    fastapi_app.include_router(mcp.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_api.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Lint + type-check**

Run: `uv run ruff check src/capybara/api/routers/mcp.py src/capybara/api/schemas.py src/capybara/main.py tests/test_mcp_api.py && uv run mypy src`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/api/routers/mcp.py src/capybara/api/schemas.py src/capybara/main.py tests/test_mcp_api.py
git commit -m "feat(mcp): /mcp router — attach, list, update, refresh, tool curation"
```

---

## Task 9: Full-suite gate + README note

**Files:**
- Modify: `README.md` (MCP section)

- [ ] **Step 1: Run the entire backend suite**

Run: `uv run pytest`
Expected: PASS (all prior tests + the new MCP tests).

- [ ] **Step 2: Full quality gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: clean. Fix any formatting with `uv run ruff format .`.

- [ ] **Step 3: Add a README MCP section**

Add a short section to `README.md` (after "Memory"), documenting: remote (HTTP/SSE) MCP servers, attach via `POST /mcp/servers` with `{name, url, headers}`, per-tool curation via `PATCH /mcp/servers/{id}/tools/{tool_id}`, that enabled tools of enabled servers are offered to the chat agent and stream through the same tool-call UI, and the **known limitation**: auth headers are stored unencrypted (a TODO for a follow-up slice), plus the fail-open behaviour (an unreachable server is skipped mid-turn). Keep it to ~12 lines, matching the style of the existing Memory section.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(mcp): document remote MCP servers and the unencrypted-headers limitation"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Remote HTTP/SSE transport → adapter Task 4 (`StreamableHttpTransport`). ✅
- Per-turn connection + cached tool metadata → tools persisted at attach (Task 5); toolsets built per turn (Tasks 5/7); session opened per turn by pydantic-ai + a reachability preflight. ✅
- Arbitrary auth headers → `headers` JSONB (Tasks 1/2), threaded through adapter (Task 4), write-only over API (Task 8). ✅
- Per-tool curation → `mcp_tools.enabled` + `PATCH .../tools/{id}` + enabled-only filtering (Tasks 1/5/8). ✅
- Per-user scoping → `user_id` FK + ownership checks (Tasks 1/5/8). ✅
- Maximum reuse / `toolsets=` on `stream_reply` + `ToolCallCard` path → Tasks 6/7. ✅
- Fail-open at turn time; loud on attach/refresh → `build_toolsets` skip (Task 5); router 502/400 (Task 8). ✅
- Tool namespacing → `prefixed(slug)` (Tasks 4/5). ✅
- Secrets stored plain, **encryption TODO** → model docstring + `McpServerOut` omits headers + README note (Tasks 1/8/9). ✅
- Error mapping (attach unreachable → 502; bad handshake → 400) → Task 8 + tests. ✅
- Testing: real Postgres + mocked MCP boundary; chat integration via `FunctionModel`/`FunctionToolset` → Tasks 3/5/6/7/8. ✅

**Type consistency:** `discover`/`build_toolset` signatures, `McpService` method names, `ChatService(..., mcp_service=)`, `stream_reply(..., toolsets=)`, and schema field names are used identically across tasks. ✅

**Placeholder scan:** the only intentional "TODO" is the flagged secret-encryption limitation (a deliberate scope boundary, not an incomplete step). The `engine_from`/`create_sessionmaker` snippet in Task 7 Step 1 is explicitly marked illustrative with an instruction to reuse the existing `test_chat_service.py` construction pattern. ✅
