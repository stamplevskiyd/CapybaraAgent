# Memory-save Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface auto-capture ("что запомнилось") in the chat UI with a collapsible footer chip on the assistant message, delivered live over a new per-user SSE channel and persisted so it survives history reload.

**Architecture:** Extraction stays a deterministic post-response background task. When it saves ≥1 fact it (a) writes a summary onto the assistant `Message.memory_saves` JSONB column and (b) publishes a `memory-save` event to a new in-process `EventBus`. A new per-user persistent SSE endpoint `GET /events` streams those events to the browser, which attaches them to the matching message. Persistence is the source of truth; the live push is best-effort (a dropped event reappears on the next history load).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic-ai (TestModel/FunctionModel in tests), pytest + testcontainers Postgres. Frontend: React + TypeScript, @assistant-ui/react (external-store runtime), Vitest + MSW.

## Global Constraints

- Python 3.12+, fully type-annotated; strict mypy (`uv run mypy src`).
- ruff lint + format; every module/class/function has a docstring (pydocstyle google convention; tests exempt).
- Layering: `api` (routers + schemas + deps) → `services` → `repositories` → `db`. No DB queries in routers/services except through repositories. Services own short-lived sessions from the app sessionmaker.
- Repository pattern for all model access. Reusable FastAPI dependencies.
- TDD: write the failing test first. Fake the LLM with pydantic-ai `TestModel`; test repos/services/API against real Postgres (testcontainers) with per-test isolation.
- Commit after each task. Stage only the files this plan touches — never `git add -A` (the user commits concurrently).
- Reference commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy src`. Frontend (in `frontend/`): `npm run test`, `npm run lint`, `npm run typecheck`.

---

## Part A — Backend

### Task 1: `EventBus` in-process pub/sub

**Files:**
- Create: `src/capybara/services/event_bus.py`
- Test: `tests/test_event_bus.py`

**Interfaces:**
- Produces:
  - `class EventBus` with:
    - `def __init__(self, max_queue: int = 100) -> None`
    - `async def publish(self, user_id: UUID, event: dict[str, Any]) -> None` — fan out `event` to every active subscriber queue for `user_id`; drop silently if a queue is full (best-effort) and no-op when there are no subscribers.
    - `subscribe(self, user_id: UUID)` — an async context manager yielding `asyncio.Queue[dict[str, Any]]`; registers the queue on enter, removes it on exit.
  - Published `event` shape: `{"event": <str>, "data": <dict>}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_bus.py
"""Unit tests for the in-process EventBus pub/sub."""

import asyncio
from uuid import uuid4

from capybara.services.event_bus import EventBus


async def test_subscriber_receives_published_event() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid) as queue:
        await bus.publish(uid, {"event": "memory-save", "data": {"n": 1}})
        item = await asyncio.wait_for(queue.get(), timeout=1)
    assert item == {"event": "memory-save", "data": {"n": 1}}


async def test_events_are_isolated_per_user() -> None:
    bus = EventBus()
    a, b = uuid4(), uuid4()
    async with bus.subscribe(a) as qa, bus.subscribe(b) as qb:
        await bus.publish(a, {"event": "x", "data": {}})
        got = await asyncio.wait_for(qa.get(), timeout=1)
        assert got["event"] == "x"
        assert qb.empty()


async def test_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid):
        pass  # subscription removed on exit
    await bus.publish(uid, {"event": "x", "data": {}})  # must not raise


async def test_two_subscribers_same_user_both_receive() -> None:
    bus = EventBus()
    uid = uuid4()
    async with bus.subscribe(uid) as q1, bus.subscribe(uid) as q2:
        await bus.publish(uid, {"event": "x", "data": {}})
        assert (await asyncio.wait_for(q1.get(), timeout=1))["event"] == "x"
        assert (await asyncio.wait_for(q2.get(), timeout=1))["event"] == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'capybara.services.event_bus'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/capybara/services/event_bus.py
