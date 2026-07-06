import pytest
from pydantic import ValidationError

from capybara.config import Settings


def test_settings_derive_database_url_from_postgres_parts(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "db")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("JWT_SECRET", "env-secret-that-is-at-least-32-chars!")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost:5433/db"
    assert settings.ollama_base_url == "http://example:11434"
    assert settings.default_model == "test-model"
    assert settings.jwt_secret == "env-secret-that-is-at-least-32-chars!"
    assert settings.jwt_ttl_minutes == 43200
    assert settings.jwt_algorithm == "HS256"


def test_database_url_percent_encodes_credentials(monkeypatch):
    """Special characters in the password must not corrupt the derived URL."""
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd")
    monkeypatch.setenv("POSTGRES_HOST", "db.host")
    monkeypatch.setenv("JWT_SECRET", "env-secret-that-is-at-least-32-chars!")
    settings = Settings()
    assert (
        settings.database_url == "postgresql+asyncpg://user:p%40ss%3Aw%2Frd@db.host:5432/capybara"
    )


def test_settings_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError):
        Settings()


_FAKE_COMMITTED = "committed-insecure-shared-dev-secret-32b!"


def test_prod_rejects_committed_jwt_secret(monkeypatch):
    """In prod, reusing the shared .env.defaults secret must fail fast."""
    import capybara.config as cfg

    monkeypatch.setattr(cfg, "_committed_jwt_secret", lambda: _FAKE_COMMITTED)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", _FAKE_COMMITTED)
    with pytest.raises(ValidationError):
        Settings()


def test_prod_accepts_rotated_jwt_secret(monkeypatch):
    """A prod secret distinct from the committed default is accepted."""
    import capybara.config as cfg

    monkeypatch.setattr(cfg, "_committed_jwt_secret", lambda: _FAKE_COMMITTED)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "a-freshly-rotated-unique-prod-secret-32b")
    assert Settings().app_env == "prod"


def test_dev_allows_committed_jwt_secret(monkeypatch):
    """Dev (the default) intentionally allows the shared committed secret."""
    import capybara.config as cfg

    monkeypatch.setattr(cfg, "_committed_jwt_secret", lambda: _FAKE_COMMITTED)
    monkeypatch.setenv("JWT_SECRET", _FAKE_COMMITTED)
    settings = Settings()
    assert settings.app_env == "dev"


def test_memory_settings_have_defaults() -> None:
    from capybara.config import Settings

    s = Settings(jwt_secret="x" * 32)
    assert s.embedding_model == "nomic-embed-text"
    assert s.memory_recall_k == 5
    assert s.memory_recall_min_similarity == 0.3
    assert s.memory_dedup_threshold == 0.9
