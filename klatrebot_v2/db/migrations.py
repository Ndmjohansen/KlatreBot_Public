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
    CREATE TABLE IF NOT EXISTS user_aliases (
        discord_user_id     INTEGER NOT NULL,
        alias               TEXT NOT NULL,
        alias_normalized    TEXT NOT NULL,
        source              TEXT NOT NULL CHECK(source IN ('config','discord_display')),
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY(discord_user_id, alias_normalized)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_aliases_normalized ON user_aliases(alias_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_user_aliases_user ON user_aliases(discord_user_id)",
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
        config_hash         TEXT,
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
        segment_key         TEXT,
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
        error               TEXT,
        retry_count         INTEGER NOT NULL DEFAULT 0,
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
    CREATE TABLE IF NOT EXISTS memory_rollups (
        id                          INTEGER PRIMARY KEY AUTOINCREMENT,
        compiler_run_id             INTEGER NOT NULL,
        channel_id                  INTEGER NOT NULL,
        period_type                 TEXT NOT NULL CHECK(period_type IN ('week','month')),
        period_start_utc            TEXT NOT NULL,
        period_end_utc              TEXT NOT NULL,
        title                       TEXT NOT NULL DEFAULT '',
        summary                     TEXT NOT NULL DEFAULT '',
        key_items_json              TEXT NOT NULL DEFAULT '[]',
        importance                  TEXT NOT NULL CHECK(importance IN ('low','normal','high')) DEFAULT 'normal',
        status                      TEXT NOT NULL CHECK(status IN ('pending','completed','failed','stale')) DEFAULT 'pending',
        error                       TEXT,
        source_fingerprint          TEXT NOT NULL DEFAULT '',
        created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(compiler_run_id) REFERENCES memory_compiler_runs(id),
        UNIQUE(compiler_run_id, channel_id, period_type, period_start_utc, period_end_utc)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rollups_run_period ON memory_rollups(compiler_run_id, period_type, period_start_utc, period_end_utc)",
    """
    CREATE TABLE IF NOT EXISTS memory_rollup_sources (
        rollup_id           INTEGER NOT NULL,
        source_kind         TEXT NOT NULL CHECK(source_kind IN ('segment','memory_item','rollup')),
        source_id           INTEGER NOT NULL,
        PRIMARY KEY(rollup_id, source_kind, source_id),
        FOREIGN KEY(rollup_id) REFERENCES memory_rollups(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_rollup_tags (
        rollup_id           INTEGER NOT NULL,
        tag                 TEXT NOT NULL,
        PRIMARY KEY(rollup_id, tag),
        FOREIGN KEY(rollup_id) REFERENCES memory_rollups(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rollup_tags_tag ON memory_rollup_tags(tag)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS conversation_segments_fts
    USING fts5(topic_title, summary, content='conversation_segments', content_rowid='id')
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
    USING fts5(type, subject, text, content='memory_items', content_rowid='id')
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_rollups_fts
    USING fts5(title, summary, key_items_json, content='memory_rollups', content_rowid='id')
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_ambient_memory (
        id                          INTEGER PRIMARY KEY AUTOINCREMENT,
        compiler_run_id             INTEGER NOT NULL,
        channel_id                  INTEGER NOT NULL,
        day_start_utc               TEXT NOT NULL,
        day_end_utc                 TEXT NOT NULL,
        title                       TEXT NOT NULL DEFAULT '',
        summary                     TEXT NOT NULL DEFAULT '',
        key_items_json              TEXT NOT NULL DEFAULT '[]',
        importance                  TEXT NOT NULL CHECK(importance IN ('low','normal','high')) DEFAULT 'low',
        status                      TEXT NOT NULL CHECK(status IN ('pending','completed','failed','stale')) DEFAULT 'pending',
        error                       TEXT,
        source_fingerprint          TEXT NOT NULL DEFAULT '',
        created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(compiler_run_id) REFERENCES memory_compiler_runs(id),
        UNIQUE(compiler_run_id, channel_id, day_start_utc, day_end_utc)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_ambient_run_day ON daily_ambient_memory(compiler_run_id, day_start_utc, day_end_utc)",
    """
    CREATE TABLE IF NOT EXISTS daily_ambient_sources (
        ambient_id          INTEGER NOT NULL,
        segment_id          INTEGER NOT NULL,
        PRIMARY KEY(ambient_id, segment_id),
        FOREIGN KEY(ambient_id) REFERENCES daily_ambient_memory(id),
        FOREIGN KEY(segment_id) REFERENCES conversation_segments(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_ambient_tags (
        ambient_id          INTEGER NOT NULL,
        tag                 TEXT NOT NULL,
        PRIMARY KEY(ambient_id, tag),
        FOREIGN KEY(ambient_id) REFERENCES daily_ambient_memory(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_ambient_tags_tag ON daily_ambient_tags(tag)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS daily_ambient_memory_fts
    USING fts5(title, summary, key_items_json, content='daily_ambient_memory', content_rowid='id')
    """,
]

_ALTER = [
    "ALTER TABLE memory_compiler_runs ADD COLUMN config_hash TEXT",
    "ALTER TABLE conversation_segments ADD COLUMN segment_key TEXT",
    "ALTER TABLE conversation_segments ADD COLUMN error TEXT",
    "ALTER TABLE conversation_segments ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
]

_POST_DDL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_run_key ON conversation_segments(compiler_run_id, segment_key)",
]


async def run(conn: aiosqlite.Connection) -> None:
    for stmt in _DDL:
        await conn.execute(stmt)
    for stmt in _ALTER:
        try:
            await conn.execute(stmt)
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    for stmt in _POST_DDL:
        await conn.execute(stmt)
    await conn.commit()
