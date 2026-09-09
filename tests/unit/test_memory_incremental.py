from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from klatrebot_v2.db import migrations, messages, users
from klatrebot_v2.memory.cache import CorpusCache
from klatrebot_v2.memory.corpus import load_corpus
from klatrebot_v2.memory.journal import boundary
from klatrebot_v2.memory.palace import Palace, DIMENSIONS
from klatrebot_v2.memory.worker import Worker


async def add(conn, mid=1, text='kan ikke klatre'):
    await users.upsert(conn, discord_user_id=1, display_name='Anna')
    await messages.insert(conn, discord_message_id=mid, channel_id=42, user_id=1,
                          content=text, timestamp_utc=datetime(2026, 9, 8, tzinfo=timezone.utc))


async def test_journal_atomic_and_noop_updates(db):
    await add(db)
    before = await boundary(db)
    await add(db)
    assert await boundary(db) == before
    await db.execute("UPDATE messages SET content='afbud' WHERE discord_message_id=1")
    assert await boundary(db) > before
    await db.rollback()
    assert await boundary(db) == before


async def test_raw_changes_never_reload_corpus_and_delete_context(tmp_path, monkeypatch):
    path = tmp_path / 'source.db'
    cache = CorpusCache(path)
    async with aiosqlite.connect(path) as conn:
        await migrations.run(conn)
        await add(conn)
        try:
            before, _ = await cache.get(0)
            monkeypatch.setattr('klatrebot_v2.memory.cache.load_corpus', AsyncMock(side_effect=AssertionError('full refresh')))
            for mid in range(2, 35):
                await add(conn, mid)
            after, _ = await cache.get(0)
            assert len(after) == 34 and after[0] is before[0]
            await messages.delete(conn, [1, 2])
            after, _ = await cache.get(0)
            assert len(after) == 32
            assert all(m.discord_message_id not in [1, 2] for m in await messages.recent(conn, channel_id=42, limit=100))
            await messages.edit(conn, 1, 'do not resurrect')
            assert len((await cache.get(0))[0]) == 32
        finally:
            await cache.close()


async def test_metadata_reuses_vectors_without_embeddings(db, tmp_path):
    await add(db)
    palace = Palace(tmp_path / 'index')
    try:
        docs = await load_corpus(db, 0)
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1)])
        docs[0].subjects = [2]
        docs[0].__dict__.pop('digest', None)
        palace.reuse_vectors(docs)
        assert not palace.pending(docs)
        assert palace.collection.get(ids=[docs[0].id], include=['metadatas'])['metadatas'][0]['subjects'] == '[2]'
        palace.collection.delete(ids=[docs[0].id])
        palace.reconcile(docs)
        assert palace.pending(docs) == docs
    finally:
        palace.backend.close()


async def test_edit_during_embedding_stays_pending_and_recovers(tmp_path, monkeypatch):
    path = tmp_path / 'source.db'
    async with aiosqlite.connect(path) as conn:
        await migrations.run(conn)
        await add(conn)
        settings = SimpleNamespace(db_path=str(path), memory_active_run_name=None, memory_active_run_id=0)
        palace = Palace(tmp_path / 'index')
        worker = Worker(settings, palace, None)
        async def edited(*args, **kwargs):
            await messages.edit(conn, 1, 'kommer alligevel')
            return [[1.] + [0.] * (DIMENSIONS - 1)], 4
        monkeypatch.setattr('klatrebot_v2.memory.worker.embed', edited)
        try:
            await worker.sync()
            assert len(palace.pending(await worker.corpus())) == 1
            assert worker.indexed_sequence < await boundary(conn)
            assert await conn.execute_fetchall('SELECT 1 FROM memory_changes')
        finally:
            await worker.cache.close()
            palace.backend.close()
        palace = Palace(tmp_path / 'index')
        worker = Worker(settings, palace, None)
        monkeypatch.setattr('klatrebot_v2.memory.worker.embed', AsyncMock(return_value=([[1.] + [0.] * (DIMENSIONS - 1)], 4)))
        try:
            await worker.sync()
            assert not palace.pending(await worker.corpus())
            assert worker.indexed_sequence == await boundary(conn)
            assert not await conn.execute_fetchall('SELECT 1 FROM memory_changes')
        finally:
            await worker.cache.close()
            palace.backend.close()


