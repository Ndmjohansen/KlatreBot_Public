"""Client for Hermes Agent's OpenAI-compatible API server.

Hermes exposes /v1/chat/completions, /v1/responses, /health on its gateway port
(default 8642). We point an AsyncOpenAI client at that base URL — same SDK we
use for OpenAI proper, just different base_url + api key.

Health probe uses plain httpx since OpenAI SDK has no /health helper.
"""
import asyncio
import logging

import httpx
from openai import AsyncOpenAI, APIError, APITimeoutError

from klatrebot_v2.llm.chat import ChatReply
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)


class HermesUnavailable(Exception):
    """Raised when Hermes can't be reached or is disabled."""


_client: AsyncOpenAI | None = None
_available: bool = False


def _get_hermes_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            base_url=f"{s.hermes_url.rstrip('/')}/v1",
            api_key=s.hermes_token or "no-key",
            timeout=s.hermes_timeout_seconds,
            max_retries=0,
        )
    return _client


def reset_client() -> None:
    """Drop cached client; next call rebuilds from current settings (test helper)."""
    global _client
    _client = None


def is_available() -> bool:
    return _available


def set_available(value: bool) -> None:
    global _available
    _available = value


async def health() -> bool:
    s = get_settings()
    if not s.hermes_enabled:
        set_available(False)
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as http:
            resp = await http.get(f"{s.hermes_url.rstrip('/')}/health")
            ok = resp.status_code == 200
    except Exception as e:
        logger.debug("hermes.health probe failed: %s", e)
        ok = False
    set_available(ok)
    return ok


async def ask(
    *,
    question: str,
    asking_user_id: int,
    channel_id: int,
    username: str,
    mentions: dict[int, str] | None = None,
) -> ChatReply:
    s = get_settings()
    if not s.hermes_enabled:
        raise HermesUnavailable("hermes_enabled=False")
    if not _available:
        raise HermesUnavailable("hermes cached as down")

    soul = load_soul()
    user_payload = (
        f"Asking user: {username} (Discord ID {asking_user_id})\n"
        f"Channel ID: {channel_id}\n"
        f"Mentions: {mentions or {}}\n\n"
        f"QUESTION: {question}"
    )

    try:
        client = _get_hermes_client()
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=s.hermes_model,
                messages=[
                    {"role": "system", "content": soul},
                    {"role": "user", "content": user_payload},
                ],
            ),
            timeout=s.hermes_timeout_seconds,
        )
    except (APIError, APITimeoutError, asyncio.TimeoutError, httpx.HTTPError) as e:
        logger.warning("hermes.ask failed: %s", e)
        set_available(False)
        raise HermesUnavailable(str(e)) from e

    try:
        text = resp.choices[0].message.content or ""
    except (IndexError, AttributeError) as e:
        logger.warning("hermes.ask malformed response: %s", e)
        raise HermesUnavailable("malformed response") from e

    return ChatReply(text=text, sources=[])
