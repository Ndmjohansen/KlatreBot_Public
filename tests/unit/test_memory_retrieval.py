from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import messages as msg_db, users as users_db
from klatrebot_v2.memory.compiler import CompilerConfig, RollupSummary, SegmentSummary, compile_run
from klatrebot_v2.memory.retrieval import get_memory_sources, recall_community_memory


async def _rollup_summarizer(rollup):
    return RollupSummary(
        title=f"{rollup.period_type} rollup",
        summary="Spanien, Pelle og udendørs klatring nævnes som adskilte minder i perioden.",
        key_items=["Spanien nævnes.", "Pelle nævnes.", "Udendørs klatring nævnes."],
        tags=["spanien", "pelle", "udendørs klatring"],
        importance="normal",
    )


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
        rollup_summarizer=_rollup_summarizer,
    )


async def test_recall_community_memory_searches_summaries_and_items(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(db, run_id=run_id, query="Spanien transport")

    assert result.answerable is True
    assert any(r.kind == "segment_summary" and r.topic_title == "Spanien klatretur" for r in result.results)
    assert any(r.kind == "memory_item" and r.type == "plan" for r in result.results)
    assert result.source_handles[0].startswith(("roll:", "seg:", "mem:"))


async def test_recall_returns_rollups_before_flat_memory_for_vague_old_query(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(db, run_id=run_id, query="hvornår snakkede vi om Spanien")

    assert result.results[0].kind in {"rollup_month", "rollup_week"}
    assert result.results[0].source_handle.startswith("roll:")


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


async def test_recall_community_memory_filters_memory_items_by_channel(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    message_id = 1
    for channel_id in [42, 99]:
        for i in range(8):
            await msg_db.insert(
                db,
                discord_message_id=message_id,
                channel_id=channel_id,
                user_id=10,
                content=f"fælles plan besked {channel_id}-{i}",
                timestamp_utc=base + timedelta(minutes=i),
            )
            message_id += 1

    async def summarizer(segment):
        return SegmentSummary(
            topic_title=f"Plan kanal {segment.channel_id}",
            summary=f"Plan i kanal {segment.channel_id}.",
            importance="normal",
            memory_items=[
                {
                    "type": "plan",
                    "subject": "fælles plan",
                    "text": f"Fælles plan fra kanal {segment.channel_id}.",
                    "confidence": "high",
                    "source_message_ids": [segment.messages[0].discord_message_id],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="channel-filter", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_rollup_summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="fælles plan", channel_id=42)

    item_texts = [r.text for r in result.results if r.kind == "memory_item"]
    assert item_texts == ["Fælles plan fra kanal 42."]


async def test_memory_item_results_expose_source_time_range(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(db, run_id=run_id, query="Nicklas kalk")
    item = next(r for r in result.results if r.kind == "memory_item" and r.type == "preference")

    assert item.time_range == "2026-05-01T12:04:00+00:00 - 2026-05-01T12:04:00+00:00"


async def test_get_memory_sources_returns_context_around_summary_and_memory_item(db):
    run_id = await _compile_spanien_run(db)
    recall = await recall_community_memory(db, run_id=run_id, query="Spanien")

    sources = await get_memory_sources(db, source_handles=recall.source_handles, context_radius=1)

    assert sources
    assert any("Spanien kunne være fedt" in source.content for source in sources)
    assert any(source.user_display_name == "Nicklas" for source in sources)


async def test_get_memory_sources_resolves_rollup_handles(db):
    run_id = await _compile_spanien_run(db)
    recall = await recall_community_memory(db, run_id=run_id, query="hvornår Spanien")
    rollup_handle = next(handle for handle in recall.source_handles if handle.startswith("roll:"))

    sources = await get_memory_sources(db, source_handles=[rollup_handle], context_radius=1)

    assert sources
    assert any("Spanien kunne være fedt" in source.content for source in sources)


async def test_recall_searches_daily_ambient_memory_and_resolves_sources(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Nicklas")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"Peak loose chat {i}",
            timestamp_utc=base + timedelta(hours=i),
        )

    async def ambient_summarizer(rollup):
        return RollupSummary(
            title="Daglig ambient hukommelse",
            summary="Løs daglig chat nævnte Peak.",
            key_items=["Peak blev nævnt i løse beskeder."],
            tags=["peak", "spil"],
            importance="normal",
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="ambient-retrieval", from_time=base, to_time=base + timedelta(days=1), compiler_model="test"),
        summarizer=lambda _segment: SegmentSummary(),
        rollup_summarizer=ambient_summarizer,
    )

    recall = await recall_community_memory(db, run_id=run_id, query="peak spil")
    ambient = next(r for r in recall.results if r.kind == "daily_ambient")

    assert ambient.source_handle.startswith("amb:")
    assert ambient.importance == "low"
    assert ambient.matched_tags == ["peak", "spil"]

    sources = await get_memory_sources(db, source_handles=[ambient.source_handle], context_radius=0)
    assert [source.content for source in sources] == ["Peak loose chat 0", "Peak loose chat 1", "Peak loose chat 2"]


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
        rollup_summarizer=_rollup_summarizer,
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
        rollup_summarizer=_rollup_summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="Udendørs plan 1", limit=1)

    assert result.results[0].related_memories == []


async def test_recall_prefers_tag_matches_over_noisy_fts_hits(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Benzon")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"cyberpunk besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 9,
            channel_id=42,
            user_id=10,
            content=f"gaming sofa besked {i}",
            timestamp_utc=base + timedelta(hours=1, minutes=i),
        )

    call_count = 0

    async def summarizer(_segment):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return SegmentSummary(
                topic_title="Cyberpunk",
                summary="Der blev talt om Cyberpunk.",
                importance="normal",
                tags=["gaming", "cyberpunk"],
                memory_items=[
                    {
                        "type": "opinion",
                        "subject": "Cyberpunk",
                        "text": "Cyberpunk blev gennemført, og DLC'en var god.",
                        "confidence": "high",
                        "importance": "normal",
                        "tags": ["gaming", "cyberpunk"],
                        "source_message_ids": [1],
                    }
                ],
            )
        return SegmentSummary(
            topic_title="Sofa",
            summary="Der blev talt om sofa.",
            importance="normal",
            tags=["sofa"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "sofa",
                    "text": "Benzon vil lave et gaming-forsøg på sofaen.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["sofa"],
                    "source_message_ids": [9],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="tag-first", from_time=base, to_time=base + timedelta(hours=2), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_rollup_summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="gaming for nyligt", limit=4)
    item_texts = [r.text for r in result.results if r.kind == "memory_item"]

    assert item_texts.index("Cyberpunk blev gennemført, og DLC'en var god.") < item_texts.index(
        "Benzon vil lave et gaming-forsøg på sofaen."
    )
    cyberpunk = next(r for r in result.results if r.text == "Cyberpunk blev gennemført, og DLC'en var god.")
    assert cyberpunk.match_source == "tag"
    assert cyberpunk.matched_tags == ["gaming"]
    assert cyberpunk.score is not None


async def test_tag_search_respects_channel_type_date_and_people_filters(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Benzon")
    await users_db.upsert(db, discord_user_id=20, display_name="Simon")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    message_id = 1
    for channel_id, user_id, offset_days in [(42, 10, 0), (99, 10, 0), (42, 20, 20)]:
        for i in range(8):
            await msg_db.insert(
                db,
                discord_message_id=message_id,
                channel_id=channel_id,
                user_id=user_id,
                content=f"spil besked {message_id}",
                timestamp_utc=base + timedelta(days=offset_days, minutes=i, hours=channel_id),
            )
            message_id += 1

    async def summarizer(segment):
        speaker_id = segment.messages[0].user_id
        return SegmentSummary(
            topic_title=f"Segment {segment.channel_id}",
            summary="Der blev talt om noget spilrelateret.",
            importance="normal",
            tags=["gaming"],
            memory_items=[
                {
                    "type": "preference" if segment.channel_id == 99 else "opinion",
                    "subject": str(speaker_id),
                    "text": f"Tag-only memory fra kanal {segment.channel_id} og bruger {speaker_id}.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["gaming"],
                    "speaker_ids": [speaker_id],
                    "source_message_ids": [segment.messages[0].discord_message_id],
                }
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="tag-filters", from_time=base, to_time=base + timedelta(days=30), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_rollup_summarizer,
    )

    result = await recall_community_memory(
        db,
        run_id=run_id,
        query="gaming",
        channel_id=42,
        memory_types=["opinion"],
        people=[10],
        date_range=(base, base + timedelta(days=2)),
    )

    item_texts = [r.text for r in result.results if r.kind == "memory_item"]
    assert item_texts == ["Tag-only memory fra kanal 42 og bruger 10."]


async def test_tag_and_text_matches_merge_into_one_result(db):
    run_id = await _compile_spanien_run(db)

    result = await recall_community_memory(db, run_id=run_id, query="Spanien")
    matches = [r for r in result.results if r.kind == "memory_item" and r.subject == "Spanien"]

    assert len(matches) == 1
    assert matches[0].match_source == "both"
    assert matches[0].matched_tags == ["spanien"]


async def test_recall_collapses_likely_duplicate_memory_items(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Benzon")
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(8):
        await msg_db.insert(
            db,
            discord_message_id=i + 1,
            channel_id=42,
            user_id=10,
            content=f"sofa gaming besked {i}",
            timestamp_utc=base + timedelta(minutes=i),
        )

    async def summarizer(_segment):
        return SegmentSummary(
            topic_title="Sofa gaming",
            summary="Der blev talt om gaming på sofaen.",
            importance="normal",
            tags=["gaming", "sofa"],
            memory_items=[
                {
                    "type": "plan",
                    "subject": "sofaen og gaming",
                    "text": "Benzon vil lave et forsøg med at game på sofaen.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["gaming", "sofa"],
                    "source_message_ids": [1],
                },
                {
                    "type": "plan",
                    "subject": "klatrebot-brugere (Benzon)",
                    "text": "Der er et forsøg på at game på sofaen for Benzon.",
                    "confidence": "high",
                    "importance": "normal",
                    "tags": ["gaming", "sofa"],
                    "source_message_ids": [1],
                },
            ],
        )

    run_id = await compile_run(
        db,
        config=CompilerConfig(name="duplicate-tag-results", from_time=base, to_time=base + timedelta(hours=1), compiler_model="test"),
        summarizer=summarizer,
        rollup_summarizer=_rollup_summarizer,
    )

    result = await recall_community_memory(db, run_id=run_id, query="gaming sofa", limit=5)
    item_results = [r for r in result.results if r.kind == "memory_item"]

    assert len(item_results) == 1
