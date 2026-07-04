# Chat Core Backend — Design (Slice 1)

**Date:** 2026-07-02
**Status:** Approved (design), pending implementation plan
**Slice:** First vertical slice of the CapybaraAgent backend

## 1. Purpose & scope

Build the backend chat core: a user creates a chat, sends a message, and receives the
LLM's reply as a live token stream over SSE; chats and messages persist in Postgres. The
service runs via `docker compose`.

**In scope:** FastAPI app, SSE streaming, pydantic-ai agent against Ollama (on host),
Postgres persistence (SQLAlchemy 2.0 async + Alembic), Docker packaging, ruff + mypy + uv,
tests.

**Out of scope (later slices):** MCP client, memory/facts, cron background tasks, auth
(login/passwords), the frontend UI, multiple concurrent LLM providers, tool-calling.

**Success criteria:**
- `POST /chats/{id}/messages` streams a real Ollama completion token-by-token over SSE.
- User and assistant messages are persisted; history is included in the next request.
- `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` all pass.
- `docker compose up` brings up `api` + `postgres` and serves `/health`.

## 2. Architecture

Layered, built for extension (see CLAUDE.md → Architecture & conventions):

```
api (routers, schemas, dependencies)
  → services (chat orchestration)
    → repositories (ChatRepo, MessageRepo, UserRepo)
      → db (models, async engine, session)
  → agent (pydantic-ai Agent + Ollama provider)
```

Chosen over a flat layout (would smear service logic into routers) and full
hexagonal/ports-and-adapters (overkill for now — YAGNI). This middle layout pays off when
MCP/memory/cron are added.

### Modules (`src/capybara/`)

- **`config.py`** — `pydantic-settings` Settings: `database_url`, `ollama_base_url`,
  `default_model`, etc. Loaded once, injected via dependency.
- **`db/`** — async engine + `async_sessionmaker`; declarative models; base metadata.
- **`repositories/`** — `UserRepo`, `ChatRepo`, `MessageRepo`. All DB access lives here.
  Each takes an `AsyncSession`. No queries outside this layer.
- **`agent/`** — builds a pydantic-ai `Agent` configured for Ollama via its
  OpenAI-compatible endpoint; exposes a thin streaming interface so providers stay
  swappable. LLM never touched directly by services.
- **`services/chat_service.py`** — orchestrates a turn: persist user message → load history
  → run agent stream → yield deltas → persist assistant message (+usage).
- **`api/`** — routers, Pydantic request/response schemas, and **reusable dependencies**
  (`get_session`, `get_current_user`, repo/service providers).
- **`main.py`** — FastAPI app; lifespan owns the engine; wires routers; `/health`.
- **`migrations/`** — Alembic (async).

## 3. Data model

- **`users`** — `id` (uuid pk), `username` (unique), `display_name`, `created_at`.
  One local user seeded by migration. No password/login yet (forward-compatible with the
  future auth slice).
- **`chats`** — `id` (uuid pk), `user_id` (fk→users), `title`, `created_at`, `updated_at`.
- **`messages`** — `id` (uuid pk), `chat_id` (fk→chats), `role`
  (`user` | `assistant` | `system`), `content` (text), `model` (nullable), `usage_json`
  (nullable jsonb), `incomplete` (bool, default false), `created_at`.

Indexes: `messages.chat_id`, `chats.user_id`. Timestamps in UTC.

## 4. API contract

| Method & path | Body | Response |
| --- | --- | --- |
| `POST /chats` | `{ "title"?: str }` | `201` chat object |
| `GET /chats` | — | list of chats (for the local user) |
| `GET /chats/{id}` | — | chat + ordered messages (`404` if missing) |
| `POST /chats/{id}/messages` | `{ "content": str }` | `text/event-stream` (SSE) |
| `GET /health` | — | `{ "status": "ok", "ollama": "up"\|"down" }` |

### SSE event schema (`POST /chats/{id}/messages`)

- `event: delta` — `data: { "text": "<chunk>" }` (repeated)
- `event: done`  — `data: { "message_id": "<uuid>" | null, "usage": {...} }`
  (`null` only when the provider completes with no assistant text and no blank assistant
  row is persisted).
- `event: error` — `data: { "message": "<safe message>" }`

The user message is persisted before streaming begins, so a failed stream still leaves a
coherent history.

## 5. Data flow — send message

1. Validate chat exists and belongs to the local user (`404` otherwise).
2. `MessageRepo` persists the user message; commit.
3. `ChatRepo`/`MessageRepo` load ordered history for the chat.
4. `agent` runs `run_stream(history)` against Ollama.
5. Each delta is emitted as an SSE `delta` event.
6. On completion: persist the assistant message with `model` + `usage_json`; emit `done`.
7. Bump `chats.updated_at`.

## 6. Error handling

- **Ollama unreachable:** `/health` reports `ollama: down`; a streaming request emits an
  SSE `error` event and stops (user message already saved).
- **Validation errors:** FastAPI `422`. **Missing chat:** `404`.
- **DB errors:** `500` with a safe message; details logged, transaction rolled back.
- **Client disconnects mid-stream:** cancel the agent run and persist the partial assistant
  message with `incomplete = true` so history is not lost.

## 7. Session & dependency discipline

- One `AsyncSession` per request via a `get_session` dependency; the engine lives in the
  app lifespan.
- Explicit commit/rollback boundaries; the session dependency rolls back on unhandled
  exceptions.
- Repositories and services are provided by reusable dependencies so future subsystems
  reuse them unchanged.

## 8. Testing (TDD)

- **Agent:** pydantic-ai `TestModel` / `FunctionModel` — no real Ollama in tests.
- **Repositories & services:** real Postgres via testcontainers, per-test transactional
  rollback for isolation.
- **API:** integration test of the SSE endpoint backed by `TestModel`, asserting the
  `delta` → `done` sequence and that messages persist.
- **Health:** `/health` with Ollama reachable and unreachable.

## 9. Infrastructure & tooling

- **`docker-compose.yml`:** `api` (uv-based image) + `postgres` (named volume). Ollama runs
  on the host; `ollama_base_url` defaults to `http://host.docker.internal:11434`.
- **`Dockerfile`:** multi-stage, uv for dependency install.
- **`pyproject.toml`:** project + dependency groups; strict mypy config; ruff lint + format.
- **`.env.example`:** `DATABASE_URL`, `OLLAMA_BASE_URL`, `DEFAULT_MODEL`.
- **`alembic.ini` + async env:** migrations, incl. the seed-user migration.

## 10. Open questions / deferred

- Concrete default Ollama model name (e.g. `llama3.1`) — pick at implementation, config-driven.
- Auth, MCP, memory-facts, cron, and the frontend are explicitly deferred to their own slices.
