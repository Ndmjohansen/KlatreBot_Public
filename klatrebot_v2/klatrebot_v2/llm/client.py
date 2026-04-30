"""AsyncOpenAI singleton — module-level, lazy."""
from openai import AsyncOpenAI

from klatrebot_v2.settings import get_settings


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            api_key=s.openai_key,
            timeout=60.0,
            max_retries=0,
        )
    return _client
