"""Schema bootstrap. Idempotent — safe to run on every startup."""
import aiosqlite


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        discord_user_id  INTEGER PRIMARY KEY,
        display_name     TEXT NOT NULL,
        is_admin         INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        discord_message_id  INTEGER PRIMARY KEY,
        channel_id          INTEGER NOT NULL,
        user_id             INTEGER NOT NULL,
        content             TEXT NOT NULL,
        timestamp_utc       TEXT NOT NULL,
        is_bot              INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, timestamp_utc)",
    """
    CREATE TABLE IF NOT EXISTS attendance_session (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        date_local          TEXT NOT NULL,
        channel_id          INTEGER NOT NULL,
        message_id          INTEGER NOT NULL,
        klatring_start_utc  TEXT NOT NULL,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(date_local, channel_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_reaction_event (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id      INTEGER NOT NULL,
        user_id         INTEGER NOT NULL,
        status          TEXT NOT NULL CHECK(status IN ('yes','no')),
        timestamp_utc   TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES attendance_session(id),
        FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reaction_session_user_ts ON attendance_reaction_event(session_id, user_id, timestamp_utc)",
    """
    CREATE TABLE IF NOT EXISTS memory_compiler_runs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        name                TEXT NOT NULL UNIQUE,
        status              TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
        source_db_label     TEXT,
        from_time_utc       TEXT,
        to_time_utc         TEXT,
        channel_ids_json    TEXT NOT NULL DEFAULT '[]',
        config_json         TEXT NOT NULL DEFAULT '{}',
        prompt_version      TEXT NOT NULL,
        compiler_model      TEXT NOT NULL,
        error               TEXT,
        started_at          TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_segments (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        compiler_run_id     INTEGER NOT NULL,
        channel_id          INTEGER NOT NULL,
        start_time_utc      TEXT NOT NULL,
        end_time_utc        TEXT NOT NULL,
        message_count       INTEGER NOT NULL,
        human_message_count INTEGER NOT NULL,
        total_chars         INTEGER NOT NULL,
        participant_ids_json TEXT NOT NULL DEFAULT '[]',
        topic_title         TEXT NOT NULL DEFAULT '',
        summary             TEXT NOT NULL DEFAULT '',
        importance          TEXT NOT NULL DEFAULT 'normal',
        status              TEXT NOT NULL CHECK(status IN ('candidate','summarized','skipped','failed')),
        skip_reason         TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(compiler_run_id) REFERENCES memory_compiler_runs(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_segments_run_time ON conversation_segments(compiler_run_id, start_time_utc, end_time_utc)",
    """
    CREATE TABLE IF NOT EXISTS segment_messages (
        segment_id          INTEGER NOT NULL,
        discord_message_id  INTEGER NOT NULL,
        position            INTEGER NOT NULL,
        PRIMARY KEY(segment_id, discord_message_id),
        FOREIGN KEY(segment_id) REFERENCES conversation_segments(id),
        FOREIGN KEY(discord_message_id) REFERENCES messages(discord_message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_items (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        compiler_run_id     INTEGER NOT NULL,
        segment_id          INTEGER NOT NULL,
        type                TEXT NOT NULL CHECK(type IN ('decision','plan','preference','fact','opinion','open_question','lore')),
        subject             TEXT NOT NULL,
        text                TEXT NOT NULL,
        confidence          TEXT NOT NULL CHECK(confidence IN ('low','medium','high')),
        importance          TEXT NOT NULL CHECK(importance IN ('low','normal','high')),
        speaker_ids_json    TEXT NOT NULL DEFAULT '[]',
        created_at_source   TEXT,
        last_seen_at_source TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(compiler_run_id) REFERENCES memory_compiler_runs(id),
        FOREIGN KEY(segment_id) REFERENCES conversation_segments(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_items_run_type ON memory_items(compiler_run_id, type)",
    """
    CREATE TABLE IF NOT EXISTS memory_item_sources (
        memory_item_id      INTEGER NOT NULL,
        discord_message_id  INTEGER NOT NULL,
        PRIMARY KEY(memory_item_id, discord_message_id),
        FOREIGN KEY(memory_item_id) REFERENCES memory_items(id),
        FOREIGN KEY(discord_message_id) REFERENCES messages(discord_message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_segment_tags (
        segment_id          INTEGER NOT NULL,
        tag                 TEXT NOT NULL,
        PRIMARY KEY(segment_id, tag),
        FOREIGN KEY(segment_id) REFERENCES conversation_segments(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_segment_tags_tag ON conversation_segment_tags(tag)",
    """
    CREATE TABLE IF NOT EXISTS memory_item_tags (
        memory_item_id      INTEGER NOT NULL,
        tag                 TEXT NOT NULL,
        PRIMARY KEY(memory_item_id, tag),
        FOREIGN KEY(memory_item_id) REFERENCES memory_items(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_item_tags_tag ON memory_item_tags(tag)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS conversation_segments_fts
    USING fts5(topic_title, summary, content='conversation_segments', content_rowid='id')
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
    USING fts5(type, subject, text, content='memory_items', content_rowid='id')
    """,
]


async def run(conn: aiosqlite.Connection) -> None:
    for stmt in _DDL:
        await conn.execute(stmt)
    await conn.commit()
