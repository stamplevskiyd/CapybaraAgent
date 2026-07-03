import pytest
from pydantic import ValidationError

from capybara.config import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("JWT_SECRET", "env-secret-that-is-at-least-32-chars!")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.ollama_base_url == "http://example:11434"
    assert settings.default_model == "test-model"
    assert settings.jwt_secret == "env-secret-that-is-at-least-32-chars!"
    assert settings.jwt_ttl_minutes == 43200
    assert settings.jwt_algorithm == "HS256"


def test_settings_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError):
        Settings()
