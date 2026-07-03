# CLAUDE.md

Guidance for working in the CapybaraAgent repository.

## What this project is

CapybaraAgent is a **local-first AI agent** with a desktop chat UI. Everything runs on
the user's machine; profiles, chats and keys stay local.

- `design_handoff_capybaraagent/` — a high-fidelity **frontend** design handoff (HTML
  prototype + tokens). It is the source of truth for UI look/behaviour, **not** production
  code. The frontend is out of scope until its own slice.
- The current work is the **Python backend** that the UI will talk to over HTTP/SSE.

### Product surface (full vision)

The full agent (built incrementally) covers: a chat engine with streaming and
tool-calling, an **MCP client** (attach tool servers), **memory** (facts + chat history),
**background tasks** on a cron schedule, and **local auth** (device-local profiles).
See `design_handoff_capybaraagent/README.md` for the UI spec of each.

## How work is sliced

Work ships as **vertical slices**, each with its own spec in `docs/superpowers/specs/`.
Do not build subsystems that are not in the current slice.

- **Slice 1 (current): backend chat core** — create chat, send message, stream the LLM
  reply via SSE, persist chats/messages to Postgres. No MCP, memory-facts, cron, auth, or
  frontend yet. A `users` table exists with one seeded local user (no login) for
  forward-compatibility.

## Tech stack

- **Language:** Python 3.12+, fully type-annotated.
- **Web:** FastAPI, streaming via **SSE**.
- **LLM:** [pydantic-ai](https://ai.pydantic.dev) — provider-agnostic. First provider is
  **Ollama running on the host** (reached via `host.docker.internal`); the design stays
  provider-agnostic (OpenAI/OpenRouter/Ollama planned).
- **Persistence:** PostgreSQL + **SQLAlchemy 2.0 (async)** + **Alembic** migrations.
- **Packaging/deps:** **uv**.
- **Quality gates:** **ruff** (lint + format) and **mypy** (strict).
- **Runtime:** Docker + docker-compose (`api` + `postgres`; Ollama on host).

## Architecture & conventions

Layered and built for extension — these apply from the first slice, not later:

- **Layering:** `api` (routers + Pydantic schemas) → `services` (orchestration) →
  `repositories` (data access) → `db` (models, engine, session). Keep boundaries explicit;
  no DB queries in routers or services.
- **Repository pattern:** all model/DB access goes through repositories. No ad-hoc queries
  scattered across the codebase.
- **Reusable FastAPI dependencies:** design dependencies (session, current user, repos,
  services) to be reused across future subsystems — not one-off per endpoint.
- **SQLAlchemy sessions:** one async session per request via a dependency; the engine lives
  in the app lifespan; commit/rollback boundaries are explicit. Get this right up front.
- **Provider-agnostic LLM:** talk to the model through a thin agent abstraction so
  providers can be swapped/added without touching services.
- **Typing:** strict mypy; prefer explicit types at module boundaries.
- **Docstrings:** every module, class, and function/method has a docstring stating what it
  does — enforced by ruff pydocstyle (`select = D`, google convention; tests exempt).
- **Testing (TDD):** write tests first. Use pydantic-ai `TestModel`/`FunctionModel` to
  avoid hitting a real LLM; test repositories/services/API against a real Postgres
  (testcontainers) with per-test transactional isolation.

## Repository layout (target)

```
src/capybara/
  config.py            # pydantic-settings
  main.py              # FastAPI app, lifespan, router wiring, /health
  api/                 # routers + request/response schemas + dependencies
  services/            # orchestration (e.g. chat_service)
  repositories/        # repository-pattern data access
  db/                  # models, engine, async session
  agent/               # pydantic-ai agent + provider config
  migrations/          # Alembic
tests/
docs/superpowers/specs/  # per-slice design docs
```

## Commands

The backend is scaffolded per the current slice's spec. Intended toolchain:

```bash
uv sync                          # install deps
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy src                  # type-check
uv run pytest                    # tests
uv run alembic upgrade head      # apply migrations
docker compose up --build        # run api + postgres (Ollama on host)
```

## Working agreement

- The user reviews backend code between iterations — keep changes reviewable and scoped to
  the current slice.
- Follow the active spec in `docs/superpowers/specs/`; when something is ambiguous, ask
  rather than guess.
