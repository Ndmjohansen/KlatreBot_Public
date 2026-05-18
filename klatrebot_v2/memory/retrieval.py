"""Retrieval over compiled community memory."""
from datetime import datetime, timedelta
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field


class RelatedMemory(BaseModel):
    source_handle: str
    type: str
    subject: str
    text: str
    relation: str
    score: float


class MemoryResult(BaseModel):
    kind: str
    source_handle: str
    topic_title: str | None = None
    summary: str | None = None
    type: str | None = None
    subject: str | None = None
    text: str | None = None
    confidence: str | None = None
    time_range: str | None = None
    participants: list[int] = Field(default_factory=list)
    segment_id: int | None = None
    created_at_source: datetime | None = None
    related_memories: list[RelatedMemory] = Field(default_factory=list)


class RecallResult(BaseModel):
    answerable: bool
    results: list[MemoryResult] = Field(default_factory=list)
    source_handles: list[str] = Field(default_factory=list)


class SourceMessage(BaseModel):
    discord_message_id: int
    channel_id: int
    user_id: int
    user_display_name: str
    content: str
    timestamp_utc: datetime
    is_bot: bool


async def recall_community_memory(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    channel_id: int | None = None,
    people: list[int] | None = None,
    date_range: tuple[datetime | None, datetime | None] | None = None,
    memory_types: list[str] | None = None,
    limit: int = 6,
) -> RecallResult:
    """Search summaries and durable memory items for a recall query."""
    query = query.strip()
    if not query:
        return RecallResult(answerable=False)

    segment_results = await _search_segments(
        conn,
        run_id=run_id,
        query=query,
        channel_id=channel_id,
        date_range=date_range,
        limit=limit,
    )
    item_results = await _search_items(
        conn,
        run_id=run_id,
        query=query,
        memory_types=memory_types,
        date_range=date_range,
        people=people,
        limit=limit,
    )
    item_results = await _attach_related_memories(conn, run_id=run_id, items=item_results)
    results = [*item_results, *segment_results][:limit]
    return RecallResult(
        answerable=bool(results),
        results=results,
        source_handles=[r.source_handle for r in results],
    )


async def get_memory_sources(
    conn: aiosqlite.Connection,
    *,
    source_handles: list[str],
    context_radius: int = 5,
) -> list[SourceMessage]:
    """Return raw source messages around segment/item handles."""
    message_ids: set[int] = set()
    for handle in source_handles:
        kind, _, raw_id = handle.partition(":")
        if not raw_id.isdigit():
            continue
        if kind == "seg":
            message_ids.update(await _segment_message_ids(conn, int(raw_id)))
        elif kind == "mem":
            message_ids.update(await _memory_item_source_ids(conn, int(raw_id)))

    expanded_ids: set[int] = set()
    for message_id in message_ids:
        expanded_ids.update(await _nearby_message_ids(conn, message_id, context_radius))

    if not expanded_ids:
        return []
    placeholders = ",".join("?" for _ in expanded_ids)
    cursor = await conn.execute(
        f"""
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM messages m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        WHERE m.discord_message_id IN ({placeholders})
        ORDER BY m.channel_id, m.timestamp_utc, m.discord_message_id
        """,
        tuple(expanded_ids),
    )
    return [
        SourceMessage(
            discord_message_id=row[0],
            channel_id=row[1],
            user_id=row[2],
            user_display_name=row[3],
            content=row[4],
            timestamp_utc=datetime.fromisoformat(row[5]),
            is_bot=bool(row[6]),
        )
        for row in await cursor.fetchall()
    ]


