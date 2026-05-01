"""Shared aiosqlite connection. Opened once in bot.setup_hook, closed on shutdown."""
import aiosqlite


async def open(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.commit()
    return conn


async def close(conn: aiosqlite.Connection) -> None:
    await conn.close()
