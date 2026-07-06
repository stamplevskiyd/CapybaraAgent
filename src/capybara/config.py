"""Application configuration via pydantic-settings."""

from functools import lru_cache
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env files.

    Precedence (low → high): field defaults, ``.env.defaults`` (committed),
    ``.env`` (gitignored override), then real process env vars — the last file in
    the tuple and real env vars both outrank earlier sources.
    """

    postgres_user: str = "capybara"
    postgres_password: str = "capybara"
    # Docker-first default; a bare local `uv run` overrides this to `localhost` in .env.
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "capybara"

    ollama_base_url: str = "http://host.docker.internal:11434"
    default_model: str = "llama3.1"
    jwt_secret: str = Field(min_length=32)
    jwt_ttl_minutes: int = 43200
    jwt_algorithm: str = "HS256"

    embedding_model: str = "nomic-embed-text"
    # Expected embedding dimensionality; must match ``facts.embedding`` (EMBEDDING_DIM
    # in capybara.db.models.fact) or writes will fail. Validated in the agent's embed().
    embedding_dimensions: int = 768
    memory_recall_k: int = 5
    memory_recall_min_similarity: float = 0.3
    memory_dedup_threshold: float = 0.9

    model_config = SettingsConfigDict(env_file=(".env.defaults", ".env"), extra="ignore")

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL derived from the composite Postgres settings.

        The POSTGRES_* fields are the single source of truth for DB credentials —
        shared with the postgres container via env vars. User and password are
        percent-encoded so special characters cannot corrupt the URL.
        """
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
