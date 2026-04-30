"""SOUL.MD loader."""
from functools import lru_cache
from pathlib import Path

from klatrebot_v2.settings import get_settings


@lru_cache(maxsize=1)
def load_soul() -> str:
    return Path(get_settings().soul_path).read_text(encoding="utf-8").strip()
