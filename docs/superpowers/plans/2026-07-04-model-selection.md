# Model Selection & Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user see the real list of Ollama models and pick one per chat, with the selector in the composer's bottom row, and replace the opaque stream error with an up-front, clear one.

**Architecture:** `BaseAgent` becomes a provider abstraction that can `list_models()`, build a model by name, and `ensure_available()`. The chosen model is stored on the chat row (`chats.model`); `ChatService.begin_turn` validates it before any SSE bytes and returns it alongside history. New endpoints `GET /models` and `PATCH /chats/{id}` expose listing and selection. The frontend fetches the list, tracks the chat's model, blocks send when no valid model is selected, and PATCHes on change.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic-ai (Ollama via OpenAI-compat), httpx; React 18 + TypeScript + Vite, lucide-react, vitest + msw.

## Global Constraints

- Python 3.12+, fully type-annotated; strict mypy (`uv run mypy src` clean).
- ruff lint + format clean, incl. pydocstyle `D` (google) — every module/class/function has a docstring; tests exempt.
- Layering: `api` → `services` → `repositories` → `db`; no DB queries in routers/services (repos only).
- All model/DB access via repositories. One async session per request via dependency.
- Provider-agnostic LLM behind the thin agent abstraction — services never touch a provider directly.
- TDD: write the failing test first. Use pydantic-ai `TestModel` for LLM; repos/services/API against real Postgres via testcontainers.
- No implicit model fallback anywhere. `chat.model = NULL` or a model absent from the live Ollama list ⇒ "not selected" ⇒ send blocked (client) and rejected up front (server).
- Backend commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy src`.
- Frontend commands (run in `frontend/`): `npm run test`, `npm run lint`, `npm run build`.
- `httpx>=0.28` is already a dependency — no new deps needed.

---

### Task 1: `chats.model` column, schemas, and repo support

**Files:**
- Modify: `src/capybara/db/models/chat.py`
- Modify: `src/capybara/repositories/chat_repo.py:22-27` (`create`)
- Modify: `src/capybara/api/schemas.py` (`ChatCreate`, `ChatOut`; add `ChatUpdate`, `ModelsOut`)
- Create: `src/capybara/migrations/versions/20260704_1400_b2d0cafe0002_chats_model.py`
- Modify: `tests/test_repositories.py` (add a model round-trip test)

**Interfaces:**
- Produces: `Chat.model: Mapped[str | None]`; `ChatRepo.create(user_id, title=None, model=None) -> Chat`; `ChatCreate.model: str | None`; `ChatOut.model: str | None`; `ChatUpdate.model: str`; `ModelsOut(provider: str, models: list[str])`.

- [ ] **Step 1: Add the `model` column to the ORM model**

In `src/capybara/db/models/chat.py`, add the mapped column after `title` (line 25):

```python
    title: Mapped[str] = mapped_column(String(200), default="Новый чат")
    #: Selected LLM model for this chat, e.g. ``llama3.1:8b``. ``NULL`` = not yet chosen;
    #: there is no server-side fallback — an unset model blocks sending.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

- [ ] **Step 2: Let `ChatRepo.create` accept a model**

Replace `ChatRepo.create` (lines 22-27) in `src/capybara/repositories/chat_repo.py`:

```python
    async def create(  # type: ignore[override]
        self, user_id: UUID, title: str | None = None, model: str | None = None
    ) -> Chat:
        """Create a chat for user_id, optionally setting a custom title and model."""
        fields: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            fields["title"] = title
        if model is not None:
            fields["model"] = model
        return await super().create(**fields)
```

- [ ] **Step 3: Update the Pydantic schemas**

In `src/capybara/api/schemas.py`, add `model` to `ChatCreate` and `ChatOut`, and add two new schemas:

```python
class ChatCreate(BaseModel):
    """Payload for creating a new chat."""

    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=128)


class ChatUpdate(BaseModel):
    """Payload for changing a chat's selected model."""

    model: str = Field(min_length=1, max_length=128)


class ModelsOut(BaseModel):
    """Available models for a provider."""

    provider: str
    models: list[str]
```

And add `model: str | None` to `ChatOut` (after `title`):

