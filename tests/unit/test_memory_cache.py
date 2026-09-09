import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

import aiosqlite

from klatrebot_v2.db import migrations, messages, users, user_aliases
from klatrebot_v2.memory.cache import CorpusCache
from klatrebot_v2.memory.corpus import load_corpus
from klatrebot_v2.memory.search import search


async def test_cache_reuses_unchanged_documents_and_sees_external_commits(tmp_path):
    path = tmp_path / "source.db"
    cache = CorpusCache(path)
    async with aiosqlite.connect(path) as writer:
        await migrations.run(writer)
        await users.upsert(writer, discord_user_id=1, display_name="Anna")
        for mid in [1, 2]:
            await messages.insert(writer, discord_message_id=mid, channel_id=42, user_id=1,
                                  content="Jeg aflyser", timestamp_utc=datetime(2026, 8, mid, tzinfo=timezone.utc))
        try:
            first, _ = await cache.get(0)
            again, _ = await cache.get(0)
            assert again is first
            await writer.execute("UPDATE messages SET content='Anna kommer alligevel' WHERE discord_message_id=1")
            await writer.commit()
            changed, _ = await cache.get(0)
            assert changed[0] is not first[0]
            assert changed[1] is first[1]
            assert first[0].text == "Jeg aflyser"
            assert changed[0].subjects == [1]
            assert changed[0].digest != first[0].digest
            await writer.execute("DELETE FROM messages WHERE discord_message_id=1")
            await writer.commit()
            deleted, _ = await cache.get(0)
            assert [d.handle for d in deleted] == ["msg:2"]
            await messages.insert(writer, discord_message_id=3, channel_id=42, user_id=1,
                                  content="kan ik", timestamp_utc=datetime(2026, 8, 3, tzinfo=timezone.utc))
            latest, _ = await cache.get(0)
            result = await search(None, dict(run_id=0, query="afbud", people=[1], order="latest",
                                            date_end="2026-09-01"), prepared_docs=latest)
            assert result.coverage["chronological_page"][0]["source_handle"] == "msg:3"
        finally:
            await cache.close()


async def test_cache_invalidates_derived_sources_aliases_and_active_run(tmp_path):
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    path = tmp_path / "source.db"
    cache = CorpusCache(path)
    async with aiosqlite.connect(path) as writer:
        await migrations.run(writer)
        run = await _compile_spanien_run(writer)
        try:
            before, _ = await cache.get(run)
            preference = next(d for d in before if d.kind == "preference")
            assert preference.authors == [20]
            await writer.execute("UPDATE messages SET user_id=10 WHERE discord_message_id=4")
            await writer.commit()
            after, _ = await cache.get(run)
            assert not any(d.kind == "preference" for d in after)
            assert preference.authors == [20]
            await user_aliases.upsert_alias(writer, discord_user_id=20, alias="Nicklas", source="config")
            ambiguous, _ = await cache.get(run)
            assert not any(d.kind == "preference" for d in ambiguous)
            await writer.execute("UPDATE memory_rollups SET status='stale'")
            await writer.commit()
            stale, _ = await cache.get(run)
            assert not any(d.kind.startswith("rollup") for d in stale)
            switched, _ = await cache.get(0)
            assert all(d.kind == "raw_message" for d in switched)
        finally:
            await cache.close()


async def test_optimized_hashes_remain_compatible_with_backfilled_index(db):
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    run = await _compile_spanien_run(db)
    for doc in await load_corpus(db, run):
        original = hashlib.sha256(json.dumps(asdict(doc), sort_keys=True).encode()).hexdigest()
        assert doc.digest == original
