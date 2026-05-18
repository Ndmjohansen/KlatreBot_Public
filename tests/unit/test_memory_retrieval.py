from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import messages as msg_db, users as users_db
from klatrebot_v2.memory.compiler import CompilerConfig, SegmentSummary, compile_run
from klatrebot_v2.memory.retrieval import get_memory_sources, recall_community_memory


async def _compile_spanien_run(db) -> int:
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    await users_db.upsert(db, discord_user_id=20, display_name="Simon")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i, content in enumerate(
        [
            "Spanien kunne være fedt",
            "men det er nok dyrt",
            "vi kan kigge på fly",
            "jeg foretrækker kalk",
            "måske uge 29",
            "transport er spørgsmålet",
            "lad os ikke beslutte endnu",
            "men Spanien er stadig på listen",
        ],
        start=1,
    ):
        await msg_db.insert(
            db,
            discord_message_id=i,
            channel_id=42,
            user_id=10 if i % 2 else 20,
            content=content,
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(_segment):
        return SegmentSummary(
            topic_title="Spanien klatretur",
            summary="Gruppen talte om en mulig klatretur til Spanien, pris, fly og transport.",
            importance="normal",
            tags=["spanien", "klatretur"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "Spanien",
                    "text": "Spanien er en mulig klatretur, men der blev ikke truffet en beslutning.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["spanien", "klatretur"],
                    "speaker_ids": [10, 20],
                    "source_message_ids": [1, 7, 8],
                },
                {
                    "type": "preference",
                    "subject": "Nicklas",
                    "text": "Nicklas foretrækker kalk til klatring.",
                    "confidence": "medium",
                    "importance": "low",
                    "tags": ["klatring", "kalk"],
                    "speaker_ids": [10],
                    "source_message_ids": [4],
                },
            ],
        )

    return await compile_run(
        db,
        config=CompilerConfig(name="retrieval-run", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
    )


async def test_recall_community_memory_searches_summaries_and_items(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(db, run_id=run_id, query="Spanien transport")

    assert result.answerable is True
    assert any(r.kind == "segment_summary" and r.topic_title == "Spanien klatretur" for r in result.results)
    assert any(r.kind == "memory_item" and r.type == "plan" for r in result.results)
    assert "seg:" in result.source_handles[0] or "mem:" in result.source_handles[0]


async def test_recall_community_memory_filters_by_memory_type(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(
        db,
        run_id=run_id,
        query="Nicklas kalk",
        memory_types=["preference"],
    )

    assert [r.type for r in result.results if r.kind == "memory_item"] == ["preference"]
    assert all(r.kind != "memory_item" or r.type == "preference" for r in result.results)


async def test_get_memory_sources_returns_context_around_summary_and_memory_item(db):
    run_id = await _compile_spanien_run(db)
    recall = await recall_community_memory(db, run_id=run_id, query="Spanien")

    sources = await get_memory_sources(db, source_handles=recall.source_handles, context_radius=1)

    assert sources
    assert any("Spanien kunne være fedt" in source.content for source in sources)
    assert any(source.user_display_name == "Nicklas" for source in sources)


async def test_recall_groups_related_memories_by_tag_and_time_window(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Tobi")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(24):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"udendørs besked {i}",
            timestamp_utc=base + timedelta(days=i // 8, minutes=i),
        )

    call_count = 0

    async def summarizer(_segment):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return SegmentSummary(
                topic_title="Udendørs dato",
                summary="Der blev talt om dato for udendørs klatring.",
                importance="normal",
                tags=["udendørs klatring", "klatretur"],
                memory_items=[
                    {
                        "type": "plan",
                        "subject": "udendørs klatring",
                        "text": "Udendørs klatretur er planlagt 24. eller 25. maj.",
                        "confidence": "high",
                        "importance": "normal",
                        "tags": ["udendørs klatring", "klatretur"],
                        "source_message_ids": [1],
                    }
                ],
            )
        return SegmentSummary(
            topic_title="Kjugekull med Tobi",
            summary="Tobi og Max talte om Kjugekull.",
            importance="normal",
            tags=["udendørs klatring", "kjugekull", "tobi"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "Kjugekull",
                    "text": "Tobi og Max tager til Kjugekull.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["udendørs klatring", "kjugekull", "tobi"],
                    "source_message_ids": [9],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="related-run", from_time=base, to_time=base + timedelta(days=3), compiler_model="test"),
        summarizer=summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="udendørs klatretur dato", limit=3)
    primary = next(r for r in result.results if r.text == "Udendørs klatretur er planlagt 24. eller 25. maj.")

    assert primary.related_memories
    assert primary.related_memories[0].text == "Tobi og Max tager til Kjugekull."
    assert "udendørs klatring" in primary.related_memories[0].relation


async def test_related_memories_exclude_items_outside_default_window(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Tobi")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i, days in enumerate([0] * 8 + [30] * 8, start=1):
        await msg_db.insert(
            db,
            discord_message_id=i,
            channel_id=42,
            user_id=10,
            content=f"udendørs besked {i}",
            timestamp_utc=base + timedelta(days=days, minutes=i),
        )

    call_count = 0

    async def summarizer(_segment):
        nonlocal call_count
        call_count += 1
        return SegmentSummary(
            topic_title=f"Segment {call_count}",
            summary="Udendørs klatring.",
            importance="normal",
            tags=["udendørs klatring"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": f"segment {call_count}",
                    "text": f"Udendørs plan {call_count}.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["udendørs klatring"],
                    "source_message_ids": [1 if call_count == 1 else 9],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="outside-window", from_time=base, to_time=base + timedelta(days=40), compiler_model="test"),
        summarizer=summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="Udendørs plan 1", limit=1)

    assert result.results[0].related_memories == []
