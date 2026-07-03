# Login (JWT) — Design (Slice 3, auth increment)

**Date:** 2026-07-03
**Status:** Approved (design), pending implementation plan
**Slice:** Login — authenticate a registered user and resolve the current user

## 1. Purpose & scope

Let a registered user log in with username + password and receive a stateless **JWT**
bearer token. Protected endpoints resolve the current user from the token, re-enabling the
chat endpoints (which have returned 401 since the registration slice removed the seed).

**In scope:** `POST /auth/login`, argon2 `verify_password`, JWT create/decode
(`security/tokens.py`), `AuthService.login`, a real `get_current_user` (Bearer → user),
config for the JWT secret/TTL/algorithm, and tests.

**Out of scope (deliberate):**
- **Logout endpoint** — with stateless JWT there is nothing to invalidate server-side without
  a denylist (which would reintroduce state). Logout = the client discards its token; the
  fixed TTL bounds exposure. Revisit only if forced revocation is needed.
- Refresh tokens, "remember me", password reset, multi-device session management.

**Success criteria:**
- `POST /auth/login {username, password}` with valid credentials → `200`
  `{access_token, token_type: "bearer"}`.
- Wrong password OR unknown username → `401` with the SAME generic error (no user enumeration).
- A request to a protected route (e.g. `GET /chats`) with `Authorization: Bearer <token>`
  resolves the token's user; missing/invalid/expired token → `401`.
- `uv run pytest`, `uv run ruff check .`, `uv run mypy src` all pass.

## 2. Components

- **Dependency:** add `pyjwt` to `pyproject.toml`.
- **`config.py`:** `Settings` gains `jwt_secret: str` (required, from env — must be stable across
  restarts or all tokens invalidate), `jwt_ttl_minutes: int = 43200` (30 days),
  `jwt_algorithm: str = "HS256"`. Add to `.env.example`.
- **`security/passwords.py`:** add `verify_password(password: str, password_hash: str) -> bool`
  using argon2 `PasswordHasher.verify`, returning `False` on `VerifyMismatchError` (and other
  argon2 verify errors) instead of raising.
- **`security/tokens.py`:** `create_access_token(user_id: UUID, *, secret: str, ttl_minutes: int,
  algorithm: str = "HS256") -> str` (payload `sub=str(user_id)`, `iat`, `exp`);
  `decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> UUID` — raises
  `jwt`-level errors on invalid/expired signatures; returns the `sub` as a `UUID`.
- **`services/auth_service.py`:** `InvalidCredentials(Exception)`; `AuthService(users: UserRepo,
  secret: str, ttl_minutes: int, algorithm: str)` with
  `login(username: str, password: str) -> str`: fetch by username; if missing OR
  `verify_password` fails → raise `InvalidCredentials`; else return a freshly issued token.
  The same error for both branches prevents username enumeration.
- **`api/dependencies.py`:**
  - `get_settings_dep(request) -> Settings` (from `app.state.settings`).
  - `get_auth_service(users, settings) -> AuthService`.
  - Rewrite `get_current_user`: use `fastapi.security.HTTPBearer` to extract the token, then
    `decode_access_token` (with the settings' secret/algorithm) → load the `User` via `UserRepo`;
    raise `HTTPException(401)` on a missing/invalid/expired token or a user that no longer exists.
- **`api/schemas.py`:** `LoginRequest(username, password)`; `TokenResponse(access_token: str,
  token_type: str = "bearer")`.
- **`api/routers/auth.py`:** `POST /auth/login` → `AuthService.login`; map `InvalidCredentials`
  → `HTTPException(401, "Invalid credentials")`. Wire the router in `main.py`.

## 3. Data flow

**Login:** `POST /auth/login` → validate body → `AuthService.login` fetches the user, verifies
the password (argon2), issues a JWT (`sub`, `exp`) → `200 {access_token, token_type}`.

**Authenticated request:** client sends `Authorization: Bearer <token>` → `get_current_user`
extracts + decodes the JWT, loads the user, and returns it; downstream chat deps proceed as
before. Invalid/missing/expired → `401`.

## 4. Error handling

- Invalid login body → `422`.
- Wrong password / unknown username → `401` "Invalid credentials" (identical for both).
- Missing/invalid/expired/tampered token, or token whose user was deleted → `401`.
- The JWT secret is server-side config; never returned to clients. Passwords are never logged.

## 5. Testing

- **Tokens (`security/tokens.py`):** create→decode round-trip returns the same `UUID`; an expired
  token (issue with a past/zero TTL) raises on decode; a token signed with a different secret or
  tampered payload raises on decode.
- **`verify_password`:** correct password → `True`; wrong password → `False` (no raise).
- **`AuthService.login`:** valid creds → a token that decodes to the user's id; wrong password →
  `InvalidCredentials`; unknown username → `InvalidCredentials`.
- **API:** `POST /auth/login` valid → `200` + `token_type == "bearer"` + decodable token; bad
  creds → `401`; missing field → `422`. **Integration for `get_current_user`:** `GET /chats`
  with a valid `Authorization: Bearer <token>` returns the user's chats (no dependency override);
  without a token or with a garbage token → `401`.
- The `settings` test fixture gains a `jwt_secret` (and default ttl/algorithm). Existing chat
  tests keep overriding `get_current_user` (still valid) and stay green.

## 6. Notes / deferred

- No server logout (stateless); client discards the token.
- Deferred: refresh tokens, denylist/forced revocation, password reset, `created_by`/`updated_by`
  audit mixin.
- `verify_password` may later use argon2 `check_needs_rehash` to upgrade stored hashes on login
  (not in this slice).
