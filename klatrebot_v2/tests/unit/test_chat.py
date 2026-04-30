import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_response():
    """Mimic the OpenAI Responses API return shape we read."""
    r = MagicMock()
    r.output_text = "Hej brormand"
    r.output = []  # Used by source extraction; empty here.
    return r


async def test_reply_returns_chat_reply(monkeypatch, tmp_path, fake_response, db):
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
    chat.set_db_conn_provider(lambda: db)

    result = await chat.reply(question="hvad så", asking_user_id=42, channel_id=0)

    assert result.text == "Hej brormand"
    assert result.sources == []
    fake_client.responses.create.assert_awaited_once()
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert call_kwargs["model"] == "gpt-5.4"
    assert "Du er en klatrebot." in call_kwargs["input"]
    assert "hvad så" in call_kwargs["input"]
    assert "42" in call_kwargs["input"]


async def test_reply_includes_recent_context(monkeypatch, tmp_path, fake_response, db):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))

    from datetime import datetime, timezone
    from klatrebot_v2.db import users as users_db, messages as msg_db
    await users_db.upsert(db, discord_user_id=10, display_name="Magnus")
    await msg_db.insert(db, discord_message_id=1, channel_id=42, user_id=10, content="første", timestamp_utc=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc))
    await msg_db.insert(db, discord_message_id=2, channel_id=42, user_id=10, content="anden", timestamp_utc=datetime(2026, 4, 30, 12, 1, tzinfo=timezone.utc))

    from klatrebot_v2.llm import client, chat, prompt
    from klatrebot_v2.settings import get_settings
    client._client = None
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(client, "_client", fake_client)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)

    result = await chat.reply(question="hvad så", asking_user_id=99, channel_id=42)

    assert result.text == "Hej brormand"
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert "Magnus: første" in call_kwargs["input"]
    assert "Magnus: anden" in call_kwargs["input"]


def test_extract_sources_from_response():
    from klatrebot_v2.llm.chat import _extract_sources

    fake_resp = MagicMock()
    fake_resp.output = [
        MagicMock(type="message"),  # not a search call
        MagicMock(
            type="web_search_call",
            action=MagicMock(sources=[
                MagicMock(url="https://a.dk"),
                MagicMock(url="https://b.dk"),
            ]),
        ),
    ]
    assert _extract_sources(fake_resp) == ["https://a.dk", "https://b.dk"]


def test_extract_sources_empty_when_no_search():
    from klatrebot_v2.llm.chat import _extract_sources

    fake_resp = MagicMock()
    fake_resp.output = [MagicMock(type="message")]
    assert _extract_sources(fake_resp) == []
