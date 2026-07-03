# User Registration Implementation Plan (slice 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add local user registration (`POST /users` with display name, login=username, password) with argon2 password hashing, replacing the seeded user.

**Architecture:** Layered `api → services → repositories → db` + a new `security/` module for password hashing. Registration logic lives in `UserService`; passwords are stored only as argon2 hashes.

**Tech Stack:** Python 3.12, FastAPI, argon2-cffi, SQLAlchemy 2.0 async, Alembic, uv, ruff (incl. pydocstyle D), strict mypy.

## Global Constraints

- Python >=3.12, fully type-annotated, strict mypy over `src`. uv; ruff (D enforced — every module/class/function in `src` has a docstring); mypy strict.
- Data access only in repositories; commit owned by the caller (repos flush); LLM only via agent module.
- Passwords NEVER stored or returned in plaintext; the hash is never serialized to clients.
- Validation: `password` min_length=8; `username` min_length=3, max_length=64; `display_name` min_length=1, max_length=128.
- Duplicate username → HTTP 409; invalid input → 422; `get_current_user` (no login yet) → HTTP 401.
- Behavior of existing tests preserved (adjust setup that constructs `User`, keep assertions).

---

### Task 1: Password hashing module

**Files:**
- Modify: `pyproject.toml` (add `argon2-cffi`)
- Create: `src/capybara/security/__init__.py`, `src/capybara/security/passwords.py`
- Test: `tests/test_passwords.py`

**Interfaces:**
- Produces: `capybara.security.passwords.hash_password(password: str) -> str` (argon2 hash).

- [ ] **Step 1: Add dependency** — in `pyproject.toml` `[project] dependencies`, add `"argon2-cffi>=23.1"`. Run `uv sync`.

- [ ] **Step 2: Write the failing test** — `tests/test_passwords.py`

```python
from capybara.security.passwords import hash_password


def test_hash_password_returns_argon2_hash() -> None:
    hashed = hash_password("s3cret-password")
    assert hashed.startswith("$argon2")
    assert hashed != "s3cret-password"


def test_hash_password_is_salted_unique() -> None:
    assert hash_password("same-input") != hash_password("same-input")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: capybara.security.passwords`.

- [ ] **Step 4: Implement** — `src/capybara/security/__init__.py`:

```python
"""Security utilities (password hashing)."""
```

`src/capybara/security/passwords.py`:

```python
"""Password hashing utilities using argon2."""

from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash of the given plaintext password."""
    return _hasher.hash(password)
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_passwords.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/capybara/security tests/test_passwords.py
git commit -m "feat: argon2 password hashing module"
```

---

### Task 2: `password_hash` column + migration + `make_user` test fixture

**Files:**
- Modify: `src/capybara/db/models/user.py`
- Create: one Alembic migration under `src/capybara/migrations/versions/`
- Modify: `tests/conftest.py` (add `make_user` fixture), `tests/test_migrations.py`, and existing tests that construct `User` (`tests/test_models.py`, `tests/test_repositories.py`, `tests/test_chat_service.py`, `tests/test_chats_api.py`)

**Interfaces:**
- Consumes: `hash_password` (Task 1).
- Produces: `User.password_hash: str` (NOT NULL); pytest fixture `make_user` — an async factory `await make_user(session, *, username=..., display_name=..., password=...) -> User`.

- [ ] **Step 1: Add the column to the model** — `src/capybara/db/models/user.py`, add inside `User` (mirror existing typed columns; `String` is already imported):

```python
    password_hash: Mapped[str] = mapped_column(String(255))
```

- [ ] **Step 2: Add the `make_user` fixture** — in `tests/conftest.py` add (imports at top: `from capybara.db.models import User`, `from capybara.security.passwords import hash_password`):

```python
@pytest.fixture
def make_user():  # type: ignore[no-untyped-def]
    """Return an async factory that inserts a User with a hashed password."""

    async def _make(
        session: AsyncSession,
        *,
        username: str = "roman",
        display_name: str = "Роман",
        password: str = "password123",
    ) -> User:
        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
        )
        session.add(user)
        await session.flush()
        return user

    return _make
```

