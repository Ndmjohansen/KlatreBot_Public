"""Vector store wrappers around sqlite-vec `message_embeddings` virtual table."""
import json
import logging
from datetime import datetime

import aiosqlite


logger = logging.getLogger(__name__)


async def upsert(conn: aiosqlite.Connection, *, message_id: int, vector: list[float]) -> None:
    """Insert or replace embedding for a message."""
    await conn.execute(
        "INSERT OR REPLACE INTO message_embeddings(message_id, embedding) VALUES (?, ?)",
        (message_id, json.dumps(vector)),
    )
    await conn.commit()


async def upsert_many(
    conn: aiosqlite.Connection, items: list[tuple[int, list[float]]]
) -> None:
    if not items:
        return
    await conn.executemany(
        "INSERT OR REPLACE INTO message_embeddings(message_id, embedding) VALUES (?, ?)",
        [(mid, json.dumps(vec)) for mid, vec in items],
    )
    await conn.commit()


async def existing_ids(conn: aiosqlite.Connection, message_ids: list[int]) -> set[int]:
    """Return subset of message_ids that already have embeddings (idempotent backfill)."""
    if not message_ids:
        return set()
    placeholders = ",".join("?" * len(message_ids))
    cursor = await conn.execute(
        f"SELECT message_id FROM message_embeddings WHERE message_id IN ({placeholders})",
        message_ids,
    )
    rows = await cursor.fetchall()
    return {r[0] for r in rows}


async def search(
    conn: aiosqlite.Connection,
    *,
    query_vector: list[float],
    k: int = 20,
    channel_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[tuple[int, float]]:
    """Top-k semantic neighbors. Returns (message_id, distance) sorted nearest-first.

    Optional channel_id / since / until filters are applied via JOIN onto messages.
    """
    where = ["e.embedding MATCH ?", "k = ?"]
    params: list = [json.dumps(query_vector), k]

    join = ""
    if channel_id is not None or since is not None or until is not None:
        join = "JOIN messages m ON m.discord_message_id = e.message_id"
        if channel_id is not None:
            where.append("m.channel_id = ?")
            params.append(channel_id)
        if since is not None:
            where.append("m.timestamp_utc >= ?")
            params.append(since.isoformat())
        if until is not None:
            where.append("m.timestamp_utc < ?")
            params.append(until.isoformat())

    sql = (
        f"SELECT e.message_id, e.distance FROM message_embeddings e {join} "
        f"WHERE {' AND '.join(where)} ORDER BY e.distance"
    )
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]
