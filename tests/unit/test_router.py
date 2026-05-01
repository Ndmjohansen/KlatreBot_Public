import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.llm import client
    from klatrebot_v2.settings import get_settings
    client._client = None
    get_settings.cache_clear()


def _patched_client(monkeypatch, *, output_text: str = '{"route":"chat"}', side_effect=None):
    from klatrebot_v2.llm import client
    fake = MagicMock()
    fake.responses = MagicMock()
    if side_effect is not None:
        fake.responses.create = AsyncMock(side_effect=side_effect)
    else:
        resp = MagicMock()
        resp.output_text = output_text
        fake.responses.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(client, "_client", fake)
    return fake


async def test_classify_returns_chat(monkeypatch):
    _patched_client(monkeypatch, output_text='{"route":"chat"}')
    from klatrebot_v2.llm import router
    assert await router.classify("hej brormand") == "chat"


async def test_classify_returns_agent(monkeypatch):
    _patched_client(monkeypatch, output_text='{"route":"agent"}')
    from klatrebot_v2.llm import router
    assert await router.classify("hvem var med sidste uge") == "agent"


async def test_classify_uses_configured_model(monkeypatch):
    fake = _patched_client(monkeypatch, output_text='{"route":"chat"}')
    from klatrebot_v2.llm import router
    await router.classify("hej")
    kwargs = fake.responses.create.await_args.kwargs
    assert kwargs["model"] == "gpt-5.4-nano"
    assert kwargs["text"]["format"]["type"] == "json_schema"


async def test_classify_timeout_falls_back_to_chat(monkeypatch):
    async def slow(*a, **k):
        await asyncio.sleep(5)
    _patched_client(monkeypatch, side_effect=slow)
    from klatrebot_v2.llm import router
    from klatrebot_v2.settings import get_settings
    monkeypatch.setattr(get_settings(), "classifier_timeout_seconds", 0.05)
    assert await router.classify("hvad så") == "chat"


async def test_classify_exception_falls_back_to_chat(monkeypatch):
    _patched_client(monkeypatch, side_effect=RuntimeError("boom"))
    from klatrebot_v2.llm import router
    assert await router.classify("hvad så") == "chat"


async def test_classify_malformed_json_falls_back_to_chat(monkeypatch):
    _patched_client(monkeypatch, output_text="not json at all")
    from klatrebot_v2.llm import router
    assert await router.classify("hvad så") == "chat"


async def test_classify_unexpected_route_value_falls_back_to_chat(monkeypatch):
    _patched_client(monkeypatch, output_text='{"route":"banana"}')
    from klatrebot_v2.llm import router
    assert await router.classify("hvad så") == "chat"
