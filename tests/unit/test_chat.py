import pytest
from types import SimpleNamespace
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
    assert call_kwargs["tools"] == [{"type": "web_search"}]
    assert "web_search_call.action.sources" in call_kwargs["include"]


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


async def test_reply_executes_memory_tool_when_enabled(monkeypatch, tmp_path, db):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_ACTIVE_RUN_ID", "7")

    first = MagicMock()
    first.id = "resp_1"
    first.output_text = ""
    first.output = [
        SimpleNamespace(
            type="function_call",
            name="recall_community_memory",
            call_id="call_1",
            arguments='{"query":"Spanien"}',
        )
    ]
    second = MagicMock()
    second.output_text = "Vi har snakket om Spanien."
    second.output = []

    from klatrebot_v2.llm import chat, client, prompt
    from klatrebot_v2.memory import tools as memory_tools
    from klatrebot_v2.settings import get_settings
    client._client = None
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(client, "_client", fake_client)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)

    async def fake_execute(conn, *, run_id, name, arguments):
        assert conn is db
        assert run_id == 7
        assert name == "recall_community_memory"
        assert arguments == {"query": "Spanien"}
        return '{"answerable": true, "results": [{"text": "Spanien er på listen"}]}'

    monkeypatch.setattr(memory_tools, "execute_memory_tool", fake_execute)

    result = await chat.reply(question="hvad sagde vi om Spanien?", asking_user_id=99, channel_id=42)

    assert result.text == "Vi har snakket om Spanien."
    assert fake_client.responses.create.await_count == 2
    first_call = fake_client.responses.create.await_args_list[0].kwargs
    assert any(tool.get("name") == "recall_community_memory" for tool in first_call["tools"])
    second_call = fake_client.responses.create.await_args_list[1].kwargs
    assert second_call["previous_response_id"] == "resp_1"
    assert second_call["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"answerable": true, "results": [{"text": "Spanien er på listen"}]}',
        }
    ]


async def test_reply_includes_known_user_aliases_when_memory_enabled(monkeypatch, tmp_path, db):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_ACTIVE_RUN_ID", "7")

    from klatrebot_v2.db import user_aliases
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobi", source="config")
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobias", source="config")

    from klatrebot_v2.llm import chat, client, prompt
    from klatrebot_v2.settings import get_settings
    client._client = None
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=MagicMock(output_text="ok", output=[]))
    monkeypatch.setattr(client, "_client", fake_client)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)

    await chat.reply(question="hvad med Tobi?", asking_user_id=99, channel_id=42)

    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert "KNOWN_USER_ALIASES:" in call_kwargs["input"]
    assert "Tobi / Tobias -> 42" in call_kwargs["input"]


async def test_reply_executes_multiple_memory_tool_rounds(monkeypatch, tmp_path, db):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_ACTIVE_RUN_ID", "7")

    first = MagicMock(id="resp_1", output_text="")
    first.output = [
        SimpleNamespace(type="function_call", name="recall_community_memory", call_id="call_1", arguments='{"query":"Spanien"}')
    ]
    second = MagicMock(id="resp_2", output_text="")
    second.output = [
        SimpleNamespace(type="function_call", name="get_memory_sources", call_id="call_2", arguments='{"source_handles":["mem:1"]}')
    ]
    third = MagicMock(id="resp_3", output_text="Kilde: Nicklas skrev om Spanien.")
    third.output = []

    from klatrebot_v2.llm import chat, client, prompt
    from klatrebot_v2.memory import tools as memory_tools
    from klatrebot_v2.settings import get_settings
    client._client = None
    prompt.load_soul.cache_clear()
    get_settings.cache_clear()
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second, third])
    monkeypatch.setattr(client, "_client", fake_client)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)

    calls = []

    async def fake_execute(conn, *, run_id, name, arguments):
        calls.append((name, arguments))
        return '{"ok": true}'

    monkeypatch.setattr(memory_tools, "execute_memory_tool", fake_execute)

    result = await chat.reply(question="hvor har du Spanien fra?", asking_user_id=99, channel_id=42)

    assert result.text == "Kilde: Nicklas skrev om Spanien."
    assert calls == [
        ("recall_community_memory", {"query": "Spanien"}),
        ("get_memory_sources", {"source_handles": ["mem:1"]}),
    ]
    assert fake_client.responses.create.await_count == 3


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
