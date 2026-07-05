# Memory (facts) — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend of the Memory slice — user-scoped `facts` with pgvector embeddings, a `recall` tool the agent can call mid-chat, a `/memory` CRUD + settings API, and gated post-stream auto-capture — all local-first against host Ollama.

**Architecture:** Layered as the rest of the app — `db/models` → `repositories` → `services` → `api/routers` + schemas, with embeddings/extraction behind the `agent/` seam. Retrieval lives behind `MemoryService.recall`, extraction behind `MemoryService.extract_and_store` (variant A: post-stream `BackgroundTask`), embeddings behind `BaseAgent.embed`, and tools behind a new `stream_reply(tools=…)` seam populated with only the recall tool this slice.

**Tech Stack:** Python 3.14, FastAPI + SSE, pydantic-ai 2.5, SQLAlchemy 2.0 async + Alembic, pgvector (`pgvector/pgvector:pg16`), uv, ruff + mypy (strict), pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-07-05-memory-facts-design.md` (frontend is a separate follow-up plan).

## Global Constraints

Every task's requirements implicitly include these:

- **Python 3.14**, fully type-annotated; **mypy strict** must pass (`uv run mypy src`).
- **ruff** lint + format must pass (`uv run ruff check .` / `uv run ruff format .`). Pydocstyle **google** convention is enforced (`select = D`): every module, class, and function/method needs a docstring. `tests/**` and `src/capybara/migrations/versions/**` are D-exempt.
- **Repository pattern**: all DB access via repositories; no ad-hoc queries in routers/services.
- **Sessions**: one async session per request via a dependency; services that stream/background own short-lived sessions from the app-wide sessionmaker. Commit/rollback boundaries explicit.
- **Provider-agnostic LLM**: embeddings + extraction go through `BaseAgent`; services never touch pydantic-ai directly.
- **Per-user isolation**: every fact query is scoped to `user_id`; user A can never see or mutate user B's facts.
- **Embedding dimensionality is 768** (`nomic-embed-text`). Define once as `EMBEDDING_DIM = 768`.
- **Category set is fixed**: `personal | project | preference`. **Source set**: `manual | auto`.
- **Local-first**: nothing leaves the device; Ollama is reached at `settings.ollama_base_url`.
- **TDD**: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- **Scoped staging**: `git add` only the files you touched — never `git add -A` (the user commits concurrently).

---

## File Structure

**New files:**
- `src/capybara/db/models/fact.py` — `Fact` ORM model (pgvector `Vector` column, HNSW + btree indexes, category/source check constraints).
- `src/capybara/repositories/fact_repo.py` — `FactRepo` (`create`, `get`, `list`, `update`, `delete` via base; `search` for cosine-nearest).
- `src/capybara/services/memory_service.py` — `MemoryService` (CRUD, `recall`, `extract_and_store`, auto-capture getters), `ExtractedFact`/`ExtractedFacts` schema, extraction prompt, `schedule_extraction` background entrypoint.
- `src/capybara/services/memory_tools.py` — `format_facts` + `make_recall_tool` (recall `Tool` closure).
- `src/capybara/api/routers/memory.py` — `/memory` router.
- `src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_add_facts_and_memory_toggle.py` — migration (extension, `facts` table, indexes, `users.memory_auto_capture`).

**Modified files:**
- `pyproject.toml` — add `pgvector` dep + mypy override.
- `docker-compose.yml` — Postgres image → `pgvector/pgvector:pg16`.
- `src/capybara/config.py` — memory settings.
- `src/capybara/db/models/user.py` — `memory_auto_capture` column.
- `src/capybara/db/models/__init__.py` — export `Fact`.
- `src/capybara/agent/base.py` — abstract `embed`, concrete `run_structured`, `stream_reply(tools=…)` + `CHAT_SYSTEM_PROMPT`.
- `src/capybara/agent/ollama.py` — `embed` implementation.
- `src/capybara/services/chat_service.py` — optional `memory_service`; `stream_turn(..., user_id=None)` assembles the recall tool.
- `src/capybara/api/dependencies.py` — `get_memory_service`, `get_fact_repo`, `get_owned_fact`; `get_chat_service` gains `memory_service`.
- `src/capybara/api/schemas.py` — `FactCreate`, `FactUpdate`, `FactOut`, `MemorySettingsOut`, `MemorySettingsUpdate`.
- `src/capybara/api/routers/chats.py` — `send_message` attaches the auto-capture `BackgroundTask`; both stream endpoints pass `user_id`.
- `src/capybara/main.py` — include the memory router.
- `tests/conftest.py` — testcontainers image + `CREATE EXTENSION vector` in the `engine` fixture.
- `tests/support.py` — agent doubles gain `embed`/`run_structured` support; `StubMemoryAgent`, `ToolCallingFakeAgent`.
- `tests/test_chats_api.py` — client fixture overrides `get_settings_dep`.
- `README.md` — embedding-model requirement + memory config.

---

## Task 1: Dependencies, Postgres image, and config

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml:3`
- Modify: `src/capybara/config.py:25-29`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.embedding_model: str`, `Settings.memory_recall_k: int`, `Settings.memory_recall_min_similarity: float`, `Settings.memory_dedup_threshold: float`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_config.py`:

```python
def test_memory_settings_have_defaults() -> None:
    from capybara.config import Settings

    s = Settings(jwt_secret="x" * 32)
    assert s.embedding_model == "nomic-embed-text"
    assert s.memory_recall_k == 5
    assert s.memory_recall_min_similarity == 0.3
    assert s.memory_dedup_threshold == 0.9
```

- [ ] **Step 2: Run it, verify failure**

Run: `uv run pytest tests/test_config.py::test_memory_settings_have_defaults -v`
Expected: FAIL (`AttributeError`/validation — fields don't exist).

- [ ] **Step 3: Add the settings** — in `src/capybara/config.py`, after the `jwt_algorithm` line (`config.py:29`) and before `model_config`:

```python
    embedding_model: str = "nomic-embed-text"
    memory_recall_k: int = 5
    memory_recall_min_similarity: float = 0.3
    memory_dedup_threshold: float = 0.9
```

- [ ] **Step 4: Add the pgvector dependency + mypy override** — in `pyproject.toml`, add `"pgvector>=0.3"` to the `[project].dependencies` list (after `"pyjwt>=2.13",`), and add a mypy override block next to the existing `testcontainers` one:

```toml
[[tool.mypy.overrides]]
module = ["pgvector.*"]
ignore_missing_imports = true
```

- [ ] **Step 5: Switch the Postgres image** — in `docker-compose.yml`, change line 3 from `    image: postgres:16` to `    image: pgvector/pgvector:pg16`.

- [ ] **Step 6: Sync and verify**

Run: `uv sync && uv run pytest tests/test_config.py -v && uv run mypy src`
Expected: PASS; pgvector installed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock docker-compose.yml src/capybara/config.py tests/test_config.py
git commit -m "feat(memory): add pgvector dep, pgvector postgres image, memory settings"
```

---

## Task 2: Fact model, users toggle, and test-DB extension

**Files:**
- Create: `src/capybara/db/models/fact.py`
- Modify: `src/capybara/db/models/user.py`
- Modify: `src/capybara/db/models/__init__.py`
- Modify: `tests/conftest.py:19-21`, `tests/conftest.py:41-49`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Fact(id, user_id, category, content, embedding, source, created_at, updated_at)`; module constants `FACT_CATEGORIES`, `FACT_SOURCES`, `EMBEDDING_DIM = 768`. `User.memory_auto_capture: Mapped[bool]` (default `True`).

- [ ] **Step 1: Switch the test container image + create the extension** — in `tests/conftest.py`:

Change the container (line 21) from `with PostgresContainer("postgres:16", driver="asyncpg") as pg:` to:

```python
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
```

And change the `engine` fixture body (lines 43-45) so the extension exists before `create_all` builds the HNSW index:

```python
    eng = create_engine(settings)
    async with eng.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
```

(`sa` is already imported in `conftest.py`.)

- [ ] **Step 2: Write the failing test** — append to `tests/test_models.py`:

```python
async def test_fact_model_persists_with_embedding(session: AsyncSession) -> None:
    from capybara.db.models import Fact, User
    from capybara.security.passwords import hash_password

    user = User(username="factuser", display_name="F", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    fact = Fact(
        user_id=user.id,
        category="personal",
        content="Пьёт чай без сахара",
        embedding=[0.1] * 768,
        source="manual",
    )
    session.add(fact)
    await session.flush()

    assert fact.id is not None
    assert fact.created_at is not None
    assert user.memory_auto_capture is True
```

(Ensure `from sqlalchemy.ext.asyncio import AsyncSession` is imported at the top of `test_models.py`; add it if missing.)

- [ ] **Step 2b: Run it, verify failure**

Run: `uv run pytest tests/test_models.py::test_fact_model_persists_with_embedding -v`
Expected: FAIL (`ImportError`: cannot import `Fact`).

- [ ] **Step 3: Create the Fact model** — `src/capybara/db/models/fact.py`:

```python
"""SQLAlchemy ORM model for the facts table (long-term memory)."""

from __future__ import annotations

from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

#: Fixed category set for a fact, coloured per the design handoff.
FACT_CATEGORIES: tuple[str, ...] = ("personal", "project", "preference")
#: How a fact was created: user-entered vs auto-captured from a conversation.
FACT_SOURCES: tuple[str, ...] = ("manual", "auto")
#: Embedding dimensionality — matches Ollama ``nomic-embed-text``.
EMBEDDING_DIM = 768

_CATEGORY_CHECK = ", ".join(f"'{c}'" for c in FACT_CATEGORIES)
_SOURCE_CHECK = ", ".join(f"'{s}'" for s in FACT_SOURCES)


class Fact(Base, TimestampMixin):
    """A single long-term memory fact owned by a user, with a vector embedding."""

    __tablename__ = "facts"
    # Short constraint labels only — the naming convention prefixes them
    # (``ck_facts_category`` / ``ix_facts_...``).
    __table_args__ = (
        CheckConstraint(f"category IN ({_CATEGORY_CHECK})", name="category"),
        CheckConstraint(f"source IN ({_SOURCE_CHECK})", name="source"),
        Index("ix_facts_user_id_created_at", "user_id", "created_at"),
        Index(
            "ix_facts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    source: Mapped[str] = mapped_column(String(16))
```

- [ ] **Step 4: Add the users toggle** — in `src/capybara/db/models/user.py`, add after the `password_hash` line (`user.py:20`):

```python
    memory_auto_capture: Mapped[bool] = mapped_column(default=True, nullable=False)
```

(No new imports needed — `Mapped`/`mapped_column` are already imported.)

- [ ] **Step 5: Export Fact** — replace `src/capybara/db/models/__init__.py` with:

```python
"""ORM model exports: User, Chat, Message, Fact."""

from capybara.db.models.chat import Chat
from capybara.db.models.fact import Fact
from capybara.db.models.message import Message
from capybara.db.models.user import User

__all__ = ["User", "Chat", "Message", "Fact"]
```

- [ ] **Step 6: Run test + type-check**

Run: `uv run pytest tests/test_models.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/capybara/db/models/fact.py src/capybara/db/models/user.py src/capybara/db/models/__init__.py tests/conftest.py tests/test_models.py
git commit -m "feat(memory): Fact model, users.memory_auto_capture, pgvector test extension"
```

---

## Task 3: Alembic migration

**Files:**
- Create: `src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_add_facts_and_memory_toggle.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: current head `d4d0cafe0004`.
- Produces: new head `e5d0cafe0005`; `facts` table + indexes; `users.memory_auto_capture` with `server_default true`; `vector` extension.

- [ ] **Step 1: Write the failing assertions** — append inside `test_migrations_create_schema_and_seed` in `tests/test_migrations.py`, after the existing index assertions (before the `with` block closes):

```python
        assert "facts" in set(tables)

        fact_cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'facts'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"embedding", "category", "source", "user_id"} <= set(fact_cols)

        user_cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "memory_auto_capture" in set(user_cols)

        fact_indexes = (
            (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'facts'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ix_facts_embedding_hnsw" in fact_indexes
        assert "ix_facts_user_id_created_at" in fact_indexes
```

- [ ] **Step 2: Run it, verify failure**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL (facts table/columns absent — migration not written).

- [ ] **Step 3: Write the migration** — create the file with this exact content:

```python
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
```

- [ ] **Step 4: Run migration test**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: PASS (upgrade + downgrade round-trip).

- [ ] **Step 5: Commit**

```bash
git add src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_add_facts_and_memory_toggle.py tests/test_migrations.py
git commit -m "feat(memory): alembic migration for facts table and memory_auto_capture"
```

---

## Task 4: FactRepo (CRUD + vector search)

**Files:**
- Create: `src/capybara/repositories/fact_repo.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Consumes: `BaseRepository[Fact]`, `Fact`, `FieldEquals`.
- Produces: `FactRepo(session)` with inherited `create(**fields)`, `get(id)`, `list(*filters)`, `update(instance, **fields)`, `delete(instance)`, and new `search(user_id: UUID, embedding: list[float], k: int) -> list[tuple[Fact, float]]` (returns `(fact, cosine_distance)` nearest-first, newest-first default `list` order).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_repositories.py`:

```python
async def test_fact_repo_search_returns_nearest_first(session: AsyncSession) -> None:
    from capybara.db.models import Fact
    from capybara.repositories.fact_repo import FactRepo

    user = await _seed_user(session)
    repo = FactRepo(session)
    # Three orthogonal-ish unit vectors in 768-space.
    near = [1.0] + [0.0] * 767
    mid = [0.6, 0.8] + [0.0] * 766
    far = [0.0, 1.0] + [0.0] * 766
    await repo.create(user_id=user.id, category="personal", content="near", embedding=near, source="manual")
    await repo.create(user_id=user.id, category="personal", content="mid", embedding=mid, source="manual")
    await repo.create(user_id=user.id, category="personal", content="far", embedding=far, source="manual")

    results = await repo.search(user.id, near, k=3)
    assert [fact.content for fact, _distance in results] == ["near", "mid", "far"]
    assert results[0][1] < results[-1][1]  # nearest has the smallest distance


async def test_fact_repo_search_is_user_scoped(session: AsyncSession) -> None:
    from capybara.db.models import Fact, User
    from capybara.repositories.fact_repo import FactRepo
    from capybara.security.passwords import hash_password

    user_a = await _seed_user(session)
    user_b = User(username="userb", display_name="B", password_hash=hash_password("password123"))
    session.add(user_b)
    await session.flush()

    vec = [1.0] + [0.0] * 767
    repo = FactRepo(session)
    await repo.create(user_id=user_b.id, category="personal", content="b-secret", embedding=vec, source="manual")

    results = await repo.search(user_a.id, vec, k=5)
    assert results == []
```

- [ ] **Step 2: Run them, verify failure**

Run: `uv run pytest tests/test_repositories.py -k fact_repo -v`
Expected: FAIL (`ImportError`: no `fact_repo`).

- [ ] **Step 3: Create the repository** — `src/capybara/repositories/fact_repo.py`:

```python
"""Repository for Fact CRUD and user-scoped vector search."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, select

from capybara.db.models import Fact
from capybara.repositories.base import BaseRepository


class FactRepo(BaseRepository[Fact]):
    """Repository for Fact rows: inherited CRUD plus cosine-nearest search."""

    model = Fact

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order facts newest-first for list views."""
        return (Fact.created_at.desc(),)

    async def search(
        self, user_id: UUID, embedding: list[float], k: int
    ) -> list[tuple[Fact, float]]:
        """Return the *k* nearest facts for *user_id* by cosine distance, nearest first.

        Each result is a ``(fact, distance)`` pair where ``distance`` is the pgvector
        cosine distance (``0`` identical, ``2`` opposite). Callers convert to similarity
        via ``1 - distance`` and apply their own threshold.
        """
        distance = Fact.embedding.cosine_distance(embedding).label("distance")  # type: ignore[attr-defined]
        stmt = (
            select(Fact, distance)
            .where(Fact.user_id == user_id)
            .order_by(distance)
            .limit(k)
        )
        result = await self._session.execute(stmt)
        return [(row.Fact, row.distance) for row in result.all()]
```

- [ ] **Step 4: Run tests + type-check**

Run: `uv run pytest tests/test_repositories.py -k fact_repo -v && uv run mypy src`
Expected: PASS. (If mypy flags `.cosine_distance`, the `# type: ignore[attr-defined]` above covers it; adjust the error code if mypy names a different one.)

- [ ] **Step 5: Commit**

```bash
git add src/capybara/repositories/fact_repo.py tests/test_repositories.py
git commit -m "feat(memory): FactRepo with user-scoped cosine-nearest search"
```

---

## Task 5: Agent embeddings + structured-output helper

**Files:**
- Modify: `src/capybara/agent/base.py`
- Modify: `src/capybara/agent/ollama.py`
- Modify: `tests/support.py`
- Test: `tests/test_agent_embed.py` (new)

**Interfaces:**
- Produces on `BaseAgent`: `async embed(texts: Sequence[str]) -> list[list[float]]` (abstract); `async run_structured[T](model_name: str, system_prompt: str, user_content: str, output_type: type[T]) -> T` (concrete).
- Produces on `OllamaAgent`: concrete `embed` calling `POST {ollama_base_url}/api/embed` `{"model": embedding_model, "input": [...]}` → `data["embeddings"]`.
- Produces test doubles: `FakeAgent.embed` (returns `[0.1]*768` per text), all doubles satisfy the new abstract method.

- [ ] **Step 1: Write the failing test** — create `tests/test_agent_embed.py`:

```python
import httpx

from capybara.agent.ollama import OllamaAgent
from capybara.config import Settings


def _settings() -> Settings:
    return Settings(jwt_secret="x" * 32, embedding_model="nomic-embed-text")


async def test_ollama_embed_posts_and_parses() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = httpx.Request.read(request).decode()
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    class MockedOllama(OllamaAgent):
        def _client_factory(self) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    agent = MockedOllama(_settings())
    vectors = await agent.embed(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"].endswith("/api/embed")  # type: ignore[union-attr]
    assert "nomic-embed-text" in captured["json"]  # type: ignore[operator]
```

- [ ] **Step 2: Run it, verify failure**

Run: `uv run pytest tests/test_agent_embed.py -v`
Expected: FAIL (`OllamaAgent` has no `embed`; also `OllamaAgent` cannot instantiate until abstract `embed` exists).

- [ ] **Step 3: Add the abstract `embed` + concrete `run_structured`** — in `src/capybara/agent/base.py`:

Add near the top with the other module constant (after `_TITLE_MAX`, ~line 29):

```python
#: System prompt for chat runs that carry tools — nudges the model to use recall.
CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the `recall` tool to search the user's "
    "long-term memory whenever the question depends on personal details, "
    "preferences, or context they may have shared earlier."
)
```

Add `Tool` to the pydantic-ai import (`base.py:8`):

```python
from pydantic_ai import Agent, Tool
```

Add these two methods to `BaseAgent` (after `ensure_available`, before `to_model_messages`):

```python
    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    async def run_structured[T](
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Run a one-shot agent that returns a validated structured result.

        Generic over the output schema so callers own their own extraction types; the
        agent layer stays domain-agnostic.
        """
        agent: Agent[None, T] = Agent(
            self._build_model(model_name),
            system_prompt=system_prompt,
            output_type=output_type,
        )
        result = await agent.run(user_content)
        return result.output
```

- [ ] **Step 4: Update `stream_reply` for the tools seam** — replace the `stream_reply` method body (`base.py:118-133`) with:

```python
    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools: Sequence[Tool[None]] = (),
    ) -> AsyncIterator[str]:
        """Stream token deltas for the named model and accumulate the reply into acc.

        When *tools* are supplied the chat system prompt (with the recall nudge) is set;
        with no tools the prompt is left empty so behaviour is unchanged.
        """
        tool_list = list(tools)
        agent: Agent[None, str] = Agent(
            self._build_model(model_name),
            system_prompt=CHAT_SYSTEM_PROMPT if tool_list else (),
            tools=tool_list,
        )
        async with agent.run_stream(user_content, message_history=history) as result:
            async for text in result.stream_text(delta=True):
                acc.text += text
                yield text
            run_usage = result.usage
            acc.usage = {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            acc.model = result.response.model_name
```

- [ ] **Step 5: Implement `OllamaAgent.embed`** — in `src/capybara/agent/ollama.py`:

Add the import at the top:

```python
from collections.abc import Sequence
```

Add the method to `OllamaAgent` (after `list_models`):

```python
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embeddings for *texts* via Ollama's native ``/api/embed`` endpoint.

        Raises:
            ModelProviderError: If Ollama cannot be reached or returns an unexpected shape.
        """
        url = f"{self._settings.ollama_base_url}/api/embed"
        payload = {"model": self._settings.embedding_model, "input": list(texts)}
        try:
            async with self._client_factory() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            data = response.json()
            return [list(vector) for vector in data["embeddings"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc
```

- [ ] **Step 6: Give the test doubles an `embed`** — in `tests/support.py`:

Add `embed` to `FakeAgent` (after `_build_model`) and change its `_build_model` so its TestModel never auto-calls tools (keeps existing chat tests unchanged even once a recall tool is attached):

```python
    def _build_model(self, name: str) -> Model:
        return TestModel(custom_output_text=self._output_text, call_tools=[])

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]
```

Add an `embed` to `RaisingAgent` and `PartialThenFailAgent` (both subclass `BaseAgent` directly, so the new abstract method must be satisfied); put it after each `_build_model`:

```python
    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]
```

Update the `stream_reply` overrides in `RaisingAgent` and `PartialThenFailAgent` to accept the new `tools` parameter — change both signatures from ending `acc: ReplyAccumulator,` to include:

```python
        tools=(),  # type: ignore[no-untyped-def]
```

as the final parameter (they ignore it). Add `from pydantic_ai import Tool` is **not** required for the doubles since they leave `tools` untyped.

- [ ] **Step 7: Run the new test + the full agent/chat suites (regression)**

Run: `uv run pytest tests/test_agent_embed.py tests/test_agent_stream.py tests/test_agent_title.py tests/test_chat_service.py -v && uv run mypy src`
Expected: PASS. In particular `test_stream_reply_yields_deltas_and_fills_accumulator` still asserts `total_tokens == 54` (no tools passed → no system prompt → usage unchanged).

- [ ] **Step 8: Commit**

```bash
git add src/capybara/agent/base.py src/capybara/agent/ollama.py tests/support.py tests/test_agent_embed.py
git commit -m "feat(memory): BaseAgent.embed + run_structured + tools-aware stream_reply"
```

---

## Task 6: MemoryService — CRUD, recall, auto-capture flag

**Files:**
- Create: `src/capybara/services/memory_service.py`
- Modify: `tests/support.py`
- Test: `tests/test_memory_service.py` (new)

**Interfaces:**
- Consumes: `async_sessionmaker`, `BaseAgent`, `Settings`, `FactRepo`, `Fact`, `User`.
- Produces: `MemoryService(sessionmaker, agent, settings)` with:
  - `async list_facts(user_id) -> list[Fact]`
  - `async add_fact(user_id, content, category) -> Fact`
  - `async update_fact(user_id, fact_id, *, content=None, category=None) -> Fact | None`
  - `async delete_fact(user_id, fact_id) -> bool`
  - `async recall(user_id, query) -> list[Fact]`
  - `async get_auto_capture(user_id) -> bool` / `async set_auto_capture(user_id, value) -> bool`
- Produces test double `StubMemoryAgent` (configurable `embeddings` map + `extracted` structured output).

- [ ] **Step 1: Add the `StubMemoryAgent` double** — in `tests/support.py`, append:

```python
class StubMemoryAgent(FakeAgent):
    """FakeAgent with a fixed embedding map and canned structured extraction output.

    ``embeddings`` maps input text → vector (unknown texts get a fixed non-zero vector so
    cosine distance is always defined). ``extracted`` is the dict fed to the extraction
    output tool, e.g. ``{"facts": [{"content": "...", "category": "personal"}]}``.
    """

    def __init__(  # type: ignore[no-untyped-def]
        self,
        settings,
        *,
        output_text="Ответ",
        embeddings=None,
        extracted=None,
        models=("test-model",),
    ):
        super().__init__(settings, output_text=output_text, models=models)
        self._embeddings = embeddings or {}
        self._extracted = extracted or {"facts": []}

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [self._embeddings.get(t, [0.0] * 767 + [1.0]) for t in texts]

    def _build_model(self, name: str) -> Model:
        return TestModel(
            custom_output_text=self._output_text,
            custom_output_args=self._extracted,
            call_tools=[],
        )
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_memory_service.py`:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.repositories.fact_repo import FactRepo
from capybara.services.memory_service import MemoryService
from support import StubMemoryAgent


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, make_user):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as s:
        user = await make_user(s, username="mem", display_name="Mem")
        await s.commit()
        return user.id


async def test_add_and_list_facts(engine: AsyncEngine, settings: Settings, user_id) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings, embeddings={"Любит горы": [1.0] + [0.0] * 767})
    service = MemoryService(maker, agent, settings)

    fact = await service.add_fact(user_id, "Любит горы", "personal")
    assert fact.source == "manual"

    facts = await service.list_facts(user_id)
    assert [f.content for f in facts] == ["Любит горы"]


async def test_recall_filters_by_min_similarity(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    near = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766
    async with maker() as s:
        repo = FactRepo(s)
        await repo.create(user_id=user_id, category="personal", content="near", embedding=near, source="manual")
        await repo.create(user_id=user_id, category="personal", content="far", embedding=far, source="manual")
        await s.commit()

    # Query embedding == `near`; min_similarity 0.3 excludes the orthogonal `far` (sim 0).
    agent = StubMemoryAgent(settings, embeddings={"q": near})
    service = MemoryService(maker, agent, settings)
    facts = await service.recall(user_id, "q")
    assert [f.content for f in facts] == ["near"]


async def test_update_reembeds_only_on_content_change(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    v1 = [1.0] + [0.0] * 767
    v2 = [0.0, 1.0] + [0.0] * 766
    agent = StubMemoryAgent(settings, embeddings={"old": v1, "new": v2})
    service = MemoryService(maker, agent, settings)

    fact = await service.add_fact(user_id, "old", "personal")
    updated = await service.update_fact(user_id, fact.id, content="new")
    assert updated is not None and updated.content == "new"

    # Re-embedded: it is now nearest to v2, not v1.
    async with maker() as s:
        results = await FactRepo(s).search(user_id, v2, k=1)
    assert results and results[0][0].id == fact.id and results[0][1] < 0.01


async def test_delete_and_ownership_guard(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings)
    service = MemoryService(maker, agent, settings)
    fact = await service.add_fact(user_id, "x", "personal")

    assert await service.delete_fact(uuid4(), fact.id) is False  # wrong owner → no-op
    assert await service.delete_fact(user_id, fact.id) is True
    assert await service.list_facts(user_id) == []


async def test_auto_capture_flag_roundtrip(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    service = MemoryService(maker, StubMemoryAgent(settings), settings)
    assert await service.get_auto_capture(user_id) is True
    assert await service.set_auto_capture(user_id, False) is False
    assert await service.get_auto_capture(user_id) is False
```

- [ ] **Step 3: Run them, verify failure**

Run: `uv run pytest tests/test_memory_service.py -v`
Expected: FAIL (`ImportError`: no `memory_service`).

- [ ] **Step 4: Create the service** — `src/capybara/services/memory_service.py` (this step adds CRUD/recall/flags only; `extract_and_store` + `schedule_extraction` come in Task 8, but define the extraction schema/prompt now so the module is complete):

```python
"""Memory service: fact CRUD, semantic recall, and (Task 8) auto-capture."""

import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent
from capybara.config import Settings
from capybara.db.models import Fact, User
from capybara.filters import FieldEquals
from capybara.repositories.fact_repo import FactRepo

logger = logging.getLogger(__name__)

FactCategory = Literal["personal", "project", "preference"]


class ExtractedFact(BaseModel):
    """A single fact the extraction model proposes from a conversation turn."""

    content: str
    category: FactCategory


class ExtractedFacts(BaseModel):
    """Structured extraction output: zero or more candidate facts."""

    facts: list[ExtractedFact]


#: Extraction prompt used by ``extract_and_store`` (Task 8).
EXTRACTION_SYSTEM_PROMPT = (
    "Extract durable, user-specific facts worth remembering long-term from the "
    "conversation turn: personal details, ongoing projects, and stated preferences. "
    "Categorise each as 'personal', 'project', or 'preference'. Ignore transient chatter, "
    "questions, and general knowledge. Return an empty list if there is nothing worth storing."
)


class MemoryService:
    """Orchestrate long-term memory: fact CRUD, recall, and auto-capture.

    Owns short-lived sessions from the app-wide sessionmaker so it is safe to use both in a
    request and in a post-response background task (it never borrows the request session).
    """

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], agent: BaseAgent, settings: Settings
    ) -> None:
        """Store the sessionmaker, provider agent, and settings."""
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._settings = settings

    async def list_facts(self, user_id: UUID) -> list[Fact]:
        """Return the user's facts, newest first."""
        async with self._sessionmaker() as session:
            return await FactRepo(session).list(FieldEquals(Fact.user_id, user_id))

    async def add_fact(self, user_id: UUID, content: str, category: str) -> Fact:
        """Embed *content* and persist a new manual fact."""
        [embedding] = await self._agent.embed([content])
        async with self._sessionmaker() as session:
            fact = await FactRepo(session).create(
                user_id=user_id,
                content=content,
                category=category,
                embedding=embedding,
                source="manual",
            )
            await session.commit()
            await session.refresh(fact)
            return fact

    async def update_fact(
        self, user_id: UUID, fact_id: UUID, *, content: str | None = None, category: str | None = None
    ) -> Fact | None:
        """Update a fact's content and/or category; re-embed only when content changes.

        Returns the updated fact, or ``None`` if it does not exist or is not owned by
        *user_id* (defence in depth — the route already gates ownership).
        """
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(fact_id)
            if fact is None or fact.user_id != user_id:
                return None
            fields: dict[str, Any] = {}
            if category is not None:
                fields["category"] = category
            if content is not None and content != fact.content:
                fields["content"] = content
                [fields["embedding"]] = await self._agent.embed([content])
            if fields:
                fact = await repo.update(fact, **fields)
            await session.commit()
            await session.refresh(fact)
            return fact

    async def delete_fact(self, user_id: UUID, fact_id: UUID) -> bool:
        """Delete a fact if owned by *user_id*; return whether anything was deleted."""
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(fact_id)
            if fact is None or fact.user_id != user_id:
                return False
            await repo.delete(fact)
            await session.commit()
            return True

    async def recall(self, user_id: UUID, query: str) -> list[Fact]:
        """Return facts semantically nearest to *query*, filtered by the min-similarity setting."""
        [embedding] = await self._agent.embed([query])
        async with self._sessionmaker() as session:
            results = await FactRepo(session).search(
                user_id, embedding, self._settings.memory_recall_k
            )
        min_similarity = self._settings.memory_recall_min_similarity
        return [fact for fact, distance in results if (1.0 - distance) >= min_similarity]

    async def get_auto_capture(self, user_id: UUID) -> bool:
        """Return the user's auto-capture toggle."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            assert user is not None
            return user.memory_auto_capture

    async def set_auto_capture(self, user_id: UUID, value: bool) -> bool:
        """Persist the user's auto-capture toggle and return the new value."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            assert user is not None
            user.memory_auto_capture = value
            await session.commit()
            return value
```

- [ ] **Step 5: Run tests + type-check**

Run: `uv run pytest tests/test_memory_service.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/services/memory_service.py tests/support.py tests/test_memory_service.py
git commit -m "feat(memory): MemoryService CRUD, recall, and auto-capture flag"
```

---

## Task 7: Recall tool + ChatService tool wiring

**Files:**
- Create: `src/capybara/services/memory_tools.py`
- Modify: `src/capybara/services/chat_service.py`
- Modify: `tests/support.py`
- Test: `tests/test_memory_recall_tool.py` (new)

**Interfaces:**
- Consumes: `MemoryService`, `Fact`, pydantic-ai `Tool`.
- Produces: `format_facts(facts: list[Fact]) -> str`; `make_recall_tool(memory_service: MemoryService, user_id: UUID) -> Tool[None]`.
- Produces: `ChatService(sessionmaker, agent, memory_service=None)`; `stream_turn(chat_id, model_name, user_content, history, *, user_id=None)` — attaches the recall tool only when both `user_id` and `memory_service` are present.
- Produces test double `ToolCallingFakeAgent` (TestModel that DOES call tools).

- [ ] **Step 1: Add the tool-calling double** — in `tests/support.py`, append:

```python
class ToolCallingFakeAgent(FakeAgent):
    """FakeAgent whose TestModel calls every registered tool — for tool-registration tests."""

    def _build_model(self, name: str) -> Model:
        return TestModel(custom_output_text=self._output_text)  # call_tools defaults to "all"
```

- [ ] **Step 2: Write the failing test** — create `tests/test_memory_recall_tool.py`:

```python
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat
from capybara.services.chat_service import ChatService
from capybara.services.memory_service import MemoryService
from support import ToolCallingFakeAgent


async def test_recall_tool_is_registered_and_reaches_seeded_facts(
    engine: AsyncEngine, settings: Settings, make_user
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    agent = ToolCallingFakeAgent(settings, "Ответ")

    async with maker() as setup:
        user = await make_user(setup, username="recall", display_name="R")
        chat = Chat(user_id=user.id, title="c", model="test-model")
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    memory = MemoryService(maker, agent, settings)
    # Seed a fact; agent.embed is constant, so recall returns it.
    await memory.add_fact(user_id, "Любит горные походы", "personal")

    recorded: list[list[str]] = []

    class RecordingMemory(MemoryService):
        async def recall(self, uid, query):  # type: ignore[no-untyped-def]
            facts = await super().recall(uid, query)
            recorded.append([f.content for f in facts])
            return facts

    service = ChatService(maker, agent, RecordingMemory(maker, agent, settings))
    model, history = await service.begin_turn(user_id, chat_id, "Что я люблю?")
    _ = [e async for e in service.stream_turn(chat_id, model, "Что я люблю?", history, user_id=user_id)]

    assert recorded, "recall tool was never invoked — tool not registered via the tools list"
    assert any("Любит горные походы" in facts for facts in recorded)
```

- [ ] **Step 3: Run it, verify failure**

Run: `uv run pytest tests/test_memory_recall_tool.py -v`
Expected: FAIL (`ImportError`: no `memory_tools`; `stream_turn` rejects `user_id`).

- [ ] **Step 4: Create the recall tool module** — `src/capybara/services/memory_tools.py`:

```python
"""Recall tool: bridges the chat agent's tool seam to MemoryService."""

from uuid import UUID

from pydantic_ai import Tool

from capybara.db.models import Fact
from capybara.services.memory_service import MemoryService


def format_facts(facts: list[Fact]) -> str:
    """Render recalled facts as a short bullet list for the model, or a not-found note."""
    if not facts:
        return "No relevant facts found."
    return "\n".join(f"- [{fact.category}] {fact.content}" for fact in facts)


def make_recall_tool(memory_service: MemoryService, user_id: UUID) -> Tool[None]:
    """Build a pydantic-ai recall tool closed over the service and user.

    The tool takes no pydantic-ai ``deps`` — the service and user are captured in the
    closure, so it composes into the generic ``stream_reply(tools=…)`` list unchanged.
    """

    async def recall(query: str) -> str:
        """Search the user's long-term memory for relevant facts."""
        return format_facts(await memory_service.recall(user_id, query))

    return Tool(recall)
```

- [ ] **Step 5: Wire ChatService** — in `src/capybara/services/chat_service.py`:

Add imports near the top (after the existing `from capybara.agent.base ...` import):

```python
from pydantic_ai import Tool

from capybara.services.memory_service import MemoryService
from capybara.services.memory_tools import make_recall_tool
```

Change the constructor (`chat_service.py:42-44`) to accept an optional memory service:

```python
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent: BaseAgent,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._memory_service = memory_service
```

Change `stream_turn` (`chat_service.py:81-103`) to take `user_id` and assemble the tool list:

```python
    async def stream_turn(
        self,
        chat_id: UUID,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        *,
        user_id: UUID | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the LLM reply as Delta events and persist the assistant message.

        No DB connection is held while the model streams. When *user_id* is given and a
        memory service is wired, the recall tool is added to the run's tool list so the
        model can search long-term memory mid-turn.
        """
        tools: list[Tool[None]] = []
        if user_id is not None and self._memory_service is not None:
            tools.append(make_recall_tool(self._memory_service, user_id))
        acc = ReplyAccumulator()
        completed = False
        try:
            async for delta in self._agent.stream_reply(
                model_name, user_content, history, acc, tools=tools
            ):
                yield Delta(text=delta)
            completed = True
        finally:
            assistant_id = await self._persist_assistant(chat_id, acc, completed=completed)
        if completed:
            yield Done(message_id=assistant_id, usage=acc.usage)
```

- [ ] **Step 6: Run the recall test + chat-service regression + type-check**

Run: `uv run pytest tests/test_memory_recall_tool.py tests/test_chat_service.py -v && uv run mypy src`
Expected: PASS. (Existing `test_chat_service.py` calls `stream_turn` without `user_id` → no tools → unchanged. If mypy objects to `Tool(recall)` not matching `Tool[None]`, annotate the closure's return or add `cast(Tool[None], Tool(recall))` in `make_recall_tool`.)

- [ ] **Step 7: Commit**

```bash
git add src/capybara/services/memory_tools.py src/capybara/services/chat_service.py tests/support.py tests/test_memory_recall_tool.py
git commit -m "feat(memory): recall Tool and ChatService generic tools seam"
```

---

## Task 8: Auto-capture — extract_and_store + schedule_extraction

**Files:**
- Modify: `src/capybara/services/memory_service.py`
- Test: `tests/test_memory_extract.py` (new)

**Interfaces:**
- Consumes: `run_structured`, `ExtractedFacts`, `EXTRACTION_SYSTEM_PROMPT`, `ChatRepo`, `MessageRepo`, `Message`.
- Produces on `MemoryService`: `async extract_and_store(user_id, chat_id) -> None`.
- Produces module function: `async schedule_extraction(service: MemoryService, user_id: UUID, chat_id: UUID) -> None` (swallows + logs all errors).

- [ ] **Step 1: Write the failing tests** — create `tests/test_memory_extract.py`:

```python
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.memory_service import MemoryService
from support import StubMemoryAgent


async def _seed_turn(maker, make_user, *, username, auto_capture=True):  # type: ignore[no-untyped-def]
    async with maker() as s:
        user = await make_user(s, username=username, display_name=username)
        user.memory_auto_capture = auto_capture
        chat = Chat(user_id=user.id, title="c", model="test-model")
        s.add(chat)
        await s.flush()
        repo = MessageRepo(s)
        await repo.create(chat_id=chat.id, role="user", content="Меня зовут Роман, люблю чай")
        await repo.create(chat_id=chat.id, role="assistant", content="Приятно, Роман!")
        await s.commit()
        return user.id, chat.id


async def test_extract_inserts_new_facts(engine: AsyncEngine, settings: Settings, make_user) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex1")
    agent = StubMemoryAgent(
        settings,
        embeddings={"Любит чай": [1.0] + [0.0] * 767},
        extracted={"facts": [{"content": "Любит чай", "category": "preference"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert [f.content for f in facts] == ["Любит чай"]
    assert facts[0].source == "auto"


async def test_extract_skips_near_duplicates(engine: AsyncEngine, settings: Settings, make_user) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex2")
    vec = [1.0] + [0.0] * 767
    async with maker() as s:
        await FactRepo(s).create(user_id=user_id, category="preference", content="Любит чай", embedding=vec, source="manual")
        await s.commit()

    agent = StubMemoryAgent(
        settings,
        embeddings={"Обожает чай": vec},  # identical vector → similarity 1.0 ≥ dedup threshold
        extracted={"facts": [{"content": "Обожает чай", "category": "preference"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert len(facts) == 1  # duplicate skipped


async def test_extract_noop_when_disabled(engine: AsyncEngine, settings: Settings, make_user) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex3", auto_capture=False)
    agent = StubMemoryAgent(
        settings,
        extracted={"facts": [{"content": "anything", "category": "personal"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert facts == []


async def test_schedule_extraction_swallows_errors(engine: AsyncEngine, settings: Settings, make_user) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    from capybara.services.memory_service import schedule_extraction

    maker = create_sessionmaker(engine)
    service = MemoryService(maker, StubMemoryAgent(settings), settings)
    # Non-existent user/chat → extract_and_store no-ops; schedule must never raise.
    await schedule_extraction(service, uuid4(), uuid4())
```

- [ ] **Step 2: Run them, verify failure**

Run: `uv run pytest tests/test_memory_extract.py -v`
Expected: FAIL (`AttributeError`: no `extract_and_store`; `ImportError`: no `schedule_extraction`).

- [ ] **Step 3: Implement extraction** — in `src/capybara/services/memory_service.py`:

Add imports at the top (with the existing `from capybara...` imports):

```python
from capybara.db.models import Message
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
```

Add a module-level helper (after `EXTRACTION_SYSTEM_PROMPT`):

```python
def _last_turn_text(messages: list[Message]) -> str | None:
    """Format the last user+assistant exchange as ``User: …\nAssistant: …``.

    Returns ``None`` when there is no completed assistant reply with a preceding user
    message — nothing to extract from.
    """
    last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
    if last_assistant is None:
        return None
    last_user = next(
        (m for m in reversed(messages) if m.role == "user" and m.seq < last_assistant.seq), None
    )
    if last_user is None:
        return None
    return f"User: {last_user.content}\nAssistant: {last_assistant.content}"
```

Add the method to `MemoryService` (after `set_auto_capture`):

```python
    async def extract_and_store(self, user_id: UUID, chat_id: UUID) -> None:
        """Extract durable facts from a chat's last turn and store the novel ones.

        Gated by the user's auto-capture flag. Uses the chat's own model for extraction and
        embedding-similarity dedup (facts within ``memory_dedup_threshold`` of an existing
        fact are skipped). Safe to run in a post-response background task.
        """
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
        turn = _last_turn_text(messages)
        if turn is None:
            return

        extracted = await self._agent.run_structured(
            model, EXTRACTION_SYSTEM_PROMPT, turn, ExtractedFacts
        )
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
```

Add the background entrypoint at the end of the module:

```python
async def schedule_extraction(service: MemoryService, user_id: UUID, chat_id: UUID) -> None:
    """Run auto-capture as a background task, swallowing and logging every error.

    Variant A stand-in for a real task queue: the endpoint attaches this via Starlette's
    ``BackgroundTask``. When the Celery slice lands, only the trigger changes.
    """
    try:
        await service.extract_and_store(user_id, chat_id)
    except Exception:
        logger.exception("auto-capture failed for chat %s", chat_id)
```

- [ ] **Step 4: Run tests + type-check**

Run: `uv run pytest tests/test_memory_extract.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/services/memory_service.py tests/test_memory_extract.py
git commit -m "feat(memory): auto-capture extract_and_store with dedup + schedule_extraction"
```

---

## Task 9: /memory API — schemas, deps, router

**Files:**
- Modify: `src/capybara/api/schemas.py`
- Modify: `src/capybara/api/dependencies.py`
- Create: `src/capybara/api/routers/memory.py`
- Modify: `src/capybara/main.py`
- Modify: `tests/test_chats_api.py` (client fixture)
- Test: `tests/test_memory_api.py` (new)

**Interfaces:**
- Produces schemas: `FactCreate {content, category}`, `FactUpdate {content?, category?}` (≥1 required), `FactOut {id, category, content, source, created_at, updated_at}`, `MemorySettingsOut {auto_capture}`, `MemorySettingsUpdate {auto_capture}`.
- Produces deps: `get_memory_service`, `get_fact_repo`, `get_owned_fact`; `get_chat_service` gains `memory_service`.
- Produces routes: `GET/POST /memory/facts`, `PATCH/DELETE /memory/facts/{fact_id}`, `GET/PATCH /memory/settings`.

- [ ] **Step 1: Write the failing API tests** — create `tests/test_memory_api.py`:

```python
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
from support import StubMemoryAgent


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
    app.dependency_overrides[get_agent] = lambda: StubMemoryAgent(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_fact_crud_flow(client: AsyncClient) -> None:
    created = await client.post("/memory/facts", json={"content": "Любит чай", "category": "preference"})
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "manual" and body["category"] == "preference"
    fact_id = body["id"]

    listed = await client.get("/memory/facts")
    assert [f["id"] for f in listed.json()] == [fact_id]

    patched = await client.patch(f"/memory/facts/{fact_id}", json={"content": "Обожает чай"})
    assert patched.status_code == 200 and patched.json()["content"] == "Обожает чай"

    deleted = await client.delete(f"/memory/facts/{fact_id}")
    assert deleted.status_code == 204
    assert (await client.get("/memory/facts")).json() == []


async def test_patch_requires_a_field(client: AsyncClient) -> None:
    created = await client.post("/memory/facts", json={"content": "x", "category": "personal"})
    fact_id = created.json()["id"]
    resp = await client.patch(f"/memory/facts/{fact_id}", json={})
    assert resp.status_code == 422


async def test_settings_toggle(client: AsyncClient) -> None:
    assert (await client.get("/memory/settings")).json() == {"auto_capture": True}
    patched = await client.patch("/memory/settings", json={"auto_capture": False})
    assert patched.status_code == 200 and patched.json() == {"auto_capture": False}


async def test_facts_are_per_user_isolated(
    client: AsyncClient, engine: AsyncEngine, settings: Settings, make_user
) -> None:  # type: ignore[no-untyped-def]
    from capybara.repositories.fact_repo import FactRepo

    maker = create_sessionmaker(engine)
    async with maker() as s:
        other = await make_user(s, username="other", display_name="Other")
        await FactRepo(s).create(
            user_id=other.id, category="personal", content="secret", embedding=[0.2] * 768, source="manual"
        )
        await s.commit()
        async with maker() as s2:
            other_fact = (await FactRepo(s2).list())[0]
            other_fact_id = other_fact.id

    # Current user cannot see it, and cannot mutate it (404, not 403 leak).
    assert (await client.get("/memory/facts")).json() == []
    assert (await client.patch(f"/memory/facts/{other_fact_id}", json={"content": "hax"})).status_code == 404
    assert (await client.delete(f"/memory/facts/{other_fact_id}")).status_code == 404
```

- [ ] **Step 2: Run them, verify failure**

Run: `uv run pytest tests/test_memory_api.py -v`
Expected: FAIL (routes 404 / import errors).

- [ ] **Step 3: Add the schemas** — in `src/capybara/api/schemas.py`:

Add `Literal` to the typing import (`schemas.py:4`): `from typing import Literal`. Then append:

```python
FactCategory = Literal["personal", "project", "preference"]


class FactCreate(BaseModel):
    """Payload for creating a manual fact."""

    content: str = Field(min_length=1, max_length=2000)
    category: FactCategory

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        """Reject whitespace-only fact content."""
        return _reject_blank_text(value)


class FactUpdate(BaseModel):
    """Partial update for a fact: content and/or category. At least one required."""

    content: str | None = Field(default=None, min_length=1, max_length=2000)
    category: FactCategory | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _strip_optional_content(cls, value: object) -> object:
        """Trim optional content and reject whitespace-only values."""
        if value is None:
            return None
        return _strip_required_text(value)

    @model_validator(mode="after")
    def _require_one(self) -> "FactUpdate":
        """Reject an empty patch — at least one field must be provided."""
        if self.content is None and self.category is None:
            raise ValueError("at least one of content, category must be provided")
        return self


class FactOut(BaseModel):
    """Response schema for a single fact."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime


class MemorySettingsOut(BaseModel):
    """Response schema for the memory auto-capture toggle."""

    auto_capture: bool


class MemorySettingsUpdate(BaseModel):
    """Request schema for updating the memory auto-capture toggle."""

    auto_capture: bool
```

- [ ] **Step 4: Add the dependencies** — in `src/capybara/api/dependencies.py`:

Add imports (with the existing service/repo imports):

```python
from capybara.db.models import Fact
from capybara.repositories.fact_repo import FactRepo
from capybara.services.memory_service import MemoryService
```

Add these providers (after `get_owned_chat`), and update `get_chat_service`:

```python
def get_memory_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> MemoryService:
    """Return a MemoryService that owns short-lived sessions from the app sessionmaker."""
    return MemoryService(sessionmaker, agent, settings)


def get_fact_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FactRepo:
    """Return a FactRepo bound to the current request session."""
    return FactRepo(session)


async def get_owned_fact(
    fact_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    facts: Annotated[FactRepo, Depends(get_fact_repo)],
) -> Fact:
    """Return the fact if it belongs to the current user, else 404."""
    fact = await facts.get(fact_id)
    if fact is None or fact.user_id != user.id:
        raise HTTPException(status_code=404, detail="Fact not found")
    return fact
```

Replace `get_chat_service` (`dependencies.py:126-131`) with:

```python
def get_chat_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> ChatService:
    """Return a ChatService that owns short-lived sessions and carries the recall tool."""
    return ChatService(sessionmaker, agent, memory_service)
```

- [ ] **Step 5: Create the router** — `src/capybara/api/routers/memory.py`:

```python
"""Router for memory (facts) CRUD and settings."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from capybara.api.dependencies import get_current_user, get_memory_service, get_owned_fact
from capybara.api.schemas import (
    FactCreate,
    FactOut,
    FactUpdate,
    MemorySettingsOut,
    MemorySettingsUpdate,
)
from capybara.db.models import Fact, User
from capybara.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/facts", response_model=list[FactOut])
async def list_facts(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> list[FactOut]:
    """Return the current user's facts, newest first."""
    rows = await service.list_facts(user.id)
    return [FactOut.model_validate(f) for f in rows]


@router.post("/facts", status_code=status.HTTP_201_CREATED, response_model=FactOut)
async def create_fact(
    payload: FactCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> FactOut:
    """Embed and store a new manual fact for the current user."""
    fact = await service.add_fact(user.id, payload.content, payload.category)
    return FactOut.model_validate(fact)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    payload: FactUpdate,
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> FactOut:
    """Update a fact's content and/or category (404 if not owned); re-embeds on content change."""
    updated = await service.update_fact(
        user.id, fact.id, content=payload.content, category=payload.category
    )
    assert updated is not None  # get_owned_fact already verified ownership
    return FactOut.model_validate(updated)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    """Delete a fact owned by the current user (404 if not owned)."""
    await service.delete_fact(user.id, fact.id)


@router.get("/settings", response_model=MemorySettingsOut)
async def get_memory_settings(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemorySettingsOut:
    """Return the current user's auto-capture toggle."""
    return MemorySettingsOut(auto_capture=await service.get_auto_capture(user.id))


@router.patch("/settings", response_model=MemorySettingsOut)
async def update_memory_settings(
    payload: MemorySettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemorySettingsOut:
    """Update the current user's auto-capture toggle."""
    value = await service.set_auto_capture(user.id, payload.auto_capture)
    return MemorySettingsOut(auto_capture=value)
```

- [ ] **Step 6: Wire the router** — in `src/capybara/main.py`, add `memory` to the router import and include it:

Change the import line to include `memory`:

```python
    from capybara.api.routers import auth, chats, health, memory, models, users
```

And add after `fastapi_app.include_router(chats.router)`:

```python
    fastapi_app.include_router(memory.router)
```

- [ ] **Step 7: Fix the chats API client fixture** — in `tests/test_chats_api.py`, the `get_chat_service` dependency now transitively needs `get_settings_dep`, which the test app never sets on `app.state`. Add the import and override.

Add `get_settings_dep` to the dependency import block (`test_chats_api.py:5-10`):

```python
from capybara.api.dependencies import (
    get_agent,
    get_current_user,
    get_session,
    get_sessionmaker,
    get_settings_dep,
)
```

And add this line next to the other `app.dependency_overrides[...]` assignments in the `client` fixture:

```python
    app.dependency_overrides[get_settings_dep] = lambda: settings
```

- [ ] **Step 8: Run the memory API tests + chats API regression + type-check**

Run: `uv run pytest tests/test_memory_api.py tests/test_chats_api.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/capybara/api/schemas.py src/capybara/api/dependencies.py src/capybara/api/routers/memory.py src/capybara/main.py tests/test_memory_api.py tests/test_chats_api.py
git commit -m "feat(memory): /memory facts CRUD + settings API"
```

---

## Task 10: Auto-capture trigger on send_message (variant A)

**Files:**
- Modify: `src/capybara/api/routers/chats.py`
- Test: `tests/test_memory_autocapture_api.py` (new)

**Interfaces:**
- Consumes: `get_memory_service`, `schedule_extraction`, Starlette `BackgroundTask`.
- Produces: `POST /chats/{id}/messages` attaches `BackgroundTask(schedule_extraction, memory, user.id, chat_id)` to its `StreamingResponse`; passes `user_id=user.id` to `stream_turn`. `regenerate` passes `user_id` but attaches **no** background task.

- [ ] **Step 1: Write the failing tests** — create `tests/test_memory_autocapture_api.py`:

```python
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
from support import StubMemoryAgent


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

    agent = StubMemoryAgent(
        settings,
        output_text="Ответ",
        extracted={"facts": [{"content": "Любит чай", "category": "preference"}]},
    )
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: agent
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_send_message_auto_captures_fact(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    facts = (await client.get("/memory/facts")).json()
    assert [f["content"] for f in facts] == ["Любит чай"]
    assert facts[0]["source"] == "auto"


async def test_regenerate_does_not_auto_capture(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as resp:
        async for _ in resp.aiter_text():
            pass
    # Clear anything captured by the first send so we measure regenerate alone.
    for f in (await client.get("/memory/facts")).json():
        await client.delete(f"/memory/facts/{f['id']}")

    async with client.stream("POST", f"/chats/{chat_id}/messages/regenerate") as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    assert (await client.get("/memory/facts")).json() == []
```

- [ ] **Step 2: Run them, verify failure**

Run: `uv run pytest tests/test_memory_autocapture_api.py -v`
Expected: FAIL (no fact captured — no background task wired).

- [ ] **Step 3: Wire the background task** — in `src/capybara/api/routers/chats.py`:

Add imports:

```python
from starlette.background import BackgroundTask

from capybara.api.dependencies import get_memory_service
from capybara.services.memory_service import MemoryService, schedule_extraction
```

(Add `get_memory_service` to the existing `from capybara.api.dependencies import (...)` block, and `MemoryService`/`schedule_extraction` as shown.)

In `send_message`, add the memory-service dependency to the signature (after `service`):

```python
    memory: Annotated[MemoryService, Depends(get_memory_service)],
```

Change the `stream_turn` call inside `send_message`'s `event_stream` (`chats.py:167`) to pass `user_id`:

```python
            async for event in service.stream_turn(
                chat_id, model, payload.content, history, user_id=user.id
            ):
```

Change the `send_message` `return StreamingResponse(...)` (`chats.py:183-187`) to attach the background task:

```python
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        background=BackgroundTask(schedule_extraction, memory, user.id, chat_id),
    )
```

In `regenerate_message`, change its `stream_turn` call (`chats.py:217`) to pass `user_id` (recall stays enabled) but **do not** attach a background task:

```python
            async for event in service.stream_turn(
                chat_id, model, last_user_content, history, user_id=user.id
            ):
```

- [ ] **Step 4: Run the auto-capture tests + full chats regression + type-check**

Run: `uv run pytest tests/test_memory_autocapture_api.py tests/test_chats_api.py -v && uv run mypy src`
Expected: PASS. If the captured fact isn't visible immediately after the stream drains, the Starlette background task may need the response fully closed — the `async for _ in resp.aiter_text(): pass` drain plus context-manager exit ensures this under `ASGITransport`; if flaky, wrap the assertion in a short retry loop.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/api/routers/chats.py tests/test_memory_autocapture_api.py
git commit -m "feat(memory): post-stream auto-capture BackgroundTask on send_message"
```

---

## Task 11: Docs — embedding model requirement + memory config

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the memory feature** — add a "Memory" section to `README.md` covering:
  - The `pgvector/pgvector:pg16` Postgres image is required (compose already updated).
  - Ollama must have the embedding model pulled: `ollama pull nomic-embed-text` (recall and auto-capture fail loudly via `ModelProviderError` otherwise).
  - Config knobs: `EMBEDDING_MODEL` (default `nomic-embed-text`), `MEMORY_RECALL_K` (5), `MEMORY_RECALL_MIN_SIMILARITY` (0.3), `MEMORY_DEDUP_THRESHOLD` (0.9).
  - Auto-capture is per-user (`users.memory_auto_capture`, default on), runs post-reply via a temporary `BackgroundTask` (variant A) that will be swapped for Celery later.
  - Limitation: changing `EMBEDDING_MODEL` requires re-embedding existing facts (no per-row model provenance in v1).

- [ ] **Step 2: Run the full suite + gates one final time**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(memory): document embedding model requirement and memory config"
```

---

## Self-Review

**1. Spec coverage:**

| Spec item | Task |
|---|---|
| `facts` table + pgvector + HNSW + btree indexes + migration | 2, 3 |
| `pgvector` extension | 3 (migration), 2 (test engine) |
| `users.memory_auto_capture` | 2, 3 |
| `BaseAgent.embed` + `OllamaAgent.embed` | 5 |
| `run_structured` helper | 5 |
| Generic `stream_reply(tools=…)` seam + recall tool | 5, 7 |
| Auto-capture variant A (`BackgroundTask` + `extract_and_store` + dedup + gate) | 8, 10 |
| `/memory` facts CRUD + settings | 9 |
| Layering (`FactRepo` → `MemoryService` → router; deps `get_memory_service`, `get_owned_fact`) | 4, 6, 9 |
| Config (`embedding_model`, `memory_recall_k`, `min_similarity`, `dedup_threshold`) | 1 |
| Docker image `pgvector/pgvector:pg16` (compose + testcontainers) | 1, 2 |
| System-prompt recall nudge | 5 |
| Tests: `FactRepo.search` order; extract insert/dedup/gate; recall-in-chat-run; API CRUD + per-user isolation; `OllamaAgent.embed` mocked | 4, 7, 8, 9, 5 |
| Success criteria (recall answers; isolation; auto-capture on/off; ruff+mypy+tests green) | all + 11 |

Frontend items (Память screen, `useFacts`, sidebar nav) are intentionally out of scope — the separate frontend plan.

**2. Placeholder scan:** none — every step ships concrete code/commands.

**3. Type consistency:** `MemoryService(sessionmaker, agent, settings)`, `stream_turn(..., *, user_id=None)`, `FactRepo.search(user_id, embedding, k) -> list[tuple[Fact, float]]`, `make_recall_tool(memory_service, user_id) -> Tool[None]`, `ExtractedFacts.facts: list[ExtractedFact{content, category}]`, `FactOut{id, category, content, source, created_at, updated_at}` are used consistently across tasks 4–10.

**Known integration risks (verified against the current suite, flagged for the implementer):**
- `stream_reply` adds the system prompt only when `tools` is non-empty, so `test_agent_stream.py`'s exact `total_tokens == 54` assertion stays valid.
- `FakeAgent`'s TestModel uses `call_tools=[]`, so existing chat API/service tests don't trigger recall; the dedicated `ToolCallingFakeAgent` exercises tool registration.
- `get_chat_service` now transitively depends on `get_settings_dep`; the chats API client fixture (Task 9 Step 7) and both new API fixtures override it, since the test app never runs lifespan.
- pgvector's `.cosine_distance` / `Vector` are untyped (mypy override in Task 1); `# type: ignore[attr-defined]` is applied at the one call site.
