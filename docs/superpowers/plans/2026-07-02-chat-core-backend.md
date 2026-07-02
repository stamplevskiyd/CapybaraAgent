# Chat Core Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CapybaraAgent backend chat core — create a chat, send a message, stream the LLM (Ollama) reply over SSE, and persist chats/messages to Postgres.

**Architecture:** Layered `api → services → repositories → db`, with a thin provider-agnostic `agent` module (pydantic-ai) so the LLM can be swapped. Async throughout; one SQLAlchemy `AsyncSession` per request via a reusable FastAPI dependency.

**Tech Stack:** Python 3.12, FastAPI, pydantic-ai (Ollama via its OpenAI-compatible endpoint), SQLAlchemy 2.0 async + asyncpg, Alembic, pydantic-settings, uv, ruff, mypy, pytest + pytest-asyncio + httpx + testcontainers.

## Global Constraints

- Python `>=3.12`. Fully type-annotated; `mypy` runs in strict mode over `src`.
- Dependency management via **uv** only. Lint + format via **ruff**; type-check via **mypy**.
- Package root is `src/capybara/`. Data access lives **only** in `repositories/`.
- One `AsyncSession` per request; engine owned by the app lifespan; explicit commit/rollback.
- LLM accessed **only** through the `agent/` module; services never import a provider SDK.
- Provider is Ollama on the **host**; default base URL `http://host.docker.internal:11434`, default model `llama3.1` — both config-driven.
- Timestamps stored in UTC. Primary keys are UUIDs.
- Tests never call a real LLM: use pydantic-ai `TestModel`. DB tests use a real Postgres via testcontainers with per-test rollback.

---

## File Structure

```
pyproject.toml              # uv project, deps, ruff + mypy config
.env.example                # DATABASE_URL, OLLAMA_BASE_URL, DEFAULT_MODEL
alembic.ini                 # Alembic config
Dockerfile                  # uv multi-stage image for api
docker-compose.yml          # api + postgres (Ollama on host)
src/capybara/
  __init__.py
  config.py                 # Settings (pydantic-settings) + get_settings()
  db/
    __init__.py
    base.py                 # DeclarativeBase
    engine.py               # create_engine / create_sessionmaker
    models.py               # User, Chat, Message
  repositories/
    __init__.py
    user_repo.py            # UserRepo
    chat_repo.py            # ChatRepo
    message_repo.py         # MessageRepo
  agent/
    __init__.py
    ollama.py               # build_agent()
    stream.py               # to_model_messages(), stream_reply(), ReplyAccumulator
  services/
    __init__.py
    events.py               # Delta / Done / Error stream events
    chat_service.py         # ChatService.stream_turn()
  api/
    __init__.py
    schemas.py              # request/response Pydantic models
    dependencies.py         # get_session, get_current_user, repo/service providers
    routers/
      __init__.py
      chats.py              # /chats endpoints incl. SSE
      health.py             # /health
  main.py                   # FastAPI app + lifespan + router wiring
  migrations/
    env.py                  # async Alembic env
    versions/               # migration scripts
tests/
  conftest.py               # settings, postgres container, async session, client fixtures
  test_config.py
  test_db_session.py
  test_models.py
  test_migrations.py
  test_repositories.py
  test_health.py
  test_agent_stream.py
  test_chat_service.py
  test_chats_api.py
```

---

