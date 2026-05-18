from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from klatrebot_v2.memory.__main__ import chat_once, main, resolve_run_id


async def test_compile_cli_passes_time_slice_to_compiler(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    called = {}

    async def fake_compile(conn, *, config, summarizer=None, progress=None):
        called["name"] = config.name
        called["from_time"] = config.from_time
        called["to_time"] = config.to_time
        called["channel_ids"] = config.channel_ids
        called["compiler_model"] = config.compiler_model
        called["concurrency"] = config.concurrency
        return 12

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)

    code = await main(
        [
            "compile",
            "--db",
            str(db_path),
            "--from",
            "2026-04-01T00:00:00+00:00",
            "--to",
            "2026-05-01T00:00:00+00:00",
            "--channel-id",
            "42",
            "--name",
            "april",
            "--model",
            "gpt-test",
            "--concurrency",
            "6",
        ]
    )

    assert code == 0
    assert called == {
        "name": "april",
        "from_time": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "to_time": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "channel_ids": [42],
        "compiler_model": "gpt-test",
        "concurrency": 6,
    }


async def test_compile_cli_uses_segment_defaults_from_env(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    monkeypatch.setenv("MEMORY_SEGMENT_GAP_MINUTES", "45")
    monkeypatch.setenv("MEMORY_SEGMENT_MIN_HUMAN_MESSAGES", "5")
    monkeypatch.setenv("MEMORY_SEGMENT_MIN_TOTAL_CHARS", "300")
    monkeypatch.setenv("MEMORY_SEGMENT_MIN_PARTICIPANTS", "2")
    monkeypatch.setenv("MEMORY_SEGMENT_MAX_MESSAGES", "80")
    monkeypatch.setenv("MEMORY_SEGMENT_MAX_DURATION_MINUTES", "90")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    called = {}

    async def fake_compile(conn, *, config, summarizer=None, progress=None):
        called["segment"] = config.segment
        return 12

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)

    code = await main(["compile", "--db", str(db_path), "--name", "env-segments", "--model", "gpt-test"])

    assert code == 0
    assert called["segment"].gap_minutes == 45
    assert called["segment"].min_human_messages == 5
    assert called["segment"].min_total_chars == 300
    assert called["segment"].min_participants == 2
    assert called["segment"].max_messages == 80
    assert called["segment"].max_duration_minutes == 90


async def test_compile_cli_updates_duplicate_run_by_default(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    called = {}

    async def fake_compile(conn, *, config, summarizer=None, rollup_summarizer=None, progress=None):
        called["rebuild"] = config.rebuild
        return 2

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)

    code = await main(["compile", "--db", str(db_path), "--name", "april"])

    assert code == 0
    assert called["rebuild"] is False


async def test_compile_cli_rebuilds_duplicate_run_with_rebuild_flag(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    called = {}

    async def fake_compile(conn, *, config, summarizer=None, rollup_summarizer=None, progress=None):
        called["rebuild"] = config.rebuild
        return 2

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)

    code = await main(["compile", "--db", str(db_path), "--name", "april", "--rebuild"])

    assert code == 0
    assert called["rebuild"] is True


async def test_compile_cli_updates_failed_duplicate_run_by_default(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.db"
    called = {}

    async def fake_compile(conn, *, config, summarizer=None, rollup_summarizer=None, progress=None):
        called["rebuild"] = config.rebuild
        return 2

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)

    code = await main(["compile", "--db", str(db_path), "--name", "april"])

    assert code == 0
    assert called["rebuild"] is False


async def test_compile_cli_prints_progress(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "memory.db"

    async def fake_compile(conn, *, config, summarizer=None, progress=None):
        progress("Loaded 8 messages.")
        progress("Built 1 segments.")
        return 2

    monkeypatch.setattr("klatrebot_v2.memory.__main__.compile_run", fake_compile)
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_compiler_run_by_name", AsyncMock(return_value=None))

    code = await main(["compile", "--db", str(db_path), "--name", "april"])

    assert code == 0
    out = capsys.readouterr().out
    assert "Loaded 8 messages." in out
    assert "Built 1 segments." in out
    assert "compiled run 2: april" in out


async def test_chat_once_uses_memory_tools_without_discord(monkeypatch, db):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    first = MagicMock()
    first.id = "resp_1"
    first.output_text = ""
    first.output = [
        type(
            "Call",
            (),
            {
                "type": "function_call",
                "name": "recall_community_memory",
                "call_id": "call_1",
                "arguments": '{"query":"Spanien"}',
            },
        )()
    ]
    second = MagicMock()
    second.output_text = "Spanien var på listen."
    second.output = []

    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    async def fake_execute(conn, *, run_id, name, arguments):
        assert conn is db
        assert run_id == 5
        assert name == "recall_community_memory"
        assert arguments["channel_id"] == 1
        return '{"answerable": true}'

    monkeypatch.setattr("klatrebot_v2.memory.__main__.execute_memory_tool", fake_execute)

    answer = await chat_once(db, run_id=5, question="hvad sagde vi om Spanien?")

    assert answer == "Spanien var på listen."
    assert fake_client.responses.create.await_count == 2


async def test_chat_once_includes_recent_cli_context(monkeypatch, db):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock(id="resp_1", output_text="Ja, det er stadig planen.")
    response.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=response)
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    answer = await chat_once(
        db,
        run_id=5,
        question="Er det stadigvæk planen?",
        recent_context=[
            "User: Hvornår tager vi til Kjugekull?",
            "KlatreBot: Planen var den 14. eller 15.",
        ],
    )

    assert answer == "Ja, det er stadig planen."
    first_call = fake_client.responses.create.await_args.kwargs
    assert "RECENT CLI CHAT:" in first_call["input"]
    assert "Hvornår tager vi til Kjugekull?" in first_call["input"]
    assert "Planen var den 14. eller 15." in first_call["input"]


