from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import messages as msg_db, users as users_db


async def test_insert_then_recent(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    await users_db.upsert(db, discord_user_id=2, display_name="B")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        await msg_db.insert(
            db,
            discord_message_id=100 + i,
            channel_id=999,
            user_id=1 if i % 2 == 0 else 2,
            content=f"msg-{i}",
            timestamp_utc=base + timedelta(minutes=i),
            is_bot=False,
        )
    rows = await msg_db.recent(db, channel_id=999, limit=2)
    assert [r.content for r in rows] == ["msg-1", "msg-2"]


async def test_recent_returns_oldest_first_within_limit(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        await msg_db.insert(
            db,
            discord_message_id=100 + i,
            channel_id=1,
            user_id=1,
            content=f"m{i}",
            timestamp_utc=base + timedelta(minutes=i),
        )
    rows = await msg_db.recent(db, channel_id=1, limit=3)
    assert [r.content for r in rows] == ["m2", "m3", "m4"]


async def test_recent_other_channel_excluded(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    await msg_db.insert(db, discord_message_id=1, channel_id=1, user_id=1, content="here", timestamp_utc=base)
    await msg_db.insert(db, discord_message_id=2, channel_id=2, user_id=1, content="not here", timestamp_utc=base)
    rows = await msg_db.recent(db, channel_id=1, limit=10)
    assert [r.content for r in rows] == ["here"]


async def test_recent_includes_display_name(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Magnus")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    await msg_db.insert(db, discord_message_id=1, channel_id=1, user_id=10, content="hej", timestamp_utc=base)
    rows = await msg_db.recent_with_authors(db, channel_id=1, limit=10)
    assert rows[0].user_display_name == "Magnus"
    assert rows[0].content == "hej"