### Task 1: Project scaffold, tooling & settings

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/capybara/__init__.py`, `src/capybara/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `capybara.config.Settings` (fields `database_url: str`, `ollama_base_url: str`, `default_model: str`); `capybara.config.get_settings() -> Settings` (lru_cached).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "capybara"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic-ai>=0.0.20",
    "pydantic-settings>=2.5",
    "sqlalchemy[asyncio]>=2.0.35",
    "asyncpg>=0.30",
    "alembic>=1.13",
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "testcontainers[postgresql]>=4.8",
    "ruff>=0.7",
    "mypy>=1.13",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/capybara"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "src"
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["testcontainers.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.env.example`**

```bash
DATABASE_URL=postgresql+asyncpg://capybara:capybara@localhost:5432/capybara
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_MODEL=llama3.1
```

- [ ] **Step 3: Install and verify toolchain**

Run: `uv sync`
Expected: resolves and installs all deps into `.venv`.

- [ ] **Step 4: Write the failing test** — `tests/test_config.py`

```python
from capybara.config import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("DEFAULT_MODEL", "test-model")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.ollama_base_url == "http://example:11434"
    assert settings.default_model == "test-model"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.config`.

- [ ] **Step 6: Write `src/capybara/__init__.py` (empty) and `src/capybara/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://host.docker.internal:11434"
    default_model: str = "llama3.1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 7: Run tests + quality gates**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check . && uv run mypy src`
Expected: test PASS, ruff clean, mypy clean.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .env.example src/capybara tests/test_config.py
git commit -m "feat: project scaffold, tooling, and settings"
```

---

### Task 2: Async DB engine, session & test fixtures

**Files:**
- Create: `src/capybara/db/__init__.py`, `src/capybara/db/base.py`, `src/capybara/db/engine.py`, `tests/conftest.py`
- Test: `tests/test_db_session.py`

**Interfaces:**
- Produces: `capybara.db.base.Base` (DeclarativeBase); `capybara.db.engine.create_engine(settings) -> AsyncEngine`; `capybara.db.engine.create_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`.
- Produces (fixtures): `pg_url` (session-scoped str), `engine` (async), `session` (function-scoped `AsyncSession` rolled back after each test).

- [ ] **Step 1: Write `src/capybara/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Write `src/capybara/db/engine.py`**

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from capybara.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from capybara.config import Settings
from capybara.db.base import Base
from capybara.db.engine import create_engine, create_sessionmaker


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def settings(pg_url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=pg_url,
        ollama_base_url="http://ollama.test:11434",
        default_model="test-model",
    )


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(settings)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = create_sessionmaker(engine)
    async with maker() as sess:
        yield sess
        await sess.rollback()
```

- [ ] **Step 4: Write the failing test** — `tests/test_db_session.py`

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_session_executes_query(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_db_session.py -v`
Expected: FAIL — import errors until `db/` modules exist (they now do); container spins up and query passes only once wiring is correct. If it fails on import, fix the module paths.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_db_session.py -v`
Expected: PASS (Docker must be running for testcontainers).

- [ ] **Step 7: Quality gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add src/capybara/db tests/conftest.py tests/test_db_session.py
git commit -m "feat: async db engine, sessionmaker, and test fixtures"
```

---

### Task 3: ORM models (User, Chat, Message)

**Files:**
- Create: `src/capybara/db/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `User(id: UUID, username: str, display_name: str, created_at: datetime)`; `Chat(id: UUID, user_id: UUID, title: str, created_at, updated_at)`; `Message(id: UUID, chat_id: UUID, role: str, content: str, model: str | None, usage_json: dict | None, incomplete: bool, created_at)`. `Message.role` ∈ {`"user"`,`"assistant"`,`"system"`}.

- [ ] **Step 1: Write the failing test** — `tests/test_models.py`

```python
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat, Message, User


async def test_insert_and_read_graph(session: AsyncSession) -> None:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()

    chat = Chat(user_id=user.id, title="First chat")
    session.add(chat)
    await session.flush()

    msg = Message(chat_id=chat.id, role="user", content="Привет")
    session.add(msg)
    await session.flush()

    loaded = (await session.execute(select(Message).where(Message.chat_id == chat.id))).scalar_one()
    assert loaded.role == "user"
    assert loaded.content == "Привет"
    assert loaded.incomplete is False
    assert loaded.model is None
    assert isinstance(user.id, type(uuid4()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.db.models`.

- [ ] **Step 3: Write `src/capybara/db/models.py`**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Новый чат")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    incomplete: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    chat: Mapped["Chat"] = relationship(back_populates="messages")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Quality gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add src/capybara/db/models.py tests/test_models.py
git commit -m "feat: User, Chat, Message ORM models"
```

---

### Task 4: Alembic setup, initial migration & seed user

**Files:**
- Create: `alembic.ini`, `src/capybara/migrations/env.py`, `src/capybara/migrations/versions/` (generated), `src/capybara/migrations/script.py.mako`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: applying migrations to an empty DB creates `users`, `chats`, `messages` and inserts one seed user with `username="roman"`.

- [ ] **Step 1: Create `alembic.ini`**

```ini
[alembic]
script_location = src/capybara/migrations
prepend_sys_path = src

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Initialise Alembic async layout**

Run: `uv run alembic init -t async src/capybara/migrations`
Then delete the `alembic.ini` it created at repo root only if it overwrote Step 1 — keep the Step 1 version.

- [ ] **Step 3: Edit `src/capybara/migrations/env.py`** — point at our metadata and settings

Replace the config/target-metadata/URL wiring with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from capybara.config import get_settings
from capybara.db.base import Base
from capybara.db import models  # noqa: F401  (register tables on metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

- [ ] **Step 4: Generate the initial schema migration**

Run (against a running Postgres — use the compose DB from Task 9 or a local one; set `DATABASE_URL` in `.env`):
`uv run alembic revision --autogenerate -m "initial schema"`
Expected: a new file in `versions/` creating `users`, `chats`, `messages`.

- [ ] **Step 5: Create the seed-user migration**

Run: `uv run alembic revision -m "seed local user"`
Edit the generated file's `upgrade()`/`downgrade()`:

```python
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers set by Alembic — keep the generated values.

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
```

- [ ] **Step 6: Write the failing test** — `tests/test_migrations.py`

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_migrations_create_schema_and_seed(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        ).scalars().all()
        assert {"users", "chats", "messages"} <= set(tables)

        count = (
            await conn.execute(text("SELECT count(*) FROM users WHERE username = 'roman'"))
        ).scalar_one()
        assert count == 1
```

Add a `migrated_engine` fixture to `tests/conftest.py` (runs Alembic instead of `create_all`):

```python
import pytest_asyncio
from alembic import command
from alembic.config import Config


@pytest_asyncio.fixture
async def migrated_engine(settings) -> AsyncIterator[AsyncEngine]:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    eng = create_engine(settings)
    yield eng
    await eng.dispose()
    command.downgrade(cfg, "base")
```

- [ ] **Step 7: Run test to verify it fails, then passes**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL first if env.py/seed not wired; PASS once migrations apply and seed inserts.

- [ ] **Step 8: Quality gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add alembic.ini src/capybara/migrations tests/test_migrations.py tests/conftest.py
git commit -m "feat: alembic async setup, initial schema, and seed user"
```

---

### Task 5: Repositories (User, Chat, Message)

**Files:**
- Create: `src/capybara/repositories/__init__.py`, `user_repo.py`, `chat_repo.py`, `message_repo.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Produces:
  - `UserRepo(session).get(user_id: UUID) -> User | None`
  - `ChatRepo(session).create(user_id: UUID, title: str | None) -> Chat`
  - `ChatRepo(session).get(chat_id: UUID) -> Chat | None`
  - `ChatRepo(session).list_for_user(user_id: UUID) -> list[Chat]`
  - `ChatRepo(session).touch(chat: Chat) -> None`
  - `MessageRepo(session).add(chat_id, role, content, *, model=None, usage=None, incomplete=False) -> Message`
  - `MessageRepo(session).list_for_chat(chat_id: UUID) -> list[Message]` (ordered by `created_at`)

- [ ] **Step 1: Write the failing test** — `tests/test_repositories.py`

```python
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo


async def _seed_user(session: AsyncSession) -> User:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()
    return user


async def test_user_repo_get(session: AsyncSession) -> None:
    user = await _seed_user(session)
    fetched = await UserRepo(session).get(user.id)
    assert fetched is not None and fetched.username == "roman"
    assert await UserRepo(session).get(uuid4()) is None


async def test_chat_repo_create_list_get(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chats = ChatRepo(session)
    chat = await chats.create(user.id, "Sales Q2")
    assert chat.title == "Sales Q2"
    assert (await chats.get(chat.id)).id == chat.id  # type: ignore[union-attr]
    listed = await chats.list_for_user(user.id)
    assert [c.id for c in listed] == [chat.id]


async def test_chat_repo_create_default_title(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, None)
    assert chat.title == "Новый чат"


async def test_message_repo_add_and_order(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "c")
    messages = MessageRepo(session)
    await messages.add(chat.id, "user", "Привет")
    await messages.add(chat.id, "assistant", "Здравствуйте", model="test-model")
    ordered = await messages.list_for_chat(chat.id)
    assert [m.role for m in ordered] == ["user", "assistant"]
    assert ordered[1].model == "test-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repositories.py -v`
Expected: FAIL — repository modules do not exist.

- [ ] **Step 3: Write `src/capybara/repositories/user_repo.py`**

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)
```

- [ ] **Step 4: Write `src/capybara/repositories/chat_repo.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat


class ChatRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, title: str | None) -> Chat:
        chat = Chat(user_id=user_id)
        if title is not None:
            chat.title = title
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def get(self, chat_id: UUID) -> Chat | None:
        return await self._session.get(Chat, chat_id)

    async def list_for_user(self, user_id: UUID) -> list[Chat]:
        stmt = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def touch(self, chat: Chat) -> None:
        from datetime import UTC, datetime

        chat.updated_at = datetime.now(UTC)
        await self._session.flush()
```

- [ ] **Step 5: Write `src/capybara/repositories/message_repo.py`**

```python
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Message


class MessageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        chat_id: UUID,
        role: str,
        content: str,
        *,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        incomplete: bool = False,
    ) -> Message:
        message = Message(
            chat_id=chat_id,
            role=role,
            content=content,
            model=model,
            usage_json=usage,
            incomplete=incomplete,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_for_chat(self, chat_id: UUID) -> list[Message]:
        stmt = (
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())
```

- [ ] **Step 6: Write `src/capybara/repositories/__init__.py`**

```python
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo

__all__ = ["ChatRepo", "MessageRepo", "UserRepo"]
```

- [ ] **Step 7: Run tests + gates**

Run: `uv run pytest tests/test_repositories.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/repositories tests/test_repositories.py
git commit -m "feat: user/chat/message repositories"
```

---

### Task 6: Agent module (pydantic-ai + Ollama) and streaming

**Files:**
- Create: `src/capybara/agent/__init__.py`, `src/capybara/agent/ollama.py`, `src/capybara/agent/stream.py`
- Test: `tests/test_agent_stream.py`

**Interfaces:**
- Produces:
  - `capybara.agent.ollama.build_agent(settings: Settings) -> Agent[None, str]`
  - `capybara.agent.stream.ReplyAccumulator` (dataclass: `text: str`, `usage: dict | None`, `model: str | None`)
  - `capybara.agent.stream.to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]`
  - `capybara.agent.stream.stream_reply(agent, user_content: str, history: list[ModelMessage], acc: ReplyAccumulator) -> AsyncIterator[str]` (yields text deltas; fills `acc` on completion)

- [ ] **Step 1: Write the failing test** — `tests/test_agent_stream.py`

```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from capybara.agent.stream import ReplyAccumulator, stream_reply, to_model_messages
from capybara.db.models import Message


