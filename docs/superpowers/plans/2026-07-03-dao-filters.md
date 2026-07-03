# DAO Filters + Default Ordering + TimestampMixin — Plan

> Execute via subagent-driven-development. Two atomic tasks; the full suite stays green + ruff + strict mypy clean after each. Behavior of existing queries is preserved; the only schema change is additive (`updated_at` on users/messages).

**Goal:** Remove repetitive `select(...).where(...).order_by(...)` from repositories by introducing (1) Superset-style `Filter` classes, (2) a default ordering in the DAO base (created_at ASC, overridable), (3) an (empty by default) default filter — and add a `TimestampMixin` (created_at + updated_at) shared by all models.

## Global Constraints

- Python >=3.12, strict mypy over `src`, ruff (incl. pydocstyle D — every module/class/function in `src` needs a docstring), uv.
- Behavior-preserving for existing query results: chat list stays scoped to the user and ordered `updated_at desc`; messages stay scoped to the chat and ordered by `seq`.
- Data access only in repositories; commit owned by the caller (repos flush). Layering unchanged.
- Migrations under `src/capybara/migrations/`, date-time filename template already active.

---

### Task DA: TimestampMixin for all models (+ migration for updated_at)

**Files:**
- Create: `src/capybara/db/mixins.py`
- Modify: `src/capybara/db/models/user.py`, `chat.py`, `message.py`
- Create: one Alembic migration (adds `updated_at` to `users` and `messages`)

**Mixin (`db/mixins.py`):**
```python
"""Reusable declarative mixins for models."""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds created_at/updated_at timezone-aware timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

**Models:** each becomes `class User(Base, TimestampMixin)`, `class Chat(Base, TimestampMixin)`, `class Message(Base, TimestampMixin)`. Remove the now-inherited timestamp columns from each model body:
- `User`: drop inline `created_at` (now from mixin); gains `updated_at` (new).
- `Chat`: drop inline `created_at` and `updated_at` (both now from mixin — same columns as before, no schema change for chats).
- `Message`: drop inline `created_at` (now from mixin); gains `updated_at` (new). Keep `seq`, `usage_json`, `incomplete`, etc. unchanged.

**Migration:** add `updated_at` to `users` and `messages` only (chats already has it). Column: `DateTime(timezone=True)`, `server_default=func.now()`, `nullable=False`. Fresh DB is empty so NOT NULL is safe; on a populated DB the server default backfills existing rows. Use the ephemeral-docker-Postgres autogenerate route (like prior migrations) OR hand-author; either way `alembic upgrade head` on a fresh DB must yield both `updated_at` columns. Do NOT leave a container running. The migration must NOT drop/recreate the chats timestamp columns — verify autogenerate only touches users/messages (edit the generated script if it tries to touch chats).

**Verify:** `uv run pytest -v` (all green; models still map — `test_models.py`/`test_migrations.py` pass), `uv run ruff check .`, `uv run mypy src`. Commit: `feat: TimestampMixin (created_at/updated_at) for all models`.

---

### Task DB: Filter classes + default ordering/filter in DAO base

**Files:**
- Create: `src/capybara/repositories/filters.py`
- Modify: `src/capybara/repositories/base.py`, `chat_repo.py`, `message_repo.py`, `__init__.py`
- Modify: `src/capybara/api/routers/chats.py`, `src/capybara/services/chat_service.py`
- Modify tests: `tests/test_repositories.py` (+ any test using the removed domain methods)

**Filters (`filters.py`):**
```python
"""Composable query filters for repositories."""
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement

from capybara.db.base import Base


class Filter(ABC):
    """A reusable query filter that yields a SQLAlchemy WHERE criterion."""

    @abstractmethod
    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Return the SQLAlchemy boolean criterion for the given model."""


class FieldEquals(Filter):
    """Filter rows where a named column equals a value."""

    def __init__(self, field: str, value: Any) -> None:
        self._field = field
        self._value = value

    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Build `model.<field> == value`."""
        return getattr(model, self._field) == self._value


class OwnedByUser(Filter):
    """Filter rows owned by a given user (`model.user_id == user_id`)."""

    def __init__(self, user_id: UUID) -> None:
        self._user_id = user_id

    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Build `model.user_id == user_id`."""
        return getattr(model, "user_id") == self._user_id
```

**BaseRepository additions (`base.py`):**
- `default_filters: ClassVar[Sequence[Filter]] = ()` (point 3 — none by default).
- overridable ordering:
```python
def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
    """Default result ordering — chronological by creation time; override per repo."""
    return (self.model.created_at.asc(),)  # type: ignore[attr-defined]  # all models carry created_at via TimestampMixin
```
  (Try to avoid the ignore if a clean typed path exists given the mixin; a single narrow, commented ignore is acceptable.)
- extend `list` to accept filters:
```python
async def list(self, *filters: Filter) -> list[ModelT]:
    """List rows matching default + given filters, in the repo's default order."""
    stmt = select(self.model)
    for query_filter in (*self.default_filters, *filters):
        stmt = stmt.where(query_filter.to_criterion(self.model))
    stmt = stmt.order_by(*self._default_order_by())
    result = await self._session.execute(stmt)
    return list(result.scalars().all())
```

**Subclasses:**
- `ChatRepo`: override `_default_order_by` → `(Chat.updated_at.desc(),)`; REMOVE `list_for_user`. Keep `touch` and the `create(user_id, title=None)` override.
- `MessageRepo`: override `_default_order_by` → `(Message.seq.asc(),)`; REMOVE `list_for_chat`.
- `UserRepo`: unchanged (inherits created_at asc default).
- `__init__.py`: also re-export `Filter`, `FieldEquals`, `OwnedByUser`.

**Call sites (preserve behavior):**
- `api/routers/chats.py` `list_chats`: `rows = await chats.list(OwnedByUser(user.id))`.
- `api/routers/chats.py` `get_chat`: `rows = await messages.list(FieldEquals("chat_id", chat_id))`.
- `services/chat_service.py` `stream_turn`: replace `self._messages.list_for_chat(chat_id)` with `self._messages.list(FieldEquals("chat_id", chat_id))`.

**Tests:** update `tests/test_repositories.py`:
- Replace `ChatRepo(...).list_for_user(uid)` with `ChatRepo(...).list(OwnedByUser(uid))` — keep the ordering assertion (updated_at desc) and the scoping assertion.
- Replace `MessageRepo(...).list_for_chat(cid)` with `MessageRepo(...).list(FieldEquals("chat_id", cid))` — keep the seq-ordering assertion.
- Add: a test that `UserRepo(...).list()` orders by `created_at` ASC (create two users, assert order); a test that `list(FieldEquals(...))` scopes correctly. Keep assertions meaningful.
Any other test that used the removed domain methods (via API/service) must still pass — the API/service call sites are updated, so `test_chats_api.py`/`test_chat_service.py` should remain green without edits, but verify.

**Verify:** `uv run pytest -v` (all green), `uv run ruff check .` (D rules satisfied — docstrings on all new code), `uv run mypy src`. Commit: `feat: Superset-style filters + default ordering/filter in DAO base`.

---

## Notes
- DA before DB.
- Future (NOT now): an audit mixin with `created_by`/`updated_by` — user flagged as a later idea.
- After both: final whole-branch review over the DA..DB range.