```python
class ChatOut(BaseModel):
    """Response schema for a chat summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    model: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Write the migration**

Create `src/capybara/migrations/versions/20260704_1400_b2d0cafe0002_chats_model.py`:

```python
"""add chats.model

Revision ID: b2d0cafe0002
Revises: a1c0ffee0001
Create Date: 2026-07-04 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d0cafe0002"
down_revision: str | Sequence[str] | None = "a1c0ffee0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable model column to chats."""
    op.add_column("chats", sa.Column("model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Drop the model column from chats."""
    op.drop_column("chats", "model")
```

- [ ] **Step 5: Write the failing repo test**

Add to `tests/test_repositories.py`:

```python
async def test_chat_repo_create_persists_model(session) -> None:  # type: ignore[no-untyped-def]
    """A chat created with a model round-trips the model value."""
    from capybara.db.models import User
    from capybara.repositories.chat_repo import ChatRepo
    from capybara.security.passwords import hash_password

    user = User(username="modeluser", display_name="M", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    repo = ChatRepo(session)
    chat = await repo.create(user.id, title="c", model="llama3.1:8b")
    assert chat.model == "llama3.1:8b"

    reloaded = await repo.get(chat.id)
    assert reloaded is not None
    assert reloaded.model == "llama3.1:8b"
```

- [ ] **Step 6: Run the repo test (expect PASS)**

Run: `uv run pytest tests/test_repositories.py::test_chat_repo_create_persists_model -v`
Expected: PASS (the ORM column + repo change make it pass; the `engine` fixture builds tables from metadata).

- [ ] **Step 7: Run the migration test**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: PASS — the new revision applies cleanly on top of the initial schema and downgrades to base.

- [ ] **Step 8: Lint, format, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/db/models/chat.py src/capybara/repositories/chat_repo.py \
  src/capybara/api/schemas.py src/capybara/migrations/versions/20260704_1400_b2d0cafe0002_chats_model.py \
  tests/test_repositories.py
git commit -m "feat: add chats.model column, schemas, and repo support"
```

---

### Task 2: Provider abstraction — list, build, validate, stream by name

Refactors `BaseAgent` so it is no longer bound to one model at construction. Adds Ollama model listing and two error types. Updates the test fakes and the agent unit test to the new signatures.

**Files:**
- Modify: `src/capybara/agent/base.py` (full rewrite of the class shape)
- Modify: `src/capybara/agent/ollama.py`
- Modify: `src/capybara/agent/__init__.py`
- Modify: `tests/support.py` (fakes for the new interface)
- Modify: `tests/test_agent_stream.py:15` (new `stream_reply` signature)
- Create: `tests/test_agent_models.py`

**Interfaces:**
- Produces:
  - `class ModelUnavailableError(Exception)` with `.model_name: str | None`, `.available: list[str]`.
  - `class ModelProviderError(Exception)` with `.url: str`.
  - `BaseAgent.__init__(self, settings: Settings)` — stores `self._settings`, binds no model.
  - `async BaseAgent.list_models(self) -> list[str]` (abstract).
  - `BaseAgent._build_model(self, name: str) -> Model` (abstract).
  - `async BaseAgent.ensure_available(self, model_name: str | None) -> None` — raises `ModelUnavailableError` when unset/absent; may raise `ModelProviderError`.
  - `async BaseAgent.stream_reply(self, model_name: str, user_content: str, history: list[ModelMessage], acc: ReplyAccumulator) -> AsyncIterator[str]`.
- Consumes: `Settings.ollama_base_url` (Task uses it for `/api/tags` and `/v1`).

- [ ] **Step 1: Write the failing Ollama listing + validation tests**

Create `tests/test_agent_models.py`:

```python
"""Tests for provider model listing and availability validation."""

import httpx
import pytest

from capybara.agent import ModelProviderError, ModelUnavailableError, OllamaAgent
from capybara.config import Settings


def _agent_with_transport(settings: Settings, handler) -> OllamaAgent:  # type: ignore[no-untyped-def]
    agent = OllamaAgent(settings)
    agent._client_factory = lambda: httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)
    )
    return agent


async def test_list_models_returns_names(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:14b"}]},
        )

    agent = _agent_with_transport(settings, handler)
    assert await agent.list_models() == ["llama3.1:8b", "qwen2.5:14b"]


async def test_list_models_raises_provider_error_when_unreachable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelProviderError):
        await agent.list_models()


async def test_ensure_available_rejects_unset_and_unknown(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelUnavailableError):
        await agent.ensure_available(None)
    with pytest.raises(ModelUnavailableError):
        await agent.ensure_available("ghost:1b")
    await agent.ensure_available("llama3.1:8b")  # no raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_models.py -v`
Expected: FAIL — `ModelProviderError`/`ModelUnavailableError`/`list_models`/`_client_factory` do not exist yet.

- [ ] **Step 3: Rewrite `BaseAgent`**

Replace the whole body of `src/capybara/agent/base.py` with:

```python
"""Abstract base agent, error types, and reply accumulator for LLM streaming."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from capybara.config import Settings
from capybara.db.models import Message


class ModelUnavailableError(Exception):
    """Raised when a chat's model is unset or not present in the provider's live list."""

    def __init__(self, model_name: str | None, available: list[str]) -> None:
        """Record the offending model name and the list of currently available models."""
        self.model_name = model_name
        self.available = available
        super().__init__(
            f"Model {model_name!r} is not available. Select an installed model."
        )


class ModelProviderError(Exception):
    """Raised when the model provider (Ollama) cannot be reached at all."""

    def __init__(self, url: str) -> None:
        """Record the provider base URL that could not be reached."""
        self.url = url
        super().__init__(f"Ollama unreachable at {url}")


@dataclass
class ReplyAccumulator:
    """Accumulate streaming text, usage stats, and model name from a single run."""

    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None


class BaseAgent(ABC):
    """Abstract provider abstraction: list models, build a model by name, and stream."""

    def __init__(self, settings: Settings) -> None:
        """Store settings; models are built per-turn, not bound at construction."""
        self._settings = settings

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the names of models currently available from the provider."""
        ...

    @abstractmethod
    def _build_model(self, name: str) -> Model:
        """Build a pydantic-ai model for the given model name."""
        ...

    async def ensure_available(self, model_name: str | None) -> None:
        """Raise ModelUnavailableError if model_name is unset or not in the live list.

        Raises:
            ModelUnavailableError: If *model_name* is ``None`` or absent from the list.
            ModelProviderError: If the provider cannot be reached (from ``list_models``).
        """
        available = await self.list_models()
        if not model_name or model_name not in available:
            raise ModelUnavailableError(model_name, available)

    @staticmethod
    def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
        """Convert DB Message rows to pydantic-ai ModelMessage history."""
        history: list[ModelMessage] = []
        for message in messages:
            if message.role == "user":
                history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
            elif message.role == "assistant":
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
            else:
                raise ValueError(f"Unknown message role: {message.role!r}")
        return history

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Stream token deltas for the named model and accumulate the reply into acc."""
        agent: Agent[None, str] = Agent(self._build_model(model_name))
        async with agent.run_stream(user_content, message_history=history) as result:
            async for text in result.stream_text(delta=True):
                acc.text += text
                yield text
            run_usage = result.usage
            acc.usage = {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            acc.model = result.response.model_name
```

- [ ] **Step 4: Rewrite `OllamaAgent` with listing + per-name build**

Replace `src/capybara/agent/ollama.py` with:

```python
"""Ollama-backed agent using the OpenAI-compatible API and the native tags endpoint."""

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.agent.base import BaseAgent, ModelProviderError


class OllamaAgent(BaseAgent):
    """Agent that targets an Ollama server via OpenAI-compatible endpoints."""

    #: Overridable in tests to inject a mock transport.
    def _client_factory(self) -> httpx.AsyncClient:
        """Create the httpx client used to query Ollama's native API."""
        return httpx.AsyncClient(timeout=10.0)

    async def list_models(self) -> list[str]:
        """Return installed model names from Ollama's ``/api/tags`` endpoint.

        Raises:
            ModelProviderError: If Ollama cannot be reached or returns an error status.
        """
        url = f"{self._settings.ollama_base_url}/api/tags"
        try:
            async with self._client_factory() as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc
        data = response.json()
        return [entry["name"] for entry in data.get("models", [])]

    def _build_model(self, name: str) -> Model:
        """Build an OpenAI-compatible model pointed at the Ollama server."""
        return OpenAIChatModel(
            name,
            provider=OpenAIProvider(
                base_url=f"{self._settings.ollama_base_url}/v1",
                api_key="ollama",  # Ollama ignores the key; required by the client.
            ),
        )
```

- [ ] **Step 5: Export the new error types**

Replace `src/capybara/agent/__init__.py` with:

```python
"""Agent abstractions for LLM interaction."""

from capybara.agent.base import (
    BaseAgent,
    ModelProviderError,
    ModelUnavailableError,
    ReplyAccumulator,
)
from capybara.agent.ollama import OllamaAgent

__all__ = [
    "BaseAgent",
    "ModelProviderError",
    "ModelUnavailableError",
    "OllamaAgent",
    "ReplyAccumulator",
]
```

- [ ] **Step 6: Update the test fakes to the new interface**

Replace `tests/support.py` with:

```python
from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.config import Settings


class FakeAgent(BaseAgent):
    """Agent backed by pydantic-ai TestModel with a fixed, configurable model list."""

    def __init__(
        self, settings: Settings, output_text: str, models: tuple[str, ...] = ("test-model",)
    ) -> None:
        self._output_text = output_text
        self._models = list(models)
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return list(self._models)

    def _build_model(self, name: str) -> Model:
        return TestModel(custom_output_text=self._output_text)


class RaisingAgent(BaseAgent):
    """Agent whose stream raises mid-reply — used to test SSE error handling."""

    def __init__(self, settings: Settings, message: str) -> None:
        self._message = message
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return ["test-model"]

    def _build_model(self, name: str) -> Model:
        return TestModel()

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Raise immediately; the trailing yield only marks this as a generator."""
        raise RuntimeError(self._message)
        yield ""  # pragma: no cover


class PartialThenFailAgent(BaseAgent):
    """Agent that streams one partial delta and then fails — models a mid-reply error."""

    def __init__(self, settings: Settings, partial: str, message: str) -> None:
        self._partial = partial
        self._message = message
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return ["test-model"]

    def _build_model(self, name: str) -> Model:
        return TestModel()

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Yield one accumulated delta, then raise to abort the stream."""
        acc.text += self._partial
        yield self._partial
        raise RuntimeError(self._message)
```

- [ ] **Step 7: Fix the existing agent stream test signature**

In `tests/test_agent_stream.py`, update line 15 (the `stream_reply` call) to pass a model name:

```python
    chunks = [delta async for delta in agent.stream_reply("test-model", "Привет", [], acc)]
```

- [ ] **Step 8: Run the agent tests**

Run: `uv run pytest tests/test_agent_models.py tests/test_agent_stream.py -v`
Expected: PASS for all (listing, provider error, ensure_available, and the existing stream test).

- [ ] **Step 9: Lint, format, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/agent tests/support.py tests/test_agent_stream.py tests/test_agent_models.py
git commit -m "feat: provider abstraction with model listing and availability checks"
```

---

### Task 3: Validate the chat's model up front and stream by name

`begin_turn` now validates `chat.model` and returns it with the history; `stream_turn` takes the model name and passes it to `stream_reply`.

**Files:**
- Modify: `src/capybara/services/chat_service.py` (`begin_turn`, `stream_turn`)
- Modify: `tests/test_chat_service.py` (seed model, new signatures, new validation test)

**Interfaces:**
- Consumes: `BaseAgent.ensure_available`, `BaseAgent.stream_reply(model_name, ...)`, `ModelUnavailableError`, `ModelProviderError`.
- Produces:
  - `async ChatService.begin_turn(user_id, chat_id, user_content) -> tuple[str, list[ModelMessage]]` — raises `ChatNotFoundError`, `ModelUnavailableError`, or `ModelProviderError`.
  - `async ChatService.stream_turn(chat_id, model_name, user_content, history) -> AsyncIterator[StreamEvent]`.

- [ ] **Step 1: Update the seed helper and existing tests to set a model**

In `tests/test_chat_service.py`, in `_seed_chat` (line ~21) set a model on the seeded chat:

```python
        chat = Chat(user_id=user.id, title="c", model="test-model")
```

Then update every `begin_turn`/`stream_turn` call site in this file to the new signatures. There are five `begin_turn` calls and one `stream_turn` call:

- `test_stream_turn_streams_and_persists` (lines ~37-38):

```python
    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = [e async for e in service.stream_turn(chat_id, model, "Вопрос", history)]  # type: ignore[arg-type]
```

- `test_stream_turn_persists_partial_on_stream_error` (lines ~69-72):

```python
    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = []
    with pytest.raises(RuntimeError):
        async for e in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
            events.append(e)
```

- `test_stream_turn_does_not_persist_empty_assistant_on_immediate_error` (lines ~99-102):

```python
    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        async for _ in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
            pass
```

- `test_begin_turn_excludes_incomplete_from_history` (line ~131):

```python
    _, history = await service.begin_turn(user_id, chat_id, "q2")  # type: ignore[arg-type]
```

- `test_begin_turn_rejects_missing_chat` (line ~155) and `test_begin_turn_rejects_foreign_chat` (line ~169) keep asserting the raise; just leave the `await service.begin_turn(...)` calls as-is (their return is unused).

- [ ] **Step 2: Write the failing "unavailable model" test**

Add to `tests/test_chat_service.py`:

```python
async def test_begin_turn_rejects_model_not_installed(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A chat whose model is not in the agent's live list is rejected before any write."""
    from capybara.agent import ModelUnavailableError

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="badmodel", display_name="B")
        chat = Chat(user_id=user.id, title="c", model="ghost:1b")
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    # FakeAgent only offers "test-model", so "ghost:1b" is unavailable.
    service = ChatService(maker, FakeAgent(settings, "x"))
    with pytest.raises(ModelUnavailableError):
        await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert stored == []  # user message must NOT be written when the model is invalid
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_chat_service.py::test_begin_turn_rejects_model_not_installed -v`
Expected: FAIL — `begin_turn` does not validate the model yet (currently returns history, writes the user message).

- [ ] **Step 4: Implement validation + model threading in the service**

In `src/capybara/services/chat_service.py`, replace `begin_turn` (lines 32-60) so it validates and returns the model. Update the return type and docstring:

```python
    async def begin_turn(
        self, user_id: UUID, chat_id: UUID, user_content: str
    ) -> tuple[str, list[ModelMessage]]:
        """Verify ownership, validate the model, persist the user message, load history.

        The model on the chat is validated against the provider's live list *before* the
        user message is written, so an unusable model never leaves an orphaned message and
        the error surfaces before any SSE bytes are sent.

        Returns:
            The validated model name and the pydantic-ai history.

        Raises:
            ChatNotFoundError: If the chat does not exist or is not owned by *user_id*.
            ModelUnavailableError: If the chat's model is unset or not installed.
            ModelProviderError: If the model provider cannot be reached.
        """
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            await self._agent.ensure_available(chat.model)
            model = chat.model
            assert model is not None  # ensure_available rejects None
            messages = MessageRepo(session)
            history_rows = await messages.list(
                FieldEquals(Message.chat_id, chat_id),
                FieldEquals(Message.incomplete, False),
            )
            await messages.create(chat_id=chat_id, role="user", content=user_content)
            await session.commit()
        return model, self._agent.to_model_messages(history_rows)
```

Then update `stream_turn` (line 62) to accept `model_name` and pass it through:

```python
    async def stream_turn(
        self, chat_id: UUID, model_name: str, user_content: str, history: list[ModelMessage]
    ) -> AsyncIterator[StreamEvent]:
```

and inside it change the stream call (line 78):

```python
            async for delta in self._agent.stream_reply(model_name, user_content, history, acc):
```

- [ ] **Step 5: Run the full chat-service suite**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: PASS for all (the seeded `test-model` is now valid; the new test rejects `ghost:1b`).

- [ ] **Step 6: Lint, format, type-check, commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src
git add src/capybara/services/chat_service.py tests/test_chat_service.py
git commit -m "feat: validate chat model before streaming and stream by name"
```

---

### Task 4: Endpoints — GET /models, PATCH /chats/{id}, and error mapping

Exposes listing and selection, threads the validated model into the stream, and maps the new errors to clear HTTP statuses (409 unavailable, 502 provider down) — replacing the opaque in-stream error for the "model missing" case.

**Files:**
- Create: `src/capybara/api/routers/models.py`
- Modify: `src/capybara/api/routers/chats.py` (create/patch/send)
- Modify: `src/capybara/main.py:31-36` (register the models router)
- Modify: `tests/test_chats_api.py` (create chats with a model; new PATCH/models/409/502 tests)

**Interfaces:**
- Consumes: `get_agent`, `get_owned_chat`, `get_chat_repo`, `get_current_user`; `ModelsOut`, `ChatUpdate`, `ChatCreate.model`, `ChatOut.model`; `ModelUnavailableError`, `ModelProviderError`; `ChatService.begin_turn -> (model, history)`.
- Produces: `GET /models -> ModelsOut`; `PATCH /chats/{chat_id} -> ChatOut`; `POST /chats` accepting `model`.

- [ ] **Step 1: Write the failing endpoint tests**

Add these to `tests/test_chats_api.py`. They rely on the `client` fixture's `FakeAgent`, whose `list_models()` returns `["test-model"]`. Import `ModelProviderError` at the top alongside the existing `support` import:

```python
from support import FakeAgent, PartialThenFailAgent, RaisingAgent  # noqa: F401  (PartialThenFail may be unused)
```

Tests:

```python
async def test_list_models_returns_provider_list(client: AsyncClient) -> None:
    resp = await client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["models"] == ["test-model"]


async def test_list_models_502_when_provider_unreachable(
    client: AsyncClient, settings: Settings
) -> None:
    from capybara.agent import ModelProviderError

    class DownAgent(FakeAgent):
        async def list_models(self) -> list[str]:
            raise ModelProviderError(settings.ollama_base_url)

    app.dependency_overrides[get_agent] = lambda: DownAgent(settings, "x")
    resp = await client.get("/models")
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


async def test_patch_chat_model_sets_and_validates(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]

    ok = await client.patch(f"/chats/{chat_id}", json={"model": "test-model"})
    assert ok.status_code == 200
    assert ok.json()["model"] == "test-model"

    bad = await client.patch(f"/chats/{chat_id}", json={"model": "ghost:1b"})
    assert bad.status_code == 409


async def test_create_chat_with_unknown_model_409(client: AsyncClient) -> None:
    resp = await client.post("/chats", json={"title": "c", "model": "ghost:1b"})
    assert resp.status_code == 409


async def test_send_without_model_returns_409(client: AsyncClient) -> None:
    """A chat with no model selected is rejected up front, not via an SSE error."""
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]  # no model
    resp = await client.post(f"/chats/{chat_id}/messages", json={"content": "Привет"})
    assert resp.status_code == 409
    assert "available" in resp.json()["detail"].lower()
```

Also update the existing send tests so their chats have a valid model. In `test_send_message_streams_sse_and_persists` (line ~80), `test_send_empty_message_returns_422` (line ~106), and `test_send_message_stream_error_is_generic` (line ~115), change the chat creation to include the model:

```python
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_chats_api.py -v`
Expected: FAIL — `GET /models` and `PATCH /chats/{id}` don't exist; send-without-model still tries to stream.

- [ ] **Step 3: Create the models router**

Create `src/capybara/api/routers/models.py`:

```python
"""Router for listing available LLM models."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.base import BaseAgent, ModelProviderError
from capybara.api.dependencies import get_agent, get_current_user
from capybara.api.schemas import ModelsOut
from capybara.db.models import User

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsOut)
async def list_models(
    _user: Annotated[User, Depends(get_current_user)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ModelsOut:
    """Return the models currently available from the provider (Ollama)."""
    try:
        names = await agent.list_models()
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return ModelsOut(provider="ollama", models=names)
```

- [ ] **Step 4: Register the router**

In `src/capybara/main.py`, update the import and wiring in `create_app` (lines 31-36):

```python
    from capybara.api.routers import auth, chats, health, models, users

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(chats.router)
    fastapi_app.include_router(models.router)
    fastapi_app.include_router(users.router)
    fastapi_app.include_router(auth.router)
```

- [ ] **Step 5: Add create-with-model, PATCH, and error mapping in the chats router**

In `src/capybara/api/routers/chats.py`:

Add imports near the top (extend the existing dependency and error imports):

```python
from capybara.agent.base import BaseAgent, ModelProviderError, ModelUnavailableError
from capybara.api.dependencies import get_agent  # add to the existing dependencies import block
from capybara.api.schemas import ChatUpdate  # add to the existing schemas import block
```

Add a small helper after `_sse` (line 76) to map model errors uniformly:

```python
def _raise_for_model_error(exc: ModelUnavailableError | ModelProviderError) -> None:
    """Translate a model error into the matching HTTP error."""
    if isinstance(exc, ModelProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
```

Replace `create_chat` (lines 38-46) to validate an optional model:

```python
@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatOut:
    """Create a new chat for the current user, optionally with a validated model."""
    if payload.model is not None:
        try:
            await agent.ensure_available(payload.model)
        except (ModelUnavailableError, ModelProviderError) as exc:
            _raise_for_model_error(exc)
    chat = await chats.create(user.id, payload.title, payload.model)
    return ChatOut.model_validate(chat)
```

Add a PATCH endpoint after `get_chat` (after line 72):

```python
@router.patch("/{chat_id}", response_model=ChatOut)
async def update_chat_model(
    payload: ChatUpdate,
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatOut:
    """Set the chat's model after validating it is installed; 404 if not owned."""
    try:
        await agent.ensure_available(payload.model)
    except (ModelUnavailableError, ModelProviderError) as exc:
        _raise_for_model_error(exc)
    updated = await chats.update(chat, model=payload.model)
    return ChatOut.model_validate(updated)
```

Update `send_message` (lines 92-101) to catch model errors from `begin_turn` and thread the model into the stream:

```python
    try:
        model, history = await service.begin_turn(user.id, chat_id, payload.content)
    except ChatNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        ) from None
    except (ModelUnavailableError, ModelProviderError) as exc:
        _raise_for_model_error(exc)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, model, payload.content, history):
```

(The rest of `event_stream` is unchanged.)

- [ ] **Step 6: Run the chats API suite**

Run: `uv run pytest tests/test_chats_api.py -v`
Expected: PASS for all — listing, PATCH validation, 409 for unset/unknown model, 502 for provider down, and the existing stream tests (now creating chats with `test-model`).

- [ ] **Step 7: Run the full backend suite + gates**

```bash
uv run pytest
uv run ruff format . && uv run ruff check . && uv run mypy src
```
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/capybara/api/routers/models.py src/capybara/api/routers/chats.py \
  src/capybara/main.py tests/test_chats_api.py
git commit -m "feat: GET /models, PATCH /chats/{id}, and clear model-error statuses"
```

---

### Task 5: Frontend API layer — types, chatApi, and a models hook

**Files:**
- Modify: `frontend/src/api/types.ts` (`ChatOut.model`, `ModelsOut`)
- Modify: `frontend/src/chat/chatApi.ts` (`listModels`, `patchChatModel`, `createChat` with model)
- Create: `frontend/src/chat/useModels.ts`
- Create: `frontend/src/chat/chatApi.test.tsx`

**Interfaces:**
- Produces:
  - `interface ModelsOut { provider: string; models: string[] }`; `ChatOut.model: string | null`.
  - `listModels(api) => Promise<ModelsOut>`; `patchChatModel(api, id, model) => Promise<ChatOut>`; `createChat(api, title?, model?) => Promise<ChatOut>`.
  - `useModels() => { models: string[]; reloadModels: () => Promise<void> }`.

- [ ] **Step 1: Write the failing chatApi test**

Create `frontend/src/chat/chatApi.test.tsx`:

```tsx
import { describe, expect, test, vi } from 'vitest'
import { createChat, listModels, patchChatModel } from './chatApi'
import type { ApiClient } from '../api/client'

function fakeApi(): ApiClient & { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; patch: ReturnType<typeof vi.fn> } {
  return {
    get: vi.fn().mockResolvedValue({ provider: 'ollama', models: ['llama3.1:8b'] }),
    post: vi.fn().mockResolvedValue({ id: 'c1' }),
    patch: vi.fn().mockResolvedValue({ id: 'c1', model: 'llama3.1:8b' }),
    stream: vi.fn(),
  } as never
}

describe('chatApi model calls', () => {
  test('listModels GETs /models', async () => {
    const api = fakeApi()
    const out = await listModels(api)
    expect(api.get).toHaveBeenCalledWith('/models')
    expect(out.models).toEqual(['llama3.1:8b'])
  })

  test('createChat sends title and model', async () => {
    const api = fakeApi()
    await createChat(api, 'Hi', 'llama3.1:8b')
    expect(api.post).toHaveBeenCalledWith('/chats', { title: 'Hi', model: 'llama3.1:8b' })
  })

  test('patchChatModel PATCHes the chat', async () => {
    const api = fakeApi()
    await patchChatModel(api, 'c1', 'llama3.1:8b')
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { model: 'llama3.1:8b' })
  })
})
```

- [ ] **Step 2: Add a `patch` method to the API client**

In `frontend/src/api/client.ts`, add `patch` to the `ApiClient` interface (after `post`):

```ts
  post<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body?: unknown): Promise<T>
```

and to the returned object (after the `post` entry):

```ts
    patch: (path, body) =>
      json(path, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
```

- [ ] **Step 3: Extend the types**

In `frontend/src/api/types.ts`, add `model` to `ChatOut` and a `ModelsOut` interface:

```ts
export interface ChatOut {
  id: string
  title: string
  model: string | null
  created_at: string
  updated_at: string
}

export interface ModelsOut {
  provider: string
  models: string[]
}
```

- [ ] **Step 4: Extend chatApi**

Replace `frontend/src/chat/chatApi.ts` with:

```ts
import type { ApiClient } from '../api/client'
import type { ChatDetailOut, ChatOut, ModelsOut } from '../api/types'

export const listChats = (api: ApiClient) => api.get<ChatOut[]>('/chats')
export const createChat = (api: ApiClient, title?: string, model?: string) =>
  api.post<ChatOut>('/chats', { title: title ?? null, model: model ?? null })
export const getChat = (api: ApiClient, id: string) =>
  api.get<ChatDetailOut>(`/chats/${id}`)
export const listModels = (api: ApiClient) => api.get<ModelsOut>('/models')
export const patchChatModel = (api: ApiClient, id: string, model: string) =>
  api.patch<ChatOut>(`/chats/${id}`, { model })
```

- [ ] **Step 5: Create the models hook**

Create `frontend/src/chat/useModels.ts`:

```ts
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import { listModels } from './chatApi'

/** Fetch the provider's available model names once, with a manual reload. */
export function useModels() {
  const api = useApiClient()
  const [models, setModels] = useState<string[]>([])

  const reloadModels = useCallback(async () => {
    try {
      const out = await listModels(api)
      setModels(out.models)
    } catch {
      setModels([])
    }
  }, [api])

  useEffect(() => {
    void reloadModels()
  }, [reloadModels])

  return { models, reloadModels }
}
```

- [ ] **Step 6: Run the frontend test**

Run (in `frontend/`): `npm run test -- chatApi`
Expected: PASS.

- [ ] **Step 7: Update the existing useChats to pass a model through newChat**

In `frontend/src/chat/useChats.ts`, change `newChat` to accept an optional model:

```ts
  const newChat = useCallback(
    async (model?: string) => {
      const chat = await createChat(api, undefined, model)
      setChats((prev) => [chat, ...prev])
      return chat
    },
    [api],
  )
```

- [ ] **Step 8: Lint, build, commit**

```bash
cd frontend && npm run lint && npm run build
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/chat/chatApi.ts \
  frontend/src/chat/chatApi.test.tsx frontend/src/chat/useModels.ts frontend/src/chat/useChats.ts
git commit -m "feat(frontend): model list types, chatApi, and useModels hook"
```

---

### Task 6: Composer model selector

Adds the dropdown to the composer's bottom row next to the paperclip, and disables send when no valid model is selected.

**Files:**
- Modify: `frontend/src/components/Composer.tsx`
- Modify: `frontend/src/components/Composer.module.css`
- Modify: `frontend/src/components/Composer.test.tsx`

**Interfaces:**
- Produces: `Composer` gains props `models: string[]`, `selectedModel: string | null`, `onSelectModel: (m: string) => void`. Send is disabled unless `selectedModel` is non-null AND in `models`. Existing callers pass the new props (Task 7).

- [ ] **Step 1: Write the failing composer tests**

Replace `frontend/src/components/Composer.test.tsx` with:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Composer } from './Composer'

const MODELS = ['llama3.1:8b', 'qwen2.5:14b']

test('submits on Enter and clears', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={vi.fn()} />)
  const box = screen.getByRole('textbox')
  await userEvent.type(box, 'Привет{Enter}')
  expect(onSend).toHaveBeenCalledWith('Привет')
  expect(box).toHaveValue('')
})

test('does not submit empty input', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), '{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})

test('blocks send when no valid model is selected', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel={null} onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(onSend).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Отправить')).toBeDisabled()
})

test('blocks send when selected model is not in the list', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="removed:1b" onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})

test('selecting a model calls onSelectModel', async () => {
  const onSelectModel = vi.fn()
  render(<Composer onSend={vi.fn()} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={onSelectModel} />)
  await userEvent.selectOptions(screen.getByRole('combobox'), 'qwen2.5:14b')
  expect(onSelectModel).toHaveBeenCalledWith('qwen2.5:14b')
})
```

- [ ] **Step 2: Run to verify failure**

Run (in `frontend/`): `npm run test -- Composer`
Expected: FAIL — `Composer` doesn't accept `models`/`selectedModel`/`onSelectModel` and has no combobox.

- [ ] **Step 3: Implement the selector in Composer**

Replace `frontend/src/components/Composer.tsx` with:

```tsx
/** Message composer: auto-growing textarea, model selector, paperclip (visual), send. */
import { useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Paperclip } from 'lucide-react'
import styles from './Composer.module.css'

/**
 * Textarea + model selector + send button.
 *
 * Send is enabled only when there is non-empty text AND a valid model is selected
 * (`selectedModel` is set and present in `models`). An unselected or stale model
 * (removed from Ollama) highlights the selector and disables send.
 */
export function Composer({
  onSend,
  disabled,
  initialText,
  models,
  selectedModel,
  onSelectModel,
}: {
  onSend: (t: string) => void
  disabled?: boolean
  initialText?: string
  models: string[]
  selectedModel: string | null
  onSelectModel: (m: string) => void
}) {
  const [value, setValue] = useState(initialText ?? '')
  const ref = useRef<HTMLTextAreaElement>(null)

  const modelValid = selectedModel !== null && models.includes(selectedModel)
  const canSend = !disabled && modelValid

  function submit() {
    const text = value.trim()
    if (!text || !canSend) return
    onSend(text)
    setValue('')
    if (ref.current) ref.current.style.height = 'auto'
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <div className={styles.composer}>
      <textarea
        ref={ref}
        className={styles.input}
        value={value}
        rows={1}
        placeholder="Спросите что-нибудь…"
        onChange={(e) => {
          setValue(e.target.value)
          e.target.style.height = 'auto'
          e.target.style.height = `${e.target.scrollHeight}px`
        }}
        onKeyDown={onKeyDown}
      />
      <div className={styles.row}>
        <button type="button" className={styles.iconBtn} disabled tabIndex={-1} aria-hidden="true">
          <Paperclip size={18} />
        </button>
        <select
          className={`${styles.modelSelect} ${modelValid ? '' : styles.modelSelectInvalid}`}
          aria-label="Модель"
          value={modelValid ? (selectedModel as string) : ''}
          onChange={(e) => onSelectModel(e.target.value)}
        >
          <option value="" disabled>
            Выберите модель
          </option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <div className={styles.spacer} />
        <button
          type="button"
          className={styles.send}
          aria-label="Отправить"
          onClick={submit}
          disabled={!canSend}
        >
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Style the selector**

Append to `frontend/src/components/Composer.module.css`:

```css
.modelSelect {
  height: 31px;
  max-width: 200px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-family: inherit;
  padding: 0 8px;
  cursor: pointer;
  outline: none;
}

.modelSelect:hover {
  background: rgba(255, 255, 255, 0.06);
}

.modelSelectInvalid {
  border-color: var(--accent);
  color: var(--accent);
}

.modelSelect option {
  color: #241a12;
}
```

- [ ] **Step 5: Run the composer tests**

Run (in `frontend/`): `npm run test -- Composer`
Expected: PASS for all five.

- [ ] **Step 6: Lint, commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/Composer.tsx frontend/src/components/Composer.module.css \
  frontend/src/components/Composer.test.tsx
git commit -m "feat(frontend): model selector in the composer, send gated on a valid model"
```

---

### Task 7: Wire per-chat model selection into ChatScreen

Fetches the model list, tracks the current chat's model, PATCHes on change, blocks send until valid, and passes the model to new-chat creation.

**Files:**
- Modify: `frontend/src/screens/ChatScreen.tsx`
- Create: `frontend/src/chat/lastModel.ts` (localStorage helper)
- Modify: `frontend/src/screens/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `useModels()`, `Composer` model props, `patchChatModel`, `useChats().newChat(model?)`, `ChatOut.model`.
- Produces: `loadLastModel() => string | null`, `saveLastModel(m: string) => void`.

- [ ] **Step 1: Create the localStorage helper**

Create `frontend/src/chat/lastModel.ts`:

```ts
const KEY = 'capybara.lastModel'

/** Read the last-used model name from localStorage, or null if unset/unavailable. */
export function loadLastModel(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Persist the last-used model name for pre-selecting new chats. */
export function saveLastModel(model: string): void {
  try {
    localStorage.setItem(KEY, model)
  } catch {
    // ignore storage failures — pre-selection is a convenience, not a requirement
  }
}
```

- [ ] **Step 2: Write the failing ChatScreen test**

Add to `frontend/src/screens/ChatScreen.test.tsx` a test that the composer shows the fetched models and reflects an active chat's model. Use the existing test's render/provider setup as the pattern (mock `/models`, `/chats`). Add:

```tsx
test('composer lists fetched models and blocks send until one is valid', async () => {
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([])),
  )
  renderChatScreen() // existing helper in this test file that mounts <ChatScreen/> with auth+api providers

  // The selector is present with the fetched option.
  const select = await screen.findByRole('combobox', { name: 'Модель' })
  expect(within(select).getByRole('option', { name: 'llama3.1:8b' })).toBeInTheDocument()

  // With nothing selected yet, send is disabled.
  expect(screen.getByLabelText('Отправить')).toBeDisabled()

  // Selecting the model enables send.
  await userEvent.selectOptions(select, 'llama3.1:8b')
  expect(screen.getByLabelText('Отправить')).toBeEnabled()
})
```

> If `ChatScreen.test.tsx` has no `renderChatScreen`/`within` import yet, add `within` to the `@testing-library/react` import and reuse whatever provider-wrapping helper the file already defines for mounting `ChatScreen`. Match the file's existing msw setup style.

- [ ] **Step 3: Run to verify failure**

Run (in `frontend/`): `npm run test -- ChatScreen`
Expected: FAIL — `ChatScreen` does not yet render the selector or wire the model.

- [ ] **Step 4: Wire the model state into ChatScreen**

In `frontend/src/screens/ChatScreen.tsx`:

Add imports:

```tsx
import { useApiClient } from '../auth/AuthContext'
import { useModels } from '../chat/useModels'
import { patchChatModel } from '../chat/chatApi'
import { loadLastModel, saveLastModel } from '../chat/lastModel'
```

Inside the component, after the existing hooks, add:

```tsx
  const api = useApiClient()
  const { models } = useModels()
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
```

Compute the model shown by the composer — the active chat's stored model when a chat is open, otherwise the draft (for a not-yet-created chat):

```tsx
  const activeChat = chats.find((c) => c.id === activeChatId)
  const selectedModel = activeChatId ? (activeChat?.model ?? null) : draftModel
```

(Replace the existing `const activeChat = ...` line near the bottom with the pair above, and remove the old duplicate.)

Add the change handler:

```tsx
  /**
   * Change the model. For an active chat this PATCHes the chat and reloads the list so
   * `activeChat.model` reflects the new value; with no chat yet it updates the local draft
   * (persisted for next time) that will be passed to `newChat` on first send.
   */
  async function handleSelectModel(model: string) {
    saveLastModel(model)
    if (activeChatId) {
      await patchChatModel(api, activeChatId, model)
      await reload()
    } else {
      setDraftModel(model)
    }
  }
```

Pass the draft model into new-chat creation in `handleSend`:

```tsx
    if (!id) {
      const chat = await newChat(draftModel ?? undefined)
      id = chat.id
```

Finally, pass the three model props to BOTH `<Composer>` usages (welcome and active):

```tsx
              <Composer
                key={composerKey}
                onSend={handleSend}
                disabled={sending}
                initialText={chipText}
                models={models}
                selectedModel={selectedModel}
                onSelectModel={handleSelectModel}
              />
```

and

```tsx
                <Composer
                  onSend={handleSend}
                  disabled={sending}
                  models={models}
                  selectedModel={selectedModel}
                  onSelectModel={handleSelectModel}
                />
```

- [ ] **Step 5: Run the ChatScreen suite**

Run (in `frontend/`): `npm run test -- ChatScreen`
Expected: PASS. If pre-existing ChatScreen tests now render a `Composer` that needs a `/models` mock, add `http.get('/api/models', ...)` to their msw handlers so the selector has options.

- [ ] **Step 6: Run the whole frontend suite + gates**

```bash
cd frontend && npm run test -- --run && npm run lint && npm run build
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/ChatScreen.tsx frontend/src/screens/ChatScreen.test.tsx \
  frontend/src/chat/lastModel.ts
git commit -m "feat(frontend): per-chat model selection wired into the chat screen"
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
cd frontend && npm run test -- --run && npm run lint && npm run build
```
Expected: all pass.

- [ ] **Step 3: Manual smoke (optional, requires Ollama on host)**

Run `docker compose up --build`, then:
- `GET /models` returns the installed models (or 502 with a clear message if Ollama is down).
- Create a chat, PATCH its model to an installed one, send a message → SSE streams.
- PATCH to a non-installed model → 409; send with no model → 409 (clear, not the old opaque stream error).

- [ ] **Step 4: Final commit if anything adjusted**

```bash
git add -A && git commit -m "chore: model selection full-stack verification"
```

---

## Self-Review

**Spec coverage:**
- Provider abstraction (`list_models`, `_build_model`, `stream_reply(model_name)`) → Task 2. ✅
- `GET /models` with 502 on Ollama-down → Task 4 (router) + Task 2 (`ModelProviderError`). ✅
- `PATCH /chats/{id}` with 409 on unknown model → Task 4. ✅
- `POST /chats` accepts model → Task 1 (schema/repo) + Task 4 (validation). ✅
- `ChatOut`/`ChatDetailOut` gain `model` → Task 1 (`ChatDetailOut` inherits `ChatOut`). ✅
- `chats.model` column + migration → Task 1. ✅
- Up-front validation → `ModelUnavailableError`, no user message written, mapped to 409 before SSE → Task 3 + Task 4. ✅
- `default_model` no longer a server fallback → Tasks 2–3 remove all use of it in agent/service; conftest still sets it harmlessly. ✅
- Composer selector next to paperclip, send gated on valid model → Task 6. ✅
- Fetch `/models`, read `chat.model`, block on null/absent, PATCH on change, new-chat via localStorage → Task 7. ✅
- API layer `listModels`/`patchChatModel`/`createChat(model)` + types → Task 5. ✅
- Tests both sides → Tasks 2–7. ✅

**Placeholder scan:** No TBD/TODO. The only conditional instructions (Task 7 Step 2/5 about reusing the test file's existing render helper) are explicit, because that helper's exact name depends on the current `ChatScreen.test.tsx`; the executor is told precisely what to match.

**Type consistency:** `begin_turn -> tuple[str, list[ModelMessage]]` produced in Task 3 and consumed as `model, history = ...` in Task 4. `stream_turn(chat_id, model_name, user_content, history)` consistent across Tasks 3–4. `ensure_available(model_name: str | None)` consistent across Tasks 2–4. `ChatRepo.create(user_id, title, model)` consistent Tasks 1/4. Frontend `Composer` props (`models`, `selectedModel`, `onSelectModel`) consistent Tasks 6–7. `createChat(api, title?, model?)` / `newChat(model?)` consistent Tasks 5/7. `ModelsOut{provider, models}` consistent backend (Task 1) and frontend (Task 5).