- [ ] **Step 3: Update existing User constructions to use the fixture.** In each test that does `User(username=..., display_name=...)` (without `password_hash`), replace the inline construction with the fixture so the NOT NULL column is satisfied. Pattern:

Before:
```python
user = User(username="roman", display_name="Роман")
session.add(user)
await session.flush()
```
After:
```python
user = await make_user(session, username="roman", display_name="Роман")
```
Apply this in `tests/test_models.py`, `tests/test_repositories.py`, `tests/test_chat_service.py`, and `tests/test_chats_api.py` (including the second-user creation in the IDOR ownership tests — use `await make_user(setup, username="other", display_name="Other")`). Add `make_user` to each affected test's parameters. Keep every existing assertion unchanged. In `tests/test_models.py`, if a test builds `User` directly to assert column defaults, either keep it but add `password_hash=hash_password("x")`, or route through `make_user` — keep its assertions.

- [ ] **Step 4: Create the migration.** Generate against an ephemeral Postgres (migrated to the current head first), or hand-author. It must: delete the seeded user, then add `password_hash` NOT NULL. Hand-authored body (fill in `down_revision` = current head revision id; keep the autogenerated date-time filename form `YYYYMMDD_HHMM_<rev>_add_password_hash`):

```python
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers kept as generated.

_SEED_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE username = 'roman'"))
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid),
        sa.column("username", sa.String),
        sa.column("display_name", sa.String),
    )
    op.bulk_insert(
        users,
        [{"id": _SEED_USER_ID, "username": "roman", "display_name": "Роман"}],
    )
```
If you generate via ephemeral docker: `docker run -d --name capy-pw -e POSTGRES_USER=capybara -e POSTGRES_PASSWORD=capybara -e POSTGRES_DB=capybara -p 5544:5432 postgres:16`, `DATABASE_URL=postgresql+asyncpg://capybara:capybara@localhost:5544/capybara` with `alembic upgrade head` then `alembic revision --autogenerate -m "add password_hash"`, edit the upgrade to also `DELETE` the seed, then `docker rm -f capy-pw`. Leave no container running.

- [ ] **Step 5: Update the migration test** — `tests/test_migrations.py`: the schema/seed test must now assert (a) the `users`, `chats`, `messages` tables exist, (b) `users.password_hash` column exists, and (c) there is NO seeded `roman` user. Replace the seed assertion:

```python
        count = (
            await conn.execute(text("SELECT count(*) FROM users WHERE username = 'roman'"))
        ).scalar_one()
        assert count == 0

        cols = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'users'"
                )
            )
        ).scalars().all()
        assert "password_hash" in set(cols)
```

- [ ] **Step 6: Run full suite + gates**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src`
Expected: all green (every `User` now has a `password_hash`; migration test reflects no-seed + new column). Ensure no leftover docker container.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: users.password_hash column, drop seed user, make_user fixture"
```

---

### Task 3: `UserRepo.get_by_username` + `UserService.register`

**Files:**
- Modify: `src/capybara/repositories/user_repo.py`
- Create: `src/capybara/services/user_service.py`
- Test: `tests/test_user_service.py`

**Interfaces:**
- Consumes: `UserRepo` (existing), `hash_password` (Task 1), `make_user` (Task 2).
- Produces:
  - `UserRepo.get_by_username(username: str) -> User | None`
  - `capybara.services.user_service.UsernameTaken` (Exception)
  - `UserService(users: UserRepo).register(display_name: str, username: str, password: str) -> User`

- [ ] **Step 1: Write the failing test** — `tests/test_user_service.py`

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password
from capybara.services.user_service import UserService, UsernameTaken


async def test_register_creates_user_with_hashed_password(session: AsyncSession) -> None:
    service = UserService(UserRepo(session))
    user = await service.register("Роман", "roman", "password123")
    assert user.username == "roman"
    assert user.display_name == "Роман"
    assert user.password_hash.startswith("$argon2")
    assert user.password_hash != "password123"


