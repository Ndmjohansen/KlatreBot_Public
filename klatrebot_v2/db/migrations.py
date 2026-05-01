"""Schema bootstrap. Idempotent — safe to run on every startup."""
import aiosqlite


DDL = [
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
]


VEC_DDL =(
    "CREATE VIRTUAL TABLE IF NOT EXISTS message_embeddings "
    "USING vec0(message_id INTEGER PRIMARY KEY, embedding FLOAT[1536])"
)


async def run(conn: aiosqlite.Connection) -> None:
    for stmt in DDL:
        await conn.execute(stmt)
    try:
        await conn.execute(VEC_DDL)
    except aiosqlite.OperationalError:
        # vec0 extension not loaded; semantic search unavailable but other tables still usable
        pass
    await conn.commit()


def run_sync(conn) -> None:
    """Apply schema to a stdlib sqlite3.Connection. Skips vec0 if extension unavailable."""
    for stmt in DDL:
        conn.execute(stmt)
    try:
        conn.execute(VEC_DDL)
    except Exception:
        pass
    conn.commit()
