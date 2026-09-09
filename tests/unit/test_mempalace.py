import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.db import messages, users, user_aliases
from klatrebot_v2.memory.corpus import load_corpus
from klatrebot_v2.memory.palace import Palace, DIMENSIONS
from klatrebot_v2.memory.search import search, filtered
from klatrebot_v2.memory.retrieval import get_memory_sources
from klatrebot_v2.memory.tools import execute_memory_tool


async def seed(db):
    for uid in [1, 2]:
        await users.upsert(db, discord_user_id=uid, display_name=f"Person {uid}")
    for mid, uid, content, day in [(101, 1, "Jeg aflyser, min skulder gør ondt", 1),
                                   (102, 2, "Jeg aflyser klatring fordi jeg er syg", 20),
                                   (103, 1, "Jeg aflyser, skal passe katten", 25),
                                   (104, 1, "kan ik alligevel", 26)]:
        await messages.insert(db, discord_message_id=mid, channel_id=42, user_id=uid,
                              content=content, timestamp_utc=datetime(2026, 8, day, tzinfo=timezone.utc))


def req(**kwargs):
    return dict(run_id=0, query="aflyser klatring", people=[1], channel_id=42,
                date_end="2026-09-01T00:00:00+00:00", **kwargs)


async def test_person_recency_and_unindexed_short_reply(db):
    await seed(db)
    result = await search(db, req(order="latest"))
    assert result.results[0].source_handle == "msg:103"
    assert "msg:102" not in result.source_handles
    assert result.coverage["chronological_page"][0]["source_handle"] == "msg:104"
    assert result.status == "degraded"
    assert result.indexing_watermark is None
    assert result.coverage["exhaustive"] is False


async def test_date_boundaries_and_cursor_no_skips(db):
    await seed(db)
    request = req(order="latest", limit=1)
    seen = []
    for _ in range(10):
        result = await search(db, request)
        seen.extend(r["source_handle"] for r in result.coverage["chronological_page"])
        if not result.continuation_cursor:
            break
        request["cursor"] = result.continuation_cursor
    assert seen == ["msg:104", "msg:103", "msg:101"]
    result = await search(db, req(order="latest", limit=1))
    with pytest.raises(ValueError, match="cursor"):
        await search(db, dict(req(order="latest"), people=[2], cursor=result.continuation_cursor))
    result = await search(db, dict(req(), date_start="2026-08-25T02:00:00+02:00", date_end="2026-08-26T00:00:00Z"))
    assert result.source_handles == ["msg:103"]


async def test_raw_source_handle_preserves_mixed_context(db):
    await seed(db)
    raw = await get_memory_sources(db, source_handles=["msg:103"], context_radius=0)
    assert [r.user_id for r in raw] == [1]
    context = await get_memory_sources(db, source_handles=["msg:103"], context_radius=2)
    assert {r.user_id for r in context} == {1, 2}


@pytest.mark.parametrize("name", ["Ukendt", "Sam", ""])
async def test_alias_fail_closed(db, monkeypatch, name):
    for uid in [1, 2]:
        await user_aliases.upsert_alias(db, discord_user_id=uid, alias="Sam", source="config")
    legacy = AsyncMock(side_effect=AssertionError("Must not search"))
    monkeypatch.setattr("klatrebot_v2.memory.tools.recall_community_memory", legacy)
    result = json.loads(await execute_memory_tool(db, run_id=0, name="recall_community_memory",
                                                  arguments={"query": "afbud", "people_names": [name]}))
    assert result["status"] == "clarification_required"
    legacy.assert_not_awaited()


async def test_mentions_and_corrected_target(db):
    await seed(db)
    settings = SimpleNamespace(memory_backend="mempalace", memory_socket_path="missing")
    for uid, expected in [(2, "msg:102"), (1, "msg:103")]:
        result = json.loads(await execute_memory_tool(db, run_id=0, settings=settings,
            name="recall_community_memory", arguments={"query": "aflyser", "people_names": [f"<@!{uid}>"],
                                                       "date_end": "2026-09-01", "order": "latest"}))
        assert result["results"][0]["source_handle"] == expected


async def test_real_backend_repeat_import_restart_stale_and_mismatch(db, tmp_path):
    await seed(db)
    docs = await load_corpus(db, 0)
    palace = Palace(tmp_path / "index")
    vectors = [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in docs]
    try:
        palace.commit_batch(docs[:2], vectors[:2])
        assert len(palace.pending(docs)) == 2
        assert palace.watermark is None
        palace.commit_batch(docs[2:], vectors[2:])
        palace.reconcile(docs)
        assert not palace.pending(docs)
        assert palace.collection.count() == 4
        sem, lex = palace.candidates(filtered(docs, req()), "aflyser", vectors[0])
        assert "msg:102:0" not in sem + lex
        assert "msg:103:0" in sem and "msg:103:0" in lex
    finally:
        palace.backend.close()
    palace = Palace(tmp_path / "index")
    try:
        assert not palace.pending(docs)
        palace.reconcile(docs[:1])
        assert palace.collection.count() == 1
        with pytest.raises(ValueError):
            palace.commit_batch(docs, [[0.0]])
    finally:
        palace.backend.close()
    (tmp_path / "index" / "index.json").write_text('{"model":"wrong"}')
    with pytest.raises(ValueError, match="mismatch"):
        Palace(tmp_path / "index")