async def test_deleted_evidence_stays_invalid_after_restart_and_reconcile(tmp_path):
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    path = tmp_path / 'source.db'
    async with aiosqlite.connect(path) as conn:
        await migrations.run(conn)
        run = await _compile_spanien_run(conn)
        docs = await load_corpus(conn, run)
        affected = {d.handle for d in docs if 4 in d.sources and d.kind != 'raw_message'}
        await messages.delete(conn, [4])
        await migrations.run(conn)
        cache = CorpusCache(path)
        try:
            for reconcile in [False, True]:
                fresh, _ = await cache.get(run, reconcile=reconcile)
                assert not affected.intersection(d.handle for d in fresh)
        finally:
            await cache.close()


def test_incremental_vectors_match_native_before_and_after_mutations(tmp_path):
    import numpy as np
    from klatrebot_v2.memory.corpus import Document
    rng = np.random.default_rng(17)
    palace = Palace(tmp_path / 'vectors')
    docs = [Document(str(i), f'msg:{i}', 'klatring', 'raw_message', 42,
                     '2026-09-08T00:00:00+00:00', [i], [1], [], []) for i in range(160)]
    vectors = rng.normal(size=(160, DIMENSIONS)).astype(np.float32)
    vectors[0] = 0
    vectors[1] = vectors[2]
    try:
        palace.commit_batch(docs[:140], vectors[:140])
        palace.prepare_vectors()
        for phase in range(3):
            if phase == 1:
                palace.commit_batch(docs[140:], vectors[140:])
                vectors[5] = vectors[6]
                palace.commit_batch([docs[5]], [vectors[5]])
            if phase == 2:
                palace.reconcile(docs[10:])
                palace.commit_batch(docs[:1], vectors[:1])
            ids = palace.collection.get(include=[])['ids']
            for q in [vectors[1], np.zeros(DIMENSIONS), rng.normal(size=DIMENSIONS)]:
                for eligible in [set(ids), set(ids[::3]), set(ids[-1:])]:
                    native = palace.collection.query(query_embeddings=[q.tolist()], n_results=30,
                        where={'doc_id': {'$in': sorted(eligible)}}, include=[])['ids'][0]
                    assert palace.vectors.query(q, eligible) == native
    finally:
        palace.backend.close()


async def test_raw_event_listeners_and_source_expansion(db):
    from klatrebot_v2.cogs.auto_responses import AutoResponsesCog
    from klatrebot_v2.memory.retrieval import get_memory_sources
    await add(db)
    cog = AutoResponsesCog(SimpleNamespace(db_conn=db))
    await cog.on_raw_message_edit(SimpleNamespace(message_id=1, data={'embeds': []}))
    assert (await messages.recent(db, channel_id=42, limit=1))[0].content == 'kan ikke klatre'
    await cog.on_raw_message_edit(SimpleNamespace(message_id=1, data={'content': 'kommer alligevel'}))
    assert (await get_memory_sources(db, source_handles=['msg:1'], context_radius=0))[0].content == 'kommer alligevel'
    await cog.on_raw_bulk_message_delete(SimpleNamespace(message_ids={1, 999}))
    assert not await get_memory_sources(db, source_handles=['msg:1'])
    await add(db, 999, 'late event must not resurrect a deleted message')
    assert not await get_memory_sources(db, source_handles=['msg:999'])


async def test_compiler_input_guard_rejects_edited_evidence(db):
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    from klatrebot_v2.memory.evidence import signature, verify_publication
    await _compile_spanien_run(db)
    sid, summary = (await db.execute_fetchall("SELECT id, summary FROM conversation_segments WHERE status='summarized' LIMIT 1"))[0]
    sources = [dict(kind='segment', id=sid, summary=summary)]
    before = await signature(db, sources)
    mid = (await db.execute_fetchall('SELECT discord_message_id FROM segment_messages WHERE segment_id=? LIMIT 1', (sid,)))[0][0]
    await messages.edit(db, mid, 'rettet tekst')
    with pytest.raises(ValueError, match='invalidated'):
        await signature(db, sources)
    assert not await verify_publication(db, 'roll:999', sources, before)
    assert await db.execute_fetchall("SELECT 1 FROM memory_invalid_current WHERE handle='roll:999'")


