from capybara.config import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("JWT_SECRET", "env-secret")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.ollama_base_url == "http://example:11434"
    assert settings.default_model == "test-model"
    assert settings.jwt_secret == "env-secret"
    assert settings.jwt_ttl_minutes == 43200
    assert settings.jwt_algorithm == "HS256"
