"""Persisted author pronouns, keyed by stable Discord identity."""
import aiosqlite


PRONOUNS = ("han/ham", "hun/hende", "de/dem")


async def set_for_user(conn: aiosqlite.Connection, discord_user_id: int, pronouns: str) -> None:
    if discord_user_id <= 0 or pronouns not in PRONOUNS:
        raise ValueError("Invalid user or pronouns")
    await conn.execute(
        """INSERT INTO user_pronouns (discord_user_id, pronouns) VALUES (?, ?)
        ON CONFLICT(discord_user_id) DO UPDATE SET
            pronouns=excluded.pronouns, updated_at=datetime('now')""",
        (discord_user_id, pronouns),
    )
    await conn.commit()


async def get_all(conn: aiosqlite.Connection) -> dict[int, str]:
    rows = await conn.execute_fetchall("SELECT discord_user_id, pronouns FROM user_pronouns")
    return {int(uid): pronouns for uid, pronouns in rows}
