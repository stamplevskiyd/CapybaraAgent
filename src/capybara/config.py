"""Application configuration via pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The committed defaults file whose JWT_SECRET is shared and therefore unsafe in prod.
_ENV_DEFAULTS = Path(".env.defaults")


def _committed_jwt_secret() -> str | None:
    """Return the JWT_SECRET committed in ``.env.defaults``, or None if unreadable.

    Read directly (not the merged effective value) so a prod deployment can detect that
    it is still running on the shared dev secret without the operator needing to know it.
    """
    try:
        for raw in _ENV_DEFAULTS.read_text().splitlines():
            line = raw.strip()
            if line.startswith("JWT_SECRET=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        return None
    return None


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

    # "dev" (default) is permissive; "prod" enables fail-fast hardening (see below).
    app_env: Literal["dev", "prod"] = "dev"

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

    @model_validator(mode="after")
    def _reject_shared_secret_in_prod(self) -> Settings:
        """In prod, refuse to boot on the shared committed JWT secret.

        The dev default in ``.env.defaults`` is public, so anyone could forge tokens. Dev
        stays permissive; prod must supply its own secret. If ``.env.defaults`` is absent
        the check is skipped (fails open) rather than blocking an otherwise valid boot.
        """
        if self.app_env == "prod" and self.jwt_secret == _committed_jwt_secret():
            raise ValueError(
                "JWT_SECRET is the shared .env.defaults value; set a unique secret when "
                "APP_ENV=prod."
            )
        return self

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