@pytest.mark.parametrize('count,fail,expected', [(1, False, [30]), (32, False, [0]), (1, True, [30, 35])])
async def test_periodic_debounce_batch_threshold_and_retry(tmp_path, monkeypatch, count, fail, expected):
    import asyncio
    import time
    from klatrebot_v2.memory import worker as module
    path = tmp_path / 'source.db'
    clock = [0]
    calls = []
    async with aiosqlite.connect(path) as conn:
        await migrations.run(conn)
        for mid in range(count):
            await add(conn, mid + 1)
        settings = SimpleNamespace(db_path=str(path), memory_active_run_name=None,
                                   memory_active_run_id=0, memory_sync_enabled=True)
        palace = Palace(tmp_path / 'index')
        worker = Worker(settings, palace, None)
        worker.last_reconcile = 0
        await worker.corpus()
        epoch = time.time()
        async def status(_conn, seq):
            outstanding = await boundary(_conn) > seq
            return dict(pending_changes=int(outstanding), oldest_pending_age_seconds=clock[0] if outstanding else 0)
        async def embedding(client, texts, **kwargs):
            calls.append(clock[0])
            if fail:
                raise TimeoutError('provider unavailable')
            return [[1.] + [0.] * (DIMENSIONS - 1) for _ in texts], len(texts)
        async def tick(_seconds):
            clock[0] += 1
            # Continued arrivals must not reset the oldest pending deadline.
            if count == 1 and clock[0] in [10, 20]:
                await add(conn, clock[0])
            if clock[0] >= 40:
                raise asyncio.CancelledError
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: epoch + clock[0]))
        monkeypatch.setattr(module, 'asyncio', SimpleNamespace(sleep=tick, create_task=asyncio.create_task,
            shield=asyncio.shield, to_thread=asyncio.to_thread, CancelledError=asyncio.CancelledError))
        monkeypatch.setattr(module, 'pending_status', status)
        monkeypatch.setattr(module, 'embed', embedding)
        try:
            with pytest.raises(asyncio.CancelledError):
                await worker.periodic()
            assert calls == expected
            if fail:
                assert worker.indexed_sequence == 0
                assert await conn.execute_fetchall('SELECT 1 FROM memory_changes')
        finally:
            await worker.cache.close()
            palace.backend.close()


async def test_background_reconcile_does_not_block_or_replace_newer_snapshot(tmp_path, monkeypatch):
    import asyncio
    import threading
    from klatrebot_v2.memory import cache as module
    path = tmp_path / 'source.db'
    cache = CorpusCache(path)
    captured, release = threading.Event(), threading.Event()
    async with aiosqlite.connect(path) as conn:
        await conn.execute('PRAGMA journal_mode=WAL')
        await migrations.run(conn)
        await add(conn)
        await cache.get(0)
        original = module.load_corpus
        async def paused(*args):
            docs = await original(*args)
            captured.set()
            await asyncio.to_thread(release.wait, 5)
            return docs
        monkeypatch.setattr(module, 'load_corpus', paused)
        task = asyncio.create_task(cache.reconcile(0))
        try:
            assert await asyncio.to_thread(captured.wait, 3)
            await messages.edit(conn, 1, 'nyeste rettelse')
            fresh, _ = await asyncio.wait_for(cache.get(0), 1)
            assert fresh[0].text == 'nyeste rettelse'
            seq = cache.sequence
            release.set()
            await task
            assert cache.sequence == seq
            assert cache.docs[0].text == 'nyeste rettelse'
        finally:
            release.set()
            await task
            await cache.close()


def test_provider_retry_headers_and_backoff(monkeypatch):
    from email.utils import formatdate
    from klatrebot_v2.memory import worker as module
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda: 1000))
    for headers, expected in [({'retry-after': '90'}, 90), ({'retry-after-ms': '12000'}, 12),
                              ({'retry-after': formatdate(1100, usegmt=True)}, 100),
                              ({'retry-after': 'invalid'}, 5)]:
        exc = SimpleNamespace(response=SimpleNamespace(headers=headers))
        assert module.retry_delay(exc, 1) == expected
    assert module.retry_delay(TimeoutError(), 20) == 300
