# User Registration — Design (Slice 2, first auth increment)

**Date:** 2026-07-03
**Status:** Approved (design), pending implementation plan
**Slice:** First increment of local auth — user registration only

## 1. Purpose & scope

Let a user register a local profile with a **display name**, **login** (the existing
`username`, unique), and **password**. Passwords are stored only as an argon2 hash. Replace
the seeded local user with real registration.

**In scope:** `POST /users` registration endpoint, argon2 password hashing, `password_hash`
column + migration, `UserRepo.get_by_username`, `UserService.register`, reusable user
dependencies, a reusable test fixture that creates a user, and registration tests.

**Out of scope (next slice — login):** login endpoint, session/token issuance, logout, and
resolving the *authenticated* current user. Because the seeded user is removed and no login
exists yet, `get_current_user` returns **HTTP 401** in this slice, so the chat endpoints are
non-functional in the running app until the login slice. Tests that need a current user
override `get_current_user` (they already do).

**Success criteria:**
- `POST /users {display_name, username, password}` → `201` with `{id, username, display_name, created_at}` and NO password/hash in the response.
- The stored `password_hash` is an argon2 hash (not the plaintext).
- Duplicate `username` → `409`; invalid input (short password, missing fields) → `422`.
- The seed migration no longer leaves a `roman` user; `users.password_hash` exists.
- `uv run pytest`, `uv run ruff check .`, `uv run mypy src` all pass; chat tests stay green.

## 2. Components

- **`src/capybara/security/passwords.py`** — `hash_password(plain: str) -> str` using
  `argon2.PasswordHasher` (library defaults for salt/params). `verify_password` is deferred
  to the login slice (YAGNI). New dependency: `argon2-cffi`.
- **`db/models/user.py`** — add `password_hash: Mapped[str]` (`String(255)`, NOT NULL). Keep
  `username` (unique, the login), `display_name`, timestamps.
- **Migration** — append-only: (a) delete the seeded user, then (b) add `password_hash`
  NOT NULL (table is empty after the delete on a fresh DB, so NOT NULL is safe). Downgrade
  drops the column and re-inserts the seed user. Remove the now-unused `LOCAL_USER_ID`
  constant from `dependencies.py`.
- **`repositories/user_repo.py`** — add `get_by_username(username: str) -> User | None`
  (used for a clean duplicate check; the DB unique constraint is the backstop).
- **`services/user_service.py`** — `UserService(users: UserRepo)` with
  `register(display_name: str, username: str, password: str) -> User`: raise a domain
  `UsernameTaken` error if `get_by_username` finds a row; otherwise hash the password and
  `users.create(...)`. Thin router, logic in the service (matches the api→services→repos
  layering).
- **`api/schemas.py`** — `UserCreate(display_name, username, password)` with validation
  (password `min_length=8`; username `min_length=3, max_length=64`; display_name
  `min_length=1, max_length=128`); `UserOut(id, username, display_name, created_at)` with
  `from_attributes` — never includes the hash.
- **`api/dependencies.py`** — `get_user_repo(session) -> UserRepo`,
  `get_user_service(users) -> UserService` (reusable). Change `get_current_user` to raise
  `HTTPException(401, "Authentication required")` (seed gone; login not built yet).
- **`api/routers/users.py`** — `POST /users` → calls `UserService.register`; maps
  `UsernameTaken` → `409`. Wire the router in `main.py`.

## 3. Data flow — registration

1. `POST /users` validates the body (Pydantic → `422` on bad input).
2. `UserService.register` checks `get_by_username` → `UsernameTaken` (→ `409`) if present.
3. Hash the password with argon2.
4. `UserRepo.create(username=..., display_name=..., password_hash=...)`; the request session
   commits at dependency teardown.
5. Return `UserOut` (no hash).

## 4. Error handling

- Invalid/missing fields → `422` (FastAPI/Pydantic).
- Duplicate username → `409` (`UsernameTaken` mapped in the router). The DB unique constraint
  is a backstop against a race; if it fires, surface `409` as well.
- The password/hash is never serialized (separate `UserOut` schema, not the ORM model).

## 5. Testing

- **New fixture:** `create_user` — a factory fixture that inserts a `User`
  (username, display_name, argon2 `password_hash`) into the test DB and returns it; reusable
  by chat tests and future auth tests.
- **Registration tests:** success (`201`, response shape, no password field); the stored
  `password_hash` is an argon2 string (starts with `$argon2`) and NOT the plaintext; duplicate
  username → `409`; short password / missing field → `422`.
- **Migration test:** update `test_migrations` — assert NO seeded `roman` user and that
  `users.password_hash` column exists.
- Chat tests stay green (they seed/override their own user and override `get_current_user`).

## 6. Notes / deferred

- Login, session/token, logout, and real `get_current_user` resolution = next slice.
- `verify_password` lands with the login slice.
- `created_by`/`updated_by` audit mixin remains a future idea.