async def test_stream_reply_yields_deltas_and_fills_accumulator() -> None:
    agent: Agent[None, str] = Agent(TestModel(custom_output_text="Привет, Роман"))
    acc = ReplyAccumulator()
    chunks = [delta async for delta in stream_reply(agent, "Привет", [], acc)]
    assert "".join(chunks) == "Привет, Роман"
    assert acc.text == "Привет, Роман"


def test_to_model_messages_maps_roles() -> None:
    msgs = [
        Message(chat_id=None, role="user", content="hi"),  # type: ignore[arg-type]
        Message(chat_id=None, role="assistant", content="hello"),  # type: ignore[arg-type]
    ]
    history = to_model_messages(msgs)
    assert len(history) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_stream.py -v`
Expected: FAIL — `capybara.agent.stream` missing.

- [ ] **Step 3: Write `src/capybara/agent/ollama.py`**

```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.config import Settings


def build_agent(settings: Settings) -> Agent[None, str]:
    model = OpenAIModel(
        settings.default_model,
        provider=OpenAIProvider(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",  # Ollama ignores the key; required by the client.
        ),
    )
    return Agent(model)
```

- [ ] **Step 4: Write `src/capybara/agent/stream.py`**

```python
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from capybara.db.models import Message


@dataclass
class ReplyAccumulator:
    text: str = ""
    usage: dict | None = None
    model: str | None = None


