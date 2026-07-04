#!/bin/sh
# Container entrypoint: apply migrations, then start the API server.
#
# Set UVICORN_RELOAD=1 (see docker-compose.yml) to run with live reload for
# local development; unset/empty runs the plain production server.
set -e

uv run alembic upgrade head

exec uv run uvicorn capybara.main:app \
  --host 0.0.0.0 --port 8000 \
  ${UVICORN_RELOAD:+--reload --reload-dir /app/src}
