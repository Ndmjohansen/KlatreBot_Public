import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from klatrebot_v2.db import messages as msg_db, users as users_db
from klatrebot_v2.memory.compiler import CompilerConfig, RollupInput, RollupSummary, SegmentConfig, SegmentSummary, compile_run
from klatrebot_v2.memory.store import (
    get_compiler_run_by_name,
    list_daily_ambient_memory_for_run,
    list_rollups_for_run,
    list_segments_for_run,
)


async def _noop_rollup_summarizer(rollup):
    return RollupSummary(
        title=f"{rollup.period_type} {rollup.period_start.date()}",
        summary="Deterministisk test-rollup.",
        key_items=["Test-rollup."],
        importance="normal",
        tags=["test"],
    )


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
        rollup_summarizer=_noop_rollup_summarizer,
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
        rollup_summarizer=_noop_rollup_summarizer,
    )
    second = await compile_run(
        db,
        config=CompilerConfig(name="run-b", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert first != second
    assert len(await list_segments_for_run(db, first)) == 1
    assert len(await list_segments_for_run(db, second)) == 1


async def test_compile_run_updates_existing_run_without_resummarizing_completed_segments(db):
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

    second_calls = []

    async def second_summarizer(segment):
        second_calls.append(segment.messages[0].discord_message_id)
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
        rollup_summarizer=_noop_rollup_summarizer,
    )
    second = await compile_run(
        db,
        config=CompilerConfig(name="same-name", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=second_summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert second == first
    assert second_calls == []
    assert [s["topic_title"] for s in await list_segments_for_run(db, first)] == ["Første"]


async def test_compile_run_rebuilds_existing_run_when_requested(db):
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
        return SegmentSummary(topic_title="Første", summary="Første compile.", importance="normal")

    async def second_summarizer(_segment):
        return SegmentSummary(topic_title="Anden", summary="Anden compile.", importance="normal")

    first = await compile_run(
        db,
        config=CompilerConfig(name="rebuild-name", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=first_summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )
    second = await compile_run(
        db,
        config=CompilerConfig(
            name="rebuild-name",
            from_time=base,
            to_time=base + timedelta(hours=1),
            compiler_model="test",
            rebuild=True,
        ),
        summarizer=second_summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert second != first
    assert [s["topic_title"] for s in await list_segments_for_run(db, second)] == ["Anden"]
    assert await list_segments_for_run(db, first) == []


async def test_compile_run_refuses_update_when_segment_config_changes(db):
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
        return SegmentSummary(topic_title="Config", summary="Config.", importance="normal")

    await compile_run(
        db,
        config=CompilerConfig(
            name="config-hash",
            from_time=base,
            to_time=base + timedelta(hours=1),
            compiler_model="test",
            segment=SegmentConfig(gap_minutes=30),
        ),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    with pytest.raises(ValueError, match="Segment config changed"):
        await compile_run(
            db,
            config=CompilerConfig(
                name="config-hash",
                from_time=base,
                to_time=base + timedelta(hours=1),
                compiler_model="test",
                segment=SegmentConfig(gap_minutes=15),
            ),
            summarizer=summarizer,
            rollup_summarizer=_noop_rollup_summarizer,
        )


async def test_compile_run_can_resume_failed_run_without_resummarizing_persisted_segments(db):
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

    calls = []

    async def crashing_summarizer(segment):
        calls.append(segment.messages[0].discord_message_id)
        if len(calls) == 2:
            raise RuntimeError("api disconnect")
        return SegmentSummary(topic_title="Første", summary="Første gemt.", importance="normal")

    first_run = await compile_run(
        db,
        config=CompilerConfig(
            name="resume-run",
            from_time=base,
            to_time=base + timedelta(days=3),
            compiler_model="test",
            concurrency=1,
            segment=SegmentConfig(gap_minutes=30),
        ),
        summarizer=crashing_summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert (await get_compiler_run_by_name(db, "resume-run"))["status"] == "completed"
    assert [s["topic_title"] for s in await list_segments_for_run(db, first_run) if s["status"] == "summarized"] == ["Første"]
    failed_rows = await db.execute_fetchall("SELECT status, error, retry_count FROM conversation_segments WHERE compiler_run_id = ? AND status = 'failed'", (first_run,))
    assert failed_rows == [("failed", "api disconnect", 1)]

    resume_calls = []

    async def resume_summarizer(segment):
        resume_calls.append(segment.messages[0].discord_message_id)
        return SegmentSummary(topic_title="Anden", summary="Anden gemt.", importance="normal")

    second_run = await compile_run(
        db,
        config=CompilerConfig(
            name="resume-run",
            from_time=base,
            to_time=base + timedelta(days=3),
            compiler_model="test",
            concurrency=1,
            segment=SegmentConfig(gap_minutes=30),
        ),
        summarizer=resume_summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert second_run == first_run
    assert resume_calls == [9]
    summarized = [s["topic_title"] for s in await list_segments_for_run(db, first_run) if s["status"] == "summarized"]
    assert summarized == ["Første", "Anden"]
    assert (await get_compiler_run_by_name(db, "resume-run"))["status"] == "completed"


async def test_compile_run_backfills_wider_date_range_without_recompiling_existing_segments(db):
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

    calls = []

    async def summarizer(segment):
        calls.append(segment.messages[0].discord_message_id)
        return SegmentSummary(topic_title=f"Segment {segment.messages[0].discord_message_id}", summary="Summary.", importance="normal")

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="widen", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )
    await compile_run(
        db,
        config=CompilerConfig(name="widen", from_time=base, to_time=base + timedelta(days=3), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    assert calls == [1, 9]
    assert len(await list_segments_for_run(db, run_id)) == 2


async def test_compile_run_replaces_overlapping_tail_segment_on_update(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"første hale {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    calls = []

    async def summarizer(segment):
        calls.append([m.discord_message_id for m in segment.messages])
        return SegmentSummary(
            topic_title=f"Segment {segment.messages[0].discord_message_id}-{segment.messages[-1].discord_message_id}",
            summary="Samtalen blev opsummeret.",
            importance="normal",
            memory_items=[
                {
                    "type": "fact",
                    "subject": "hale",
                    "text": f"Segmentet går til besked {segment.messages[-1].discord_message_id}.",
                    "source_message_ids": [segment.messages[-1].discord_message_id],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="tail-overlap", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    for i in range(8, 16):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"senere hale {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    await compile_run(
        db,
        config=CompilerConfig(name="tail-overlap", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

    segments = await list_segments_for_run(db, run_id)
    item_rows = await db.execute_fetchall(
        "SELECT text FROM memory_items WHERE compiler_run_id = ? ORDER BY id",
        (run_id,),
    )
    assert calls == [list(range(1, 9)), list(range(1, 17))]
    assert [s["topic_title"] for s in segments] == ["Segment 1-16"]
    assert item_rows == [("Segmentet går til besked 16.",)]


async def test_compile_run_builds_weekly_and_monthly_rollups(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    mid = 1
    for week in range(2):
        for i in range(8):
            await msg_db.insert(
                db,
                discord_message_id=mid,
                channel_id=42,
                user_id=10,
                content=f"januar besked {week}-{i}",
                timestamp_utc=base + timedelta(days=week * 7, minutes=i),
            )
            mid += 1

    async def summarizer(segment):
        return SegmentSummary(
            topic_title=f"Uge fra {segment.start_time_utc.date()}",
            summary="Der var Pelle-relateret social planlægning.",
            importance="normal",
            tags=["pelle", "social"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "Pelle",
                    "text": "Der blev planlagt noget hos Pelle.",
                    "tags": ["pelle", "social"],
                    "source_message_ids": [segment.messages[0].discord_message_id],
                }
            ],
        )

    async def rollup_summarizer(rollup: RollupInput):
        return RollupSummary(
            title=f"{rollup.period_type} {rollup.period_start.date()}",
            summary=f"Opsummering for {rollup.period_type} med Pelle og social planlægning.",
            key_items=["Pelle og social planlægning nævnes som separat hukommelse."],
            tags=["pelle", "social"],
            importance="normal",
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="rollups", from_time=base, to_time=base + timedelta(days=20), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=rollup_summarizer,
    )

    rollups = await list_rollups_for_run(db, run_id)
    assert sorted(r["period_type"] for r in rollups) == ["month", "week", "week"]
    assert all(r["status"] == "completed" for r in rollups)


async def test_compile_run_builds_daily_ambient_memory_from_skipped_segments(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"peak loose message {i}",
            timestamp_utc=base + timedelta(hours=i),
        )

    ambient_inputs = []

    async def ambient_summarizer(rollup: RollupInput):
        ambient_inputs.append(rollup)
        return RollupSummary(
            title="Daglig ambient hukommelse",
            summary="Der var løs snak om Peak.",
            key_items=["Peak blev nævnt i løs daglig chat."],
            tags=["peak", "spil"],
            importance="normal",
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="daily-ambient", from_time=base, to_time=base + timedelta(days=1), compiler_model="test"),
        summarizer=AsyncMock(),
        rollup_summarizer=ambient_summarizer,
    )

    ambient_rows = await list_daily_ambient_memory_for_run(db, run_id)
    assert len(ambient_rows) == 1
    assert ambient_rows[0]["status"] == "completed"
    assert ambient_rows[0]["importance"] == "low"
    assert ambient_rows[0]["summary"] == "Der var løs snak om Peak."
    assert ambient_inputs[0].period_type == "daily_ambient"
    assert [source["kind"] for source in ambient_inputs[0].sources] == ["skipped_segment"]


async def test_compile_run_marks_rollup_failure_without_aborting(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
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
        return SegmentSummary(topic_title="Rollup fail", summary="Rollup fail summary.", importance="normal")

    async def rollup_summarizer(_rollup):
        raise RuntimeError("rollup disconnect")

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="rollup-failure", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=rollup_summarizer,
    )

    rollups = await list_rollups_for_run(db, run_id)
    assert [(r["period_type"], r["status"], r["error"]) for r in rollups] == [("week", "failed", "rollup disconnect")]
    assert (await get_compiler_run_by_name(db, "rollup-failure"))["status"] == "completed"


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
        rollup_summarizer=_noop_rollup_summarizer,
        progress=events.append,
    )

    assert events[0] == "Loaded 8 messages."
    assert events[1] == "Built 1 segments."
    assert events[2] == "Segments: existing=0, missing=1, retry=0, pending=1."
    assert events[3] == "Summarizing 1 meaningful segments with concurrency 4."
    assert events[4] == "Summarized 1/1 meaningful segments."
    assert events[-1] == "Completed memory run 'progress'."


async def test_compile_run_reports_total_llm_token_usage(monkeypatch, db):
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
    response = MagicMock()
    response.output_text = '{"topic_title":"Usage","summary":"Usage summary.","importance":"normal","memory_items":[]}'
    response.usage = SimpleNamespace(input_tokens=100, output_tokens=25, total_tokens=125)
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=response)
    monkeypatch.setattr("klatrebot_v2.memory.compiler.get_client", lambda: fake_client)
    events = []

    await compile_run(
        db,
        config=CompilerConfig(name="usage", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        progress=events.append,
    )

    assert "[compile usage]" in events
    assert "responses_calls: 3" in events
    assert "input_tokens: 300" in events
    assert "output_tokens: 75" in events
    assert "total_tokens: 375" in events


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
        rollup_summarizer=_noop_rollup_summarizer,
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
        rollup_summarizer=_noop_rollup_summarizer,
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


async def test_compile_run_treats_null_llm_id_lists_as_empty(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=100,
            user_id=10,
            content=f"Besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(segment):
        return SegmentSummary(
            topic_title="Null ids",
            summary="Segment hvor modellen returnerer null id-lister.",
            importance="normal",
            memory_items=[
                {
                    "type": "fact",
                    "subject": "test",
                    "text": "Compiler bør håndtere null source/speaker ids.",
                    "source_message_ids": None,
                    "speaker_ids": None,
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="null-id-lists", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_noop_rollup_summarizer,
    )

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
    assert source_rows == [(1,), (2,), (3,)]