async def _search_segments(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    channel_id: int | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    limit: int,
) -> list[MemoryResult]:
    where = ["cs.compiler_run_id = ?", "cs.status = 'summarized'", "conversation_segments_fts MATCH ?"]
    params: list[Any] = [run_id, _fts_query(query)]
    if channel_id is not None:
        where.append("cs.channel_id = ?")
        params.append(channel_id)
    _append_date_filter(where, params, "cs.start_time_utc", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT cs.id, cs.topic_title, cs.summary, cs.start_time_utc, cs.end_time_utc,
               cs.participant_ids_json
        FROM conversation_segments_fts
        JOIN conversation_segments cs ON cs.id = conversation_segments_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25(conversation_segments_fts)
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        MemoryResult(
            kind="segment_summary",
            source_handle=f"seg:{row[0]}",
            topic_title=row[1],
            summary=row[2],
            time_range=f"{row[3]} - {row[4]}",
            participants=_json_int_list(row[5]),
        )
        for row in rows
    ]


async def _search_items(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    memory_types: list[str] | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    people: list[int] | None,
    limit: int,
) -> list[MemoryResult]:
    where = ["mi.compiler_run_id = ?", "memory_items_fts MATCH ?"]
    params: list[Any] = [run_id, _fts_query(query)]
    if memory_types:
        where.append(f"mi.type IN ({','.join('?' for _ in memory_types)})")
        params.extend(memory_types)
    _append_date_filter(where, params, "mi.created_at_source", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT mi.id, mi.type, mi.subject, mi.text, mi.confidence, mi.speaker_ids_json,
               mi.segment_id, mi.created_at_source
        FROM memory_items_fts
        JOIN memory_items mi ON mi.id = memory_items_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25(memory_items_fts)
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    results = [
        MemoryResult(
            kind="memory_item",
            source_handle=f"mem:{row[0]}",
            type=row[1],
            subject=row[2],
            text=row[3],
            confidence=row[4],
            participants=_json_int_list(row[5]),
            segment_id=row[6],
            created_at_source=datetime.fromisoformat(row[7]) if row[7] else None,
        )
        for row in rows
    ]
    if people:
        wanted = set(people)
        results = [r for r in results if wanted.intersection(r.participants)]
    return results


async def _attach_related_memories(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    items: list[MemoryResult],
    window_days: int = 14,
    limit: int = 5,
) -> list[MemoryResult]:
    for item in items:
        if item.kind != "memory_item" or item.created_at_source is None:
            continue
        item_id = _handle_id(item.source_handle)
        if item_id is None:
            continue
        item_tags = await _memory_item_tags(conn, item_id)
        if not item_tags:
            continue
        start = item.created_at_source - timedelta(days=window_days)
        end = item.created_at_source + timedelta(days=window_days)
        candidates = await _related_candidates(
            conn,
            run_id=run_id,
            item_id=item_id,
            tags=item_tags,
            start=start,
            end=end,
        )
        item.related_memories = _rank_related(item, item_tags, candidates, limit)
    return items


async def _memory_item_tags(conn: aiosqlite.Connection, memory_item_id: int) -> set[str]:
    rows = await conn.execute_fetchall(
        "SELECT tag FROM memory_item_tags WHERE memory_item_id = ?",
        (memory_item_id,),
    )
    return {str(row[0]) for row in rows}


async def _related_candidates(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    item_id: int,
    tags: set[str],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in tags)
    rows = await conn.execute_fetchall(
        f"""
        SELECT mi.id, mi.type, mi.subject, mi.text, mi.segment_id, mi.created_at_source,
               group_concat(mit.tag)
        FROM memory_items mi
        JOIN memory_item_tags mit ON mit.memory_item_id = mi.id
        WHERE mi.compiler_run_id = ?
          AND mi.id != ?
          AND mi.created_at_source >= ?
          AND mi.created_at_source <= ?
          AND mit.tag IN ({placeholders})
        GROUP BY mi.id
        """,
        (run_id, item_id, start.isoformat(), end.isoformat(), *tags),
    )
    return [
        {
            "id": row[0],
            "type": row[1],
            "subject": row[2],
            "text": row[3],
            "segment_id": row[4],
            "created_at_source": datetime.fromisoformat(row[5]) if row[5] else None,
            "tags": set(str(row[6] or "").split(",")) if row[6] else set(),
        }
        for row in rows
    ]


def _rank_related(
    item: MemoryResult,
    item_tags: set[str],
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[RelatedMemory]:
    ranked = []
    for candidate in candidates:
        overlap = item_tags.intersection(candidate["tags"])
        if not overlap:
            continue
        days = abs((candidate["created_at_source"] - item.created_at_source).total_seconds()) / 86400 if candidate["created_at_source"] and item.created_at_source else 14
        same_segment = 1 if candidate["segment_id"] == item.segment_id else 0
        same_type_group = 1 if _type_group(candidate["type"]) == _type_group(item.type or "") else 0
        score = len(overlap) * 2 + same_segment + same_type_group + max(0, 1 - (days / 14))
        ranked.append((score, overlap, candidate))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return [
        RelatedMemory(
            source_handle=f"mem:{candidate['id']}",
            type=candidate["type"],
            subject=candidate["subject"],
            text=candidate["text"],
            relation=f"fælles tags: {', '.join(sorted(overlap))}; inden for 14 dage",
            score=round(score, 3),
        )
        for score, overlap, candidate in ranked[:limit]
    ]


def _type_group(memory_type: str) -> str:
    if memory_type in {"plan", "decision", "open_question"}:
        return "coordination"
    return memory_type


def _handle_id(source_handle: str) -> int | None:
    kind, _, raw_id = source_handle.partition(":")
    if kind != "mem" or not raw_id.isdigit():
        return None
    return int(raw_id)


async def _segment_message_ids(conn: aiosqlite.Connection, segment_id: int) -> list[int]:
    rows = await conn.execute_fetchall(
        "SELECT discord_message_id FROM segment_messages WHERE segment_id = ? ORDER BY position",
        (segment_id,),
    )
    return [int(row[0]) for row in rows]


async def _memory_item_source_ids(conn: aiosqlite.Connection, memory_item_id: int) -> list[int]:
    rows = await conn.execute_fetchall(
        "SELECT discord_message_id FROM memory_item_sources WHERE memory_item_id = ?",
        (memory_item_id,),
    )
    return [int(row[0]) for row in rows]


async def _nearby_message_ids(
    conn: aiosqlite.Connection,
    message_id: int,
    radius: int,
) -> list[int]:
    row = await conn.execute_fetchall(
        "SELECT channel_id, timestamp_utc FROM messages WHERE discord_message_id = ?",
        (message_id,),
    )
    if not row:
        return []
    channel_id, timestamp = row[0]
    before = await conn.execute_fetchall(
        """
        SELECT discord_message_id
        FROM messages
        WHERE channel_id = ? AND timestamp_utc <= ?
        ORDER BY timestamp_utc DESC, discord_message_id DESC
        LIMIT ?
        """,
        (channel_id, timestamp, radius + 1),
    )
    after = await conn.execute_fetchall(
        """
        SELECT discord_message_id
        FROM messages
        WHERE channel_id = ? AND timestamp_utc > ?
        ORDER BY timestamp_utc ASC, discord_message_id ASC
        LIMIT ?
        """,
        (channel_id, timestamp, radius),
    )
    return [int(r[0]) for r in before + after]


def _fts_query(query: str) -> str:
    tokens = [t.replace('"', "") for t in query.split() if t.strip()]
    return " OR ".join(f'"{token}"' for token in tokens) or '""'


def _append_date_filter(
    where: list[str],
    params: list[Any],
    column: str,
    date_range: tuple[datetime | None, datetime | None] | None,
) -> None:
    if not date_range:
        return
    start, end = date_range
    if start is not None:
        where.append(f"{column} >= ?")
        params.append(start.isoformat())
    if end is not None:
        where.append(f"{column} < ?")
        params.append(end.isoformat())


def _json_int_list(raw: str) -> list[int]:
    import json

    try:
        return [int(x) for x in json.loads(raw or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
