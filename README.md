# CapybaraAgent

## Running (backend chat core)

Prerequisites: Docker, and Ollama running on the host with a model pulled
(`ollama pull llama3.1`).

```bash
docker compose up --build
curl -s localhost:8000/health
```

## Configuration

`docker compose up` boots zero-config from the committed `.env.defaults`
(non-secret dev defaults). Precedence, low → high: `Settings` field defaults →
`.env.defaults` → `.env` (gitignored) → real environment variables.

Postgres credentials are the single source of truth: the `POSTGRES_*` vars feed
both the postgres container and the API's derived `DATABASE_URL`.

For a bare local `uv run` (outside Docker), create a gitignored `.env`:

```bash
POSTGRES_HOST=localhost
JWT_SECRET=<your own 32+ character secret>
```

Dev loop: `uv sync && uv run pytest && uv run ruff check . && uv run mypy src`

## Memory

The memory system stores and recalls user-specific facts via semantic embedding.

**Prerequisites:**

- `pgvector/pgvector:pg16` Postgres image (configured in `docker-compose.yml`)
- Ollama embedding model pulled: `ollama pull nomic-embed-text`

Recall and auto-capture fail with `ModelProviderError` if the embedding model is not pulled.

**Configuration:**

Set via environment variables (see Configuration section precedence):

- `EMBEDDING_MODEL` (default `nomic-embed-text`) — embedding model for semantic search
- `MEMORY_RECALL_K` (default `5`) — number of facts to retrieve per query
- `MEMORY_RECALL_MIN_SIMILARITY` (default `0.3`) — minimum cosine similarity threshold (0–1)
- `MEMORY_DEDUP_THRESHOLD` (default `0.9`) — similarity threshold to merge duplicate facts (0–1)

**Auto-capture:**

Auto-capture is per-user (toggle: `users.memory_auto_capture`, default on). After each reply, a temporary `BackgroundTask` extracts facts from the response and stores them deduplicated (will migrate to Celery in a later phase).

**Limitation:** Changing `EMBEDDING_MODEL` at runtime requires re-embedding all existing facts (no per-row model provenance in v1).