def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for message in messages:
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
        elif message.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return history


async def stream_reply(
    agent: Agent[None, str],
    user_content: str,
    history: list[ModelMessage],
    acc: ReplyAccumulator,
) -> AsyncIterator[str]:
    async with agent.run_stream(user_content, message_history=history) as result:
        async for text in result.stream_text(delta=True):
            acc.text += text
            yield text
        usage = result.usage()
        acc.usage = {"total_tokens": usage.total_tokens} if usage else None
        acc.model = result.model_name
```

- [ ] **Step 5: Write `src/capybara/agent/__init__.py`**

```python
from capybara.agent.ollama import build_agent
from capybara.agent.stream import ReplyAccumulator, stream_reply, to_model_messages

__all__ = ["ReplyAccumulator", "build_agent", "stream_reply", "to_model_messages"]
```

- [ ] **Step 6: Run tests + gates**

Run: `uv run pytest tests/test_agent_stream.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean. (If `result.model_name` differs in the installed pydantic-ai version, adjust to the documented attribute — the accumulator contract stays the same.)

- [ ] **Step 7: Commit**

```bash
git add src/capybara/agent tests/test_agent_stream.py
git commit -m "feat: pydantic-ai Ollama agent and streaming wrapper"
```

---

### Task 7: Chat service (orchestration) & stream events

