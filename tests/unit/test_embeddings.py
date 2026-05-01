import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.llm import client
    from klatrebot_v2.settings import get_settings
    client._client = None
    get_settings.cache_clear()


def _patch_embed(monkeypatch, vectors_per_input: list[list[float]]):
    from klatrebot_v2.llm import client
    fake = MagicMock()
    fake.embeddings = MagicMock()
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors_per_input]
    fake.embeddings.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(client, "_client", fake)
    return fake


async def test_embed_skips_empty_inputs(monkeypatch):
    fake = _patch_embed(monkeypatch, [[0.1, 0.2]])
    from klatrebot_v2.llm import embeddings
    out = await embeddings.embed(["", "hej", "   "])
    assert out[0] is None
    assert out[1] == [0.1, 0.2]
    assert out[2] is None
    fake.embeddings.create.assert_awaited_once()
    kwargs = fake.embeddings.create.await_args.kwargs
    assert kwargs["input"] == ["hej"]


async def test_embed_all_empty_no_api_call(monkeypatch):
    fake = _patch_embed(monkeypatch, [])
    from klatrebot_v2.llm import embeddings
    out = await embeddings.embed(["", "  ", ""])
    assert out == [None, None, None]
    fake.embeddings.create.assert_not_called()


async def test_db_upsert_and_search_roundtrip(db):
    from klatrebot_v2.db import embeddings as emb_db
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE name='message_embeddings'")
    if not await cursor.fetchone():
        pytest.skip("vec0 extension not available")

    v1 = [1.0] + [0.0] * 1535
    v2 = [0.0, 1.0] + [0.0] * 1534
    v3 = [0.99] + [0.0] * 1535  # close to v1

    await emb_db.upsert(db, message_id=1, vector=v1)
    await emb_db.upsert(db, message_id=2, vector=v2)
    await emb_db.upsert(db, message_id=3, vector=v3)

    results = await emb_db.search(db, query_vector=v1, k=2)
    ids = [r[0] for r in results]
    assert 1 in ids
    assert 3 in ids


async def test_db_existing_ids(db):
    from klatrebot_v2.db import embeddings as emb_db
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE name='message_embeddings'")
    if not await cursor.fetchone():
        pytest.skip("vec0 extension not available")

    v = [0.5] + [0.0] * 1535
    await emb_db.upsert(db, message_id=10, vector=v)
    await emb_db.upsert(db, message_id=20, vector=v)
    found = await emb_db.existing_ids(db, [10, 20, 30])
    assert found == {10, 20}
