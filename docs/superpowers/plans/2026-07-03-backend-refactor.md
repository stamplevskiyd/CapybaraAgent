# Backend Refactor Implementation Plan (slice 1 hardening)

> **For agentic workers:** execute task-by-task via superpowers:subagent-driven-development. These are refactors of existing code — the 18-test suite is the safety net. Behavior must not change; every task ends with the FULL suite green, ruff clean, mypy strict clean.

**Goal:** Apply 5 structural improvements to the chat-core backend: split models into a package, introduce a generic DAO base repository, introduce a base agent class, date-time migration filenames, and enforce docstrings.

**Architecture:** Same layered `api → services → repositories → db` + `agent/`. These changes deepen the reusable abstractions the project will extend on.

**Tech Stack:** Python 3.12, FastAPI, pydantic-ai 2.3.0, SQLAlchemy 2.0 async, Alembic, uv, ruff, strict mypy.

## Global Constraints

- Behavior-preserving refactor: the existing 18 tests must stay green (adjust only tests whose imports/interfaces change; do not weaken assertions). `uv run pytest -v`, `uv run ruff check .`, `uv run mypy src` all pass after every task.
- Python >=3.12, fully type-annotated, strict mypy over `src`. uv; ruff; mypy strict. Package root `src/capybara/`.
- Data access only in repositories; LLM only via the agent module; one async session per request; commit owned by the caller (repos use `flush`).
- Docker: Ollama on host; provider-agnostic design preserved.

---

### Task 1: Split `models.py` into a `db/models/` package

**Files:**
- Delete: `src/capybara/db/models.py`
- Create: `src/capybara/db/models/__init__.py`, `src/capybara/db/models/user.py`, `src/capybara/db/models/chat.py`, `src/capybara/db/models/message.py`

**What to do:**
- Move each model to its own file (`User`→user.py, `Chat`→chat.py, `Message`→message.py), unchanged field-for-field (including the `seq` identity column and all indexes/defaults).
- Cross-file relationships use string targets (`relationship(back_populates=...)` with `Mapped[list["Message"]]`); add `if TYPE_CHECKING:` imports for the referenced classes so strict mypy resolves the annotations without runtime circular imports. Use `from __future__ import annotations` where helpful.
- `db/models/__init__.py` re-exports all three: `from capybara.db.models.user import User` etc., with `__all__ = ["User", "Chat", "Message"]`, so `from capybara.db.models import User, Chat, Message` and Alembic's `from capybara.db import models` (registering tables on `Base.metadata`) keep working.

**Verification:** `uv run pytest -v` (all green — imports resolve, migrations test still passes), `uv run ruff check .`, `uv run mypy src`. Commit: `refactor: split models into db/models package`.

---

### Task 2: Generic DAO base repository

**Files:**
- Create: `src/capybara/repositories/base.py`
- Modify: `src/capybara/repositories/user_repo.py`, `chat_repo.py`, `message_repo.py`, `__init__.py`
- Modify: `src/capybara/services/chat_service.py` (calls that used `MessageRepo.add(...)`)
- Modify tests that construct/use repos as needed (keep assertions).

**Base class (`base.py`):**
```python
from typing import Any, Generic, TypeVar
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from capybara.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)

class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id_: UUID) -> ModelT | None:
        return await self._session.get(self.model, id_)

    async def list(self) -> list[ModelT]:
        result = await self._session.execute(select(self.model))
        return list(result.scalars().all())

    async def create(self, **fields: Any) -> ModelT:
        instance = self.model(**fields)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def add(self, instance: ModelT) -> ModelT:
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, instance: ModelT, **fields: Any) -> ModelT:
        for key, value in fields.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self._session.delete(instance)
        await self._session.flush()
```
- If mypy strict complains about `self.model(**fields)` (generic constructor), resolve cleanly (e.g. a narrowly-scoped `# type: ignore[call-arg]` with a comment) — do not loosen types elsewhere.

**Subclasses:**
- `UserRepo(BaseRepository[User])`: `model = User`. (Inherited `get` covers current usage.)
- `ChatRepo(BaseRepository[Chat])`: `model = Chat`; keep domain methods:
  - `list_for_user(user_id: UUID) -> list[Chat]` (order by `updated_at desc`)
  - `touch(chat: Chat) -> None`
  - thin override `create(self, user_id: UUID, title: str | None = None) -> Chat` that preserves "title None → model default": build fields `{"user_id": user_id}` and add `title` only if not None, then call `super().create(**fields)`.
- `MessageRepo(BaseRepository[Message])`: `model = Message`; keep `list_for_chat(chat_id: UUID) -> list[Message]` (order by `seq`). Remove the bespoke `add(...)`; callers now use generic `create(**fields)`.
- `__init__.py` re-exports `BaseRepository`, `UserRepo`, `ChatRepo`, `MessageRepo`.

**ChatService change:** replace `self._messages.add(chat_id, "user", user_content)` with `self._messages.create(chat_id=chat_id, role="user", content=user_content)`, and the assistant persist with `self._messages.create(chat_id=chat_id, role="assistant", content=acc.text, model=acc.model, usage_json=acc.usage, incomplete=not completed)`. (Note the model field is `usage_json`.)

**Verification:** full suite green, ruff, mypy. Commit: `refactor: generic DAO base repository`.

---

### Task 3: Base agent class

