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
