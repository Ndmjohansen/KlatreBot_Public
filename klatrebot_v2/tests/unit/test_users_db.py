async def test_migrations_create_tables(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    rows = await cursor.fetchall()
    names = [r[0] for r in rows]
    assert "users" in names
    assert "messages" in names
    assert "attendance_session" in names
    assert "attendance_reaction_event" in names


from klatrebot_v2.db import users as users_db
from klatrebot_v2.db.models import User


async def test_upsert_inserts_new_user(db):
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle")
    found = await users_db.get(db, 42)
    assert found == User(discord_user_id=42, display_name="Pelle", is_admin=False)


async def test_upsert_updates_display_name(db):
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle")
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle Lauritsen")
    found = await users_db.get(db, 42)
    assert found.display_name == "Pelle Lauritsen"


async def test_get_returns_none_for_missing(db):
    assert await users_db.get(db, 999) is None
