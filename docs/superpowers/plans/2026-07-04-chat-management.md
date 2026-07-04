# Chat Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Favorite (star), delete, and rename chats, and auto-generate a chat title from the first message via the LLM — following the updated design with lucide icons.

**Architecture:** A new `chats.is_favorite` column; one unified `PATCH /chats/{id}` for title/model/is_favorite; a `DELETE /chats/{id}`; LLM auto-title generated after the first reply and pushed to the client via a new SSE `title` event. Frontend: a favorites group + per-chat star toggle, a context menu (rename/favorite/delete), inline rename, and live title updates.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic-ai (Ollama), uv; React 18 + TypeScript + Vite, lucide-react, vitest + msw.

## Global Constraints

- Python 3.12+, fully typed; strict mypy (`uv run mypy src`) clean.
- ruff lint + format clean incl. pydocstyle `D` (google); every module/class/function has a docstring; tests exempt.
- Layering: `api → services → repositories → db`; no DB access outside repositories; reuse existing FastAPI dependencies.
- Favorite is named **`is_favorite`** everywhere; the UI icon is a filled `Star`.
- One `PATCH /chats/{id}` handles title/model/is_favorite; `model` is validated (409/502) only when present.
- No implicit model fallback (unchanged): unset/absent model still blocks sending and 409s.
- Auto-title is LLM-generated, only on the first turn, only when the title is still the default, and never delays or breaks the reply stream.
- TypeScript strict; ESLint clean (`npm run lint --max-warnings 0`); `npm run build` clean.
- Backend cmds: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy src`.
- Frontend cmds (from `frontend/`, Node via nvm): prefix with `PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"`; `npm run test -- --run`, `npm run lint`, `npm run build`.
- SCOPED STAGING: subagents `git add <specific files>` only — never `git add -A`/`-u` (the user commits concurrently on main).
- Migration head to chain on: `b2d0cafe0002`.

---

### Task 1: `chats.is_favorite` column + migration + ChatOut

**Files:**
- Modify: `src/capybara/db/models/chat.py`
- Modify: `src/capybara/api/schemas.py` (`ChatOut`)
- Create: `src/capybara/migrations/versions/20260704_1500_c3d0cafe0003_chats_is_favorite.py`
- Modify: `tests/test_repositories.py`

**Interfaces:**
- Produces: `Chat.is_favorite: Mapped[bool]` (default False); `ChatOut.is_favorite: bool`; module constant `DEFAULT_CHAT_TITLE = "Новый чат"` (defined in `chat.py`).

- [ ] **Step 1: Add the column + extract the default-title constant**

In `src/capybara/db/models/chat.py`, add a module-level constant and the column. Add the import for `text` if needed (use `sqlalchemy.false()` in the model default is not needed — use Python `default=False`). Replace the `title` line and add `is_favorite`:

```python
#: Default title for a freshly created chat (before auto-title or manual rename).
DEFAULT_CHAT_TITLE = "Новый чат"


class Chat(Base, TimestampMixin):
    """ORM model representing a chat conversation owned by a user."""

    __tablename__ = "chats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default=DEFAULT_CHAT_TITLE)
    #: Selected LLM model for this chat, e.g. ``llama3.1:8b``. ``NULL`` = not yet chosen;
    #: there is no server-side fallback — an unset model blocks sending.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Whether the user has starred this chat; starred chats group at the top of the sidebar.
    is_favorite: Mapped[bool] = mapped_column(default=False, nullable=False)
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
```

(Keep the existing `if TYPE_CHECKING` / imports block. `DEFAULT_CHAT_TITLE` must be defined before the class.)

- [ ] **Step 2: Add `is_favorite` to `ChatOut`**

In `src/capybara/api/schemas.py`, add the field to `ChatOut` (after `model`):

```python
class ChatOut(BaseModel):
    """Response schema for a chat summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    model: str | None
    is_favorite: bool
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Update the explicit `ChatDetailOut` construction**

`get_chat` in `src/capybara/api/routers/chats.py` builds `ChatDetailOut(...)` with explicit kwargs; add `is_favorite=chat.is_favorite` so mypy/pydantic are satisfied:

```python
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        model=chat.model,
        is_favorite=chat.is_favorite,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageOut.model_validate(m) for m in rows],
    )
