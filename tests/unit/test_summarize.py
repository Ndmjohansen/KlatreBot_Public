from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


async def test_summarize_calls_llm_with_messages(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))

    from klatrebot_v2.llm import client, chat, prompt
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.db.messages import MessageWithAuthor
    client._client = None
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()

    fake_resp = MagicMock(); fake_resp.output_text = "Her er hvad boomerene har yappet om i dag..."
    fake_client = MagicMock(); fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(client, "_client", fake_client)

    msgs = [
        MessageWithAuthor(
            discord_message_id=1, channel_id=1, user_id=10,
            user_display_name="Magnus", content="hej alle",
            timestamp_utc=datetime(2026, 4, 30, 6, 0, tzinfo=timezone.utc), is_bot=False,
        ),
        MessageWithAuthor(
            discord_message_id=2, channel_id=1, user_id=11,
            user_display_name="Pelle", content="god morgen",
            timestamp_utc=datetime(2026, 4, 30, 6, 5, tzinfo=timezone.utc), is_bot=False,
        ),
    ]
    summary = await chat.summarize(msgs)

    assert "Her er hvad boomerene" in summary
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert "Magnus (10): hej alle" in call_kwargs["input"]
    assert "Pelle (11): god morgen" in call_kwargs["input"]
    assert "tools" not in call_kwargs or call_kwargs["tools"] == []