async def test_register_duplicate_username_raises(session: AsyncSession) -> None:
    user = User(username="roman", display_name="Роман", password_hash=hash_password("x"))
    session.add(user)
    await session.flush()
    service = UserService(UserRepo(session))
    with pytest.raises(UsernameTaken):
        await service.register("Other", "roman", "password123")
```
(Add `from capybara.db.models import User` to the imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_user_service.py -v`
Expected: FAIL — `capybara.services.user_service` missing.

- [ ] **Step 3: Add `get_by_username` to `UserRepo`** — `src/capybara/repositories/user_repo.py` (add `from sqlalchemy import select` if absent):

```python
    async def get_by_username(self, username: str) -> User | None:
        """Return the user with the given username, or None if there is none."""
        stmt = select(User).where(User.username == username)
        return (await self._session.execute(stmt)).scalar_one_or_none()
```

- [ ] **Step 4: Implement the service** — `src/capybara/services/user_service.py`

```python
"""User registration orchestration."""

from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password


class UsernameTaken(Exception):
    """Raised when registering a username that is already in use."""


class UserService:
    """Orchestrate user registration."""

    def __init__(self, users: UserRepo) -> None:
        self._users = users

    async def register(self, display_name: str, username: str, password: str) -> User:
        """Create a user; raise UsernameTaken if the username already exists."""
        if await self._users.get_by_username(username) is not None:
            raise UsernameTaken(username)
        return await self._users.create(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
        )
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_user_service.py -v && uv run ruff check . && uv run mypy src`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/repositories/user_repo.py src/capybara/services/user_service.py tests/test_user_service.py
git commit -m "feat: UserRepo.get_by_username and UserService.register"
```

---

### Task 4: `POST /users` API + dependencies + `get_current_user` → 401

**Files:**
- Modify: `src/capybara/api/schemas.py`, `src/capybara/api/dependencies.py`, `src/capybara/main.py`
- Create: `src/capybara/api/routers/users.py`
- Test: `tests/test_users_api.py`

**Interfaces:**
- Consumes: `UserService.register`, `UsernameTaken` (Task 3); `get_session`, `get_user_repo` deps.
- Produces: `POST /users` (201 → UserOut; 409 on duplicate; 422 on invalid). `get_current_user` now raises 401.

- [ ] **Step 1: Add schemas** — `src/capybara/api/schemas.py` (uses existing `BaseModel`, `ConfigDict`, `Field`? add `from pydantic import Field` if absent; `UUID`, `datetime` already imported):

```python
class UserCreate(BaseModel):
    """Request body for registering a user."""

    display_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    """Public user representation — never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    created_at: datetime
```

- [ ] **Step 2: Add dependencies + change `get_current_user`** — `src/capybara/api/dependencies.py`:
  - Add imports: `from fastapi import HTTPException`, `from capybara.repositories.user_repo import UserRepo`, `from capybara.services.user_service import UserService`.
  - Add providers:

```python
def get_user_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRepo:
    """Return a UserRepo bound to the current request session."""
    return UserRepo(session)


def get_user_service(
    users: Annotated[UserRepo, Depends(get_user_repo)],
) -> UserService:
    """Return a UserService wired with the request-scoped UserRepo."""
    return UserService(users)
```
  - Replace `get_current_user` (remove the `LOCAL_USER_ID` lookup and the constant) with:

```python
async def get_current_user() -> User:
    """Resolve the authenticated user — 401 until the login slice exists."""
    raise HTTPException(status_code=401, detail="Authentication required")
```
  - Delete the `LOCAL_USER_ID = UUID(...)` constant. Grep for any remaining `LOCAL_USER_ID` reference in `src` and `tests` and remove/fix it (tests override `get_current_user`, so none should remain in src).

- [ ] **Step 3: Create the router** — `src/capybara/api/routers/users.py`

```python
"""Router for user registration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.api.dependencies import get_user_service
from capybara.api.schemas import UserCreate, UserOut
from capybara.services.user_service import UserService, UsernameTaken

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(
    payload: UserCreate,
    users: Annotated[UserService, Depends(get_user_service)],
) -> UserOut:
    """Register a new local user; 409 if the username is already taken."""
    try:
        user = await users.register(payload.display_name, payload.username, payload.password)
    except UsernameTaken:
        raise HTTPException(status_code=409, detail="Username already taken") from None
    return UserOut.model_validate(user)