**Files:**
- Create: `src/capybara/agent/base.py`
- Modify: `src/capybara/agent/ollama.py`, `src/capybara/agent/stream.py` (fold into base or re-export), `src/capybara/agent/__init__.py`
- Modify: `src/capybara/services/chat_service.py`, `src/capybara/api/dependencies.py`, `src/capybara/main.py`
- Modify tests: `tests/test_agent_stream.py`, `tests/test_chat_service.py`, `tests/test_chats_api.py` (+ a shared `FakeAgent` helper)

**Base class (`base.py`):** move `ReplyAccumulator` here; define
```python
class BaseAgent(ABC):
    def __init__(self, settings: Settings) -> None:
        self._agent: Agent[None, str] = Agent(self._create_model(settings))

    @abstractmethod
    def _create_model(self, settings: Settings) -> Model: ...

    @staticmethod
    def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]: ...  # move existing logic

    async def stream_reply(
        self, user_content: str, history: list[ModelMessage], acc: ReplyAccumulator
    ) -> AsyncIterator[str]: ...  # move existing stream logic (result.usage property, result.response.model_name)
```
Preserve the EXACT working streaming logic from the current `stream.py` (pydantic-ai 2.3.0: `run_stream` context manager, `stream_text(delta=True)`, `result.usage` property + `has_values()`, `result.response.model_name`). `Model` is imported from `pydantic_ai.models`.

**OllamaAgent (`ollama.py`):**
```python
class OllamaAgent(BaseAgent):
    def _create_model(self, settings: Settings) -> Model:
        return OpenAIChatModel(
            settings.default_model,
            provider=OpenAIProvider(base_url=f"{settings.ollama_base_url}/v1", api_key="ollama"),
        )
```
Remove the old module-level `build_agent`. `agent/__init__.py` re-exports `BaseAgent`, `OllamaAgent`, `ReplyAccumulator` (keep `to_model_messages`/`stream_reply` reachable if any test imports them, else drop).

**Wiring:**
- `ChatService.__init__(self, chats, messages, agent: BaseAgent)`; call `self._agent.to_model_messages(...)` and `self._agent.stream_reply(user_content, history, acc)`.
- `dependencies.get_agent(request) -> BaseAgent` (from `request.app.state.agent`); `get_chat_service` unchanged except the type.
- `main.py` lifespan: `app.state.agent = OllamaAgent(settings)`.

**Tests:** add a shared helper (e.g. `tests/support.py`):
```python
class FakeAgent(BaseAgent):
    def __init__(self, settings: Settings, output_text: str) -> None:
        self._output_text = output_text
        super().__init__(settings)
    def _create_model(self, settings: Settings) -> Model:
        return TestModel(custom_output_text=self._output_text)
```
Update `test_agent_stream.py` to exercise `FakeAgent(...).stream_reply(...)`/`BaseAgent.to_model_messages(...)`; `test_chat_service.py` and `test_chats_api.py` to build/override with `FakeAgent(settings, "...")` instead of `Agent(TestModel(...))`. Keep all assertions (deltas concat, acc.text/model/usage, roles/order, incomplete, SSE events).

**Verification:** full suite green, ruff, mypy. Commit: `refactor: base agent class with OllamaAgent subclass`.

---

### Task 4: Date-time migration filenames

**Files:**
- Modify: `alembic.ini`
- Rename: the 3 files under `src/capybara/migrations/versions/`

**What to do:**
- Add to `[alembic]` in `alembic.ini`:
  `file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev).12s_%%(slug)s`
- Rename the 3 existing migration files to `YYYYMMDD_HHMM_<rev>_<slug>.py`, taking the timestamp from each file's `Create Date:` header and the `<rev>`/slug from its revision id and message. Order must match the `down_revision` chain (initial schema → seed user → add messages.seq). Do NOT change any `revision`/`down_revision` identifiers or file contents — only the filenames. (Filenames don't affect Alembic's graph.)

**Verification:** `uv run pytest tests/test_migrations.py -v` (upgrade→head still works), full suite green, ruff. Confirm files sort chronologically by name. Commit: `chore: date-time prefixed migration filenames`.

---

### Task 5: Docstrings everywhere + ruff enforcement + CLAUDE.md rule

**Files:**
- Modify: `pyproject.toml` (ruff config), `CLAUDE.md`, and add docstrings across `src/capybara/**`.

**What to do:**
- Ruff: add `"D"` to `[tool.ruff.lint] select`; add `[tool.ruff.lint.pydocstyle] convention = "google"`; add `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["D"]` (don't require docstrings on every test). If a couple of D rules are genuinely counterproductive after applying (e.g. D105 magic methods, D107 `__init__`), you may ignore those specific codes with a one-line comment — but keep presence rules for modules/classes/public functions.
- Add a concise docstring to EVERY function/method/class/module in `src/capybara/**` describing what it does. Keep them short and accurate.
- CLAUDE.md: under "Architecture & conventions", add a rule: "Every function/method has a docstring stating what it does (enforced by ruff pydocstyle)."

**Verification:** `uv run ruff check .` clean (D rules now active and satisfied in src), full suite green, `uv run mypy src` clean. Commit: `style: docstrings across src + enforce via ruff pydocstyle`.

---

## Notes
- Do tasks in order 1→5; docstrings last so new files from tasks 1–3 are covered.
- After all tasks: run the final whole-branch review over the refactor range.
