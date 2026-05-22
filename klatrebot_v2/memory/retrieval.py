"""Retrieval over compiled community memory."""
from datetime import datetime, timedelta, timezone
import re
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

from klatrebot_v2.memory.tags import normalize_tags


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
    importance: str | None = None
    time_range: str | None = None
    participants: list[int] = Field(default_factory=list)
    segment_id: int | None = None
    created_at_source: datetime | None = None
    related_memories: list[RelatedMemory] = Field(default_factory=list)
    matched_tags: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    match_source: str | None = None
    score: float | None = None


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

    tag_terms = _query_tag_terms(query)
    rollup_results = []
    if _should_search_rollups(query, date_range, memory_types):
        rollup_results = [
            *await _search_rollups_by_tags(
                conn,
                run_id=run_id,
                tag_terms=tag_terms,
                channel_id=channel_id,
                limit=limit * 3,
            ),
            *await _search_rollups(
                conn,
                run_id=run_id,
                query=query,
                channel_id=channel_id,
                limit=limit * 3,
            ),
        ]
    ambient_results = [
        *await _search_daily_ambient_by_tags(
            conn,
            run_id=run_id,
            tag_terms=tag_terms,
            channel_id=channel_id,
            date_range=date_range,
            limit=limit * 3,
        ),
        *await _search_daily_ambient(
            conn,
            run_id=run_id,
            query=query,
            channel_id=channel_id,
            date_range=date_range,
            limit=limit * 3,
        ),
    ]
    segment_results = [
        *await _search_segments_by_tags(
            conn,
            run_id=run_id,
            tag_terms=tag_terms,
            channel_id=channel_id,
            date_range=date_range,
            limit=limit * 3,
        ),
        *await _search_segments(
            conn,
            run_id=run_id,
            query=query,
            channel_id=channel_id,
            date_range=date_range,
            limit=limit * 3,
        ),
    ]
    item_results = [
        *await _search_items_by_tags(
            conn,
            run_id=run_id,
            tag_terms=tag_terms,
            channel_id=channel_id,
            memory_types=memory_types,
            date_range=date_range,
            people=people,
            limit=limit * 3,
        ),
        *await _search_items(
            conn,
            run_id=run_id,
            query=query,
            channel_id=channel_id,
            memory_types=memory_types,
            date_range=date_range,
            people=people,
            limit=limit * 3,
        ),
    ]
    item_results = _dedupe_memory_items(_merge_results(item_results))
    item_results = await _attach_related_memories(conn, run_id=run_id, items=item_results)
    results = _rank_results(
        _merge_results([*rollup_results, *item_results, *ambient_results, *segment_results])
    )[:limit]
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
        elif kind == "roll":
            message_ids.update(await _rollup_message_ids(conn, int(raw_id)))
        elif kind == "amb":
            message_ids.update(await _daily_ambient_message_ids(conn, int(raw_id)))

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


async def _search_rollups(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    channel_id: int | None,
    limit: int,
) -> list[MemoryResult]:
    where = ["mr.compiler_run_id = ?", "mr.status = 'completed'", "memory_rollups_fts MATCH ?"]
    params: list[Any] = [run_id, _fts_query(query)]
    if channel_id is not None:
        where.append("mr.channel_id = ?")
        params.append(channel_id)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT mr.id, mr.period_type, mr.title, mr.summary, mr.key_items_json,
               mr.period_start_utc, mr.period_end_utc
        FROM memory_rollups_fts
        JOIN memory_rollups mr ON mr.id = memory_rollups_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY CASE mr.period_type WHEN 'month' THEN 0 ELSE 1 END,
                 bm25(memory_rollups_fts)
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        MemoryResult(
            kind=f"rollup_{row[1]}",
            source_handle=f"roll:{row[0]}",
            topic_title=row[2],
            summary=row[3],
            text="\n".join(_json_str_list(row[4])),
            time_range=f"{row[5]} - {row[6]}",
            matched_terms=_fts_terms(query),
            match_source="text",
            score=_base_score("text", f"rollup_{row[1]}", importance="normal"),
        )
        for row in rows
    ]


