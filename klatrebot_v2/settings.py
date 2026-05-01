"""Configuration loaded from .env via Pydantic BaseSettings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    discord_key: str
    openai_key: str
    discord_main_channel_id: int
    discord_sandbox_channel_id: int
    admin_user_id: int

    # Optional (defaults)
    model: str = "gpt-5.4"
    soul_path: str = "./SOUL.MD"
    db_path: str = "./klatrebot_v2.db"

    timezone: str = "Europe/Copenhagen"
    klatretid_days: list[int] = [0, 3]
    klatretid_post_hour: int = 17
    klatretid_start_hour: int = 20

    gpt_recent_message_count: int = 25
    rate_limit_per_user_per_hour: int = 30
    log_level: str = "INFO"

    # Read-only HTTP API for Hermes
    api_enabled: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8765
    api_token: str = ""
    api_query_timeout_seconds: float = 5.0
    api_max_rows: int = 500

    # Embeddings
    embedding_model: str = "text-embedding-3-small"
    embeddings_enabled: bool = True

    # Router + Hermes
    classifier_model: str = "gpt-5.4-nano"
    classifier_timeout_seconds: float = 1.5
    hermes_enabled: bool = False
    hermes_url: str = "http://localhost:8642"
    hermes_token: str = ""
    hermes_model: str = "hermes-agent"
    hermes_timeout_seconds: float = 25.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