async def test_chat_once_defaults_channel_id_from_settings(monkeypatch, db):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1003718776430268588")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    response = MagicMock(id="resp_1", output_text="ok")
    response.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=response)
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    await chat_once(db, run_id=5, question="hvad skete der?")

    first_call = fake_client.responses.create.await_args.kwargs
    assert "CHANNEL_ID: 1003718776430268588" in first_call["input"]


async def test_chat_once_includes_known_user_aliases(monkeypatch, db):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.db import user_aliases
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobi", source="config")
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobias", source="config")

    response = MagicMock(id="resp_1", output_text="ok")
    response.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=response)
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    await chat_once(db, run_id=5, question="hvad med Tobi?")

    first_call = fake_client.responses.create.await_args.kwargs
    assert "KNOWN_USER_ALIASES:" in first_call["input"]
    assert "Tobi / Tobias -> 42" in first_call["input"]


async def test_chat_once_executes_multiple_memory_tool_rounds(monkeypatch, db):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    first = MagicMock(id="resp_1", output_text="")
    first.output = [
        type("Call", (), {"type": "function_call", "name": "recall_community_memory", "call_id": "call_1", "arguments": '{"query":"Spanien"}'})()
    ]
    second = MagicMock(id="resp_2", output_text="")
    second.output = [
        type("Call", (), {"type": "function_call", "name": "get_memory_sources", "call_id": "call_2", "arguments": '{"source_handles":["mem:1"]}'})()
    ]
    third = MagicMock(id="resp_3", output_text="Kilde fundet.")
    third.output = []

    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second, third])
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    calls = []

    async def fake_execute(conn, *, run_id, name, arguments):
        calls.append((name, arguments))
        return '{"ok": true}'

    monkeypatch.setattr("klatrebot_v2.memory.__main__.execute_memory_tool", fake_execute)

    answer = await chat_once(db, run_id=5, question="hvor er kilden?")

    assert answer == "Kilde fundet."
    assert calls == [
        ("recall_community_memory", {"query": "Spanien", "channel_id": 1}),
        ("get_memory_sources", {"source_handles": ["mem:1"]}),
    ]
    assert fake_client.responses.create.await_count == 3


async def test_chat_once_pretty_prints_show_memory_json(monkeypatch, db, capsys):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    first = MagicMock(id="resp_1", output_text="")
    first.output = [
        type("Call", (), {"type": "function_call", "name": "recall_community_memory", "call_id": "call_1", "arguments": '{"query":"Spanien"}'})()
    ]
    second = MagicMock(id="resp_2", output_text="Svar.")
    second.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    async def fake_execute(conn, *, run_id, name, arguments):
        return '{"answerable":true,"results":[{"text":"Spanien er på listen"}]}'

    monkeypatch.setattr("klatrebot_v2.memory.__main__.execute_memory_tool", fake_execute)

    await chat_once(db, run_id=5, question="Spanien?", show_memory=True)

    out = capsys.readouterr().out
    assert '"answerable": true' in out
    assert '  "results": [' in out
    assert '"text": "Spanien er på listen"' in out


async def test_chat_once_prints_agent_tool_trace(monkeypatch, db, capsys):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    first = MagicMock(id="resp_1", output_text="")
    first.output = [
        type("Call", (), {"type": "function_call", "name": "recall_community_memory", "call_id": "call_1", "arguments": '{"query":"Spanien"}'})()
    ]
    second = MagicMock(id="resp_2", output_text="Svar.")
    second.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    async def fake_execute(conn, *, run_id, name, arguments):
        return '{"answerable":true}'

    monkeypatch.setattr("klatrebot_v2.memory.__main__.execute_memory_tool", fake_execute)

    await chat_once(db, run_id=5, question="Spanien?", show_agent=True)

    out = capsys.readouterr().out
    assert "[agent response 1]" in out
    assert '"name": "recall_community_memory"' in out
    assert '"raw_arguments": {' in out
    assert '"effective_arguments": {' in out
    assert '"channel_id": 1' in out
    assert "[agent response 2]" in out
    assert "Svar." in out


async def test_chat_once_prints_total_token_usage(monkeypatch, db, capsys):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()

    first = MagicMock(id="resp_1", output_text="")
    first.usage = SimpleNamespace(input_tokens=10, output_tokens=3, total_tokens=13)
    first.output = [
        type("Call", (), {"type": "function_call", "name": "recall_community_memory", "call_id": "call_1", "arguments": '{"query":"Spanien"}'})()
    ]
    second = MagicMock(id="resp_2", output_text="Svar.")
    second.usage = SimpleNamespace(input_tokens=20, output_tokens=7, total_tokens=27)
    second.output = []
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_client", lambda: fake_client)

    async def fake_execute(conn, *, run_id, name, arguments):
        return '{"answerable":true}'

    monkeypatch.setattr("klatrebot_v2.memory.__main__.execute_memory_tool", fake_execute)

    await chat_once(db, run_id=5, question="Spanien?", show_usage=True)

    out = capsys.readouterr().out
    assert "[usage]" in out
    assert "responses_calls: 2" in out
    assert "input_tokens: 30" in out
    assert "output_tokens: 10" in out
    assert "total_tokens: 40" in out


async def test_resolve_run_id_accepts_numeric_id_or_name(monkeypatch, db):
    async def fake_get_by_name(conn, name):
        assert conn is db
        assert name == "april"
        return {"id": 44}

    monkeypatch.setattr("klatrebot_v2.memory.__main__.get_compiler_run_by_name", fake_get_by_name)

    assert await resolve_run_id(db, "12") == 12
    assert await resolve_run_id(db, "april") == 44
