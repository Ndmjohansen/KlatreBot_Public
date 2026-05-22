"""SQLite persistence helpers for durable memory."""
import hashlib
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
    config_hash: str | None = None,
    source_db_label: str | None = None,
) -> int:
    await delete_compiler_run_by_name(conn, name)
    cursor = await conn.execute(
        """
        INSERT INTO memory_compiler_runs
            (name, status, source_db_label, from_time_utc, to_time_utc, channel_ids_json,
             config_json, config_hash, prompt_version, compiler_model)
        VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            source_db_label,
            _dt(from_time),
            _dt(to_time),
            json.dumps(channel_ids or []),
            json.dumps(config or {}),
            config_hash,
            PROMPT_VERSION,
            compiler_model,
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid)


async def resume_or_create_compiler_run(
    conn: aiosqlite.Connection,
    *,
    name: str,
    compiler_model: str,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    channel_ids: list[int] | None = None,
    config: dict[str, Any] | None = None,
    config_hash: str | None = None,
    source_db_label: str | None = None,
) -> int:
    existing = await get_compiler_run_by_name(conn, name)
    if not existing:
        return await create_compiler_run(
            conn,
            name=name,
            compiler_model=compiler_model,
            from_time=from_time,
            to_time=to_time,
            channel_ids=channel_ids,
            config=config,
            config_hash=config_hash,
            source_db_label=source_db_label,
        )
    run_id = int(existing["id"])
    await conn.execute(
        """
        UPDATE memory_compiler_runs
        SET status = 'running',
            completed_at = NULL,
            error = NULL,
            source_db_label = ?,
            from_time_utc = CASE
                WHEN from_time_utc IS NULL OR ? < from_time_utc THEN ?
                ELSE from_time_utc
            END,
            to_time_utc = CASE
                WHEN to_time_utc IS NULL OR ? > to_time_utc THEN ?
                ELSE to_time_utc
            END,
            channel_ids_json = ?,
            config_json = ?,
            config_hash = COALESCE(config_hash, ?),
            compiler_model = ?
        WHERE id = ?
        """,
        (
            source_db_label,
            _dt(from_time),
            _dt(from_time),
            _dt(to_time),
            _dt(to_time),
            json.dumps(channel_ids or []),
            json.dumps(config or {}),
            config_hash,
            compiler_model,
            run_id,
        ),
    )
    await conn.commit()
    return run_id


async def delete_compiler_run_by_name(conn: aiosqlite.Connection, name: str) -> None:
    existing = await _fetch_one_dict(conn, "SELECT id FROM memory_compiler_runs WHERE name = ?", (name,))
    if not existing:
        return
    run_id = int(existing["id"])
    await conn.execute("DELETE FROM reflection_documents WHERE compiler_run_id = ?", (run_id,))
    await conn.execute(
        """
        DELETE FROM memory_rollups_fts
        WHERE rowid IN (SELECT id FROM memory_rollups WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_rollup_sources
        WHERE rollup_id IN (SELECT id FROM memory_rollups WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_rollup_tags
        WHERE rollup_id IN (SELECT id FROM memory_rollups WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute("DELETE FROM memory_rollups WHERE compiler_run_id = ?", (run_id,))
    await conn.execute(
        """
        DELETE FROM daily_ambient_memory_fts
        WHERE rowid IN (SELECT id FROM daily_ambient_memory WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM daily_ambient_sources
        WHERE ambient_id IN (SELECT id FROM daily_ambient_memory WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute(
        """
        DELETE FROM daily_ambient_tags
        WHERE ambient_id IN (SELECT id FROM daily_ambient_memory WHERE compiler_run_id = ?)
        """,
        (run_id,),
    )
    await conn.execute("DELETE FROM daily_ambient_memory WHERE compiler_run_id = ?", (run_id,))
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


async def get_segment_by_key(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    segment_key: str,
) -> dict[str, Any] | None:
    return await _fetch_one_dict(
        conn,
        "SELECT * FROM conversation_segments WHERE compiler_run_id = ? AND segment_key = ?",
        (run_id, segment_key),
    )


async def delete_segment_tree(conn: aiosqlite.Connection, segment_id: int) -> None:
    await conn.execute(
        "DELETE FROM memory_items_fts WHERE rowid IN (SELECT id FROM memory_items WHERE segment_id = ?)",
        (segment_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_item_sources
        WHERE memory_item_id IN (SELECT id FROM memory_items WHERE segment_id = ?)
        """,
        (segment_id,),
    )
    await conn.execute(
        """
        DELETE FROM memory_item_tags
        WHERE memory_item_id IN (SELECT id FROM memory_items WHERE segment_id = ?)
        """,
        (segment_id,),
    )
    await conn.execute("DELETE FROM memory_items WHERE segment_id = ?", (segment_id,))
    await conn.execute("DELETE FROM conversation_segments_fts WHERE rowid = ?", (segment_id,))
    await conn.execute("DELETE FROM conversation_segment_tags WHERE segment_id = ?", (segment_id,))
    await conn.execute("DELETE FROM segment_messages WHERE segment_id = ?", (segment_id,))
    await conn.execute("DELETE FROM conversation_segments WHERE id = ?", (segment_id,))
    await conn.commit()


async def list_segment_message_id_sets_for_run(
    conn: aiosqlite.Connection,
    run_id: int,
) -> set[tuple[int, ...]]:
    rows = await conn.execute_fetchall(
        """
        SELECT sm.segment_id, sm.discord_message_id
        FROM segment_messages sm
        JOIN conversation_segments cs ON cs.id = sm.segment_id
        WHERE cs.compiler_run_id = ?
        ORDER BY sm.segment_id, sm.position
        """,
        (run_id,),
    )
    grouped: dict[int, list[int]] = {}
    for segment_id, message_id in rows:
        grouped.setdefault(int(segment_id), []).append(int(message_id))
    return {tuple(ids) for ids in grouped.values()}


async def overlapping_segments_for_messages(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    message_ids: list[int],
) -> list[dict[str, Any]]:
    if not message_ids:
        return []
    placeholders = ",".join("?" for _ in message_ids)
    return await _fetch_all_dicts(
        conn,
        f"""
        SELECT DISTINCT cs.id, cs.status, cs.segment_key
        FROM conversation_segments cs
        JOIN segment_messages sm ON sm.segment_id = cs.id
        WHERE cs.compiler_run_id = ?
          AND cs.channel_id = ?
          AND sm.discord_message_id IN ({placeholders})
        ORDER BY cs.id
        """,
        (run_id, channel_id, *message_ids),
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
    segment_key: str | None = None,
    topic_title: str,
    summary: str,
    importance: str,
    tags: list[str] | None = None,
    status: str = "summarized",
    skip_reason: str | None = None,
    error: str | None = None,
    retry_count: int = 0,
) -> int:
    cursor = await conn.execute(
        """
        INSERT INTO conversation_segments
            (compiler_run_id, segment_key, channel_id, start_time_utc, end_time_utc, message_count,
             human_message_count, total_chars, participant_ids_json, topic_title,
             summary, importance, status, skip_reason, error, retry_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            compiler_run_id,
            segment_key,
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
            error,
            retry_count,
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


async def completed_segments_for_rollups(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT id, channel_id, start_time_utc, end_time_utc, topic_title, summary, importance
        FROM conversation_segments
        WHERE compiler_run_id = ? AND status = 'summarized'
        ORDER BY channel_id, start_time_utc, id
        """,
        (run_id,),
    )


async def skipped_segments_for_daily_ambient(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT id, channel_id, start_time_utc, end_time_utc, message_count,
               human_message_count, total_chars, participant_ids_json,
               topic_title, summary, importance, skip_reason
        FROM conversation_segments
        WHERE compiler_run_id = ? AND status = 'skipped'
        ORDER BY channel_id, start_time_utc, id
        """,
        (run_id,),
    )


async def memory_items_for_segments(
    conn: aiosqlite.Connection,
    segment_ids: list[int],
) -> list[dict[str, Any]]:
    if not segment_ids:
        return []
    placeholders = ",".join("?" for _ in segment_ids)
    return await _fetch_all_dicts(
        conn,
        f"""
        SELECT id, segment_id, type, subject, text, confidence, importance,
               created_at_source, last_seen_at_source
        FROM memory_items
        WHERE segment_id IN ({placeholders})
        ORDER BY created_at_source, id
        """,
        tuple(segment_ids),
    )


async def list_daily_ambient_memory_for_run(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT * FROM daily_ambient_memory
        WHERE compiler_run_id = ?
        ORDER BY day_start_utc, channel_id
        """,
        (run_id,),
    )


async def list_rollups_for_run(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT * FROM memory_rollups
        WHERE compiler_run_id = ?
        ORDER BY period_start_utc, period_type, channel_id
        """,
        (run_id,),
    )


async def reflection_rollups_for_range(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    from_time: datetime,
    to_time: datetime,
    limit: int = 40,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT id, period_type, period_start_utc, period_end_utc, title, summary,
               key_items_json, importance, channel_id
        FROM memory_rollups
        WHERE compiler_run_id = ?
          AND status = 'completed'
          AND period_end_utc > ?
          AND period_start_utc < ?
        ORDER BY period_type DESC, period_start_utc DESC, id DESC
        LIMIT ?
        """,
        (run_id, from_time.isoformat(), to_time.isoformat(), limit),
    )


async def reflection_daily_ambient_for_range(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    from_time: datetime,
    to_time: datetime,
    limit: int = 40,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT id, day_start_utc, day_end_utc, title, summary, key_items_json,
               importance, channel_id
        FROM daily_ambient_memory
        WHERE compiler_run_id = ?
          AND status = 'completed'
          AND day_end_utc > ?
          AND day_start_utc < ?
        ORDER BY day_start_utc DESC, id DESC
        LIMIT ?
        """,
        (run_id, from_time.isoformat(), to_time.isoformat(), limit),
    )


async def reflection_memory_items_for_range(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    from_time: datetime,
    to_time: datetime,
    limit: int = 120,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT mi.id, mi.type, mi.subject, mi.text, mi.confidence, mi.importance,
               mi.speaker_ids_json, mi.created_at_source, mi.last_seen_at_source,
               cs.start_time_utc, cs.end_time_utc, cs.topic_title
        FROM memory_items mi
        JOIN conversation_segments cs ON cs.id = mi.segment_id
        WHERE mi.compiler_run_id = ?
          AND COALESCE(mi.created_at_source, cs.start_time_utc) >= ?
          AND COALESCE(mi.created_at_source, cs.start_time_utc) < ?
          AND mi.importance IN ('normal','high')
        ORDER BY
          CASE mi.importance WHEN 'high' THEN 0 ELSE 1 END,
          COALESCE(mi.created_at_source, cs.start_time_utc) DESC,
          mi.id DESC
        LIMIT ?
        """,
        (run_id, from_time.isoformat(), to_time.isoformat(), limit),
    )


async def reflection_user_activity_for_range(
    conn: aiosqlite.Connection,
    *,
    from_time: datetime,
    to_time: datetime,
    limit: int = 40,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT
            m.user_id,
            COALESCE(u.display_name, '') AS current_display_name,
            COUNT(*) AS message_count,
            MIN(m.timestamp_utc) AS first_seen_in_range,
            MAX(m.timestamp_utc) AS last_seen_in_range,
            COALESCE(
                (
                    SELECT json_group_array(alias)
                    FROM user_aliases ua
                    WHERE ua.discord_user_id = m.user_id
                      AND ua.source = 'config'
                    ORDER BY ua.alias_normalized
                ),
                '[]'
            ) AS config_aliases_json,
            COALESCE(
                (
                    SELECT json_group_array(alias)
                    FROM user_aliases ua
                    WHERE ua.discord_user_id = m.user_id
                      AND ua.source = 'discord_display'
                    ORDER BY ua.alias_normalized
                ),
                '[]'
            ) AS observed_display_names_json
        FROM messages m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        WHERE m.timestamp_utc >= ?
          AND m.timestamp_utc < ?
          AND m.is_bot = 0
        GROUP BY m.user_id, current_display_name
        ORDER BY message_count DESC, last_seen_in_range DESC
        LIMIT ?
        """,
        (from_time.isoformat(), to_time.isoformat(), limit),
    )


async def insert_reflection_document(
    conn: aiosqlite.Connection,
    *,
    compiler_run_id: int,
    name: str,
    from_time: datetime,
    to_time: datetime,
    model: str,
    status: str,
    error: str | None,
    content_markdown: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    content_hash = hashlib.sha256(content_markdown.encode("utf-8")).hexdigest()
    cursor = await conn.execute(
        """
        INSERT INTO reflection_documents
            (compiler_run_id, name, from_utc, to_utc, model, status, error,
             content_markdown, content_hash, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            compiler_run_id,
            name,
            from_time.isoformat(),
            to_time.isoformat(),
            model,
            status,
            error,
            content_markdown,
            content_hash,
            input_tokens,
            output_tokens,
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid)


async def get_latest_reflection_document(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    name: str,
) -> dict[str, Any] | None:
    return await _fetch_one_dict(
        conn,
        """
        SELECT *
        FROM reflection_documents
        WHERE compiler_run_id = ?
          AND name = ?
          AND status = 'completed'
        ORDER BY completed_at DESC, id DESC
        LIMIT 1
        """,
        (run_id, name),
    )


async def delete_reflection_documents(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    name: str,
) -> int:
    cursor = await conn.execute(
        "DELETE FROM reflection_documents WHERE compiler_run_id = ? AND name = ?",
        (run_id, name),
    )
    await conn.commit()
    return int(cursor.rowcount)


async def get_rolling_state(conn: aiosqlite.Connection, run_name: str) -> dict[str, Any] | None:
    return await _fetch_one_dict(
        conn,
        "SELECT * FROM memory_rolling_state WHERE run_name = ?",
        (run_name,),
    )


async def acquire_rolling_lock(
    conn: aiosqlite.Connection,
    *,
    run_name: str,
    owner: str,
    now: datetime,
    lock_expires_at: datetime,
) -> bool:
    await conn.execute(
        "INSERT OR IGNORE INTO memory_rolling_state (run_name) VALUES (?)",
        (run_name,),
    )
    cursor = await conn.execute(
        """
        UPDATE memory_rolling_state
        SET lock_owner = ?, lock_expires_utc = ?, last_started_at = ?,
            last_error = NULL, updated_at = datetime('now')
        WHERE run_name = ?
          AND (
            lock_expires_utc IS NULL
            OR lock_expires_utc <= ?
            OR lock_owner = ?
          )
        """,
        (
            owner,
            lock_expires_at.isoformat(),
            now.isoformat(),
            run_name,
            now.isoformat(),
            owner,
        ),
    )
    await conn.commit()
    return int(cursor.rowcount or 0) > 0


async def complete_rolling_compile(
    conn: aiosqlite.Connection,
    *,
    run_name: str,
    completed_to: datetime,
    completed_at: datetime,
) -> None:
    await conn.execute(
        """
        INSERT INTO memory_rolling_state
            (run_name, last_successful_to_utc, last_completed_at, last_error,
             lock_owner, lock_expires_utc, updated_at)
        VALUES (?, ?, ?, NULL, NULL, NULL, datetime('now'))
        ON CONFLICT(run_name) DO UPDATE SET
            last_successful_to_utc = excluded.last_successful_to_utc,
            last_completed_at = excluded.last_completed_at,
            last_error = NULL,
            lock_owner = NULL,
            lock_expires_utc = NULL,
            updated_at = datetime('now')
        """,
        (run_name, completed_to.isoformat(), completed_at.isoformat()),
    )
    await conn.commit()


async def fail_rolling_compile(
    conn: aiosqlite.Connection,
    *,
    run_name: str,
    error: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO memory_rolling_state
            (run_name, last_error, lock_owner, lock_expires_utc, updated_at)
        VALUES (?, ?, NULL, NULL, datetime('now'))
        ON CONFLICT(run_name) DO UPDATE SET
            last_error = excluded.last_error,
            lock_owner = NULL,
            lock_expires_utc = NULL,
            updated_at = datetime('now')
        """,
        (run_name, error),
    )
    await conn.commit()


async def release_rolling_lock(conn: aiosqlite.Connection, *, run_name: str) -> None:
    await conn.execute(
        """
        UPDATE memory_rolling_state
        SET lock_owner = NULL, lock_expires_utc = NULL, updated_at = datetime('now')
        WHERE run_name = ?
        """,
        (run_name,),
    )
    await conn.commit()


async def get_daily_ambient_by_day(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    day_start_utc: str,
    day_end_utc: str,
) -> dict[str, Any] | None:
    return await _fetch_one_dict(
        conn,
        """
        SELECT * FROM daily_ambient_memory
        WHERE compiler_run_id = ? AND channel_id = ?
          AND day_start_utc = ? AND day_end_utc = ?
        """,
        (run_id, channel_id, day_start_utc, day_end_utc),
    )


async def upsert_daily_ambient_memory(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    day_start_utc: str,
    day_end_utc: str,
    title: str,
    summary: str,
    key_items: list[str],
    tags: list[str],
    importance: str,
    status: str,
    error: str | None,
    source_fingerprint: str,
    source_segments: list[int],
) -> int:
    existing = await get_daily_ambient_by_day(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        day_start_utc=day_start_utc,
        day_end_utc=day_end_utc,
    )
    if existing:
        ambient_id = int(existing["id"])
        await conn.execute(
            """
            UPDATE daily_ambient_memory
            SET title = ?, summary = ?, key_items_json = ?, importance = ?,
                status = ?, error = ?, source_fingerprint = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (title, summary, json.dumps(key_items, ensure_ascii=False), importance, status, error, source_fingerprint, ambient_id),
        )
        await conn.execute("DELETE FROM daily_ambient_memory_fts WHERE rowid = ?", (ambient_id,))
        await conn.execute("DELETE FROM daily_ambient_sources WHERE ambient_id = ?", (ambient_id,))
        await conn.execute("DELETE FROM daily_ambient_tags WHERE ambient_id = ?", (ambient_id,))
    else:
        cursor = await conn.execute(
            """
            INSERT INTO daily_ambient_memory
                (compiler_run_id, channel_id, day_start_utc, day_end_utc,
                 title, summary, key_items_json, importance, status, error, source_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                channel_id,
                day_start_utc,
                day_end_utc,
                title,
                summary,
                json.dumps(key_items, ensure_ascii=False),
                importance,
                status,
                error,
                source_fingerprint,
            ),
        )
        ambient_id = int(cursor.lastrowid)
    await conn.execute(
        """
        INSERT INTO daily_ambient_memory_fts(rowid, title, summary, key_items_json)
        VALUES (?, ?, ?, ?)
        """,
        (ambient_id, title, summary, json.dumps(key_items, ensure_ascii=False)),
    )
    for segment_id in source_segments:
        await conn.execute(
            """
            INSERT OR IGNORE INTO daily_ambient_sources (ambient_id, segment_id)
            VALUES (?, ?)
            """,
            (ambient_id, segment_id),
        )
    for tag in tags:
        await conn.execute(
            "INSERT OR IGNORE INTO daily_ambient_tags (ambient_id, tag) VALUES (?, ?)",
            (ambient_id, tag),
        )
    await conn.commit()
    return ambient_id


async def completed_rollups_for_months(
    conn: aiosqlite.Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    return await _fetch_all_dicts(
        conn,
        """
        SELECT * FROM memory_rollups
        WHERE compiler_run_id = ? AND period_type = 'week' AND status = 'completed'
        ORDER BY channel_id, period_start_utc
        """,
        (run_id,),
    )


async def get_rollup_by_period(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    period_type: str,
    period_start_utc: str,
    period_end_utc: str,
) -> dict[str, Any] | None:
    return await _fetch_one_dict(
        conn,
        """
        SELECT * FROM memory_rollups
        WHERE compiler_run_id = ? AND channel_id = ? AND period_type = ?
          AND period_start_utc = ? AND period_end_utc = ?
        """,
        (run_id, channel_id, period_type, period_start_utc, period_end_utc),
    )


async def upsert_rollup(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    period_type: str,
    period_start_utc: str,
    period_end_utc: str,
    title: str,
    summary: str,
    key_items: list[str],
    tags: list[str],
    importance: str,
    status: str,
    error: str | None,
    source_fingerprint: str,
    source_segments: list[int] | None = None,
    source_memory_items: list[int] | None = None,
    source_rollups: list[int] | None = None,
) -> int:
    existing = await get_rollup_by_period(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        period_type=period_type,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
    )
    if existing:
        rollup_id = int(existing["id"])
        await conn.execute(
            """
            UPDATE memory_rollups
            SET title = ?, summary = ?, key_items_json = ?, importance = ?,
                status = ?, error = ?, source_fingerprint = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (title, summary, json.dumps(key_items, ensure_ascii=False), importance, status, error, source_fingerprint, rollup_id),
        )
        await conn.execute("DELETE FROM memory_rollups_fts WHERE rowid = ?", (rollup_id,))
        await conn.execute("DELETE FROM memory_rollup_sources WHERE rollup_id = ?", (rollup_id,))
        await conn.execute("DELETE FROM memory_rollup_tags WHERE rollup_id = ?", (rollup_id,))
    else:
        cursor = await conn.execute(
            """
            INSERT INTO memory_rollups
                (compiler_run_id, channel_id, period_type, period_start_utc, period_end_utc,
                 title, summary, key_items_json, importance, status, error, source_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                channel_id,
                period_type,
                period_start_utc,
                period_end_utc,
                title,
                summary,
                json.dumps(key_items, ensure_ascii=False),
                importance,
                status,
                error,
                source_fingerprint,
            ),
        )
        rollup_id = int(cursor.lastrowid)
    await conn.execute(
        """
        INSERT INTO memory_rollups_fts(rowid, title, summary, key_items_json)
        VALUES (?, ?, ?, ?)
        """,
        (rollup_id, title, summary, json.dumps(key_items, ensure_ascii=False)),
    )
    for source_kind, ids in (
        ("segment", source_segments or []),
        ("memory_item", source_memory_items or []),
        ("rollup", source_rollups or []),
    ):
        for source_id in ids:
            await conn.execute(
                """
                INSERT OR IGNORE INTO memory_rollup_sources (rollup_id, source_kind, source_id)
                VALUES (?, ?, ?)
                """,
                (rollup_id, source_kind, source_id),
            )
    for tag in tags:
        await conn.execute(
            "INSERT OR IGNORE INTO memory_rollup_tags (rollup_id, tag) VALUES (?, ?)",
            (rollup_id, tag),
        )
    await conn.commit()
    return rollup_id


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
