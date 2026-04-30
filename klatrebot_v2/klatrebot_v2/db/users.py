"""User upsert + lookup."""
import aiosqlite

from klatrebot_v2.db.models import User


async def upsert(conn: aiosqlite.Connection, *, discord_user_id: int, display_name: str, is_admin: bool = False) -> None:
    await conn.execute(
        """
        INSERT INTO users (discord_user_id, display_name, is_admin)
        VALUES (?, ?, ?)
        ON CONFLICT(discord_user_id) DO UPDATE SET
            display_name = excluded.display_name,
            updated_at   = datetime('now')
        """,
        (discord_user_id, display_name, 1 if is_admin else 0),
    )
    await conn.commit()


async def get(conn: aiosqlite.Connection, discord_user_id: int) -> User | None:
    cursor = await conn.execute(
        "SELECT discord_user_id, display_name, is_admin FROM users WHERE discord_user_id = ?",
        (discord_user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return User(discord_user_id=row[0], display_name=row[1], is_admin=bool(row[2]))
