# CLAUDE.md

Guidance for working in the CapybaraAgent repository.

## What this project is

CapybaraAgent is a **local-first AI agent** with a desktop chat UI. Everything runs on
the user's machine; profiles, chats and keys stay local.

- `frontend/` — the Vite/React app (custom design shell). It renders chat through
  Chainlit's React client and calls the custom REST APIs for memory/MCP/prefs.
- `design_handoff_capybaraagent/` — the high-fidelity design handoff (HTML prototype +
  tokens). It is the source of truth for UI look/behaviour, **not** production code.
- `src/capybara/` — the Python backend: a FastAPI shell with the Chainlit runtime
  mounted under `/chainlit` and custom domain APIs beside it.

### Product surface (full vision)

The full agent (built incrementally) covers: a chat engine with streaming and
tool-calling, an **MCP client** (attach tool servers), **memory** (facts + chat history),
**background tasks** on a cron schedule, and **local auth** (device-local profiles).
See `design_handoff_capybaraagent/README.md` for the UI spec of each.

## How work is sliced

Work ships as **vertical slices**, each with its own spec in `docs/superpowers/specs/`.
Do not build subsystems that are not in the current slice. Shipped so far: chat via
Chainlit + DeepAgents, local auth (JWT), memory facts with semantic recall, MCP client
(attach/curate remote servers), per-thread chat settings.

## Tech stack

- **Language:** Python 3.12+, fully type-annotated.
- **Chat runtime:** **Chainlit** (mounted into FastAPI) owns sessions, streaming,
  steps, and thread persistence (its tables live in a dedicated `chainlit` Postgres
  schema). The frontend talks to it through `@chainlit/react-client`.
- **Agent:** **DeepAgents** (LangGraph) — the graph is rebuilt per turn with the
  selected model and the current user's tools; an `InMemorySaver` checkpointer keyed
  by thread id carries conversation state. Providers are abstracted behind
  `agent/model_registry.py::ModelRegistry`; the first provider is **Ollama on the host**
  (`host.docker.internal`), OpenAI/OpenRouter planned.
- **Web:** FastAPI for the custom domain APIs (auth, users, memory, MCP, chat-settings,
  models, health).
- **Persistence:** PostgreSQL (+pgvector) + **SQLAlchemy 2.0 (async)** + **Alembic**.
- **Packaging/deps:** **uv**. **Quality gates:** **ruff** (lint + format), **mypy** (strict).
- **Runtime:** Docker + docker-compose (`api` + `postgres` + `frontend`; Ollama on host).

## Architecture & conventions

Layering: `api` (routers + Pydantic schemas + dependencies) → `commands` (use cases) →
`repositories` (data access) → `db` (models, engine, session). The `agent/` package
(DeepAgents runner, tools, model registry, MCP adapter) depends on narrow callables
wired to commands in the app lifespan — never on command classes.

- **Commands:** every use case (reads and mutations) is a command —
  `commands/<entity>/<action>.py`, one class per action, inheriting
  `commands/base.py::BaseCommand[ResultT]`. `validate()` holds I/O prechecks
  (ownership, uniqueness); input *format* validation stays on the API schemas;
  checks that must be transactional with the write live in `run()`.
  `execute()` = validate + run. Dependencies are explicit constructor arguments;
  routers build commands from the `Annotated` aliases in `api/dependencies.py`
  (`CurrentUser`, `Sessionmaker`, `Registry`, `AppSettings`).
- **Repositories:** all DB access goes through repositories. `BaseRepository` carries
  the common surface — `get`, `get_one`, `get_list` (with `Filter`-based
  `default_filters` and a `bypass_default_filters` flag), `create`/`update` (accept a
  pydantic payload and/or kwargs), `delete`. Subclasses only bind `model` and add
  genuinely custom queries (e.g. `FactRepo.search`). Reusable filters live in
  `filters/` (`Filter` ABC, `FieldEquals`).
- **SQLAlchemy sessions:** commands own short-lived sessions from the app-wide
  sessionmaker (never a request session); the engine lives in the app lifespan;
  commit boundaries are explicit. The REST layer's `get_session` dependency exists
  for auth resolution.
- **Typing:** strict mypy; prefer explicit types at module boundaries.
- **Docstrings:** every module, class, and function/method has a docstring — enforced
  by ruff pydocstyle (`select = D`, google convention; tests and migration versions
  exempt).
- **Testing (TDD):** write tests first. Fake `ModelRegistry` (see `tests/support.py`)
  instead of hitting a real LLM; test commands/repositories/API against a real
  Postgres (testcontainers). Frontend: vitest + msw (needs node ≥ 20).

## Repository layout

```
src/capybara/
  config.py            # pydantic-settings
  app.py               # FastAPI app, lifespan wiring, Chainlit mount
  main.py              # ASGI entrypoint
  chainlit_app.py      # Chainlit callbacks: auth, data layer, on_message
  api/                 # routers + request/response schemas + dependencies
  commands/            # use cases: <entity>/<action>.py, base.py
  repositories/        # repository-pattern data access
  filters/             # composable query filters (Filter ABC, FieldEquals)
  db/                  # models, engine, base, mixins
  agent/               # DeepAgents runner, tools, ModelRegistry, MCP adapter
  migrations/          # Alembic (single baseline revision)
tests/
frontend/              # Vite/React app (custom shell + Chainlit react-client)
docs/superpowers/specs/  # per-slice design docs
```

## Commands

```bash
uv sync                          # install deps
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy src                  # type-check
uv run pytest                    # tests (needs Docker for testcontainers)
uv run alembic upgrade head      # apply migrations
docker compose up --build        # run api + postgres + frontend (Ollama on host)
cd frontend && npm test          # frontend tests (node >= 20)
```

## Working agreement

- The user reviews backend code between iterations — keep changes reviewable and scoped
  to the current slice.
- Follow the active spec in `docs/superpowers/specs/`; when something is ambiguous, ask
  rather than guess.
