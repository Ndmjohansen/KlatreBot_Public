import asyncio
from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import messages as msg_db, users as users_db
from klatrebot_v2.memory.compiler import CompilerConfig, SegmentSummary, compile_run
from klatrebot_v2.memory.store import get_compiler_run_by_name, list_segments_for_run


async def test_compile_run_persists_run_segments_memory_items_and_sources(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    await users_db.upsert(db, discord_user_id=20, display_name="Simon")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10 if i % 2 == 0 else 20,
            content=f"Spanien plan besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(_segment):
        return SegmentSummary(
            topic_title="Spanien tur",
            summary="Nicklas og Simon talte om en mulig klatretur til Spanien.",
            importance="normal",
            tags=[" Spanien ", "klatretur", "Klatretur", "outdoor climbing"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "Spanien",
                    "text": "Der var en løs plan om en klatretur til Spanien.",
                    "confidence": "medium",
                    "importance": "normal",
                    "tags": ["Spanien", "klatretur", "🧗", "x" * 80],
                    "speaker_ids": [10, 20],
                    "source_message_ids": [1, 2],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(
            name="spanien-test",
            from_time=base,
            to_time=base + timedelta(hours=1),
            channel_ids=[42],
            compiler_model="test-model",
        ),
        summarizer=summarizer,
    )

    run = await get_compiler_run_by_name(db, "spanien-test")
    assert run is not None
    assert run["id"] == run_id
    assert run["status"] == "completed"

    segments = await list_segments_for_run(db, run_id)
    assert len(segments) == 1
    assert segments[0]["topic_title"] == "Spanien tur"
    assert segments[0]["summary"] == "Nicklas og Simon talte om en mulig klatretur til Spanien."

    row = await db.execute_fetchall("SELECT type, subject, text FROM memory_items WHERE compiler_run_id = ?", (run_id,))
    assert row == [("plan", "Spanien", "Der var en løs plan om en klatretur til Spanien.")]

    source_rows = await db.execute_fetchall(
        """
        SELECT mis.discord_message_id
        FROM memory_item_sources mis
        JOIN memory_items mi ON mi.id = mis.memory_item_id
        WHERE mi.compiler_run_id = ?
        ORDER BY mis.discord_message_id
        """,
        (run_id,),
    )
    assert source_rows == [(1,), (2,)]

    segment_tags = await db.execute_fetchall(
        "SELECT tag FROM conversation_segment_tags WHERE segment_id = ? ORDER BY tag",
        (segments[0]["id"],),
    )
    assert segment_tags == [("klatretur",), ("outdoor climbing",), ("spanien",)]

    item_tags = await db.execute_fetchall(
        """
        SELECT mit.tag
        FROM memory_item_tags mit
        JOIN memory_items mi ON mi.id = mit.memory_item_id
        WHERE mi.compiler_run_id = ?
        ORDER BY mit.tag
        """,
        (run_id,),
    )
    assert item_tags == [("klatretur",), ("spanien",)]


async def test_compile_run_keeps_multiple_runs_in_same_database(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(segment):
        return SegmentSummary(
            topic_title=f"Run summary {segment.messages[0].discord_message_id}",
            summary="Kort opsummering.",
            importance="normal",
            memory_items=[],
        )

    first = await compile_run(
        db,
        config=CompilerConfig(name="run-a", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
    )
    second = await compile_run(
        db,
        config=CompilerConfig(name="run-b", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
    )

    assert first != second
    assert len(await list_segments_for_run(db, first)) == 1
    assert len(await list_segments_for_run(db, second)) == 1


async def test_compile_run_overwrites_existing_run_with_same_name(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def first_summarizer(_segment):
        return SegmentSummary(
            topic_title="Første",
            summary="Første compile.",
            importance="normal",
            memory_items=[
                {
                    "type": "fact",
                    "subject": "første",
                    "text": "Gammel memory skal fjernes.",
                    "source_message_ids": [1],
                }
            ],
        )

    async def second_summarizer(_segment):
        return SegmentSummary(
            topic_title="Anden",
            summary="Anden compile.",
            importance="normal",
            memory_items=[],
        )

    first = await compile_run(
        db,
        config=CompilerConfig(name="same-name", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=first_summarizer,
    )
    second = await compile_run(
        db,
        config=CompilerConfig(name="same-name", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=second_summarizer,
    )

    assert second != first
    assert [s["topic_title"] for s in await list_segments_for_run(db, second)] == ["Anden"]
    assert await list_segments_for_run(db, first) == []
    assert await db.execute_fetchall("SELECT text FROM memory_items WHERE compiler_run_id = ?", (first,)) == []


async def test_compile_run_reports_progress(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(_segment):
        return SegmentSummary(topic_title="Progress", summary="Progress summary.", importance="normal")

    events = []

    await compile_run(
        db,
        config=CompilerConfig(name="progress", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        progress=events.append,
    )

    assert events[0] == "Loaded 8 messages."
    assert events[1] == "Built 1 segments."
    assert events[2] == "Summarizing 1 meaningful segments with concurrency 4."
    assert events[3] == "Summarized 1/1 meaningful segments."
    assert events[-1] == "Completed memory run 'progress'."


async def test_compile_run_summarizes_meaningful_segments_concurrently(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    mid = 1
    for day in range(2):
        for i in range(8):
            await msg_db.insert(
                db,
                discord_message_id=mid,
                channel_id=42,
                user_id=10,
                content=f"besked {day}-{i}",
                timestamp_utc=base + timedelta(days=day, minutes=i),
            )
            mid += 1

    active = 0
    max_active = 0

    async def summarizer(_segment):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return SegmentSummary(topic_title="Concurrent", summary="Concurrent summary.", importance="normal")

    await compile_run(
        db,
        config=CompilerConfig(
            name="concurrent",
            from_time=base,
            to_time=base + timedelta(days=3),
            compiler_model="test",
            concurrency=2,
        ),
        summarizer=summarizer,
    )

    assert max_active == 2


async def test_compile_run_skips_invalid_llm_source_ids(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(_segment):
        return SegmentSummary(
            topic_title="Kilde ids",
            summary="Segment med dårlig kilde-id.",
            importance="normal",
            memory_items=[
                {
                    "type": "fact",
                    "subject": "test",
                    "text": "Compiler bør ignorere ugyldige source ids.",
                    "source_message_ids": ["abc", 999, 1],
                    "speaker_ids": ["nope", 10],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="bad-source-id", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
    )

    source_rows = await db.execute_fetchall(
        """
        SELECT mis.discord_message_id
        FROM memory_item_sources mis
        JOIN memory_items mi ON mi.id = mis.memory_item_id
        WHERE mi.compiler_run_id = ?
        """,
        (run_id,),
    )
    assert source_rows == [(1,)]