```

- [ ] **Step 4: Write the migration**

Create `src/capybara/migrations/versions/20260704_1500_c3d0cafe0003_chats_is_favorite.py`:

```python
"""add chats.is_favorite

Revision ID: c3d0cafe0003
Revises: b2d0cafe0002
Create Date: 2026-07-04 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d0cafe0003"
down_revision: str | Sequence[str] | None = "b2d0cafe0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the non-null is_favorite column defaulting to false."""
    op.add_column(
        "chats",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Drop the is_favorite column."""
    op.drop_column("chats", "is_favorite")
```

- [ ] **Step 5: Write the repo round-trip test**

Add to `tests/test_repositories.py`:

```python
async def test_chat_repo_toggle_favorite(session) -> None:  # type: ignore[no-untyped-def]
    """A chat defaults to not-favorite and can be flipped via update."""
    from capybara.db.models import User
    from capybara.repositories.chat_repo import ChatRepo
    from capybara.security.passwords import hash_password

    user = User(username="favuser", display_name="F", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    repo = ChatRepo(session)
    chat = await repo.create(user.id, title="c")
    assert chat.is_favorite is False

    await repo.update(chat, is_favorite=True)
    reloaded = await repo.get(chat.id)
    assert reloaded is not None
    assert reloaded.is_favorite is True
```

- [ ] **Step 6: Run repo + migration tests**

Run: `uv run pytest tests/test_repositories.py::test_chat_repo_toggle_favorite tests/test_migrations.py -v`
Expected: PASS (the new revision applies on top of `b2d0cafe0002`).

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/db/models/chat.py src/capybara/api/schemas.py \
  src/capybara/api/routers/chats.py \
  src/capybara/migrations/versions/20260704_1500_c3d0cafe0003_chats_is_favorite.py \
  tests/test_repositories.py
git commit -m "feat: add chats.is_favorite column, migration, and ChatOut field"
```

---

### Task 2: Unified `PATCH /chats/{id}` (title / model / is_favorite)

**Files:**
- Modify: `src/capybara/api/schemas.py` (`ChatUpdate`)
- Modify: `src/capybara/api/routers/chats.py` (`update_chat_model` → `update_chat`)
- Modify: `tests/test_chats_api.py`

**Interfaces:**
- Consumes: `ChatRepo.update`, `get_owned_chat`, `get_agent`, `_raise_for_model_error`.
- Produces: `ChatUpdate{ title?: str, model?: str, is_favorite?: bool }` (≥1 field); `PATCH /chats/{id}` applies provided fields, validating `model` only when present.

- [ ] **Step 1: Write failing PATCH tests**

Add to `tests/test_chats_api.py` (the `client` fixture's `FakeAgent.list_models()` returns `["test-model"]`):

```python
async def test_patch_chat_rename_only(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"title": "Переименовано"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Переименовано"
    assert resp.json()["model"] == "test-model"  # untouched


async def test_patch_chat_favorite_only(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"is_favorite": True})
    assert resp.status_code == 200
    assert resp.json()["is_favorite"] is True


async def test_patch_chat_empty_body_422(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={})
    assert resp.status_code == 422


async def test_patch_chat_model_still_validates(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    ok = await client.patch(f"/chats/{chat_id}", json={"model": "test-model"})
    assert ok.status_code == 200
    bad = await client.patch(f"/chats/{chat_id}", json={"model": "ghost:1b"})
    assert bad.status_code == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_chats_api.py -k patch_chat -v`
Expected: FAIL — `ChatUpdate` rejects unknown fields / requires `model`; rename/favorite not handled.

- [ ] **Step 3: Rewrite `ChatUpdate`**

In `src/capybara/api/schemas.py`, replace `ChatUpdate` and add the `model_validator` import (`from pydantic import BaseModel, ConfigDict, Field, model_validator`):

```python
class ChatUpdate(BaseModel):
    """Partial update for a chat: any of title, model, or favorite. At least one required."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    is_favorite: bool | None = None

    @model_validator(mode="after")
    def _require_one(self) -> "ChatUpdate":
        """Reject an empty patch — at least one field must be provided."""
        if self.title is None and self.model is None and self.is_favorite is None:
            raise ValueError("at least one of title, model, is_favorite must be provided")
        return self
```

- [ ] **Step 4: Rewrite the PATCH endpoint**

In `src/capybara/api/routers/chats.py`, replace `update_chat_model` with:

```python
@router.patch("/{chat_id}", response_model=ChatOut)
async def update_chat(
    payload: ChatUpdate,
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatOut:
    """Update a chat's title, model, and/or favorite flag; 404 if not owned.

    The model, when provided, is validated against the live provider list first
    (409 unavailable / 502 provider down). Title and favorite need no validation.
    """
    if payload.model is not None:
        try:
            await agent.ensure_available(payload.model)
        except (ModelUnavailableError, ModelProviderError) as exc:
            _raise_for_model_error(exc)
    updated = await chats.update(chat, **payload.model_dump(exclude_none=True))
    return ChatOut.model_validate(updated)
```

- [ ] **Step 5: Run the PATCH tests + existing model-select tests**

Run: `uv run pytest tests/test_chats_api.py -k "patch_chat or model" -v`
Expected: PASS (rename/favorite/model/empty-422 all green; existing model PATCH tests still pass).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/api/schemas.py src/capybara/api/routers/chats.py tests/test_chats_api.py
git commit -m "feat: unified PATCH /chats/{id} for title, model, and favorite"
```

---

### Task 3: `DELETE /chats/{id}`

**Files:**
- Modify: `src/capybara/api/routers/chats.py`
- Modify: `tests/test_chats_api.py`

**Interfaces:**
- Consumes: `get_owned_chat`, `ChatRepo.delete` (from `BaseRepository`).
- Produces: `DELETE /chats/{chat_id}` → 204; cascades to messages.

- [ ] **Step 1: Write failing delete tests**

Add to `tests/test_chats_api.py`:

```python
async def test_delete_chat_removes_it_and_messages(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    # produce a message so the cascade has something to remove
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as r:
        async for _ in r.aiter_text():
            pass

    resp = await client.delete(f"/chats/{chat_id}")
    assert resp.status_code == 204

    gone = await client.get(f"/chats/{chat_id}")
    assert gone.status_code == 404
    listed = await client.get("/chats")
    assert all(c["id"] != chat_id for c in listed.json())


async def test_delete_other_users_chat_404(
    client: AsyncClient, engine, make_user  # type: ignore[no-untyped-def]
) -> None:
    from capybara.db.engine import create_sessionmaker
    from capybara.db.models import Chat

    maker = create_sessionmaker(engine)
    async with maker() as sess:
        other = await make_user(sess, username="delother", display_name="O")
        chat = Chat(user_id=other.id, title="private", model="test-model")
        sess.add(chat)
        await sess.commit()
        other_chat_id = chat.id

    resp = await client.delete(f"/chats/{other_chat_id}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_chats_api.py -k delete_chat -v`
Expected: FAIL — no DELETE route (405/404 on the method).

- [ ] **Step 3: Add the DELETE endpoint**

In `src/capybara/api/routers/chats.py`, add after `get_chat` (or near the other `/{chat_id}` routes):

```python
@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> None:
    """Delete a chat and its messages (cascade); 404 if not owned."""
    await chats.delete(chat)
```

- [ ] **Step 4: Run the delete tests**

Run: `uv run pytest tests/test_chats_api.py -k delete_chat -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/api/routers/chats.py tests/test_chats_api.py
git commit -m "feat: DELETE /chats/{id} with message cascade"
```

---

### Task 4: LLM auto-title on the first turn (SSE `title` event)

**Files:**
- Modify: `src/capybara/agent/base.py` (`generate_title`, `_clean_title`, `TITLE_SYSTEM_PROMPT`)
- Modify: `src/capybara/services/chat_service.py` (`generate_title`)
- Modify: `src/capybara/api/routers/chats.py` (`send_message` emits `title`)
- Modify: `tests/support.py` (FakeAgent title support)
- Create: `tests/test_agent_title.py`
- Modify: `tests/test_chat_service.py`, `tests/test_chats_api.py`

**Interfaces:**
- Produces:
  - `BaseAgent.generate_title(model_name: str, first_user_message: str) -> str` — never raises; returns a cleaned title or a truncation fallback.
  - `_clean_title(raw: str, *, fallback: str) -> str` (module function in `agent/base.py`).
  - `ChatService.generate_title(chat_id: UUID, first_user_message: str) -> str | None` — returns the persisted title, or None when not a first-turn/default-title chat or on failure.
- Consumes: `DEFAULT_CHAT_TITLE` (from `capybara.db.models.chat`), `ChatRepo.update`, `_build_model`.

- [ ] **Step 1: Write the `_clean_title` + `generate_title` agent tests**

Create `tests/test_agent_title.py`:

```python
"""Tests for LLM chat-title generation and cleaning."""

from capybara.agent.base import _clean_title
from capybara.config import Settings
from support import FakeAgent


def test_clean_title_strips_quotes_and_truncates() -> None:
    assert _clean_title('"Привет мир"', fallback="x") == "Привет мир"
    assert _clean_title("Строка один\nСтрока два", fallback="x") == "Строка один"
    long = "a" * 100
    assert _clean_title(long, fallback="x") == "a" * 60


def test_clean_title_empty_falls_back() -> None:
    assert _clean_title("   ", fallback="Как дела, друг?") == "Как дела, друг?"
    assert _clean_title("''", fallback="Очень длинный вопрос " * 5).__len__() <= 60


async def test_generate_title_returns_cleaned_model_output(settings: Settings) -> None:
    agent = FakeAgent(settings, "Заголовок чата")
    title = await agent.generate_title("test-model", "О чём этот чат?")
    assert title == "Заголовок чата"


async def test_generate_title_falls_back_on_empty_output(settings: Settings) -> None:
    agent = FakeAgent(settings, "")  # model returns empty → fallback to the user message
    title = await agent.generate_title("test-model", "Расскажи про капибар")
    assert title == "Расскажи про капибар"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_agent_title.py -v`
Expected: FAIL — `_clean_title` / `generate_title` don't exist.

- [ ] **Step 3: Implement `_clean_title`, prompt, and `generate_title`**

In `src/capybara/agent/base.py`, add near the top (after imports) a constant and helper, and a method on `BaseAgent`:

```python
#: System prompt used to derive a short chat title from the first user message.
TITLE_SYSTEM_PROMPT = (
    "You generate a concise chat title of 3-5 words in the same language as the "
    "user's message. Reply with the title only — no quotes, no punctuation at the "
    "end, no preamble."
)

#: Maximum length of a generated/fallback title.
_TITLE_MAX = 60


def _clean_title(raw: str, *, fallback: str) -> str:
    """Normalise a model-produced title; fall back to a truncation of *fallback* if empty.

    Takes the first line, strips surrounding quotes and whitespace, collapses inner
    whitespace, and truncates to ``_TITLE_MAX``. If nothing usable remains, returns the
    first line of *fallback* truncated the same way.
    """
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    cleaned = " ".join(first_line.strip("\"'«»`“” \t").split())[:_TITLE_MAX]
    if cleaned:
        return cleaned
    fb_line = fallback.strip().splitlines()[0] if fallback.strip() else fallback.strip()
    return " ".join(fb_line.split())[:_TITLE_MAX]
```

Add the method to `BaseAgent` (after `stream_reply`):

```python
    async def generate_title(self, model_name: str, first_user_message: str) -> str:
        """Ask the model for a short chat title; never raises.

        On any failure or empty output, falls back to a truncation of the user message,
        so the returned title is always at least as good as the default.
        """
        try:
            agent: Agent[None, str] = Agent(
                self._build_model(model_name), system_prompt=TITLE_SYSTEM_PROMPT
            )
            result = await agent.run(first_user_message)
            return _clean_title(result.output, fallback=first_user_message)
        except Exception:  # title generation must never break the reply flow
            return _clean_title("", fallback=first_user_message)
```

- [ ] **Step 4: Run the agent title tests**

Run: `uv run pytest tests/test_agent_title.py -v`
Expected: PASS (TestModel returns the `custom_output_text`; empty output falls back).

- [ ] **Step 5: Write the service-level test**

Add to `tests/test_chat_service.py` (imports at top already include `create_sessionmaker`, `Chat`, `FakeAgent`):

```python
async def test_generate_title_sets_title_only_when_default(
    engine: AsyncEngine, settings: Settings, make_user  # type: ignore[no-untyped-def]
) -> None:
    """Title is generated for a default-titled chat, and skipped for a renamed one."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="titler", display_name="T")
        default_chat = Chat(user_id=user.id, model="test-model")  # title defaults
        named_chat = Chat(user_id=user.id, title="Моё имя", model="test-model")
        setup.add_all([default_chat, named_chat])
        await setup.commit()
        default_id, named_id = default_chat.id, named_chat.id

    service = ChatService(maker, FakeAgent(settings, "Сгенерённый заголовок"))

    t1 = await service.generate_title(default_id, "О чём поговорим?")
    assert t1 == "Сгенерённый заголовок"
    t2 = await service.generate_title(named_id, "О чём поговорим?")
    assert t2 is None  # already has a custom title → skipped

    async with maker() as check:
        from capybara.repositories.chat_repo import ChatRepo

        assert (await ChatRepo(check).get(default_id)).title == "Сгенерённый заголовок"  # type: ignore[union-attr]
        assert (await ChatRepo(check).get(named_id)).title == "Моё имя"  # type: ignore[union-attr]
```

- [ ] **Step 6: Run it to verify failure**

Run: `uv run pytest tests/test_chat_service.py::test_generate_title_sets_title_only_when_default -v`
Expected: FAIL — `ChatService.generate_title` doesn't exist.

- [ ] **Step 7: Implement `ChatService.generate_title`**

In `src/capybara/services/chat_service.py`, add the import and method. Add to imports:

```python
from capybara.db.models.chat import DEFAULT_CHAT_TITLE
```

Add a module logger near the top (after imports):

```python
import logging

logger = logging.getLogger(__name__)
```

Add the method (after `regenerate_turn`):

```python
    async def generate_title(self, chat_id: UUID, first_user_message: str) -> str | None:
        """Generate and persist a chat title from the first user message.

        Only acts on a chat that still has the default title and a selected model; returns
        the new title, or ``None`` when skipped or on failure. Never raises — a title is a
        nicety and must not affect the reply stream.
        """
        try:
            async with self._sessionmaker() as session:
                chats = ChatRepo(session)
                chat = await chats.get(chat_id)
                if chat is None or chat.title != DEFAULT_CHAT_TITLE or chat.model is None:
                    return None
                title = await self._agent.generate_title(chat.model, first_user_message)
                await chats.update(chat, title=title)
                await session.commit()
                return title
        except Exception:
            logger.exception("title generation failed for chat %s", chat_id)
            return None
```

- [ ] **Step 8: Run the service test**

Run: `uv run pytest tests/test_chat_service.py::test_generate_title_sets_title_only_when_default -v`
Expected: PASS.

- [ ] **Step 9: Write the API-level SSE `title` test**

Add to `tests/test_chats_api.py`:

```python
def _sse_events(body: str) -> list[str]:
    return [ln[len("event: ") :] for ln in body.splitlines() if ln.startswith("event: ")]


async def test_first_message_emits_title_event(client: AsyncClient) -> None:
    """The first turn of a default-titled chat emits an SSE title event; later turns do not."""
    chat_id = (await client.post("/chats", json={"model": "test-model"})).json()["id"]  # default title

    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as r:
        first = "".join([c async for c in r.aiter_text()])
    assert "title" in _sse_events(first)
    assert 'event: title' in first

    # Second turn: title already set → no title event.
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Ещё"}) as r:
        second = "".join([c async for c in r.aiter_text()])
    assert "title" not in _sse_events(second)
```

- [ ] **Step 10: Run to verify failure**

Run: `uv run pytest tests/test_chats_api.py::test_first_message_emits_title_event -v`
Expected: FAIL — no `title` event emitted yet.

- [ ] **Step 11: Emit the `title` event in `send_message`**

In `src/capybara/api/routers/chats.py`, inside `send_message`'s `event_stream`, after the `async for` loop and still inside the `try`, add the title emission. The `history` variable from `begin_turn` is empty exactly on the first turn:

```python
    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, model, payload.content, history):
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Done):
                    yield _sse(
                        "done",
                        {"message_id": event.message_id, "usage": event.usage},
                    )
            if not history:  # first turn → derive a title without delaying the answer
                title = await service.generate_title(chat_id, payload.content)
                if title:
                    yield _sse("title", {"title": title})
        except Exception:  # surface a generic SSE error, never a broken stream
            logger.exception("chat stream failed for chat %s", chat_id)
            yield _sse("error", {"message": "Internal server error while streaming the reply"})
```

- [ ] **Step 12: Run the full backend suite + gates**

```bash
uv run pytest
uv run ruff format . && uv run ruff check . && uv run mypy src
```
Expected: all green.

- [ ] **Step 13: Commit**

```bash
git add src/capybara/agent/base.py src/capybara/services/chat_service.py \
  src/capybara/api/routers/chats.py tests/support.py tests/test_agent_title.py \
  tests/test_chat_service.py tests/test_chats_api.py
git commit -m "feat: LLM auto-title on first turn via SSE title event"
```

> Note on `tests/support.py`: no change is required — `FakeAgent.generate_title` is inherited from `BaseAgent` and runs the `TestModel`, whose `custom_output_text` drives the returned title. Only stage `tests/support.py` if you actually modified it.

---

### Task 5: Frontend API layer — delete, rename, favorite, title event

**Files:**
- Modify: `frontend/src/api/client.ts` (add `del`)
- Modify: `frontend/src/api/types.ts` (`ChatOut.is_favorite`)
- Modify: `frontend/src/chat/chatApi.ts`
- Modify: `frontend/src/chat/useChats.ts` (local mutations)
- Modify: `frontend/src/chat/useChatStream.ts` (`onTitle`)
- Create: `frontend/src/chat/chatApi.mutations.test.tsx`
- Modify: `frontend/src/chat/useChatStream.test.tsx`

**Interfaces:**
- Produces:
  - `ApiClient.del(path: string) => Promise<void>`.
  - `ChatOut.is_favorite: boolean`.
  - `deleteChat(api, id) => Promise<void>`; `renameChat(api, id, title) => Promise<ChatOut>`; `setFavorite(api, id, isFavorite) => Promise<ChatOut>`.
  - `useChats()` additionally returns `patchLocal(id, fields: Partial<ChatOut>) => void` and `removeLocal(id) => void`.
  - `useChatStream(chatId, onTitle?)` handles `event: title` by calling `onTitle(title)`.

- [ ] **Step 1: Write the failing chatApi mutation tests**

Create `frontend/src/chat/chatApi.mutations.test.tsx`:

```tsx
import { describe, expect, test, vi } from 'vitest'
import { deleteChat, renameChat, setFavorite } from './chatApi'
import type { ApiClient } from '../api/client'

function fakeApi() {
  return {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn().mockResolvedValue({ id: 'c1' }),
    del: vi.fn().mockResolvedValue(undefined),
    stream: vi.fn(),
  } as unknown as ApiClient & Record<string, ReturnType<typeof vi.fn>>
}

describe('chat mutation calls', () => {
  test('deleteChat DELETEs the chat', async () => {
    const api = fakeApi()
    await deleteChat(api, 'c1')
    expect(api.del).toHaveBeenCalledWith('/chats/c1')
  })
  test('renameChat PATCHes title', async () => {
    const api = fakeApi()
    await renameChat(api, 'c1', 'Новое имя')
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { title: 'Новое имя' })
  })
  test('setFavorite PATCHes is_favorite', async () => {
    const api = fakeApi()
    await setFavorite(api, 'c1', true)
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { is_favorite: true })
  })
})
```

- [ ] **Step 2: Add `del` to the API client**

In `frontend/src/api/client.ts`, add to the `ApiClient` interface (after `patch`):

```ts
  del(path: string): Promise<void>
```

and to the returned object (after the `patch` entry) a method that expects a bodyless 204:

```ts
    del: async (path) => {
      const res = await request(path, { method: 'DELETE' })
      if (!res.ok) throw new ApiError(res.status, await res.text())
    },
```

(`request` is the existing internal helper that adds auth + handles 401.)

- [ ] **Step 3: Extend types + chatApi**

In `frontend/src/api/types.ts`, add `is_favorite` to `ChatOut`:

```ts
export interface ChatOut {
  id: string
  title: string
  model: string | null
  is_favorite: boolean
  created_at: string
  updated_at: string
}
```

In `frontend/src/chat/chatApi.ts`, add:

```ts
export const deleteChat = (api: ApiClient, id: string) => api.del(`/chats/${id}`)
export const renameChat = (api: ApiClient, id: string, title: string) =>
  api.patch<ChatOut>(`/chats/${id}`, { title })
export const setFavorite = (api: ApiClient, id: string, isFavorite: boolean) =>
  api.patch<ChatOut>(`/chats/${id}`, { is_favorite: isFavorite })
```

- [ ] **Step 4: Run the mutation tests**

Run: `cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run chatApi.mutations`
Expected: PASS.

- [ ] **Step 5: Add local mutations to `useChats`**

In `frontend/src/chat/useChats.ts`, add two helpers and return them:

```ts
  const patchLocal = useCallback((id: string, fields: Partial<ChatOut>) => {
    setChats((prev) => prev.map((c) => (c.id === id ? { ...c, ...fields } : c)))
  }, [])

  const removeLocal = useCallback((id: string) => {
    setChats((prev) => prev.filter((c) => c.id !== id))
  }, [])
```

and add `patchLocal, removeLocal` to the returned object:

```ts
  return { chats, loading, reload, newChat, patchLocal, removeLocal }
```

- [ ] **Step 6: Write the failing `onTitle` stream test**

Add to `frontend/src/chat/useChatStream.test.tsx` a test that a `title` SSE event invokes `onTitle`. Follow the file's existing pattern (it already mocks `api.stream` returning an SSE body and renders the hook). Concretely add:

```tsx
test('invokes onTitle when a title event arrives', async () => {
  const onTitle = vi.fn()
  const body = sseStream(
    'event: delta\ndata: {"text":"Хай"}\n\n' +
      'event: done\ndata: {"message_id":"m1"}\n\n' +
      'event: title\ndata: {"title":"Про капибар"}\n\n',
  )
  const api = makeApi({ stream: vi.fn().mockResolvedValue(new Response(body)) })
  const { result } = renderHook(() => useChatStream('c1', onTitle), { wrapper: wrapperFor(api) })
  await act(async () => {
    await result.current.send('Привет')
  })
  expect(onTitle).toHaveBeenCalledWith('Про капибар')
})
```

> The exact helpers (`sseStream`, `makeApi`, `wrapperFor`) must match what `useChatStream.test.tsx` already defines — reuse the file's existing setup for building an SSE `Response` and providing the api client. If a helper name differs, use the file's actual one.

- [ ] **Step 7: Run to verify failure**

Run: `cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run useChatStream`
Expected: FAIL — the `title` event is ignored; `onTitle` never called.

- [ ] **Step 8: Handle `title` in `useChatStream`**

In `frontend/src/chat/useChatStream.ts`, change the signature to accept `onTitle` and thread it through. Update the hook signature:

```ts
export function useChatStream(chatId: string | null, onTitle?: (title: string) => void) {
```

Keep an always-current ref so `streamAssistant`'s `useCallback` need not depend on it:

```ts
  const onTitleRef = useRef(onTitle)
  onTitleRef.current = onTitle
```

In `streamAssistant`'s event loop, add a branch after the `error` branch:

```ts
          } else if (ev.event === 'title') {
            const { title } = JSON.parse(ev.data) as { title: string }
            onTitleRef.current?.(title)
          }
```

- [ ] **Step 9: Run the stream test + full frontend suite**

```bash
cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run
PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run lint
PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run build
```
Expected: all pass. Note: `ChatScreen.tsx` does not yet pass `onTitle` — that is fine (the parameter is optional; build stays clean). Task 7 wires it.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/types.ts frontend/src/chat/chatApi.ts \
  frontend/src/chat/chatApi.mutations.test.tsx frontend/src/chat/useChats.ts \
  frontend/src/chat/useChatStream.ts frontend/src/chat/useChatStream.test.tsx
git commit -m "feat(frontend): delete/rename/favorite api + onTitle stream handling"
```

---

### Task 6: ChatListItem (star + menu + inline rename) and ChatContextMenu

**Files:**
- Modify: `frontend/src/components/ChatListItem.tsx`
- Create: `frontend/src/components/ChatContextMenu.tsx`
- Modify: `frontend/src/components/Sidebar.module.css` (item/menu styles)
- Modify: `frontend/src/components/ChatListItem.test.tsx` (create if absent)
- Create: `frontend/src/components/ChatContextMenu.test.tsx`

**Interfaces:**
- Produces:
  - `ChatListItem` props: `{ chat: ChatOut, active: boolean, renaming: boolean, onSelect: () => void, onToggleFavorite: () => void, onOpenMenu: (anchor: DOMRect) => void, onRenameCommit: (title: string) => void, onRenameCancel: () => void }`.
  - `ChatContextMenu` props: `{ x: number, y: number, isFavorite: boolean, onRename: () => void, onToggleFavorite: () => void, onDelete: () => void, onClose: () => void }`.

- [ ] **Step 1: Write the failing ChatListItem tests**

Replace/create `frontend/src/components/ChatListItem.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatListItem } from './ChatListItem'
import type { ChatOut } from '../api/types'

const chat: ChatOut = {
  id: 'c1', title: 'Мой чат', model: 'm', is_favorite: false,
  created_at: '', updated_at: '',
}

function noop() {}

test('renders title and toggles favorite', async () => {
  const onToggleFavorite = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={false} onSelect={noop}
      onToggleFavorite={onToggleFavorite} onOpenMenu={noop}
      onRenameCommit={noop} onRenameCancel={noop} />,
  )
  expect(screen.getByText('Мой чат')).toBeInTheDocument()
  await userEvent.click(screen.getByLabelText('В избранное'))
  expect(onToggleFavorite).toHaveBeenCalled()
})

test('rename mode shows an input that commits on Enter', async () => {
  const onRenameCommit = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={true} onSelect={noop}
      onToggleFavorite={noop} onOpenMenu={noop}
      onRenameCommit={onRenameCommit} onRenameCancel={noop} />,
  )
  const input = screen.getByRole('textbox')
  await userEvent.clear(input)
  await userEvent.type(input, 'Переименован{Enter}')
  expect(onRenameCommit).toHaveBeenCalledWith('Переименован')
})

test('menu button reports its anchor rect', async () => {
  const onOpenMenu = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={false} onSelect={noop}
      onToggleFavorite={noop} onOpenMenu={onOpenMenu}
      onRenameCommit={noop} onRenameCancel={noop} />,
  )
  await userEvent.click(screen.getByLabelText('Меню чата'))
  expect(onOpenMenu).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run ChatListItem`
Expected: FAIL — the new props/controls don't exist.

- [ ] **Step 3: Rewrite `ChatListItem`**

Replace `frontend/src/components/ChatListItem.tsx`:

```tsx
/** Presentational list item for a single chat: star toggle, title/inline-rename, menu button. */
import { useState, type KeyboardEvent } from 'react'
import { Star, MoreHorizontal } from 'lucide-react'
import type { ChatOut } from '../api/types'
import styles from './Sidebar.module.css'

/** One chat row. Star toggles favorite; the ⋯ button opens the context menu at its anchor. */
export function ChatListItem({
  chat,
  active,
  renaming,
  onSelect,
  onToggleFavorite,
  onOpenMenu,
  onRenameCommit,
  onRenameCancel,
}: {
  chat: ChatOut
  active: boolean
  renaming: boolean
  onSelect: () => void
  onToggleFavorite: () => void
  onOpenMenu: (anchor: DOMRect) => void
  onRenameCommit: (title: string) => void
  onRenameCancel: () => void
}) {
  const [draft, setDraft] = useState(chat.title)

  if (renaming) {
    const commit = () => {
      const t = draft.trim()
      if (t) onRenameCommit(t)
      else onRenameCancel()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        commit()
      } else if (e.key === 'Escape') {
        onRenameCancel()
      }
    }
    return (
      <input
        className={styles.renameInput}
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
        aria-label="Переименовать чат"
      />
    )
  }

  return (
    <div className={active ? `${styles.chatRow} ${styles.chatRowActive}` : styles.chatRow}>
      <button
        type="button"
        className={chat.is_favorite ? `${styles.star} ${styles.starOn}` : styles.star}
        aria-label={chat.is_favorite ? 'Убрать из избранного' : 'В избранное'}
        onClick={onToggleFavorite}
      >
        <Star size={15} fill={chat.is_favorite ? 'currentColor' : 'none'} />
      </button>
      <button type="button" className={styles.chatTitleBtn} onClick={onSelect}>
        <span className={styles.chatTitle}>{chat.title}</span>
      </button>
      <button
        type="button"
        className={styles.menuBtn}
        aria-label="Меню чата"
        onClick={(e) => onOpenMenu(e.currentTarget.getBoundingClientRect())}
      >
        <MoreHorizontal size={15} />
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Write the ChatContextMenu tests**

Create `frontend/src/components/ChatContextMenu.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatContextMenu } from './ChatContextMenu'

function noop() {}

test('delete requires a confirm second click', async () => {
  const onDelete = vi.fn()
  render(
    <ChatContextMenu x={10} y={10} isFavorite={false} onRename={noop}
      onToggleFavorite={noop} onDelete={onDelete} onClose={noop} />,
  )
  await userEvent.click(screen.getByText('Удалить'))
  expect(onDelete).not.toHaveBeenCalled() // first click arms confirmation
  await userEvent.click(screen.getByText('Точно удалить?'))
  expect(onDelete).toHaveBeenCalled()
})

test('rename fires and shows favorite label based on state', async () => {
  const onRename = vi.fn()
  render(
    <ChatContextMenu x={0} y={0} isFavorite={true} onRename={onRename}
      onToggleFavorite={noop} onDelete={noop} onClose={noop} />,
  )
  expect(screen.getByText('Убрать из избранного')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Переименовать'))
  expect(onRename).toHaveBeenCalled()
})
```

- [ ] **Step 5: Implement `ChatContextMenu`**

Create `frontend/src/components/ChatContextMenu.tsx`:

```tsx
/** Floating context menu for a chat row: rename, favorite toggle, and delete (with confirm). */
import { useState } from 'react'
import { Pencil, Star, Trash2 } from 'lucide-react'
import styles from './Sidebar.module.css'

/** Rendered at (x, y); a click on the backdrop closes it. Delete arms a confirm on first click. */
export function ChatContextMenu({
  x,
  y,
  isFavorite,
  onRename,
  onToggleFavorite,
  onDelete,
  onClose,
}: {
  x: number
  y: number
  isFavorite: boolean
  onRename: () => void
  onToggleFavorite: () => void
  onDelete: () => void
  onClose: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className={styles.menuBackdrop} onClick={onClose} role="presentation">
      <div
        className={styles.menu}
        style={{ left: x, top: y }}
        role="menu"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className={styles.menuItem} role="menuitem" onClick={onRename}>
          <Pencil size={14} />
          Переименовать
        </button>
        <button type="button" className={styles.menuItem} role="menuitem" onClick={onToggleFavorite}>
          <Star size={14} />
          {isFavorite ? 'Убрать из избранного' : 'В избранное'}
        </button>
        <div className={styles.menuSep} />
        <button
          type="button"
          className={`${styles.menuItem} ${styles.menuItemDanger}`}
          role="menuitem"
          onClick={() => (confirming ? onDelete() : setConfirming(true))}
        >
          <Trash2 size={14} />
          {confirming ? 'Точно удалить?' : 'Удалить'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Add styles**

Append to `frontend/src/components/Sidebar.module.css`:

```css
.chatRow {
  display: flex;
  align-items: center;
  gap: 2px;
  border-radius: 10px;
  padding: 0 4px;
}
.chatRow:hover {
  background: rgba(255, 255, 255, 0.05);
}
.chatRowActive {
  background: rgba(255, 255, 255, 0.08);
}
.chatTitleBtn {
  flex: 1;
  min-width: 0;
  text-align: left;
  background: transparent;
  border: none;
  color: #d6cdc3;
  font-family: inherit;
  font-size: 13px;
  padding: 8px 2px;
  cursor: pointer;
}
.chatTitleBtn .chatTitle {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}
.star,
.menuBtn {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #8a8178;
  cursor: pointer;
  border-radius: 6px;
}
.star:hover,
.menuBtn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #e6ddd3;
}
.starOn {
  color: var(--accent, #d89b6c);
}
.renameInput {
  width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(216, 155, 108, 0.5);
  background: rgba(0, 0, 0, 0.28);
  color: #f2ece4;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
}
.menuBackdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
}
.menu {
  position: fixed;
  min-width: 190px;
  background: rgba(40, 35, 30, 0.97);
  backdrop-filter: blur(30px) saturate(1.5);
  -webkit-backdrop-filter: blur(30px) saturate(1.5);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 5px;
  box-shadow: 0 16px 44px rgba(0, 0, 0, 0.55);
}
.menuItem {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border: none;
  background: transparent;
  color: #e6ddd3;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
  border-radius: 8px;
  text-align: left;
}
.menuItem:hover {
  background: rgba(255, 255, 255, 0.08);
}
.menuItemDanger {
  color: #e08a7a;
}
.menuItemDanger:hover {
  background: rgba(224, 138, 122, 0.12);
}
.menuSep {
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  margin: 4px 6px;
}
```

- [ ] **Step 7: Run the component tests + lint**

```bash
cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run ChatListItem ChatContextMenu
PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run lint
```
Expected: PASS + lint clean. Note: `Sidebar.tsx` still renders the old `ChatListItem` signature, so `npm run build` will report type errors in `Sidebar.tsx` only — that is expected and closed by Task 7.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ChatListItem.tsx frontend/src/components/ChatContextMenu.tsx \
  frontend/src/components/ChatListItem.test.tsx frontend/src/components/ChatContextMenu.test.tsx \
  frontend/src/components/Sidebar.module.css
git commit -m "feat(frontend): chat row star/menu/rename + context menu component"
```

---

### Task 7: Wire favorites grouping + menu + delete into Sidebar & ChatScreen

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/screens/ChatScreen.tsx`
- Modify: `frontend/src/components/CapyLogo.tsx` (adopt new mark — only if it references the asset path)
- Modify: `frontend/src/components/Sidebar.test.tsx`
- Modify: `frontend/src/screens/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `ChatListItem`, `ChatContextMenu`, `useChats().{patchLocal, removeLocal, reload}`, `chatApi.{deleteChat, renameChat, setFavorite}`, `useChatStream(chatId, onTitle)`.
- Produces: `Sidebar` gains props `onToggleFavorite(id)`, `onRename(id, title)`, `onDelete(id)`; a top "Избранное" group; menu + rename state managed inside `Sidebar`.

- [ ] **Step 1: Write the failing Sidebar test**

Add to `frontend/src/components/Sidebar.test.tsx` a test that favorites render under an "Избранное" group. Follow the file's existing render pattern (it renders `<Sidebar chats={...} .../>` inside the auth/api providers). Add:

```tsx
test('favorites appear under an Избранное group', () => {
  const chats = [
    { id: 'a', title: 'Обычный', model: 'm', is_favorite: false, created_at: new Date().toISOString(), updated_at: '' },
    { id: 'b', title: 'Звёздный', model: 'm', is_favorite: true, created_at: new Date().toISOString(), updated_at: '' },
  ]
  renderSidebar({ chats }) // reuse the file's existing render helper / inline render
  expect(screen.getByText('Избранное')).toBeInTheDocument()
  // "Звёздный" is listed above the date-group "Обычный"
  const fav = screen.getByText('Звёздный')
  const normal = screen.getByText('Обычный')
  expect(fav.compareDocumentPosition(normal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
```

> Match the file's actual render setup (props, providers). If there's no helper, render `<Sidebar>` directly with all required props (stub the new callbacks with `vi.fn()`).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run Sidebar`
Expected: FAIL — no favorites group; new props/signature missing.

- [ ] **Step 3: Rewrite `Sidebar`**

Replace `frontend/src/components/Sidebar.tsx`. Keep the existing `groupChats` (date buckets), add a favorites split, own the menu + rename state, and render `ChatContextMenu`:

```tsx
/** Sidebar: logo, new-chat, search, favorites + date-grouped chat list, deferred nav, user card. */
import { useState } from 'react'
import { Plus, Search, Brain, Clock, Settings, Star } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { ChatListItem } from './ChatListItem'
import { ChatContextMenu } from './ChatContextMenu'
import { UserCard } from './UserCard'
import { useAuth } from '../auth/AuthContext'
import type { ChatOut } from '../api/types'
import styles from './Sidebar.module.css'

/** Groups chats into today / yesterday / earlier buckets based on `created_at`. */
function groupChats(chats: ChatOut[]): { label: string; items: ChatOut[] }[] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const todayItems: ChatOut[] = []
  const yesterdayItems: ChatOut[] = []
  const earlierItems: ChatOut[] = []
  for (const chat of chats) {
    const d = new Date(chat.created_at)
    const chatDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
    if (chatDay >= today) todayItems.push(chat)
    else if (chatDay >= yesterday) yesterdayItems.push(chat)
    else earlierItems.push(chat)
  }
  const groups: { label: string; items: ChatOut[] }[] = []
  if (todayItems.length) groups.push({ label: 'Сегодня', items: todayItems })
  if (yesterdayItems.length) groups.push({ label: 'Вчера', items: yesterdayItems })
  if (earlierItems.length) groups.push({ label: 'Ранее', items: earlierItems })
  return groups
}

export function Sidebar({
  chats,
  activeChatId,
  onSelect,
  onNewChat,
  onToggleFavorite,
  onRename,
  onDelete,
}: {
  chats: ChatOut[]
  activeChatId: string | null
  onSelect: (id: string) => void
  onNewChat: () => void
  onToggleFavorite: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const filtered = query
    ? chats.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
    : chats
  const favorites = filtered.filter((c) => c.is_favorite)
  const dateGroups = groupChats(filtered.filter((c) => !c.is_favorite))
  const menuChat = menu ? chats.find((c) => c.id === menu.id) : undefined

  const renderItem = (chat: ChatOut) => (
    <ChatListItem
      key={chat.id}
      chat={chat}
      active={chat.id === activeChatId}
      renaming={renamingId === chat.id}
      onSelect={() => onSelect(chat.id)}
      onToggleFavorite={() => onToggleFavorite(chat.id)}
      onOpenMenu={(rect) => setMenu({ id: chat.id, x: rect.left, y: rect.bottom + 4 })}
      onRenameCommit={(title) => {
        setRenamingId(null)
        onRename(chat.id, title)
      }}
      onRenameCancel={() => setRenamingId(null)}
    />
  )

  return (
    <aside className={styles.sidebar}>
      <div className={styles.logoBlock}>
        <CapyLogo size={90} />
        <div className={styles.logoText}>
          <span className={styles.logoSub}>
            С возвращением, {user?.displayName || user?.username || 'гость'}
          </span>
        </div>
      </div>

      <button type="button" className={styles.newChatBtn} onClick={onNewChat}>
        <span className={styles.newChatIcon}>
          <Plus size={16} />
        </span>
        Новый чат
      </button>

      <div className={styles.searchWrap}>
        <span className={styles.searchIcon}>
          <Search size={14} />
        </span>
        <input
          type="search"
          className={styles.searchInput}
          placeholder="Поиск…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Поиск по чатам"
        />
      </div>

      <div className={styles.chatList}>
        {favorites.length > 0 && (
          <div>
            <div className={styles.groupLabel}>
              <Star size={11} fill="currentColor" className={styles.groupStar} /> Избранное
            </div>
            {favorites.map(renderItem)}
          </div>
        )}
        {dateGroups.map((group) => (
          <div key={group.label}>
            <div className={styles.groupLabel}>{group.label}</div>
            {group.items.map(renderItem)}
          </div>
        ))}
      </div>

      <div className={styles.bottomBlock}>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Brain size={16} />
          Память
        </div>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Clock size={16} />
          Фоновые задачи
          <span className={styles.badge}>2</span>
        </div>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Settings size={16} />
          Настройки
        </div>
        <UserCard />
      </div>

      {menu && menuChat && (
        <ChatContextMenu
          x={menu.x}
          y={menu.y}
          isFavorite={menuChat.is_favorite}
          onRename={() => {
            setRenamingId(menu.id)
            setMenu(null)
          }}
          onToggleFavorite={() => {
            onToggleFavorite(menu.id)
            setMenu(null)
          }}
          onDelete={() => {
            onDelete(menu.id)
            setMenu(null)
          }}
          onClose={() => setMenu(null)}
        />
      )}
    </aside>
  )
}
```

- [ ] **Step 4: Add the group-star style**

Append to `frontend/src/components/Sidebar.module.css`:

```css
.groupLabel {
  display: flex;
  align-items: center;
  gap: 5px;
}
.groupStar {
  color: var(--accent, #d89b6c);
  margin-top: -1px;
}
```

(If `.groupLabel` already exists in the file, merge these `display/align/gap` rules into it instead of duplicating the selector.)

- [ ] **Step 5: Wire handlers into `ChatScreen`**

In `frontend/src/screens/ChatScreen.tsx`:

Add imports:

```tsx
import { deleteChat, renameChat, setFavorite, patchChatModel } from '../chat/chatApi'
```

Destructure the new `useChats` helpers and pass `onTitle` to `useChatStream`:

```tsx
  const { chats, reload, newChat, patchLocal, removeLocal } = useChats()
  const { models } = useModels()
  const { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate } =
    useChatStream(activeChatId, (title) => {
      if (activeChatId) patchLocal(activeChatId, { title })
    })
```

Add the three handlers (after `handleSelectModel`):

```tsx
  /** Toggle favorite: optimistic local flip, then persist. */
  async function handleToggleFavorite(id: string) {
    const chat = chats.find((c) => c.id === id)
    const next = !(chat?.is_favorite ?? false)
    patchLocal(id, { is_favorite: next })
    await setFavorite(api, id, next)
  }

  /** Rename: optimistic local update, then persist. */
  async function handleRename(id: string, title: string) {
    patchLocal(id, { title })
    await renameChat(api, id, title)
  }

  /** Delete: remove locally (returning to welcome if it was active), then persist. */
  async function handleDelete(id: string) {
    if (id === activeChatId) setActiveChatId(null)
    removeLocal(id)
    await deleteChat(api, id)
  }
```

Pass them to `<Sidebar>`:

```tsx
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          onSelect={setActiveChatId}
          onNewChat={() => setActiveChatId(null)}
          onToggleFavorite={handleToggleFavorite}
          onRename={handleRename}
          onDelete={handleDelete}
        />
```

- [ ] **Step 6: Update the existing ChatScreen test for the new Sidebar props**

The existing `ChatScreen.test.tsx` renders `<ChatScreen/>`, which now renders the new Sidebar — no prop changes needed there (ChatScreen supplies them internally). Run the ChatScreen suite and, if any test mocks `/api/chats` responses with chat objects lacking `is_favorite`, add `is_favorite: false` to those fixtures so they type-check and group correctly:

Run: `cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run ChatScreen Sidebar`
Expected: PASS (fix fixtures if a chat literal is missing `is_favorite`).

- [ ] **Step 7: Full frontend gates**

```bash
cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run
PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run lint
PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run build
```
Expected: all green (build now closes — Sidebar uses the new ChatListItem signature).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Sidebar.tsx frontend/src/components/Sidebar.module.css \
  frontend/src/components/Sidebar.test.tsx frontend/src/screens/ChatScreen.tsx \
  frontend/src/screens/ChatScreen.test.tsx
git commit -m "feat(frontend): favorites group, chat context menu, delete/rename/favorite wiring"
```

---

### Task 8: Full-stack verification

**Files:** none (verification only).

- [ ] **Step 1: Backend gates**

```bash
uv run pytest && uv run ruff check . && uv run mypy src
```
Expected: all pass.

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run test -- --run \
  && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run lint \
  && PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH" npm run build
```
Expected: all pass.

- [ ] **Step 3: Manual smoke (optional, requires the stack + Ollama)**

`docker compose up --build`, then: create a chat and send a first message → the tab title updates to an LLM-generated title shortly after the reply; star a chat → it jumps to the "Избранное" group; rename via the ⋯ menu → title updates; delete via the ⋯ menu (confirm) → the chat disappears and, if active, returns to welcome.

---

## Self-Review

**Spec coverage:**
- `chats.is_favorite` + migration + `ChatOut` → Task 1. ✅
- Unified `PATCH` (title/model/is_favorite, ≥1, model-only validation) → Task 2. ✅
- `DELETE /chats/{id}` + cascade → Task 3. ✅
- `BaseAgent.generate_title` (clean + fallback, never raises) → Task 4 (agent). ✅
- Auto-title trigger (first turn + default title) + SSE `title` event → Task 4 (service + router). ✅
- FE types/api `deleteChat`/`renameChat`/`setFavorite`, `client.del` → Task 5. ✅
- `useChatStream` `title` event → `onTitle` → Task 5. ✅
- ChatListItem star/menu/inline-rename, ChatContextMenu (rename/favorite/delete + confirm) → Task 6. ✅
- Sidebar favorites group + wiring, ChatScreen handlers + delete-active→welcome + live title → Task 7. ✅
- lucide icons (Star/Trash2/Pencil/MoreHorizontal) + logo → Tasks 6–7. ✅
- Tests both sides → Tasks 1–7. ✅

**Placeholder scan:** The only conditional instructions (Task 5 Step 6 and Task 7 Steps 1/6 about reusing the test files' existing render/SSE helpers) are explicit — the exact helper names depend on the current test files, and the executor is told precisely what to match. No TBD/TODO left.

**Type consistency:** `is_favorite` used identically across `Chat`, `ChatOut`, `ChatUpdate`, `ChatListItem`, `ChatContextMenu`, `Sidebar`, `setFavorite`. `generate_title` signature matches between `BaseAgent` (Task 4), `ChatService.generate_title` (Task 4), and the router call (Task 4). `deleteChat`/`renameChat`/`setFavorite` signatures match between `chatApi` (Task 5) and `ChatScreen` (Task 7). `patchLocal`/`removeLocal`/`onTitle` consistent between `useChats`/`useChatStream` (Task 5) and `ChatScreen` (Task 7). `DEFAULT_CHAT_TITLE` defined in `chat.py` (Task 1) and consumed in the service (Task 4).
