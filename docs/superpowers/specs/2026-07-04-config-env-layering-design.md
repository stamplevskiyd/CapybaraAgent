# Config: composite DB settings + two-level .env — Design

**Date:** 2026-07-04
**Status:** Approved (pending spec review)
**Type:** Architecture improvement (config), not a bug fix

## Problem

Configuration is currently tangled and duplicated:

- Postgres credentials live as a single opaque `DATABASE_URL` string. The same
  `postgresql+asyncpg://capybara:capybara@localhost:5432/capybara` is duplicated
  between the committed `.env.example` and `docker-compose.yml`.
- `docker-compose.yml` hardcodes application config (`OLLAMA_BASE_URL`,
  `DEFAULT_MODEL`, `JWT_SECRET`) and the postgres container credentials
  (`POSTGRES_USER/PASSWORD/DB`) independently of the app's URL — two sources of
  truth for the same credentials.
- There is a single `.env.example` template with no layering: no committed
  non-secret defaults that the stack actually loads, and no clean place for
  per-developer overrides/secrets.

## Goals

1. Store Postgres credentials as **separate** settings (user, password, host,
   port, db) and **derive** `DATABASE_URL` from them — one source of truth shared
   by the postgres container and the API.
2. Introduce a **two-level `.env` scheme** (Superset-style), wired at the
   docker-compose `env_file` level *and* honoured by pydantic-settings for local
   `uv run`:
   - `.env.defaults` — committed, non-secret dev defaults.
   - `.env` — gitignored, per-developer overrides/secrets; later in the chain, so
     it wins over the defaults.
3. Remove the `DATABASE_URL` duplication between `.env.example` and compose.
4. Remove **all** app config (Ollama URL, model, secret) hardcoded in
   `docker-compose.yml`; those come from the env files. Ports/wiring stay in
   compose.

## Precedence model

Effective value resolution, lowest to highest priority:

1. pydantic field defaults in `Settings` (last-resort fallback).
2. `.env.defaults` (committed).
3. `.env` (gitignored override) — **wins over `.env.defaults`**.
4. Real process environment variables (what docker-compose injects from the
   `env_file` list, or an exported shell var) — **win over all dotenv files**.

`.env` is deliberately the override name: it is what developers reach for, and it
is the default both for pydantic-settings and for docker-compose's own file
handling. A password placed in `.env` therefore overrides `.env.defaults` in both
the local `uv run` and the docker-compose contexts. (There is no separate
`.env.local`; it would be silently ignored and is not used.)

## Non-goals

- No change to JWT, Ollama, or model settings beyond moving them into the env
  files (they remain single scalar vars).
- No secrets manager / vault integration (YAGNI for a local-first app).
- No change to application/runtime behaviour — this is purely configuration
  plumbing.

## Design

### 1. `config.py` — `Settings`

- Remove the `database_url: str` field.
- Add composite Postgres fields with dev-first defaults:
  - `postgres_user: str = "capybara"`
  - `postgres_password: str = "capybara"`
  - `postgres_host: str = "postgres"`  (docker-first; local dev overrides to `localhost`)
  - `postgres_port: int = 5432`
  - `postgres_db: str = "capybara"`
- Add a computed `database_url` property:
  `postgresql+asyncpg://{quote(user)}:{quote(password)}@{host}:{port}/{db}`.
  User and password are URL-encoded via `urllib.parse.quote` so special
  characters in a password can't corrupt the URL.
- `model_config`: `env_file=(".env.defaults", ".env")`, `extra="ignore"`.
  pydantic-settings applies the **last** file in the tuple with higher priority,
  and real environment variables (injected by compose) outrank both dotenv files.
  Missing env files are ignored. (Tuple order — last-wins — is verified against
  pydantic-settings during implementation; reverse the tuple if the library
  resolves first-wins.)

Downstream consumers (`db/engine.py`, `migrations/env.py`, `main.py`) keep using
`settings.database_url` unchanged — it is now a property instead of a field.

### 2. Env files

`.env.defaults` (committed, non-secret):