**Files:**
- Create: `src/capybara/services/__init__.py`, `src/capybara/services/events.py`, `src/capybara/services/chat_service.py`
- Test: `tests/test_chat_service.py`

**Interfaces:**
- Produces:
  - `capybara.services.events.Delta(text: str)`, `Done(message_id: str, usage: dict | None)`, `Error(message: str)`; `StreamEvent = Delta | Done | Error`
  - `ChatService(chats: ChatRepo, messages: MessageRepo, agent: Agent[None, str])`
  - `ChatService.stream_turn(chat_id: UUID, user_content: str) -> AsyncIterator[StreamEvent]`

- [ ] **Step 1: Write the failing test** — `tests/test_chat_service.py`

```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done


async def test_stream_turn_streams_and_persists(session: AsyncSession) -> None:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()
    chats, messages = ChatRepo(session), MessageRepo(session)
    chat = await chats.create(user.id, "c")

    agent: Agent[None, str] = Agent(TestModel(custom_output_text="Ответ"))
    service = ChatService(chats, messages, agent)

    events = [e async for e in service.stream_turn(chat.id, "Вопрос")]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Ответ"
    assert len(done) == 1

    stored = await messages.list_for_chat(chat.id)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].content == "Ответ"
    assert stored[1].incomplete is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: FAIL — service modules missing.

- [ ] **Step 3: Write `src/capybara/services/events.py`**

```python
from dataclasses import dataclass


@dataclass
class Delta:
    text: str


@dataclass
class Done:
    message_id: str
    usage: dict | None


@dataclass
class Error:
    message: str


StreamEvent = Delta | Done | Error
```

- [ ] **Step 4: Write `src/capybara/services/chat_service.py`**

```python
from collections.abc import AsyncIterator
from uuid import UUID

from pydantic_ai import Agent

from capybara.agent.stream import ReplyAccumulator, stream_reply, to_model_messages
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.events import Delta, Done, StreamEvent


class ChatService:
    def __init__(
        self, chats: ChatRepo, messages: MessageRepo, agent: Agent[None, str]
    ) -> None:
        self._chats = chats
        self._messages = messages
        self._agent = agent

    async def stream_turn(
        self, chat_id: UUID, user_content: str
    ) -> AsyncIterator[StreamEvent]:
        history_rows = await self._messages.list_for_chat(chat_id)
        await self._messages.add(chat_id, "user", user_content)
        history = to_model_messages(history_rows)

        acc = ReplyAccumulator()
        completed = False
        try:
            async for delta in stream_reply(self._agent, user_content, history, acc):
                yield Delta(text=delta)
            completed = True
        finally:
            assistant = await self._messages.add(
                chat_id,
                "assistant",
                acc.text,
                model=acc.model,
                usage=acc.usage,
                incomplete=not completed,
            )
            chat = await self._chats.get(chat_id)
            if chat is not None:
                await self._chats.touch(chat)
            if completed:
                yield Done(message_id=str(assistant.id), usage=acc.usage)
