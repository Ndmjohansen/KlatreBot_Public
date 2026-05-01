"""Shared aiosqlite connection. Opened once in bot.setup_hook, closed on shutdown."""
import logging

import aiosqlite
import sqlite_vec


logger = logging.getLogger(__name__)


async def open(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await _load_vec_extension(conn)
    await conn.commit()
    return conn


async def _load_vec_extension(conn: aiosqlite.Connection) -> None:
    """Load sqlite-vec for vector ops. Logs + skips if Python sqlite3 lacks ext support."""
    try:
        await conn.enable_load_extension(True)
        await conn.load_extension(sqlite_vec.loadable_path())
        await conn.enable_load_extension(False)
        logger.info("sqlite-vec extension loaded")
    except (AttributeError, aiosqlite.OperationalError, Exception) as e:
        logger.warning("sqlite-vec load failed (%s); semantic search will be disabled", e)


async def close(conn: aiosqlite.Connection) -> None:
    await conn.close()