"""In-process per-user pub/sub for pushing server-side events to SSE subscribers.

Process-local by design: this is the single-container stand-in for a shared broker
(Redis pub/sub) that a future horizontal-scaling / background-tasks slice will swap in,
mirroring ``schedule_extraction`` being a stand-in for a real task queue.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class EventBus:
    """Fan out events to per-user subscriber queues held entirely in memory."""

    def __init__(self, max_queue: int = 100) -> None:
        """Create an empty bus whose subscriber queues hold at most *max_queue* events."""
        self._max_queue = max_queue
        self._subscribers: dict[UUID, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def publish(self, user_id: UUID, event: dict[str, Any]) -> None:
        """Deliver *event* to every active subscriber of *user_id* (best-effort)."""
        for queue in list(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer — drop rather than block the publisher
                logger.warning("dropping event for user %s: subscriber queue full", user_id)

    @asynccontextmanager
    async def subscribe(self, user_id: UUID) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Register a fresh queue for *user_id* and remove it when the context exits."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.setdefault(user_id, set()).add(queue)
        try:
            yield queue
        finally:
            subs = self._subscribers.get(user_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subscribers[user_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_event_bus.py -v && uv run mypy src && uv run ruff check .`
Expected: PASS (4 passed), mypy clean, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/services/event_bus.py tests/test_event_bus.py
git commit -m "feat(events): in-process per-user EventBus pub/sub"
```

---

### Task 2: `GET /events` SSE endpoint + wiring

**Files:**
- Create: `src/capybara/api/sse.py`
- Create: `src/capybara/api/routers/events.py`
- Modify: `src/capybara/api/dependencies.py` (add `get_event_bus`)
- Modify: `src/capybara/main.py` (create bus in lifespan; register router)
- Test: `tests/test_events_api.py`

**Interfaces:**
- Consumes: `EventBus` (Task 1); `get_current_user` (existing).
- Produces:
  - `def format_sse(event: str, data: dict[str, Any]) -> str` and `SSE_HEADERS: dict[str, str]` in `api/sse.py`.
  - `def get_event_bus(request: Request) -> EventBus` (lazy-inits `request.app.state.event_bus` so tests that don't run the lifespan still work).
  - `GET /events` streaming `text/event-stream`, emitting `format_sse(item["event"], item["data"])` per published event and `": keepalive\n\n"` every 15s.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_api.py
"""Integration test for the per-user GET /events SSE channel."""

import asyncio

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import get_current_user, get_event_bus
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app
from capybara.services.event_bus import EventBus


@pytest_asyncio.fixture
async def bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings, make_user, bus: EventBus):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="roman", display_name="Роман")
        await setup.commit()
        user_id = user.id

    async def _override_user():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_event_bus] = lambda: bus
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.user_id = user_id  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


async def test_events_endpoint_streams_published_event(client: AsyncClient, bus: EventBus) -> None:
    async with client.stream("GET", "/events") as resp:
        assert resp.status_code == 200

        async def _publish_after_subscribe() -> None:
            await asyncio.sleep(0.1)  # let the endpoint register its subscription
            await bus.publish(
                client.user_id,  # type: ignore[attr-defined]
                {"event": "memory-save", "data": {"message_id": "m1"}},
            )

        task = asyncio.create_task(_publish_after_subscribe())
        received = ""
        async for chunk in resp.aiter_text():
            received += chunk
            if "event: memory-save" in received:
                break
        await task
    assert "event: memory-save" in received
    assert '"message_id": "m1"' in received
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_event_bus'` (and no `/events` route).

- [ ] **Step 3a: Add the shared SSE helper**

```python
# src/capybara/api/sse.py
"""Shared Server-Sent-Events framing helpers for streaming endpoints."""

import json
from typing import Any

# Headers every SSE streaming response must carry so the Vite dev proxy, nginx, and the
# browser treat this as a live stream and never buffer chunks.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame as ``event: <name>`` / ``data: <json>``."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

- [ ] **Step 3b: Add the `get_event_bus` dependency**

In `src/capybara/api/dependencies.py`, add the import near the other service imports:

```python
from capybara.services.event_bus import EventBus
```

and add this dependency (place it just above `get_memory_service`):

```python
def get_event_bus(request: Request) -> EventBus:
    """Return the app-wide EventBus, lazily creating it if the lifespan did not run.

    Lazy creation keeps tests that override other app-state dependencies working without
    starting the lifespan, while production sets it once in ``main.lifespan``.
    """
    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        bus = EventBus()
        request.app.state.event_bus = bus
    return cast(EventBus, bus)
```

- [ ] **Step 3c: Add the `/events` router**

```python
# src/capybara/api/routers/events.py
"""Per-user server push channel: a persistent SSE stream of background events."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from capybara.api.dependencies import get_current_user, get_event_bus
from capybara.api.sse import SSE_HEADERS, format_sse
from capybara.db.models import User
from capybara.services.event_bus import EventBus

router = APIRouter(tags=["events"])

#: Idle interval after which a keepalive comment is sent to hold the connection open.
_KEEPALIVE_SECONDS = 15.0


