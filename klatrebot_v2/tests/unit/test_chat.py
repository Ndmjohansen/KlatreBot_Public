import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_response():
    """Mimic the OpenAI Responses API return shape we read."""
    r = MagicMock()
    r.output_text = "Hej brormand"
    r.output = []  # Used by source extraction; empty here.
    return r


async def test_reply_returns_chat_reply(monkeypatch, tmp_path, fake_response):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Du er en klatrebot.")
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    monkeypatch.setenv("SOUL_PATH", str(soul))

    # Patch the OpenAI client
    from klatrebot_v2.llm import client, chat, prompt
    from klatrebot_v2.settings import get_settings
    client._client = None             # reset singleton
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()

    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(client, "_client", fake_client)

    result = await chat.reply(question="hvad så", asking_user_id=42)

    assert result.text == "Hej brormand"
    assert result.sources == []
    fake_client.responses.create.assert_awaited_once()
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert call_kwargs["model"] == "gpt-5.4"
    assert "Du er en klatrebot." in call_kwargs["input"]
    assert "hvad så" in call_kwargs["input"]
    assert "42" in call_kwargs["input"]
