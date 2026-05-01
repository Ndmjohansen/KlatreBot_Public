from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import attendance as att_db, users as users_db


async def _seed_users(db, ids):
    for i in ids:
        await users_db.upsert(db, discord_user_id=i, display_name=f"u{i}")


async def test_create_and_get_active_session(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(
        db,
        date_local="2026-05-04",
        channel_id=999,
        message_id=42,
        klatring_start_utc=start,
    )
    sess = await att_db.active_session(db, channel_id=999, today_local="2026-05-04")
    assert sess is not None
    assert sess.id == sess_id
    assert sess.message_id == 42


async def test_record_event_and_count(db):
    await _seed_users(db, [1, 2])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    t = datetime(2026, 5, 4, 17, 30, tzinfo=timezone.utc)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=t)
    await att_db.record_event(db, session_id=sess_id, user_id=2, status="no", timestamp_utc=t)
    yes, no = await att_db.tally(db, session_id=sess_id)
    assert {u.discord_user_id for u in yes} == {1}
    assert {u.discord_user_id for u in no} == {2}


async def test_bailers_query(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    yes_t = start - timedelta(hours=3)
    bail_t = start - timedelta(minutes=30)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=yes_t)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=bail_t)
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert {u.discord_user_id for u in bailers} == {1}


async def test_user_who_was_no_then_yes_then_no_within_hour_is_bailer(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(hours=4))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=start - timedelta(hours=2))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(minutes=30))
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert {u.discord_user_id for u in bailers} == {1}


async def test_user_who_says_no_outside_window_is_not_bailer(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=start - timedelta(hours=4))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(hours=2))
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert bailers == []
