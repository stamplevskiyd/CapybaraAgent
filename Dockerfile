FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn capybara.main:app --host 0.0.0.0 --port 8000"]
