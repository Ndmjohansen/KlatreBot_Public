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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