async def _search_rollups_by_tags(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    tag_terms: list[str],
    channel_id: int | None,
    limit: int,
) -> list[MemoryResult]:
    if not tag_terms:
        return []
    where = ["mr.compiler_run_id = ?", "mr.status = 'completed'", f"mrt.tag IN ({_placeholders(tag_terms)})"]
    params: list[Any] = [run_id, *tag_terms]
    if channel_id is not None:
        where.append("mr.channel_id = ?")
        params.append(channel_id)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT mr.id, mr.period_type, mr.title, mr.summary, mr.key_items_json,
               mr.period_start_utc, mr.period_end_utc, mr.importance,
               group_concat(mrt.tag)
        FROM memory_rollups mr
        JOIN memory_rollup_tags mrt ON mrt.rollup_id = mr.id
        WHERE {' AND '.join(where)}
        GROUP BY mr.id
        ORDER BY COUNT(DISTINCT mrt.tag) DESC,
                 CASE mr.period_type WHEN 'month' THEN 0 ELSE 1 END,
                 mr.period_start_utc DESC
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        MemoryResult(
            kind=f"rollup_{row[1]}",
            source_handle=f"roll:{row[0]}",
            topic_title=row[2],
            summary=row[3],
            text="\n".join(_json_str_list(row[4])),
            time_range=f"{row[5]} - {row[6]}",
            matched_tags=_csv_list(row[8]),
            matched_terms=_matched_terms(tag_terms, _csv_list(row[8])),
            match_source="tag",
            score=_base_score("tag", f"rollup_{row[1]}", importance=row[7]) + len(_csv_list(row[8])) * 10,
        )
        for row in rows
    ]


async def _search_daily_ambient(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    channel_id: int | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    limit: int,
) -> list[MemoryResult]:
    where = ["dam.compiler_run_id = ?", "dam.status = 'completed'", "daily_ambient_memory_fts MATCH ?"]
    params: list[Any] = [run_id, _fts_query(query)]
    if channel_id is not None:
        where.append("dam.channel_id = ?")
        params.append(channel_id)
    _append_date_filter(where, params, "dam.day_start_utc", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT dam.id, dam.title, dam.summary, dam.key_items_json,
               dam.day_start_utc, dam.day_end_utc, dam.importance
        FROM daily_ambient_memory_fts
        JOIN daily_ambient_memory dam ON dam.id = daily_ambient_memory_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25(daily_ambient_memory_fts)
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        MemoryResult(
            kind="daily_ambient",
            source_handle=f"amb:{row[0]}",
            topic_title=row[1],
            summary=row[2],
            text="\n".join(_json_str_list(row[3])),
            importance=row[6],
            time_range=f"{row[4]} - {row[5]}",
            matched_terms=_fts_terms(query),
            match_source="text",
            score=_base_score("text", "daily_ambient", importance=row[6]),
        )
        for row in rows
    ]


async def _search_daily_ambient_by_tags(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    tag_terms: list[str],
    channel_id: int | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    limit: int,
) -> list[MemoryResult]:
    if not tag_terms:
        return []
    where = ["dam.compiler_run_id = ?", "dam.status = 'completed'", f"dat.tag IN ({_placeholders(tag_terms)})"]
    params: list[Any] = [run_id, *tag_terms]
    if channel_id is not None:
        where.append("dam.channel_id = ?")
        params.append(channel_id)
    _append_date_filter(where, params, "dam.day_start_utc", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT dam.id, dam.title, dam.summary, dam.key_items_json,
               dam.day_start_utc, dam.day_end_utc, dam.importance,
               group_concat(dat.tag)
        FROM daily_ambient_memory dam
        JOIN daily_ambient_tags dat ON dat.ambient_id = dam.id
        WHERE {' AND '.join(where)}
        GROUP BY dam.id
        ORDER BY COUNT(DISTINCT dat.tag) DESC, dam.day_start_utc DESC
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [
        MemoryResult(
            kind="daily_ambient",
            source_handle=f"amb:{row[0]}",
            topic_title=row[1],
            summary=row[2],
            text="\n".join(_json_str_list(row[3])),
            importance=row[6],
            time_range=f"{row[4]} - {row[5]}",
            matched_tags=_csv_list(row[7]),
            matched_terms=_matched_terms(tag_terms, _csv_list(row[7])),
            match_source="tag",
            score=_base_score("tag", "daily_ambient", importance=row[6]) + len(_csv_list(row[7])) * 10,
        )
        for row in rows
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
            matched_terms=_fts_terms(query),
            match_source="text",
            score=_base_score("text", "segment_summary", importance="normal"),
        )
        for row in rows
    ]


