"""Message log queries."""
import asyncio
import logging
from datetime import datetime

import aiosqlite
from pydantic import BaseModel

from klatrebot_v2.db.models import Message


logger = logging.getLogger(__name__)


async def insert(
    conn: aiosqlite.Connection,
    *,
    discord_message_id: int,
    channel_id: int,
    user_id: int,
    content: str,
    timestamp_utc: datetime,
    is_bot: bool = False,
) -> None:
    await conn.execute(
        """
        INSERT OR IGNORE INTO messages
            (discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            discord_message_id,
            channel_id,
            user_id,
            content,
            timestamp_utc.isoformat(),
            1 if is_bot else 0,
        ),
    )
    await conn.commit()
    _schedule_embed(conn, discord_message_id, content)


def _schedule_embed(conn: aiosqlite.Connection, message_id: int, content: str) -> None:
    """Fire-and-forget: embed message and upsert vector. Skips silently on any failure."""
    try:
        from klatrebot_v2.settings import get_settings
        if not get_settings().embeddings_enabled:
            return
    except Exception:
        return
    if not (content or "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_embed_and_store(conn, message_id, content))


async def _embed_and_store(conn: aiosqlite.Connection, message_id: int, content: str) -> None:
    try:
        from klatrebot_v2.llm import embeddings as emb_llm
        from klatrebot_v2.db import embeddings as emb_db
        vectors = await emb_llm.embed([content])
        if not vectors or vectors[0] is None:
            return
        await emb_db.upsert(conn, message_id=message_id, vector=vectors[0])
    except Exception as e:
        logger.warning("embed-on-insert failed for message_id=%d: %s", message_id, e)


async def recent(conn: aiosqlite.Connection, *, channel_id: int, limit: int) -> list[Message]:
    """Return the last `limit` messages for `channel_id`, oldest-first within that window."""
    cursor = await conn.execute(
        """
        SELECT discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot
        FROM (
            SELECT * FROM messages
            WHERE channel_id = ?
            ORDER BY timestamp_utc DESC
            LIMIT ?
        )
        ORDER BY timestamp_utc ASC
        """,
        (channel_id, limit),
    )
    rows = await cursor.fetchall()
    return [
        Message(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            content=r[3],
            timestamp_utc=datetime.fromisoformat(r[4]),
            is_bot=bool(r[5]),
        )
        for r in rows
    ]


class MessageWithAuthor(BaseModel):
    discord_message_id: int
    channel_id: int
    user_id: int
    user_display_name: str
    content: str
    timestamp_utc: datetime
    is_bot: bool


async def recent_with_authors(
    conn: aiosqlite.Connection, *, channel_id: int, limit: int
) -> list[MessageWithAuthor]:
    cursor = await conn.execute(
        """
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM (
            SELECT * FROM messages
            WHERE channel_id = ?
            ORDER BY timestamp_utc DESC
            LIMIT ?
        ) m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, limit),
    )
    rows = await cursor.fetchall()
    return [
        MessageWithAuthor(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            user_display_name=r[3],
            content=r[4],
            timestamp_utc=datetime.fromisoformat(r[5]),
            is_bot=bool(r[6]),
        )
        for r in rows
    ]


async def in_window(
    conn: aiosqlite.Connection,
    *,
    channel_id: int,
    start: datetime,
    end: datetime,
) -> list[MessageWithAuthor]:
    """[start, end) window, oldest-first."""
    cursor = await conn.execute(
        """
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM messages m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        WHERE m.channel_id = ?
          AND m.timestamp_utc >= ?
          AND m.timestamp_utc <  ?
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, start.isoformat(), end.isoformat()),
    )
    rows = await cursor.fetchall()
    return [
        MessageWithAuthor(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            user_display_name=r[3],
            content=r[4],
            timestamp_utc=datetime.fromisoformat(r[5]),
            is_bot=bool(r[6]),
        )
        for r in rows
    ]
