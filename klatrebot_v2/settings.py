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
    user_aliases_config_path: str | None = None

    timezone: str = "Europe/Copenhagen"
    klatretid_days: list[int] = [0, 3]
    klatretid_post_hour: int = 17
    klatretid_start_hour: int = 20

    gpt_recent_message_count: int = 25
    rate_limit_per_user_per_hour: int = 30
    log_level: str = "INFO"

    memory_enabled: bool = False
    memory_active_run_id: int | None = None
    memory_active_run_name: str | None = None
    memory_compiler_model: str = "gpt-5.4-mini"
    memory_segment_gap_minutes: int = 30
    memory_segment_min_human_messages: int = 8
    memory_segment_min_total_chars: int = 500
    memory_segment_min_participants: int = 3
    memory_segment_max_messages: int = 100
    memory_segment_max_duration_minutes: int = 120
    memory_rolling_enabled: bool = False
    memory_rolling_run_name: str = "production"
    memory_rolling_settle_minutes: int = 45
    memory_rolling_tail_buffer_minutes: int = 180
    memory_rolling_initial_lookback_hours: int = 24
    memory_rolling_concurrency: int = 2
    memory_rolling_lock_ttl_minutes: int = 180


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
