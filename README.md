# CapybaraAgent

A **local-first AI agent** with a desktop chat UI. Everything runs on your machine —
profiles, chats, keys, and long-term memory stay local. Chat streams from a local
[Ollama](https://ollama.com) model; memory recalls facts via on-device embeddings.

Stack: FastAPI + SSE, PostgreSQL (pgvector), SQLAlchemy-async + Alembic, pydantic-ai,
Vite + React frontend — orchestrated with Docker Compose.

## Quickstart

**1. Prerequisites**

- [Docker](https://docs.docker.com/get-docker/) (Compose v2)
- [Ollama](https://ollama.com/download) installed and **running on your host** (the API
  container reaches it at `host.docker.internal:11434`)

**2. Pull the models** (both are required)

```bash
ollama pull llama3.1          # chat model (matches the default; pull whichever you'll chat with)
ollama pull nomic-embed-text  # embedding model — REQUIRED for memory (save/recall/auto-capture)
```

> Chat and memory use **different** models. Chat works with only a chat model pulled, but
> saving or recalling a fact needs `nomic-embed-text`. Without it, memory endpoints return
> **503** with the message `… Pull it first: ollama pull nomic-embed-text`.

**3. Start everything**

```bash
docker compose up --build
```

This starts three services and **applies database migrations automatically** on API
startup:

| Service    | URL                     | What it is                                  |
| ---------- | ----------------------- | ------------------------------------------- |
| `frontend` | http://localhost:3000   | the chat UI (Vite dev server)               |
| `api`      | http://localhost:8000   | FastAPI backend (SSE streaming)             |
| `postgres` | localhost:5432          | PostgreSQL + pgvector                        |

**4. Verify**

```bash
curl -s localhost:8000/health      # {"status":"ok","ollama":"up"}
```

Then open **http://localhost:3000**, start a chat, and visit **«Память»** in the sidebar
to add and recall facts.

## Configuration

`docker compose up` boots zero-config from the committed `.env.defaults` (non-secret dev
defaults). Precedence, low → high: `Settings` field defaults → `.env.defaults` → `.env`
(gitignored) → real environment variables.

Postgres credentials are the single source of truth: the `POSTGRES_*` vars feed both the
postgres container and the API's derived `DATABASE_URL`.

Common overrides (set in a gitignored `.env`):

```bash
DEFAULT_MODEL=llama3.1          # chat model
EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://host.docker.internal:11434
JWT_SECRET=<your own 32+ character secret>
```

For a bare local `uv run` (outside Docker), also set `POSTGRES_HOST=localhost`.

## Memory

CapybaraAgent stores and recalls user-specific **facts** via semantic embeddings
(pgvector). The agent can `recall` facts mid-chat, and — when enabled — **auto-captures**
facts from replies.

**Requirements**

- `pgvector/pgvector:pg16` Postgres image (already set in `docker-compose.yml`)
- The embedding model pulled in Ollama: `ollama pull nomic-embed-text`

If the embedding model is missing, memory fails **loudly and actionably**: the API returns
`503 Service Unavailable` with `Embedding model 'nomic-embed-text' is not available in
Ollama. Pull it first: ollama pull nomic-embed-text` (a genuine Ollama outage returns
`502` instead). Auto-capture logs the same message and skips the turn.

**Settings** (environment variables, see precedence above)

| Variable                       | Default            | Meaning                                          |
| ------------------------------ | ------------------ | ------------------------------------------------ |
| `EMBEDDING_MODEL`              | `nomic-embed-text` | Ollama model used to embed facts and queries     |
| `MEMORY_RECALL_K`              | `5`                | Max facts retrieved per recall                   |
| `MEMORY_RECALL_MIN_SIMILARITY` | `0.3`              | Min cosine similarity to include a fact (0–1)    |
| `MEMORY_DEDUP_THRESHOLD`       | `0.9`              | Similarity at/above which a new fact is a dupe   |

**Auto-capture** is per-user (`users.memory_auto_capture`, default on). After each reply a
temporary `BackgroundTask` extracts facts and stores the novel ones, deduplicated (this
trigger migrates to Celery in a later phase). Toggle it on the «Память» screen.

**Limitation:** changing `EMBEDDING_MODEL` requires re-embedding existing facts — v1 stores
no per-row model provenance.

## Development

```bash
uv sync                                        # install backend deps
uv run pytest                                  # backend tests (testcontainers Postgres)
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run alembic upgrade head                    # apply migrations locally

cd frontend && npm install                     # frontend deps (Node ≥ 20)
npm run test && npm run lint && npm run build
```

The backend follows a layered architecture (`api` → `services` → `repositories` → `db`)
with the LLM behind a provider-agnostic `agent/` seam. See `CLAUDE.md` for conventions and
`docs/superpowers/specs/` for per-slice design docs.