async def _search_segments_by_tags(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    tag_terms: list[str],
    channel_id: int | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    limit: int,
) -> list[MemoryResult]:
    if not tag_terms:
        return []
    where = ["cs.compiler_run_id = ?", "cs.status = 'summarized'", f"cst.tag IN ({_placeholders(tag_terms)})"]
    params: list[Any] = [run_id, *tag_terms]
    if channel_id is not None:
        where.append("cs.channel_id = ?")
        params.append(channel_id)
    _append_date_filter(where, params, "cs.start_time_utc", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT cs.id, cs.topic_title, cs.summary, cs.start_time_utc, cs.end_time_utc,
               cs.participant_ids_json, cs.importance, group_concat(cst.tag)
        FROM conversation_segments cs
        JOIN conversation_segment_tags cst ON cst.segment_id = cs.id
        WHERE {' AND '.join(where)}
        GROUP BY cs.id
        ORDER BY COUNT(DISTINCT cst.tag) DESC, cs.start_time_utc DESC
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
            matched_tags=_csv_list(row[7]),
            matched_terms=_matched_terms(tag_terms, _csv_list(row[7])),
            match_source="tag",
            score=_base_score("tag", "segment_summary", importance=row[6]) + len(_csv_list(row[7])) * 10,
        )
        for row in rows
    ]


async def _search_items(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    query: str,
    channel_id: int | None,
    memory_types: list[str] | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    people: list[int] | None,
    limit: int,
) -> list[MemoryResult]:
    where = ["mi.compiler_run_id = ?", "memory_items_fts MATCH ?"]
    params: list[Any] = [run_id, _fts_query(query)]
    if channel_id is not None:
        where.append("cs.channel_id = ?")
        params.append(channel_id)
    if memory_types:
        where.append(f"mi.type IN ({','.join('?' for _ in memory_types)})")
        params.extend(memory_types)
    _append_date_filter(where, params, "mi.created_at_source", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT mi.id, mi.type, mi.subject, mi.text, mi.confidence, mi.speaker_ids_json,
               mi.segment_id, mi.created_at_source, mi.last_seen_at_source, mi.importance
        FROM memory_items_fts
        JOIN memory_items mi ON mi.id = memory_items_fts.rowid
        JOIN conversation_segments cs ON cs.id = mi.segment_id
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
            time_range=f"{row[7]} - {row[8]}" if row[7] and row[8] else None,
            participants=_json_int_list(row[5]),
            segment_id=row[6],
            created_at_source=datetime.fromisoformat(row[7]) if row[7] else None,
            matched_terms=_fts_terms(query),
            match_source="text",
            score=_base_score("text", "memory_item", importance=row[9], memory_type=row[1]),
        )
        for row in rows
    ]
    if people:
        wanted = set(people)
        results = [r for r in results if wanted.intersection(r.participants)]
    return results


