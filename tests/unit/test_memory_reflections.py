from datetime import datetime, timezone

import pytest

from klatrebot_v2.db import connection, migrations
from klatrebot_v2.memory import reflections, store


async def _memory_run(conn, name: str = "production") -> int:
    return await store.create_compiler_run(
        conn,
        name=name,
        compiler_model="gpt-test",
        from_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        to_time=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )


async def test_reflection_documents_latest_completed_ignores_failed(tmp_path):
    conn = await connection.open(str(tmp_path / "memory.db"))
    try:
        await migrations.run(conn)
        run_id = await _memory_run(conn)
        first_id = await store.insert_reflection_document(
            conn,
            compiler_run_id=run_id,
            name="social-reflections",
            from_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            model="gpt-test",
            status="completed",
            error=None,
            content_markdown="# First",
            input_tokens=10,
            output_tokens=5,
        )
        failed_id = await store.insert_reflection_document(
            conn,
            compiler_run_id=run_id,
            name="social-reflections",
            from_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 3, tzinfo=timezone.utc),
            model="gpt-test",
            status="failed",
            error="boom",
            content_markdown="",
            input_tokens=1,
            output_tokens=0,
        )

        latest = await store.get_latest_reflection_document(conn, run_id=run_id, name="social-reflections")

        assert latest is not None
        assert latest["id"] == first_id
        assert latest["id"] != failed_id
        assert latest["content_hash"]
    finally:
        await connection.close(conn)


async def test_reflection_documents_deleted_with_compiler_run(tmp_path):
    conn = await connection.open(str(tmp_path / "memory.db"))
    try:
        await migrations.run(conn)
        run_id = await _memory_run(conn)
        await store.insert_reflection_document(
            conn,
            compiler_run_id=run_id,
            name="social-reflections",
            from_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            model="gpt-test",
            status="completed",
            error=None,
            content_markdown="# Reflection",
            input_tokens=10,
            output_tokens=5,
        )

        await store.delete_compiler_run_by_name(conn, "production")

        rows = await conn.execute_fetchall("SELECT id FROM reflection_documents")
        assert rows == []
    finally:
        await connection.close(conn)


async def test_generate_reflection_includes_previous_reflection_and_aliases(tmp_path):
    conn = await connection.open(str(tmp_path / "memory.db"))
    seen = {}
    try:
        await migrations.run(conn)
        run_id = await _memory_run(conn)
        await store.insert_reflection_document(
            conn,
            compiler_run_id=run_id,
            name="social-reflections",
            from_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            model="gpt-test",
            status="completed",
            error=None,
            content_markdown="# Previous\n\nPelle is Twink.",
            input_tokens=10,
            output_tokens=5,
        )
        await conn.execute(
            """
            INSERT INTO user_aliases (discord_user_id, alias, alias_normalized, source)
            VALUES (123, 'Pelle', 'pelle', 'config')
            """
        )
        await conn.execute(
            """
            INSERT INTO user_aliases (discord_user_id, alias, alias_normalized, source)
            VALUES (456, 'Jess', 'jess', 'config')
            """
        )
        await conn.execute(
            """
            INSERT INTO users (discord_user_id, display_name)
            VALUES (123, 'Den Sygt Laekre Twink')
            """
        )
        await conn.execute(
            """
            INSERT INTO messages (discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot)
            VALUES (1, 42, 123, 'hej', '2026-05-02T12:00:00+00:00', 0)
            """
        )
        await conn.commit()

        async def fake_reflector(reflection_input):
            seen["previous"] = reflection_input.previous_markdown
            seen["aliases"] = reflection_input.alias_map
            seen["identity_registry"] = reflection_input.identity_registry
            seen["soul"] = reflection_input.soul
            seen["user_activity"] = reflection_input.user_activity
            seen["prompt"] = reflections.build_reflection_prompt(reflection_input)
            return "# KlatreBot Reflections\n\n## Active People\n\n### Pelle\nAliases from config: Pelle"

        result = await reflections.generate_reflection(
            conn,
            run_id=run_id,
            run_name="production",
            name="social-reflections",
            from_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 3, tzinfo=timezone.utc),
            model="gpt-test",
            reflector=fake_reflector,
        )

        saved = await store.get_latest_reflection_document(conn, run_id=run_id, name="social-reflections")
        assert result.document_id == saved["id"]
        assert seen["previous"] == "# Previous\n\nPelle is Twink."
        assert "Pelle -> 123" in seen["aliases"]
        assert {entry["discord_user_id"] for entry in seen["identity_registry"]} == {123, 456}
        assert seen["soul"]
        assert seen["user_activity"][0]["user_id"] == 123
        assert seen["user_activity"][0]["message_count"] == 1
        assert "Do not merge two people unless" in seen["prompt"]
        assert "identity_registry" in seen["prompt"]
        assert "Hvis Pelle og Jess er forskellige IDs" in seen["prompt"]
        assert "Memory facts er råmateriale, ikke slutprodukt" in seen["prompt"]
        assert "socialt lag ovenpå" in seen["prompt"]
        assert "SOUL" in seen["prompt"]
        assert saved["content_markdown"].startswith("# KlatreBot Reflections")
        assert "<!--" not in saved["content_markdown"]
    finally:
        await connection.close(conn)


async def test_generate_reflection_records_failed_document_on_error(tmp_path):
    conn = await connection.open(str(tmp_path / "memory.db"))
    try:
        await migrations.run(conn)
        run_id = await _memory_run(conn)

        async def failing_reflector(_reflection_input):
            raise RuntimeError("upstream broke")

        with pytest.raises(RuntimeError):
            await reflections.generate_reflection(
                conn,
                run_id=run_id,
                run_name="production",
                name="social-reflections",
                from_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
                to_time=datetime(2026, 5, 3, tzinfo=timezone.utc),
                model="gpt-test",
                reflector=failing_reflector,
            )

        rows = await conn.execute_fetchall(
            "SELECT status, error, content_markdown FROM reflection_documents WHERE compiler_run_id = ?",
            (run_id,),
        )
        assert rows == [("failed", "upstream broke", "")]
    finally:
        await connection.close(conn)


async def test_generate_reflection_records_llm_usage(monkeypatch, tmp_path):
    conn = await connection.open(str(tmp_path / "memory.db"))
    try:
        await migrations.run(conn)
        run_id = await _memory_run(conn)

        class FakeResponses:
            async def create(self, **_kwargs):
                return type(
                    "Resp",
                    (),
                    {
                        "output_text": "# KlatreBot Reflections\n\n## Active People",
                        "usage": {
                            "input_tokens": 123,
                            "output_tokens": 45,
                            "total_tokens": 168,
                        },
                    },
                )()

        fake_client = type("Client", (), {"responses": FakeResponses()})()
        monkeypatch.setattr("klatrebot_v2.memory.reflections.get_client", lambda: fake_client)
        usage = reflections.ReflectionUsage()

        result = await reflections.generate_reflection(
            conn,
            run_id=run_id,
            run_name="production",
            name="social-reflections",
            from_time=datetime(2026, 5, 2, tzinfo=timezone.utc),
            to_time=datetime(2026, 5, 3, tzinfo=timezone.utc),
            model="gpt-test",
            usage=usage,
        )

        saved = await store.get_latest_reflection_document(conn, run_id=run_id, name="social-reflections")
        assert saved["id"] == result.document_id
        assert saved["input_tokens"] == 123
        assert saved["output_tokens"] == 45
        assert usage.total_tokens == 168
    finally:
        await connection.close(conn)
