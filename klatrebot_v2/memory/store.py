"""SQLite persistence helpers for durable memory."""
import json
from datetime import datetime
from typing import Any

import aiosqlite

from klatrebot_v2.memory.segmentation import RawMemoryMessage, SegmentCandidate


PROMPT_VERSION = "summary-memory-v1"


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def create_compiler_run(
    conn: aiosqlite.Connection,
    *,
    name: str,
    compiler_model: str,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    channel_ids: list[int] | None = None,
    config: dict[str, Any] | None = None,
    source_db_label: str | None = None,
) -> int:
    await delete_compiler_run_by_name(conn, name)
    cursor = await conn.execute(
        """
        INSERT INTO memory_compiler_runs
            (name, status, source_db_label, from_time_utc, to_time_utc, channel_ids_json,
             config_json, prompt_version, compiler_model)
        VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            source_db_label,
            _dt(from_time),
            _dt(to_time),
            json.dumps(channel_ids or []),
            json.dumps(config or {}),
            PROMPT_VERSION,
            compiler_model,
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid)


async def delete_compiler_run_by_name(conn: aiosqlite.Connection, name: str) -> None:
    existing = await _fetch_one_dict(conn, "SELECT id FROM memory_compiler_runs WHERE name = ?", (name,))
    if not existing:
        return
    run_id = int(existing["id"])
    await conn.execute(
        """
        DELETE FROM memory_items_fts
        WHERE rowid IN (SELECT id FROM memory_items WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM conversation_segments_fts
        WHERE rowid IN (SELECT id FROM conversation_segments WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_item_sources
        WHERE memory_item_id IN (SELECT id FROM memory_items WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_item_tags
        WHERE memory_item_id IN (SELECT id FROM memory_items WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM conversation_segment_tags
        WHERE segment_id IN (SELECT id FROM conversation_segments WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM segment_messages
        WHERE segment_id IN (SELECT id FROM conversation_segments WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute("DELETE FROM memory_items WHERE compiler_run_id = ?", (run_id,))
    await conn.execute("DELETE FROM conversation_segments WHERE compiler_run_id = ?", (run_id,))
    await conn.execute("DELETE FROM memory_compiler_runs WHERE id = ?", (run_id,))
    await conn.commit()


async def complete_compiler_run(conn: aiosqlite.Connection, run_id: int) -> None:
    await conn.execute(
        """
        UPDATE memory_compiler_runs
        SET status = 'completed', completed_at = datetime('now'), error = NULL
        WHERE id = ?
        """,
        (run_id,),
    )
    await conn.commit()


async def fail_compiler_run(conn: aiosqlite.Connection, run_id: int, error: str) -> None:
    await conn.execute(
        """
        UPDATE memory_compiler_runs
        SET status = 'failed', completed_at = datetime('now'), error = ?
        WHERE id = ?
        """,
        (error, run_id),
    )
    await conn.commit()


async def get_compiler_run_by_name(
    conn: aiosqlite.Connection,
    name: str,
) -> dict[str, Any] | None:
    return await _fetch_one_dict(conn, "SELECT * FROM memory_compiler_runs WHERE name = ?", (name,))


async def get_compiler_run(conn: aiosqlite.Connection, run_id: int) -> dict[str, Any] | None:
    return await _fetch_one_dict(conn, "SELECT * FROM memory_compiler_runs WHERE id = ?", (run_id,))


async def list_segments_for_run(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        "SELECT * FROM conversation_segments WHERE compiler_run_id = ? ORDER BY start_time_utc",
        (run_id,),
    )


async def load_messages(
    conn: aiosqlite.Connection,
    *,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    channel_ids: list[int] | None = None,
) -> list[RawMemoryMessage]:
    where = []
    params: list[Any] = []
    if from_time is not None:
        where.append("m.timestamp_utc >= ?")
        params.append(from_time.isoformat())
    if to_time is not None:
        where.append("m.timestamp_utc < ?")
        params.append(to_time.isoformat())
    if channel_ids:
        where.append(f"m.channel_id IN ({','.join('?' for _ in channel_ids)})")
        params.extend(channel_ids)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cursor = await conn.execute(
        f"""
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM messages m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        {where_sql}
        ORDER BY m.channel_id, m.timestamp_utc, m.discord_message_id
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        RawMemoryMessage(
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


async def insert_segment(
    conn: aiosqlite.Connection,
    *,
    compiler_run_id: int,
    segment: SegmentCandidate,
    topic_title: str,
    summary: str,
    importance: str,
    tags: list[str] | None = None,
    status: str = "summarized",
    skip_reason: str | None = None,
) -> int:
    cursor = await conn.execute(
        """
        INSERT INTO conversation_segments
            (compiler_run_id, channel_id, start_time_utc, end_time_utc, message_count,
             human_message_count, total_chars, participant_ids_json, topic_title,
             summary, importance, status, skip_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            compiler_run_id,
            segment.channel_id,
            segment.start_time_utc.isoformat(),
            segment.end_time_utc.isoformat(),
            segment.message_count,
            segment.human_message_count,
            segment.total_chars,
            json.dumps(segment.participant_ids),
            topic_title,
            summary,
            importance,
            status,
            skip_reason,
        ),
    )
    segment_id = int(cursor.lastrowid)
    for pos, message in enumerate(segment.messages):
        await conn.execute(
            """
            INSERT INTO segment_messages (segment_id, discord_message_id, position)
            VALUES (?, ?, ?)
            """,
            (segment_id, message.discord_message_id, pos),
        )
    await conn.execute(
        """
        INSERT INTO conversation_segments_fts(rowid, topic_title, summary)
        VALUES (?, ?, ?)
        """,
        (segment_id, topic_title, summary),
    )
    for tag in tags or []:
        await conn.execute(
            """
            INSERT OR IGNORE INTO conversation_segment_tags (segment_id, tag)
            VALUES (?, ?)
            """,
            (segment_id, tag),
        )
    await conn.commit()
    return segment_id


async def insert_memory_item(
    conn: aiosqlite.Connection,
    *,
    compiler_run_id: int,
    segment_id: int,
    item: dict[str, Any],
    segment: SegmentCandidate,
) -> int:
    source_ids = [int(x) for x in item.get("source_message_ids", []) if x]
    created_at_source, last_seen_at_source = _source_time_bounds(segment, source_ids)
    cursor = await conn.execute(
        """
        INSERT INTO memory_items
            (compiler_run_id, segment_id, type, subject, text, confidence, importance,
             speaker_ids_json, created_at_source, last_seen_at_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            compiler_run_id,
            segment_id,
            item["type"],
            item.get("subject", ""),
            item["text"],
            item.get("confidence", "medium"),
            item.get("importance", "normal"),
            json.dumps(item.get("speaker_ids", [])),
            _dt(created_at_source),
            _dt(last_seen_at_source),
        ),
    )
    item_id = int(cursor.lastrowid)
    for message_id in source_ids:
        await conn.execute(
            """
            INSERT OR IGNORE INTO memory_item_sources (memory_item_id, discord_message_id)
            VALUES (?, ?)
            """,
            (item_id, message_id),
        )
    for tag in item.get("tags", []):
        await conn.execute(
            """
            INSERT OR IGNORE INTO memory_item_tags (memory_item_id, tag)
            VALUES (?, ?)
            """,
            (item_id, tag),
        )
    await conn.execute(
        """
        INSERT INTO memory_items_fts(rowid, type, subject, text)
        VALUES (?, ?, ?, ?)
        """,
        (item_id, item["type"], item.get("subject", ""), item["text"]),
    )
    await conn.commit()
    return item_id


def _source_time_bounds(
    segment: SegmentCandidate,
    source_ids: list[int],
) -> tuple[datetime | None, datetime | None]:
    by_id = {m.discord_message_id: m for m in segment.messages}
    selected = [by_id[mid].timestamp_utc for mid in source_ids if mid in by_id]
    if not selected:
        return segment.start_time_utc, segment.end_time_utc
    return min(selected), max(selected)


async def _fetch_one_dict(
    conn: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> dict[str, Any] | None:
    old_factory = conn.row_factory
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.row_factory = old_factory


async def _fetch_all_dicts(
    conn: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    old_factory = conn.row_factory
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        conn.row_factory = old_factory
