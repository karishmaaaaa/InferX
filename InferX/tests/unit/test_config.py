from app.core.config import Settings, get_settings


def test_settings_read_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "InferX Test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://inferx:inferx@localhost:5432/inferx_test",
    )

    settings = get_settings()

    assert settings.app_name == "InferX Test"
    assert settings.environment == "test"
    assert str(settings.redis_url) == "redis://localhost:6379/1"
    assert str(settings.database_url).startswith("postgresql+asyncpg://")


def test_provider_keys_default_to_unset() -> None:
    settings = Settings()

    assert settings.sarvam_api_key is None
    assert settings.openai_api_key is None
    assert settings.gemini_api_key is None
    assert settings.groq_api_key is None
