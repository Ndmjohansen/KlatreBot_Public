"""Persisted author pronouns, keyed by stable Discord identity."""
import aiosqlite


async def get_all(conn: aiosqlite.Connection) -> dict[int, str]:
    rows = await conn.execute_fetchall("SELECT discord_user_id, pronouns FROM user_pronouns")
    return {int(uid): pronouns for uid, pronouns in rows}
