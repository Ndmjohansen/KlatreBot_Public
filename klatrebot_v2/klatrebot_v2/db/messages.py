"""Message log queries."""
from datetime import datetime
import aiosqlite
from pydantic import BaseModel

from klatrebot_v2.db.models import Message


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