async def _search_items_by_tags(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    tag_terms: list[str],
    channel_id: int | None,
    memory_types: list[str] | None,
    date_range: tuple[datetime | None, datetime | None] | None,
    people: list[int] | None,
    limit: int,
) -> list[MemoryResult]:
    if not tag_terms:
        return []
    where = ["mi.compiler_run_id = ?", f"mit.tag IN ({_placeholders(tag_terms)})"]
    params: list[Any] = [run_id, *tag_terms]
    if channel_id is not None:
        where.append("cs.channel_id = ?")
        params.append(channel_id)
    if memory_types:
        where.append(f"mi.type IN ({_placeholders(memory_types)})")
        params.extend(memory_types)
    _append_date_filter(where, params, "mi.created_at_source", date_range)
    params.append(limit)
    cursor = await conn.execute(
        f"""
        SELECT mi.id, mi.type, mi.subject, mi.text, mi.confidence, mi.speaker_ids_json,
               mi.segment_id, mi.created_at_source, mi.last_seen_at_source, mi.importance,
               group_concat(mit.tag)
        FROM memory_items mi
        JOIN conversation_segments cs ON cs.id = mi.segment_id
        JOIN memory_item_tags mit ON mit.memory_item_id = mi.id
        WHERE {' AND '.join(where)}
        GROUP BY mi.id
        ORDER BY COUNT(DISTINCT mit.tag) DESC, mi.created_at_source DESC
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
            time_range=f"{row[7]} - {row[8]}" if row[7] and row[8] else None,
            participants=_json_int_list(row[5]),
            segment_id=row[6],
            created_at_source=datetime.fromisoformat(row[7]) if row[7] else None,
            matched_tags=_csv_list(row[10]),
            matched_terms=_matched_terms(tag_terms, _csv_list(row[10])),
            match_source="tag",
            score=_base_score("tag", "memory_item", importance=row[9], memory_type=row[1]) + len(_csv_list(row[10])) * 10,
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
        for score, overlap, candidate in _dedupe_related(ranked, limit)
    ]


def _type_group(memory_type: str) -> str:
    if memory_type in {"plan", "decision", "open_question"}:
        return "coordination"
    return memory_type


def _query_tag_terms(query: str) -> list[str]:
    raw_tokens = [token for token in re.split(r"\s+", query.strip()) if token]
    candidates: list[str] = []
    for size in (3, 2, 1):
        for index in range(0, len(raw_tokens) - size + 1):
            candidates.append(" ".join(raw_tokens[index:index + size]))
    return normalize_tags(candidates)


def _fts_terms(query: str) -> list[str]:
    return normalize_tags(query.split())


def _matched_terms(tag_terms: list[str], matched_tags: list[str]) -> list[str]:
    matched = set(matched_tags)
    return [term for term in tag_terms if term in matched]


def _placeholders(values: list[Any] | tuple[Any, ...] | set[Any]) -> str:
    return ",".join("?" for _ in values)


def _csv_list(raw: str | None) -> list[str]:
    return normalize_tags(str(raw or "").split(","))


def _base_score(
    match_source: str,
    kind: str,
    *,
    importance: str,
    memory_type: str | None = None,
) -> float:
    source_score = 100.0 if match_source == "tag" else 20.0
    kind_score = {
        "rollup_month": 35.0,
        "rollup_week": 30.0,
        "memory_item": 15.0,
        "segment_summary": 5.0,
        "daily_ambient": 2.0,
    }.get(kind, 0.0)
    importance_score = {"high": 8.0, "normal": 4.0, "low": 0.0}.get(importance, 0.0)
    type_score = {"decision": 4.0, "plan": 4.0, "preference": 2.0, "fact": 2.0}.get(memory_type or "", 0.0)
    return source_score + kind_score + importance_score + type_score


def _merge_results(results: list[MemoryResult]) -> list[MemoryResult]:
    merged: dict[str, MemoryResult] = {}
    for result in results:
        existing = merged.get(result.source_handle)
        if existing is None:
            merged[result.source_handle] = result
            continue
        existing.matched_tags = _merge_list(existing.matched_tags, result.matched_tags)
        existing.matched_terms = _merge_list(existing.matched_terms, result.matched_terms)
        existing.related_memories = _merge_related(existing.related_memories, result.related_memories)
        existing.score = max(existing.score or 0.0, result.score or 0.0)
        if existing.match_source != result.match_source:
            existing.match_source = "both"
            existing.score += 15.0
        elif existing.match_source is None:
            existing.match_source = result.match_source
    return list(merged.values())


def _merge_list(left: list[str], right: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*left, *right]:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _rank_results(results: list[MemoryResult]) -> list[MemoryResult]:
    return sorted(
        results,
        key=lambda result: (
            result.score or 0.0,
            result.created_at_source or _result_start_time(result) or datetime.min.replace(tzinfo=timezone.utc),
            result.source_handle,
        ),
        reverse=True,
    )


def _result_start_time(result: MemoryResult) -> datetime | None:
    if not result.time_range:
        return None
    raw_start, _, _ = result.time_range.partition(" - ")
    try:
        return datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe_memory_items(items: list[MemoryResult]) -> list[MemoryResult]:
    kept: list[MemoryResult] = []
    for item in _rank_results(items):
        duplicate = next((existing for existing in kept if _is_likely_duplicate_item(existing, item)), None)
        if duplicate is None:
            kept.append(item)
            continue
        duplicate.matched_tags = _merge_list(duplicate.matched_tags, item.matched_tags)
        duplicate.matched_terms = _merge_list(duplicate.matched_terms, item.matched_terms)
        duplicate.related_memories = _merge_related(duplicate.related_memories, item.related_memories)
        duplicate.score = max(duplicate.score or 0.0, item.score or 0.0)
        if duplicate.match_source != item.match_source:
            duplicate.match_source = "both"
    return kept


def _is_likely_duplicate_item(left: MemoryResult, right: MemoryResult) -> bool:
    if left.kind != "memory_item" or right.kind != "memory_item":
        return False
    if left.created_at_source is None or right.created_at_source is None:
        return False
    if left.created_at_source != right.created_at_source:
        return False
    if _type_group(left.type or "") != _type_group(right.type or ""):
        return False
    return len(set(left.matched_tags).intersection(right.matched_tags)) >= 2


def _dedupe_related(
    ranked: list[tuple[float, set[str], dict[str, Any]]],
    limit: int,
) -> list[tuple[float, set[str], dict[str, Any]]]:
    out: list[tuple[float, set[str], dict[str, Any]]] = []
    seen_handles: set[str] = set()
    seen_texts: set[str] = set()
    for score, overlap, candidate in ranked:
        handle = f"mem:{candidate['id']}"
        text_key = _text_key(candidate["text"])
        if handle in seen_handles or text_key in seen_texts:
            continue
        seen_handles.add(handle)
        seen_texts.add(text_key)
        out.append((score, overlap, candidate))
        if len(out) >= limit:
            break
    return out


def _merge_related(left: list[RelatedMemory], right: list[RelatedMemory]) -> list[RelatedMemory]:
    ranked = sorted([*left, *right], key=lambda related: related.score, reverse=True)
    out: list[RelatedMemory] = []
    seen_handles: set[str] = set()
    seen_texts: set[str] = set()
    for related in ranked:
        text_key = _text_key(related.text)
        if related.source_handle in seen_handles or text_key in seen_texts:
            continue
        seen_handles.add(related.source_handle)
        seen_texts.add(text_key)
        out.append(related)
    return out


def _text_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


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


async def _rollup_message_ids(conn: aiosqlite.Connection, rollup_id: int, seen: set[int] | None = None) -> list[int]:
    seen = seen or set()
    if rollup_id in seen:
        return []
    seen.add(rollup_id)
    rows = await conn.execute_fetchall(
        """
        SELECT source_kind, source_id
        FROM memory_rollup_sources
        WHERE rollup_id = ?
        ORDER BY source_kind, source_id
        """,
        (rollup_id,),
    )
    out: set[int] = set()
    for source_kind, source_id in rows:
        if source_kind == "segment":
            out.update(await _segment_message_ids(conn, int(source_id)))
        elif source_kind == "memory_item":
            out.update(await _memory_item_source_ids(conn, int(source_id)))
        elif source_kind == "rollup":
            out.update(await _rollup_message_ids(conn, int(source_id), seen))
    return sorted(out)


async def _daily_ambient_message_ids(conn: aiosqlite.Connection, ambient_id: int) -> list[int]:
    rows = await conn.execute_fetchall(
        """
        SELECT segment_id
        FROM daily_ambient_sources
        WHERE ambient_id = ?
        ORDER BY segment_id
        """,
        (ambient_id,),
    )
    out: set[int] = set()
    for row in rows:
        out.update(await _segment_message_ids(conn, int(row[0])))
    return sorted(out)


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


def _json_str_list(raw: str) -> list[str]:
    import json

    try:
        return [str(x) for x in json.loads(raw or "[]") if str(x)]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _should_search_rollups(
    query: str,
    date_range: tuple[datetime | None, datetime | None] | None,
    memory_types: list[str] | None,
) -> bool:
    if date_range or memory_types:
        return False
    lowered = query.lower()
    return any(
        token in lowered
        for token in ["hvornår", "sidst", "plejer", "skete", "fest", "tur", "hos ", "julefrokost"]
    )
