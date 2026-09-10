import aiosqlite
import pytest

from klatrebot_v2.db import migrations, user_pronouns, users
from klatrebot_v2.memory import pronouns


@pytest.mark.parametrize("existing", [False, True])
async def test_migration_seeds_fresh_and_existing_identity_databases(existing):
    async with aiosqlite.connect(":memory:") as conn:
        if existing:
            await conn.execute("""CREATE TABLE users (
                discord_user_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')))""")
            for uid in (101, 102, 123):
                await conn.execute("INSERT INTO users(discord_user_id, display_name) VALUES(?, 'Old name')", (uid,))
        await migrations.run(conn, pronoun_seeds={101: "hun/hende", 102: "hun/hende"})
        stored = await user_pronouns.get_all(conn)
        assert stored[101] == "hun/hende"
        assert stored[102] == "hun/hende"
        if existing:
            assert stored[123] == "han/ham"
        await users.upsert(conn, discord_user_id=456, display_name="New member")
        assert (await user_pronouns.get_all(conn))[456] == "han/ham"
        await users.upsert(conn, discord_user_id=101, display_name="Renamed")
        assert (await user_pronouns.get_all(conn))[101] == "hun/hende"


async def test_migration_and_user_updates_preserve_edited_pronouns(db):
    await migrations.run(db, pronoun_seeds={101: "hun/hende"})
    await users.upsert(db, discord_user_id=123, display_name="Member")
    for uid in (123, 101):
        await db.execute("UPDATE user_pronouns SET pronouns='de/dem' WHERE discord_user_id=?", (uid,))
    await migrations.run(db, pronoun_seeds={101: "hun/hende"})
    for uid in (123, 101):
        await users.upsert(db, discord_user_id=uid, display_name="Renamed")
        assert (await pronouns.author_pronouns(db))[uid] == "de/dem"


def test_missing_identity_has_no_application_gender_default():
    row = dict(user_id=123, user_display_name="member_one", content="Original")
    enriched = pronouns.enrich([row], {})[0]
    assert enriched["author_pronouns"] == "brug navnet"
    assert enriched["content"] == row["content"]


@pytest.mark.parametrize("seeds", [{0: "hun/hende"}, {1: ""}, {1: "x" * 81}])
async def test_invalid_private_seeds_do_not_change_schema(seeds):
    async with aiosqlite.connect(":memory:") as conn:
        with pytest.raises(ValueError, match="Invalid pronoun seed"):
            await migrations.run(conn, pronoun_seeds=seeds)
        assert await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'") == []