```

- [ ] **Step 5: Write `src/capybara/services/__init__.py`**

```python
from capybara.services.chat_service import ChatService

__all__ = ["ChatService"]
```

- [ ] **Step 6: Run tests + gates**

Run: `uv run pytest tests/test_chat_service.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 7: Commit**

```bash
git add src/capybara/services tests/test_chat_service.py
git commit -m "feat: chat service orchestration with stream events"
```

---

### Task 8: FastAPI app, reusable dependencies & /health

**Files:**
- Create: `src/capybara/api/__init__.py`, `src/capybara/api/dependencies.py`, `src/capybara/api/routers/__init__.py`, `src/capybara/api/routers/health.py`, `src/capybara/main.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Produces (reusable deps): `get_session() -> AsyncIterator[AsyncSession]`, `get_current_user(session) -> User`, `get_chat_repo(session) -> ChatRepo`, `get_message_repo(session) -> MessageRepo`, `get_agent() -> Agent[None, str]`, `get_chat_service(...) -> ChatService`.
- Produces: `capybara.main.app` (FastAPI). `GET /health -> {"status": "ok", "ollama": "up"|"down"}`.
- App state: `app.state.sessionmaker`, `app.state.agent` set in lifespan.

- [ ] **Step 1: Write the failing test** — `tests/test_health.py`

```python
import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from capybara.api.dependencies import get_session
from capybara.main import app


@pytest_asyncio.fixture
async def client(engine, monkeypatch) -> AsyncClient:  # type: ignore[no-untyped-def]
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)

    async def _override_session():
        async with maker() as sess:
            yield sess

    app.dependency_overrides[get_session] = _override_session

    async def _fake_ollama_up() -> bool:
        return True

    monkeypatch.setattr("capybara.api.routers.health.ollama_is_up", _fake_ollama_up)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_health_reports_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "ollama": "up"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `capybara.main` / dependencies missing.

- [ ] **Step 3: Write `src/capybara/api/dependencies.py`**

```python
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request
from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    maker = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, LOCAL_USER_ID)
    if user is None:
        raise RuntimeError("Local user not seeded — run migrations")
    return user


def get_chat_repo(session: AsyncSession = Depends(get_session)) -> ChatRepo:
    return ChatRepo(session)


def get_message_repo(session: AsyncSession = Depends(get_session)) -> MessageRepo:
    return MessageRepo(session)


def get_agent(request: Request) -> Agent[None, str]:
    return request.app.state.agent


def get_chat_service(
    chats: ChatRepo = Depends(get_chat_repo),
    messages: MessageRepo = Depends(get_message_repo),
    agent: Agent[None, str] = Depends(get_agent),
) -> ChatService:
    return ChatService(chats, messages, agent)
```

- [ ] **Step 4: Write `src/capybara/api/routers/health.py`**

```python
import httpx
from fastapi import APIRouter, Request

router = APIRouter()


async def ollama_is_up(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(base_url)
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    base_url = request.app.state.settings.ollama_base_url
    up = await ollama_is_up(base_url)
    return {"status": "ok", "ollama": "up" if up else "down"}
```

Note: the test monkeypatches `capybara.api.routers.health.ollama_is_up`; keep the name.

- [ ] **Step 5: Write `src/capybara/main.py`**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from capybara.agent.ollama import build_agent
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.agent = build_agent(settings)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
    from capybara.api.routers import chats, health

    app.include_router(health.router)
    app.include_router(chats.router)
    return app


app = create_app()
```

Note: `chats.router` is created in Task 9. For this task, temporarily include only `health.router` and add `chats` import in Task 9. To keep this task self-contained, create an empty `src/capybara/api/routers/chats.py` with `from fastapi import APIRouter` and `router = APIRouter()`.

- [ ] **Step 6: Create stub `src/capybara/api/routers/chats.py`**

```python
from fastapi import APIRouter

