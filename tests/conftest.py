"""Shared pytest fixtures."""
import pytest
import pytest_asyncio
import aiosqlite

from klatrebot_v2.db import connection, migrations


@pytest_asyncio.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await connection._load_vec_extension(conn)
    await migrations.run(conn)
    yield conn
    await conn.close()