```
# Postgres — consumed by both the postgres container and the API.
# For local `uv run` (outside docker), override POSTGRES_HOST=localhost in .env.
POSTGRES_USER=capybara
POSTGRES_PASSWORD=capybara
POSTGRES_DB=capybara
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# LLM
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_MODEL=llama3.1

# Auth — dev-only secret so `docker compose up` boots zero-config.
# Set a real JWT_SECRET (and any overrides) in .env.
JWT_SECRET=dev-insecure-jwt-secret-change-me-please
JWT_TTL_MINUTES=43200
JWT_ALGORITHM=HS256
```

`.env` (gitignored, not committed): per-developer overrides/secrets. Optional —
absence is fine. Any key set here overrides `.env.defaults`.

`.env.example` is **deleted**; `.env.defaults` supersedes it as both the loaded
defaults and the documentation of available keys.

### 3. `docker-compose.yml`

Both services load the same env files:

```yaml
env_file:
  - .env.defaults
  - path: .env
    required: false
```

- `postgres`: drop the hardcoded `environment:` block; the official image reads
  `POSTGRES_USER/PASSWORD/DB` from the env files. Healthcheck uses
  `pg_isready -U $$POSTGRES_USER`. Ports/volume unchanged.
- `api`: drop the entire `environment:` block. `DATABASE_URL` is no longer set
  anywhere — the app derives it from `POSTGRES_*` (host=`postgres` from
  defaults). `build`, `depends_on`, `extra_hosts`, `ports` unchanged.

Requires Docker Compose that supports the `env_file` entry `required: false`
(Compose v2.24+).

### 4. `.gitignore` / `.dockerignore`

- `.gitignore`: **no change needed** — it already ignores `.env` (the override),
  and `.env.defaults` is not matched, so it stays tracked.
- `.dockerignore`: ignore `.env*` — env files are not baked into the image;
  compose injects the variables host-side and pydantic reads them from
  `os.environ` inside the container.

### 5. Tests

- `conftest.py`: the postgres fixture yields the `PostgresContainer`; the
  `settings` fixture builds `Settings` from container **parts**
  (`.username`, `.password`, host ip, exposed port, `.dbname`) instead of a URL
  string. Explicit kwargs override any dotenv values.
- `test_config.py`: `test_settings_read_from_env` switches to `POSTGRES_*` env
  vars and asserts the **derived** `database_url`. The short-`JWT_SECRET` test is
  updated to the new fields (no `DATABASE_URL`).

### 6. `README.md`

Add a short **Configuration** section: `docker compose up` works out of the box
from `.env.defaults`; for local `uv run` create a `.env` with
`POSTGRES_HOST=localhost` and your own `JWT_SECRET`.

## Data flow

```
.env.defaults ─┐                         ┌─ postgres container (POSTGRES_USER/PASSWORD/DB)
               ├─ compose env_file ──────┤
.env (override)┘                         └─ api container env ─┐
                                                               ├─ pydantic Settings ─ database_url property
local `uv run`: pydantic reads .env.defaults then .env ────────┘
```

Single source of truth for DB credentials: the `POSTGRES_*` variables. Both the
database container and the application's derived URL read the same values.

## Testing strategy

- Unit: `test_config.py` verifies the derived `database_url` from `POSTGRES_*`
  and that a short `JWT_SECRET` is rejected.
- Integration: the existing testcontainers-backed suite must stay green with the
  `settings` fixture built from parts (proves the derived URL connects).
- Manual/CI-not-required: `docker compose config` validates the compose file;
  `docker compose up` boots zero-config from `.env.defaults`.

## Risks / trade-offs

- **Committed dev `JWT_SECRET`.** Intentional: it is a non-secret placeholder so
  the stack boots zero-config. Real values live only in `.env`. Documented in
  `.env.defaults`.
- **`POSTGRES_HOST=postgres` default** means a bare local `uv run` fails until
  the developer sets `POSTGRES_HOST=localhost` in `.env`. Accepted:
  `docker compose up` is the documented primary run path; tests use
  testcontainers.
- **Compose `required: false`** needs a reasonably recent Compose. Acceptable for
  a dev-tooling repo.
