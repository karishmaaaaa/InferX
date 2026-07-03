from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "InferX"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://inferx:inferx@localhost:5432/inferx"
    )

    sarvam_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    api_key_header: str = "X-API-Key"
    api_key_cache_ttl_seconds: float = Field(default=60.0, ge=0)
    bootstrap_dev_data: bool = False
    local_free_api_key: str | None = None
    local_premium_api_key: str | None = None
    local_dev_user_email: str = "local-dev@inferx.internal"

    enable_dev_provider: bool = False
    dev_provider_latency_ms: int = Field(default=0, ge=0)
    dev_provider_stream_chunk_delay_ms: int = Field(default=250, ge=0)
    enable_demo_controls: bool = False
    enable_ollama_provider: bool = False
    provider_priority: str = "dev_echo,dev_backup,ollama,groq,openai,gemini,sarvam"
    provider_request_timeout_seconds: float = Field(default=5.0, gt=0)
    provider_score_interval_seconds: float = Field(default=60.0, ge=0)
    provider_score_window_seconds: float = Field(default=300.0, gt=0)

    circuit_failure_threshold: int = Field(default=3, ge=1)
    circuit_cooldown_seconds: float = Field(default=30.0, gt=0)
    provider_health_check_interval_seconds: float = Field(default=5.0, gt=0)

    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = Field(default=0.88, ge=0, le=1)
    semantic_cache_ttl_seconds: int = Field(default=3600, ge=1)
    semantic_cache_max_entries: int = Field(default=250, ge=1)
    semantic_embedding_dimensions: int = Field(default=256, ge=16)

    request_queue_max_size: int = Field(default=1000, ge=1)
    request_queue_workers: int = Field(default=8, ge=1)
    usage_writer_queue_size: int = Field(default=10000, ge=1)
    usage_writer_workers: int = Field(default=4, ge=1)

    database_pool_size: int = Field(default=20, ge=1)
    database_max_overflow: int = Field(default=40, ge=0)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0)

    otel_service_name: str = "inferx"
    otel_exporter_otlp_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