async def test_derived_attribution_uses_sources_not_speaker_hint(db):
    # Existing anonymized compiler fixture deliberately annotates the wrong speaker.
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    run_id = await _compile_spanien_run(db)
    docs = await load_corpus(db, run_id)
    author_docs = filtered(docs, dict(people=[10], person_role="author"))
    assert not any(d.kind == "segment_summary" for d in author_docs)
    assert not any(d.kind == "preference" for d in author_docs)
    subject_docs = filtered(docs, dict(people=[10], person_role="subject"))
    assert any(d.kind == "preference" for d in subject_docs)
    assert any(d.kind.startswith("rollup") for d in docs)


async def test_embedding_outage_uses_filtered_lexical(db, tmp_path):
    await seed(db)
    docs = await load_corpus(db, 0)
    palace = Palace(tmp_path / "index")
    try:
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1) for _ in docs])
        palace.reconcile(docs)
        client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError)))
        result = await search(db, req(), palace, client)
        assert result.status == "degraded"
        assert set(result.source_handles) == {"msg:101", "msg:103"}
        none = await search(db, dict(req(), query="intetmatch"), palace, client)
        assert not none.answerable
    finally:
        palace.backend.close()


async def test_worker_interrupted_sync_and_snapshot_restore(tmp_path, monkeypatch):
    from klatrebot_v2.memory.worker import Worker
    from klatrebot_v2.memory.evaluate import seed as seed_file
    from pathlib import Path
    cases = json.loads(Path("tests/fixtures/danish_recall.json").read_text(encoding="utf-8"))
    source = tmp_path / "source.db"
    await seed_file(source, cases)
    palace = Palace(tmp_path / "index")
    settings = SimpleNamespace(db_path=str(source), memory_active_run_name=None, memory_active_run_id=0)
    worker = Worker(settings, palace, None)
    async def failed(*args, **kwargs):
        raise TimeoutError
    monkeypatch.setattr("klatrebot_v2.memory.worker.embed", failed)
    try:
        with pytest.raises(TimeoutError):
            await worker.sync()
        assert palace.watermark is None
        assert len(palace.pending(await worker.corpus())) == 30
        async def success(client, texts, **kwargs):
            return [[1.] + [0.] * (DIMENSIONS - 1) for _ in texts], 100
        monkeypatch.setattr("klatrebot_v2.memory.worker.embed", success)
        await worker.sync()
        await worker.sync()
        assert palace.collection.count() == 30
        snapshot = worker.snapshot(str(Path(settings.db_path).resolve()))
        restored = Palace(snapshot["snapshot_path"])
        try:
            assert restored.collection.count() == 30
            assert restored.watermark == palace.watermark
            restored_settings = SimpleNamespace(db_path=str(Path(snapshot["snapshot_path"]) / "source.db"),
                                               memory_active_run_name=None, memory_active_run_id=0)
            restored_worker = Worker(restored_settings, restored, None)
            assert not restored.pending(await restored_worker.corpus())
        finally:
            await restored_worker.cache.close()
            restored.backend.close()
    finally:
        await worker.cache.close()
        palace.backend.close()


async def test_danish_fixture_lexical_baseline(db):
    from pathlib import Path
    from klatrebot_v2.memory.corpus import utc
    cases = json.loads(Path("tests/fixtures/danish_recall.json").read_text(encoding="utf-8"))
    await users.upsert(db, discord_user_id=1, display_name="Anna")
    for case in cases:
        for msg in case["messages"]:
            await messages.insert(db, **dict(msg, timestamp_utc=utc(msg["timestamp_utc"])))
    found = 0
    for case in cases:
        result = await search(db, dict(case["request"], run_id=0, limit=10))
        source_ids = {mid for r in result.results for mid in r.source_ids}
        found += set(case["expected_source_ids"]) <= source_ids
    assert len(cases) >= 30
    assert found / len(cases) >= .9


async def test_legacy_does_not_call_mempalace(db, monkeypatch):
    await seed(db)
    from klatrebot_v2.memory.retrieval import RecallResult
    legacy = RecallResult(answerable=False)
    monkeypatch.setattr("klatrebot_v2.memory.tools.recall_community_memory", AsyncMock(return_value=legacy))
    worker = AsyncMock(side_effect=AssertionError("Legacy must not call the worker"))
    monkeypatch.setattr("klatrebot_v2.memory.tools.request", worker)
    settings = SimpleNamespace(memory_backend="legacy", memory_socket_path="missing")
    output = json.loads(await execute_memory_tool(db, run_id=0, settings=settings,
        name="recall_community_memory", arguments={"query": "aflyser", "people": [1]}))
    assert not output["answerable"]
    worker.assert_not_awaited()


