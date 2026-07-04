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