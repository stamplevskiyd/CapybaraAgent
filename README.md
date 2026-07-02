# CapybaraAgent

## Running (backend chat core)

Prerequisites: Docker, and Ollama running on the host with a model pulled
(`ollama pull llama3.1`).

```bash
cp .env.example .env
docker compose up --build
curl -s localhost:8000/health
```

Dev loop: `uv sync && uv run pytest && uv run ruff check . && uv run mypy src`