```

- [ ] **Step 4: Wire the router** — `src/capybara/main.py` in `create_app`, import and include it:

```python
    from capybara.api.routers import chats, health, users

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(chats.router)
    fastapi_app.include_router(users.router)
```

- [ ] **Step 5: Write the API tests** — `tests/test_users_api.py`

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from capybara.api.dependencies import get_session
from capybara.db.models import User
from capybara.main import app


@pytest_asyncio.fixture
async def client(engine):  # type: ignore[no-untyped-def]
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)

    async def _override_session():
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

    async with maker() as cleanup:
        for row in (await cleanup.execute(select(User))).scalars().all():
            await cleanup.delete(row)
        await cleanup.commit()


async def test_register_success(client: AsyncClient, engine) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/users",
        json={"display_name": "Роман", "username": "roman", "password": "password123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "roman"
    assert body["display_name"] == "Роман"
    assert "password" not in body and "password_hash" not in body

    from capybara.db.engine import create_sessionmaker

    async with create_sessionmaker(engine)() as sess:
        user = (
            await sess.execute(select(User).where(User.username == "roman"))
        ).scalar_one()
        assert user.password_hash.startswith("$argon2")
        assert user.password_hash != "password123"


async def test_register_duplicate_username_conflict(client: AsyncClient) -> None:
    payload = {"display_name": "Роман", "username": "roman", "password": "password123"}
    assert (await client.post("/users", json=payload)).status_code == 201
    dup = await client.post(
        "/users",
        json={"display_name": "Other", "username": "roman", "password": "password456"},
    )
    assert dup.status_code == 409


async def test_register_short_password_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/users",
        json={"display_name": "Роман", "username": "roman", "password": "short"},
    )
    assert resp.status_code == 422


async def test_register_missing_field_422(client: AsyncClient) -> None:
    resp = await client.post("/users", json={"username": "roman", "password": "password123"})
    assert resp.status_code == 422
```
Note: this `client` fixture cleans up created users afterward (registration commits real rows, unlike the per-test-rollback `session` fixture). If cross-test isolation still bites (e.g. `roman` persists), give each test a distinct username instead.

- [ ] **Step 6: Run full suite + gates**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src`
Expected: all green; chat tests still pass (they override `get_current_user`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: POST /users registration endpoint; get_current_user returns 401"
```

---

## Self-Review

**Spec coverage:**
- argon2 hashing / `security/passwords.py` → Task 1. ✔
- `password_hash` column + migration (drop seed, add NOT NULL) → Task 2. ✔
- `make_user` fixture → Task 2. ✔
- `UserRepo.get_by_username` + `UserService.register` + `UsernameTaken` → Task 3. ✔
- `POST /users`, `UserCreate`/`UserOut` (no hash), validation, 409/422 → Task 4. ✔
- `get_current_user` → 401; remove `LOCAL_USER_ID` → Task 4. ✔
- reusable `get_user_repo`/`get_user_service` deps → Task 4. ✔
- registration tests (success/no-hash/argon2-stored/409/422); migration test updated → Tasks 2, 4. ✔
- chat tests stay green (override `get_current_user`) → verified in Tasks 2 & 4 full-suite runs. ✔

**Placeholder scan:** none — every step has concrete code/commands. The `down_revision` value in Task 2's migration is filled from the current head at implementation (Alembic assigns it); that is a real value the tool provides, not a placeholder.

**Type consistency:** `hash_password(str) -> str` (Tasks 1,2,3); `UserRepo.get_by_username(str) -> User | None` (Task 3) consumed by `UserService.register` (Task 3); `UserService(users).register(display_name, username, password) -> User` used by the router (Task 4); `get_user_service -> UserService` (Task 4) matches the router's `Depends`. `UserCreate`/`UserOut` names consistent between schemas and router.

## Notes
- Do tasks 1→4 in order.
- Deferred (next slice): login endpoint, session/token, logout, real `get_current_user`, `verify_password`.