router = APIRouter()
```

- [ ] **Step 7: Run tests + gates**

Run: `uv run pytest tests/test_health.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/api src/capybara/main.py tests/test_health.py
git commit -m "feat: FastAPI app, reusable dependencies, and /health"
```

---

### Task 9: Chat API routers (CRUD + SSE streaming)

**Files:**
- Create: `src/capybara/api/schemas.py`
- Modify: `src/capybara/api/routers/chats.py` (replace the stub)
- Test: `tests/test_chats_api.py`

**Interfaces:**
- Consumes: `get_current_user`, `get_chat_repo`, `get_message_repo`, `get_chat_service` from Task 8; `ChatService.stream_turn` from Task 7.
- Produces: `POST /chats`, `GET /chats`, `GET /chats/{chat_id}`, `POST /chats/{chat_id}/messages` (SSE).

- [ ] **Step 1: Write the failing test** — `tests/test_chats_api.py`

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from capybara.api.dependencies import get_agent, get_current_user, get_session
from capybara.db.models import User
from capybara.main import app


@pytest_asyncio.fixture
async def client(engine):  # type: ignore[no-untyped-def]
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = User(username="roman", display_name="Роман")
        setup.add(user)
        await setup.commit()
        user_id = user.id

    async def _override_session():
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def _override_user():
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_agent] = lambda: Agent(
        TestModel(custom_output_text="Ответ агента")
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_create_and_get_chat(client: AsyncClient) -> None:
    created = await client.post("/chats", json={"title": "Продажи"})
    assert created.status_code == 201
    chat_id = created.json()["id"]

    listed = await client.get("/chats")
    assert any(c["id"] == chat_id for c in listed.json())

    fetched = await client.get(f"/chats/{chat_id}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == []


async def test_get_missing_chat_404(client: AsyncClient) -> None:
    resp = await client.get("/chats/00000000-0000-0000-0000-0000000000ff")
    assert resp.status_code == 404


async def test_send_message_streams_sse_and_persists(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]

    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    assert "event: delta" in body
    assert "event: done" in body
    assert "Ответ агента" in body

    fetched = await client.get(f"/chats/{chat_id}")
    roles = [m["role"] for m in fetched.json()["messages"]]
    assert roles == ["user", "assistant"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chats_api.py -v`
Expected: FAIL — schemas and real chat routes missing.

- [ ] **Step 3: Write `src/capybara/api/schemas.py`**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatCreate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    model: str | None
    incomplete: bool
    created_at: datetime


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    messages: list[MessageOut]
```

- [ ] **Step 4: Replace `src/capybara/api/routers/chats.py`**

```python
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from capybara.api.dependencies import (
    get_chat_repo,
    get_chat_service,
    get_current_user,
    get_message_repo,
)
from capybara.api.schemas import (
    ChatCreate,
    ChatDetailOut,
    ChatOut,
    MessageCreate,
    MessageOut,
)
from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done, Error

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: User = Depends(get_current_user),
    chats: ChatRepo = Depends(get_chat_repo),
) -> ChatOut:
    chat = await chats.create(user.id, payload.title)
    return ChatOut.model_validate(chat)


@router.get("", response_model=list[ChatOut])
async def list_chats(
    user: User = Depends(get_current_user),
    chats: ChatRepo = Depends(get_chat_repo),
) -> list[ChatOut]:
    rows = await chats.list_for_user(user.id)
    return [ChatOut.model_validate(c) for c in rows]


@router.get("/{chat_id}", response_model=ChatDetailOut)
async def get_chat(
    chat_id: UUID,
    chats: ChatRepo = Depends(get_chat_repo),
    messages: MessageRepo = Depends(get_message_repo),
) -> ChatDetailOut:
    chat = await chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    rows = await messages.list_for_chat(chat_id)
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageOut.model_validate(m) for m in rows],
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: UUID,
    payload: MessageCreate,
    chats: ChatRepo = Depends(get_chat_repo),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    if await chats.get(chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, payload.content):
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Done):
                    yield _sse("done", {"message_id": event.message_id, "usage": event.usage})
                elif isinstance(event, Error):
                    yield _sse("error", {"message": event.message})
        except Exception as exc:  # surface as SSE error, never a broken stream
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 5: Ensure `main.py` includes `chats.router`**