@router.get("/events")
async def events(
    user: Annotated[User, Depends(get_current_user)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Stream this user's background events (e.g. memory-save) as SSE until disconnect."""

    async def event_stream() -> AsyncIterator[str]:
        async with bus.subscribe(user.id) as queue:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield format_sse(item["event"], item["data"])

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
```

- [ ] **Step 3d: Wire the bus and router in `main.py`**

In `src/capybara/main.py` lifespan, after `app.state.agent = OllamaAgent(settings)` add:

```python
    from capybara.services.event_bus import EventBus

    app.state.event_bus = EventBus()
```

In `create_app`, add `events` to the router imports and include it:

```python
    from capybara.api.routers import auth, chats, events, health, memory, models, users
    ...
    fastapi_app.include_router(events.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events_api.py -v && uv run mypy src && uv run ruff check .`
Expected: PASS (1 passed), mypy clean, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/api/sse.py src/capybara/api/routers/events.py \
        src/capybara/api/dependencies.py src/capybara/main.py tests/test_events_api.py
git commit -m "feat(events): per-user GET /events SSE channel backed by EventBus"
```

---

### Task 3: `Message.memory_saves` column + migration

**Files:**
- Modify: `src/capybara/db/models/message.py`
- Create: `src/capybara/migrations/versions/20260706_1200_a7f0cafe0007_message_memory_saves.py`
- Test: `tests/test_repositories.py` (add one test)

**Interfaces:**
- Produces: `Message.memory_saves: list[dict[str, Any]] | None` (JSONB, nullable). Each entry `{"content": str, "category": str}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_repositories.py` (it already imports `ChatRepo`, `MessageRepo`, `_seed_user`, `AsyncSession`):

```python
async def test_message_memory_saves_roundtrips(session: AsyncSession) -> None:
    """memory_saves persists a list of {content, category} dicts and reads back intact."""
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "c")
    messages = MessageRepo(session)
    msg = await messages.create(chat_id=chat.id, role="assistant", content="hi")
    saves = [{"content": "Любит чай", "category": "preference"}]
    await messages.update(msg, memory_saves=saves)
    refetched = await messages.get(msg.id)
    assert refetched is not None
    assert refetched.memory_saves == saves
```

If `test_repositories.py` does not already import `MessageRepo`, add:
`from capybara.repositories.message_repo import MessageRepo`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repositories.py::test_message_memory_saves_roundtrips -v`
Expected: FAIL — `ValueError: Unknown field 'memory_saves' for Message` (column not mapped).

- [ ] **Step 3a: Add the column to the model**

In `src/capybara/db/models/message.py`, add just below the `tool_calls` mapped column:

```python
    #: Display-only record of facts auto-captured from this assistant turn: a list of
    #: ``{"content", "category"}``. ``NULL`` when nothing was stored. Written by the
    #: post-response extraction task, never replayed into model context.
    memory_saves: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 3b: Create the Alembic migration**

First confirm the current head:

Run: `uv run alembic heads`
Expected: prints one revision (e.g. `f6e0cafe0006 (head)`). Use it as `down_revision` below — adjust if different.

```python
# src/capybara/migrations/versions/20260706_1200_a7f0cafe0007_message_memory_saves.py
"""add messages.memory_saves jsonb column

Revision ID: a7f0cafe0007
Revises: f6e0cafe0006
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a7f0cafe0007"
down_revision: str | Sequence[str] | None = "f6e0cafe0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable memory_saves JSONB column to messages."""
    op.add_column("messages", sa.Column("memory_saves", JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the memory_saves column from messages."""
    op.drop_column("messages", "memory_saves")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repositories.py::test_message_memory_saves_roundtrips -v && uv run mypy src && uv run ruff check .`
Expected: PASS. Then verify the migration chain applies cleanly against a fresh DB:
Run: `uv run pytest tests/ -k migrat -v` (exercises the `migrated_engine` fixture)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/db/models/message.py \
        src/capybara/migrations/versions/20260706_1200_a7f0cafe0007_message_memory_saves.py \
        tests/test_repositories.py
git commit -m "feat(db): add messages.memory_saves jsonb column"
```

---

### Task 4: Expose `memory_saves` in the API schema

**Files:**
- Modify: `src/capybara/api/schemas.py`
- Test: `tests/test_memory_saves_api.py`

**Interfaces:**
- Consumes: `Message.memory_saves` (Task 3).
- Produces: `MemorySaveOut { content: str; category: str }`; `MessageOut.memory_saves: list[MemorySaveOut] | None = None` serialized by `GET /chats/{id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_saves_api.py
"""GET /chats/{id} exposes persisted memory_saves on assistant messages."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import (
    get_agent,
    get_current_user,
    get_session,
    get_sessionmaker,
    get_settings_dep,
)
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from support import FakeAgent


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="roman", display_name="Роман")
        await setup.commit()
        user_id = user.id

    async def _override_session():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def _override_user():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: FakeAgent(settings, "Ответ")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        c.user_id = user_id  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


async def test_get_chat_serializes_memory_saves(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    saves = [{"content": "Любит чай", "category": "preference"}]
    async with client.maker() as sess:  # type: ignore[attr-defined]
        chat = await ChatRepo(sess).get(chat_id)  # type: ignore[arg-type]
        assert chat is not None
        messages = MessageRepo(sess)
        msg = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await messages.update(msg, memory_saves=saves)
        await sess.commit()

    detail = (await client.get(f"/chats/{chat_id}")).json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert assistant["memory_saves"] == saves
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_saves_api.py -v`
Expected: FAIL — `KeyError: 'memory_saves'` (field not serialized).

- [ ] **Step 3: Add the schema fields**

In `src/capybara/api/schemas.py`, add above `MessageOut`:

```python
class MemorySaveOut(BaseModel):
    """Response schema for a single fact auto-captured from an assistant turn."""

    content: str
    category: str
```

and add the field to `MessageOut` (after `tool_calls`):

```python
    memory_saves: list[MemorySaveOut] | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_saves_api.py -v && uv run mypy src && uv run ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/api/schemas.py tests/test_memory_saves_api.py
git commit -m "feat(api): expose memory_saves on MessageOut"
```

---

### Task 5: Extraction persists + publishes memory-save

**Files:**
- Modify: `src/capybara/services/memory_service.py`
- Modify: `src/capybara/api/dependencies.py` (`get_memory_service` injects the bus)
- Test: `tests/test_memory_service.py` (add one test)

**Interfaces:**
- Consumes: `EventBus` (Task 1); `Message.memory_saves` (Task 3).
- Produces: `MemoryService.__init__` gains `event_bus: EventBus | None = None`. On a turn that stores ≥1 novel fact, `extract_and_store` sets that assistant message's `memory_saves` and publishes `{"event": "memory-save", "data": {"chat_id", "message_id", "facts": [{"content", "category"}, ...]}}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory_service.py` (it already imports `MemoryService`, `create_sessionmaker`, `StubMemoryAgent`, `Settings`, and uses the `user_id` fixture):

```python
import asyncio

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.event_bus import EventBus


async def test_extract_and_store_publishes_and_persists(engine, settings, user_id) -> None:  # type: ignore[no-untyped-def]
    """A stored fact is written to the message's memory_saves AND published on the bus."""
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(
        settings, extracted={"facts": [{"content": "Любит чай", "category": "preference"}]}
    )
    bus = EventBus()
    service = MemoryService(maker, agent, settings, bus)

    async with maker() as s:
        user = await s.get(User, user_id)
        assert user is not None
        user.memory_auto_capture = True
        chat = await ChatRepo(s).create(user_id, "c", "test-model")
        messages = MessageRepo(s)
        await messages.create(chat_id=chat.id, role="user", content="Привет")
        assistant = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await s.commit()
        chat_id, assistant_id = chat.id, assistant.id

    async with bus.subscribe(user_id) as queue:
        await service.extract_and_store(user_id, chat_id)
        event = await asyncio.wait_for(queue.get(), timeout=2)

    assert event["event"] == "memory-save"
    assert event["data"]["chat_id"] == str(chat_id)
    assert event["data"]["message_id"] == str(assistant_id)
    assert event["data"]["facts"] == [{"content": "Любит чай", "category": "preference"}]

    async with maker() as s:
        stored = await MessageRepo(s).get(assistant_id)
        assert stored is not None
        assert stored.memory_saves == [{"content": "Любит чай", "category": "preference"}]


async def test_extract_and_store_no_facts_publishes_nothing(engine, settings, user_id) -> None:  # type: ignore[no-untyped-def]
    """When extraction yields no facts, nothing is persisted or published."""
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings, extracted={"facts": []})
    bus = EventBus()
    service = MemoryService(maker, agent, settings, bus)

    async with maker() as s:
        user = await s.get(User, user_id)
        assert user is not None
        user.memory_auto_capture = True
        chat = await ChatRepo(s).create(user_id, "c", "test-model")
        messages = MessageRepo(s)
        await messages.create(chat_id=chat.id, role="user", content="Привет")
        assistant = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await s.commit()
        chat_id, assistant_id = chat.id, assistant.id

    async with bus.subscribe(user_id) as queue:
        await service.extract_and_store(user_id, chat_id)
        assert queue.empty()

    async with maker() as s:
        stored = await MessageRepo(s).get(assistant_id)
        assert stored is not None
        assert stored.memory_saves is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_service.py -k "publishes_and_persists or publishes_nothing" -v`
Expected: FAIL — `TypeError: MemoryService.__init__() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3a: Extend the `MemoryService` constructor**

In `src/capybara/services/memory_service.py`, add the import:

```python
from capybara.services.event_bus import EventBus
```

Change `__init__` to accept and store the bus:

```python
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent: BaseAgent,
        settings: Settings,
        event_bus: EventBus | None = None,
    ) -> None:
        """Store the sessionmaker, provider agent, settings, and optional event bus."""
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._settings = settings
        self._event_bus = event_bus
```

- [ ] **Step 3b: Persist + publish inside `extract_and_store`**

Rewrite the body of `extract_and_store` from the `messages = await MessageRepo(...)` load onward so it captures the assistant message id, collects stored facts, then persists and publishes:

```python
        # Best-effort per turn: post-response run; incomplete=False filter and dedup keep this safe.
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None or not user.memory_auto_capture:
                return
            chat = await ChatRepo(session).get(chat_id)
            if chat is None or chat.model is None:
                return
            model = chat.model
            messages = await MessageRepo(session).list(
                FieldEquals(Message.chat_id, chat_id),
                FieldEquals(Message.incomplete, False),
            )
        last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
        turn = _last_turn_text(messages)
        if turn is None or last_assistant is None:
            return
        assistant_id = last_assistant.id

        extracted = await self._agent.run_structured(
            model, EXTRACTION_SYSTEM_PROMPT, turn, ExtractedFacts
        )
        saved: list[ExtractedFact] = []
        for candidate in extracted.facts:
            [embedding] = await self._agent.embed([candidate.content])
            async with self._sessionmaker() as session:
                repo = FactRepo(session)
                nearest = await repo.search(user_id, embedding, 1)
                if nearest and (1.0 - nearest[0][1]) >= self._settings.memory_dedup_threshold:
                    continue
                await repo.create(
                    user_id=user_id,
                    content=candidate.content,
                    category=candidate.category,
                    embedding=embedding,
                    source="auto",
                )
                await session.commit()
            saved.append(candidate)

        if not saved:
            return
        facts_payload = [{"content": f.content, "category": f.category} for f in saved]
        async with self._sessionmaker() as session:
            repo_m = MessageRepo(session)
            message = await repo_m.get(assistant_id)
            if message is not None:
                await repo_m.update(message, memory_saves=facts_payload)
                await session.commit()
        if self._event_bus is not None:
            await self._event_bus.publish(
                user_id,
                {
                    "event": "memory-save",
                    "data": {
                        "chat_id": str(chat_id),
                        "message_id": str(assistant_id),
                        "facts": facts_payload,
                    },
                },
            )
```

- [ ] **Step 3c: Inject the bus in `get_memory_service`**

In `src/capybara/api/dependencies.py`, update `get_memory_service`:

```python
def get_memory_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> MemoryService:
    """Return a MemoryService that owns short-lived sessions and can publish events."""
    return MemoryService(sessionmaker, agent, settings, event_bus)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_memory_service.py -v && uv run mypy src && uv run ruff check .`
Expected: PASS (including the two new tests and all pre-existing memory-service tests).

- [ ] **Step 5: Commit**

```bash
git add src/capybara/services/memory_service.py src/capybara/api/dependencies.py \
        tests/test_memory_service.py
git commit -m "feat(memory): persist and publish memory-save on auto-capture"
```

---

### Task 6: End-to-end API coverage

**Files:**
- Modify: `tests/test_memory_autocapture_api.py` (add one test)

**Interfaces:**
- Consumes: full `send_message` → background extraction → persistence path (Tasks 3–5).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory_autocapture_api.py` (reuses its existing `client` fixture with `StubMemoryAgent` that extracts `{"content": "Любит чай", "category": "preference"}`):

```python
async def test_send_message_persists_memory_saves_on_message(client: AsyncClient) -> None:
    """After the background task runs, the assistant message carries memory_saves."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    detail = (await client.get(f"/chats/{chat_id}")).json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert assistant["memory_saves"] == [{"content": "Любит чай", "category": "preference"}]
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `uv run pytest tests/test_memory_autocapture_api.py::test_send_message_persists_memory_saves_on_message -v`
Expected: PASS (Tasks 3–5 already implement the behavior; this is the integration guard). If it fails with `memory_saves == None`, confirm the `StubMemoryAgent` in this file's fixture still sets `extracted={"facts": [{"content": "Любит чай", "category": "preference"}]}`.

- [ ] **Step 3: Full backend gate**

Run: `uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_autocapture_api.py
git commit -m "test(memory): end-to-end memory_saves persisted via send_message"
```

---

## Part B — Frontend

### Task 7: Thread the memory-save data through types, state, and conversion

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/chat/useChatStream.ts` (type + history mapping)
- Modify: `frontend/src/chat/convertMessage.ts`
- Create: `frontend/src/chat/memorySave.ts`
- Test: `frontend/src/chat/memorySave.test.ts`
- Test: `frontend/src/chat/convertMessage.test.ts` (add one case)

**Interfaces:**
- Produces:
  - `MemorySaveOut { content: string; category: string }`; `MessageOut.memory_saves?: MemorySaveOut[] | null`.
  - `ChatMessage.memorySaves?: { content: string; category: string }[]`.
  - `type MemorySaveEvent = { chat_id: string; message_id: string; facts: { content: string; category: string }[] }`.
  - `function applyMemorySave(messages: ChatMessage[], evt: MemorySaveEvent): ChatMessage[]` — returns a new array with `memorySaves` set on the message whose `id === evt.message_id` (no-op if absent).
  - `convertMessage` attaches `metadata: { custom: { memorySaves } }`.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/chat/memorySave.test.ts
import { describe, expect, test } from 'vitest'
import { applyMemorySave } from './memorySave'
import type { ChatMessage } from './useChatStream'

const base: ChatMessage[] = [
  { id: 'm1', role: 'assistant', content: 'Здравствуй', streaming: false },
  { id: 'm2', role: 'user', content: 'Привет', streaming: false },
]

describe('applyMemorySave', () => {
  test('attaches facts to the matching message', () => {
    const next = applyMemorySave(base, {
      chat_id: 'c1',
      message_id: 'm1',
      facts: [{ content: 'Любит чай', category: 'preference' }],
    })
    expect(next.find((m) => m.id === 'm1')?.memorySaves).toEqual([
      { content: 'Любит чай', category: 'preference' },
    ])
    // other messages untouched
    expect(next.find((m) => m.id === 'm2')?.memorySaves).toBeUndefined()
  })

  test('is a no-op when the message is not present', () => {
    const next = applyMemorySave(base, { chat_id: 'c1', message_id: 'gone', facts: [] })
    expect(next).toEqual(base)
  })
})
```

Add to `frontend/src/chat/convertMessage.test.ts`:

```typescript
test('passes memorySaves through message metadata', () => {
  const msg = convertMessage({
    id: 'a1',
    role: 'assistant',
    content: 'Ответ',
    streaming: false,
    memorySaves: [{ content: 'Любит чай', category: 'preference' }],
  })
  expect((msg.metadata?.custom as { memorySaves?: unknown })?.memorySaves).toEqual([
    { content: 'Любит чай', category: 'preference' },
  ])
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `frontend/`): `npm run test -- memorySave convertMessage`
Expected: FAIL — `applyMemorySave` not exported; `metadata` undefined.

- [ ] **Step 3a: Extend API types**

In `frontend/src/api/types.ts`, add:

```typescript
export interface MemorySaveOut {
  content: string
  category: string
}
```

and add to `MessageOut`:

```typescript
  memory_saves?: MemorySaveOut[] | null
```

- [ ] **Step 3b: Extend `ChatMessage` and history mapping**

In `frontend/src/chat/useChatStream.ts`, add to the `ChatMessage` type:

```typescript
  memorySaves?: { content: string; category: string }[]
```

and in `loadHistory`'s `detail.messages.map(...)`, add after the `toolCalls` mapping:

```typescript
          memorySaves: m.memory_saves ?? undefined,
```

- [ ] **Step 3c: Create `applyMemorySave`**

```typescript
// frontend/src/chat/memorySave.ts
/** Applies a memory-save push event to the message list (immutably). */
import type { ChatMessage } from './useChatStream'

export type MemorySaveEvent = {
  chat_id: string
  message_id: string
  facts: { content: string; category: string }[]
}

/** Returns a new message list with `memorySaves` set on the event's target message. */
export function applyMemorySave(messages: ChatMessage[], evt: MemorySaveEvent): ChatMessage[] {
  return messages.map((m) => (m.id === evt.message_id ? { ...m, memorySaves: evt.facts } : m))
}
```

- [ ] **Step 3d: Attach metadata in `convertMessage`**

In `frontend/src/chat/convertMessage.ts`, add the metadata to the returned object (keep the existing `content` and `status`):

```typescript
  return {
    id: m.id,
    role: m.role,
    content: [...toolParts, ...textParts],
    status: m.streaming ? { type: 'running' } : undefined,
    metadata: { custom: { memorySaves: m.memorySaves ?? [] } },
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run (in `frontend/`): `npm run test -- memorySave convertMessage && npm run typecheck && npm run lint`
Expected: PASS, types clean, lint clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/chat/useChatStream.ts \
        frontend/src/chat/convertMessage.ts frontend/src/chat/memorySave.ts \
        frontend/src/chat/memorySave.test.ts frontend/src/chat/convertMessage.test.ts
git commit -m "feat(chat-ui): thread memory-save data through state and conversion"
```

---

### Task 8: Subscribe to the `/events` channel and apply memory-save

**Files:**
- Modify: `frontend/src/api/client.ts` (add `eventStream`)
- Modify: `frontend/src/chat/useChatStream.ts` (open `/events`, apply events)
- Test: `frontend/src/api/client.test.ts` (add `eventStream` case, or create if absent)

**Interfaces:**
- Consumes: `applyMemorySave` / `MemorySaveEvent` (Task 7); `parseSse` (existing).
- Produces: `ApiClient.eventStream(path: string, signal?: AbortSignal): Promise<Response>` (GET, auth header, no body). `useChatStream` opens `/events` once and applies `memory-save` frames via `setMessages(applyMemorySave(...))`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/api/client.test.ts` (create the file if it does not exist, mirroring the MSW setup used by other API tests):

```typescript
import { describe, expect, test } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { createApiClient } from './client'

describe('eventStream', () => {
  test('opens a GET stream to the given path with the auth header', async () => {
    let seenMethod = ''
    let seenAuth: string | null = null
    server.use(
      http.get('/api/events', ({ request }) => {
        seenMethod = request.method
        seenAuth = request.headers.get('Authorization')
        return new HttpResponse('event: memory-save\ndata: {}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }),
    )
    const api = createApiClient({ getToken: () => 'tok', onUnauthorized: () => {} })
    const res = await api.eventStream('/events')
    expect(res.ok).toBe(true)
    expect(seenMethod).toBe('GET')
    expect(seenAuth).toBe('Bearer tok')
  })
})
```

If `../test/server` is not the correct import path for the MSW server in this project, use the same import the existing `useChatStream.test.tsx` uses for `server`.

- [ ] **Step 2: Run test to verify it fails**

Run (in `frontend/`): `npm run test -- client`
Expected: FAIL — `api.eventStream is not a function`.

- [ ] **Step 3a: Add `eventStream` to the client**

In `frontend/src/api/client.ts`, add to the `ApiClient` interface:

```typescript
  eventStream(path: string, signal?: AbortSignal): Promise<Response>
```

and add to the returned object (after `stream`):

```typescript
    eventStream: (path, signal) => stream(path, { method: 'GET', signal }),
```

- [ ] **Step 3b: Open `/events` from `useChatStream`**

In `frontend/src/chat/useChatStream.ts`, add the imports:

```typescript
import { applyMemorySave, type MemorySaveEvent } from './memorySave'
```

and add this effect inside `useChatStream` (after the existing unmount-abort effect). It opens the channel once and reconnects on drop:

```typescript
  // Open the per-user push channel once for the lifetime of this screen. It delivers
  // background events (currently memory-save) that arrive after a reply's own stream has
  // closed. Best-effort: a missed event is restored on the next history load.
  useEffect(() => {
    const controller = new AbortController()
    let stopped = false
    ;(async () => {
      while (!stopped) {
        try {
          const res = await api.eventStream('/events', controller.signal)
          if (!res.body) throw new Error('no stream')
          for await (const ev of parseSse(res.body, controller.signal)) {
            if (ev.event === 'memory-save') {
              const evt = JSON.parse(ev.data) as MemorySaveEvent
              setMessages((prev) => applyMemorySave(prev, evt))
            }
          }
        } catch {
          if (stopped || controller.signal.aborted) return
        }
        if (stopped) return
        await new Promise((r) => setTimeout(r, 2000)) // backoff before reconnect
      }
    })()
    return () => {
      stopped = true
      controller.abort()
    }
  }, [api])
```

- [ ] **Step 4: Run test to verify it passes**

Run (in `frontend/`): `npm run test -- client && npm run typecheck && npm run lint`
Expected: PASS, types clean, lint clean. Also run the full suite to confirm no regression in `useChatStream.test.tsx`:
Run: `npm run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/chat/useChatStream.ts frontend/src/api/client.test.ts
git commit -m "feat(chat-ui): subscribe to /events and apply memory-save pushes"
```

---

### Task 9: Render the "Запомнил" footer chip

**Files:**
- Create: `frontend/src/components/MemorySaveChip.tsx`
- Create: `frontend/src/components/plural.ts`
- Modify: `frontend/src/components/Thread.tsx` (render the chip in `AssistantMessage`)
- Test: `frontend/src/components/MemorySaveChip.test.tsx`
- Test: `frontend/src/components/plural.test.ts`

**Interfaces:**
- Consumes: `memorySaves` from message `metadata.custom` (Task 7).
- Produces: `MemorySaveChip({ saves }: { saves: { content: string; category: string }[] })`; `pluralFacts(n: number): string`.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/components/plural.test.ts
import { expect, test } from 'vitest'
import { pluralFacts } from './plural'

test('russian plural for facts', () => {
  expect(pluralFacts(1)).toBe('факт')
  expect(pluralFacts(2)).toBe('факта')
  expect(pluralFacts(5)).toBe('фактов')
  expect(pluralFacts(11)).toBe('фактов')
  expect(pluralFacts(21)).toBe('факт')
})
```

```typescript
// frontend/src/components/MemorySaveChip.test.tsx
import { expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemorySaveChip } from './MemorySaveChip'

test('shows the saved-fact count and expands to the list', async () => {
  render(
    <MemorySaveChip
      saves={[
        { content: 'Любит чай', category: 'preference' },
        { content: 'Пишет на Python', category: 'personal' },
      ]}
    />,
  )
  expect(screen.getByText('Запомнил 2 факта')).toBeInTheDocument()
  // collapsed by default
  expect(screen.queryByText('Любит чай')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button'))
  expect(screen.getByText('Любит чай')).toBeInTheDocument()
  expect(screen.getByText('Пишет на Python')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `frontend/`): `npm run test -- MemorySaveChip plural`
Expected: FAIL — modules not found.

- [ ] **Step 3a: Add the plural helper**

```typescript
// frontend/src/components/plural.ts
/** Returns the Russian plural form of «факт» for a count. */
export function pluralFacts(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'факт'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'факта'
  return 'фактов'
}
```

- [ ] **Step 3b: Add the chip component**

Reuses the existing `ToolCallCard.module.css` so the chip is visually symmetric with the recall chip.

```typescript
// frontend/src/components/MemorySaveChip.tsx
/**
 * Collapsible footer chip showing what the assistant auto-captured to long-term memory
 * this turn. Symmetric with ToolCallCard but rendered below the answer, since saving
 * happens after the reply. Collapsed by default; expands to the list of saved facts.
 */
import { useState } from 'react'
import { Check, ChevronRight, Save } from 'lucide-react'
import styles from './ToolCallCard.module.css'
import { pluralFacts } from './plural'

export function MemorySaveChip({
  saves,
}: {
  saves: { content: string; category: string }[]
}) {
  const [open, setOpen] = useState(false)
  if (saves.length === 0) return null
  const label = `Запомнил ${saves.length} ${pluralFacts(saves.length)}`
  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Save size={15} />
        <span className={styles.label}>{label}</span>
        <Check size={15} className={styles.check} />
        <ChevronRight size={15} className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`} />
      </button>
      {open && (
        <div className={styles.body}>
          {saves.map((s, i) => (
            <div key={i} className={styles.field}>
              <span className={styles.fieldLabel}>{s.category}:</span>
              <span className={styles.value}>{s.content}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3c: Render the chip in `AssistantMessage`**

In `frontend/src/components/Thread.tsx`, add imports:

```typescript
import { useMessage } from '@assistant-ui/react'
import { MemorySaveChip } from './MemorySaveChip'
```

Add a small subcomponent (above `AssistantMessage`) that reads memorySaves from message metadata:

```typescript
function MemorySaves() {
  const saves = useMessage(
    (m) =>
      (m.metadata?.custom as { memorySaves?: { content: string; category: string }[] } | undefined)
        ?.memorySaves ?? [],
  )
  return <MemorySaveChip saves={saves} />
}
```

Then render `<MemorySaves />` inside `assistantContent`, after the `ActionBarPrimitive.Root` block (footer position, below the answer and action bar).

- [ ] **Step 4: Run tests to verify they pass**

Run (in `frontend/`): `npm run test -- MemorySaveChip plural && npm run typecheck && npm run lint`
Expected: PASS. Then confirm no regression in the message-render tests:
Run: `npm run test -- Thread`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MemorySaveChip.tsx frontend/src/components/plural.ts \
        frontend/src/components/Thread.tsx frontend/src/components/MemorySaveChip.test.tsx \
        frontend/src/components/plural.test.ts
git commit -m "feat(chat-ui): 'Запомнил' footer chip on assistant messages"
```

---

### Task 10: Manual full-stack verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite, both sides**

Run: `uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Run (in `frontend/`): `npm run test && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 2: Manual end-to-end check**

Start Postgres + api (`docker compose up --build`) with Ollama on the host and auto-capture enabled for the local user. In the UI:
1. Send a message that states a durable fact (e.g. «Меня зовут Роман, я люблю горные походы»).
2. Confirm the reply streams as usual, then a «Запомнил N фактов» chip appears **below** the assistant message a moment later (after the background extraction runs).
3. Expand the chip — it lists the saved fact(s) with their category.
4. Reload the chat — the chip is still there (restored from history), proving persistence.
5. Send a message with nothing worth remembering (e.g. «Который час?») — no chip appears.

- [ ] **Step 3: Commit (if any verification-driven fixes were needed)**

```bash
git add <touched files>
git commit -m "fix(memory-save): address issues found in manual verification"
```

---

## Self-review notes (coverage map)

- Spec "EventBus / per-user pub/sub" → Task 1.
- Spec "GET /events persistent SSE + keepalive + cleanup" → Task 2.
- Spec "Message.memory_saves persistence + migration" → Task 3.
- Spec "MessageOut.memory_saves exposure / history reconstruction" → Task 4 (backend) + Task 7 (frontend mapping) + Task 9 (render).
- Spec "extract_and_store persists + publishes, honest empty case" → Task 5 (+ Task 6 e2e).
- Spec "global /events subscription + apply to message + reconnect" → Task 8.
- Spec "footer chip below answer, expandable, no running state" → Task 9.
- Known limitations (regenerate has no chip; process-local bus) are preserved by construction — no task adds extraction to regenerate, and the bus is the in-process `EventBus`.
