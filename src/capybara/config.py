"""Application configuration via pydantic-settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a .env file."""

    database_url: str
    ollama_base_url: str = "http://host.docker.internal:11434"
    default_model: str = "llama3.1"
    jwt_secret: str = Field(min_length=32)
    jwt_ttl_minutes: int = 43200
    jwt_algorithm: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