async def test_long_chunks_and_edited_deleted_sources(db, tmp_path):
    await seed(db)
    await db.execute("UPDATE messages SET content=? WHERE discord_message_id=101", ("😀" * 5000,))
    docs = await load_corpus(db, 0)
    assert len([d for d in docs if d.handle == "msg:101"]) == 4
    assert all(len(d.text.encode()) <= 6000 for d in docs)
    palace = Palace(tmp_path / "index")
    try:
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1) for _ in docs])
        palace.reconcile(docs)
        await db.execute("UPDATE messages SET content='nyt indhold' WHERE discord_message_id=103")
        await db.execute("DELETE FROM messages WHERE discord_message_id=102")
        changed = await load_corpus(db, 0)
        sem, lex = palace.candidates(changed, "aflyser", [1.] + [0.] * (DIMENSIONS - 1))
        assert "msg:103:0" not in sem + lex
        assert "msg:102:0" not in sem + lex
        palace.reconcile(changed)
        assert [d.id for d in palace.pending(changed)] == ["msg:103:0"]
    finally:
        palace.backend.close()


async def test_cached_lexical_scores_match_native_collection_ranking(db, tmp_path):
    from tests.unit.test_memory_retrieval import _compile_spanien_run
    run = await _compile_spanien_run(db)
    docs = await load_corpus(db, run)
    palace = Palace(tmp_path / "index")
    try:
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1) for _ in docs])
        for query in ["Spanien transport", "Spanien Spanien fly", "kalk klatring", "udendørs klatretur", "ingenmatch"]:
            for subset in [docs, [d for d in docs if d.authors == [10]], docs[:3]]:
                eligible = {d.id for d in subset}
                native = palace.collection.lexical_search(query=query, n_results=30,
                                                          where={"doc_id": {"$in": eligible}})
                assert palace.lexical_candidates(query, eligible) == [hit.id for hit in native.hits]
        # Updating any document changes corpus-wide BM25 statistics.
        palace.commit_batch(docs[:1], [[1.] + [0.] * (DIMENSIONS - 1)])
        assert not palace.lexical_cache
    finally:
        palace.backend.close()


async def test_semantic_filter_is_applied_before_candidate_limit(db, tmp_path):
    from klatrebot_v2.memory.corpus import Document
    palace = Palace(tmp_path / "index")
    docs = [Document(str(i), f"msg:{i}", "klatring", "raw_message", 42,
                     "2026-08-01T00:00:00+00:00", [i], [1 if i == 40 else 2], [], []) for i in range(41)]
    try:
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1) for _ in docs])
        semantic, _ = palace.candidates([docs[-1]], "klatring", [1.] + [0.] * (DIMENSIONS - 1))
        assert semantic == ["40"]
    finally:
        palace.backend.close()


def test_fusion_can_use_lexical_support_below_semantic_rank_thirty(tmp_path):
    from klatrebot_v2.memory.corpus import Document
    from klatrebot_v2.memory.search import fuse
    palace = Palace(tmp_path / "index")
    docs = [Document(f"{i:03}", f"msg:{i}", "specialterm" if i == 34 else "ordinary",
        "raw_message", 42, "2026-08-01T00:00:00+00:00", [i], [1], [], []) for i in range(65)]
    try:
        palace.commit_batch(docs, [[1.] + [0.] * (DIMENSIONS - 1) for _ in docs])
        semantic, lexical = palace.candidates(docs, "specialterm", [1.] + [0.] * (DIMENSIONS - 1))
        assert len(semantic) == 60
        assert semantic.index("034") >= 30
        assert fuse(semantic, lexical)[0] == "034"
    finally:
        palace.backend.close()


@pytest.mark.skipif(__import__("os").name != "posix", reason="Unix worker transport requires Linux")
async def test_unix_worker_transport_and_restart(tmp_path):
    import asyncio
    from klatrebot_v2.memory.worker import Worker
    from klatrebot_v2.memory.evaluate import seed as seed_file
    from klatrebot_v2.memory.transport import request
    from pathlib import Path
    cases = json.loads(Path("tests/fixtures/danish_recall.json").read_text(encoding="utf-8"))
    source = tmp_path / "source.db"
    await seed_file(source, cases)
    settings = SimpleNamespace(db_path=str(source), memory_active_run_name=None, memory_active_run_id=0)
    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError)))
    socket_path = tmp_path / "worker.sock"
    for _ in range(2):
        palace = Palace(tmp_path / "index")
        worker = Worker(settings, palace, client)
        socket_path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(worker.handle, path=str(socket_path))
        try:
            async with server:
                result = await request(str(socket_path), dict(cases[0]["request"], run_id=0))
                assert result["status"] == "degraded"
                assert result["coverage"]["worker_peak_rss_mb"] > 0
                snapshot = await request(str(socket_path), {"operation": "snapshot", "db_path": str(Path(settings.db_path).resolve())})
                assert (Path(snapshot["snapshot_path"]) / "source.db").exists()
        finally:
            await worker.cache.close()
            palace.backend.close()