It already imports and includes `chats` from Task 8. Confirm no stub remains.

- [ ] **Step 6: Run tests + gates**

Run: `uv run pytest tests/test_chats_api.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 7: Full suite**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/api tests/test_chats_api.py
git commit -m "feat: chat CRUD endpoints and SSE message streaming"
```

---

### Task 10: Docker packaging & compose

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Modify: `README.md` (run instructions)

**Interfaces:**
- Produces: `docker compose up` starts `postgres` and `api`; `api` runs migrations then serves on `:8000`.

- [ ] **Step 1: Write `.dockerignore`**

```
.venv
__pycache__
.pytest_cache
.git
*.pyc
.env
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn capybara.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: capybara
      POSTGRES_PASSWORD: capybara
      POSTGRES_DB: capybara
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U capybara"]
      interval: 3s
      timeout: 3s
      retries: 10

  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://capybara:capybara@postgres:5432/capybara
      OLLAMA_BASE_URL: http://host.docker.internal:11434
      DEFAULT_MODEL: llama3.1
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "8000:8000"

volumes:
  pgdata:
```

- [ ] **Step 4: Validate compose config**

Run: `docker compose config`
Expected: prints the merged config with no errors.

- [ ] **Step 5: Build and smoke-test**

Run: `docker compose up --build -d && sleep 5 && curl -s localhost:8000/health`
Expected: JSON `{"status":"ok","ollama":"up"|"down"}` (Ollama `down` is acceptable if not running on host).
Then: `docker compose down`.

- [ ] **Step 6: Update `README.md`**

Add a "Running" section:

````markdown
## Running (backend chat core)

Prerequisites: Docker, and Ollama running on the host with a model pulled
(`ollama pull llama3.1`).

```bash
cp .env.example .env
docker compose up --build
curl -s localhost:8000/health
```

Dev loop: `uv sync && uv run pytest && uv run ruff check . && uv run mypy src`
````

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore README.md
git commit -m "feat: docker image and compose for api + postgres"
```

---

## Self-Review

**Spec coverage:**
- Purpose/streaming turn → Tasks 6, 7, 9. ✔
- Layered architecture (api→services→repositories→db) → Tasks 2–9. ✔
- Data model (users seeded, chats, messages incl. `incomplete`, `usage_json`) → Tasks 3, 4. ✔
- API contract (`POST/GET /chats`, `GET /chats/{id}`, SSE messages, `/health`) → Tasks 8, 9. ✔
- SSE event schema (`delta`/`done`/`error`) → Tasks 7, 9. ✔
- Error handling (404 missing chat, Ollama down in health, disconnect→incomplete via `finally`) → Tasks 7, 8, 9. ✔
- Session & dependency discipline (per-request session, reusable deps) → Tasks 2, 8. ✔
- Testing (TestModel, testcontainers, per-test rollback) → Tasks 2, 6, 7, 9. ✔
- Infra (compose api+postgres, Dockerfile uv, .env.example) → Tasks 1, 10. ✔

**Placeholder scan:** No TBD/TODO; every code step contains full code. The one stub (`chats.py` in Task 8) is intentional and replaced in Task 9.

**Type consistency:** `stream_reply`/`ReplyAccumulator`/`to_model_messages` signatures match between Tasks 6 and 7; `ChatService.stream_turn` signature matches between Tasks 7 and 9; dependency provider names (`get_session`, `get_current_user`, `get_chat_repo`, `get_message_repo`, `get_agent`, `get_chat_service`) match between Tasks 8 and 9; `Delta/Done/Error` used consistently in Tasks 7 and 9.

**Known adaptation points (flagged for the implementer, not placeholders):**
- pydantic-ai attribute names (`result.model_name`, `usage.total_tokens`) may differ slightly by installed version — Task 6 Step 6 notes this; the accumulator contract is stable.
- The initial Alembic autogenerate (Task 4 Step 4) needs a reachable Postgres; use the compose DB or a local instance.
