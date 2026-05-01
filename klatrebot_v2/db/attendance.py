"""Attendance session + event log + bailer detection."""
from datetime import datetime, timedelta
import aiosqlite

from klatrebot_v2.db.models import AttendanceSession, User


async def create_session(
    conn: aiosqlite.Connection,
    *,
    date_local: str,
    channel_id: int,
    message_id: int,
    klatring_start_utc: datetime,
) -> int:
    cursor = await conn.execute(
        """
        INSERT INTO attendance_session (date_local, channel_id, message_id, klatring_start_utc)
        VALUES (?, ?, ?, ?)
        """,
        (date_local, channel_id, message_id, klatring_start_utc.isoformat()),
    )
    await conn.commit()
    return cursor.lastrowid


async def active_session(
    conn: aiosqlite.Connection, *, channel_id: int, today_local: str
) -> AttendanceSession | None:
    cursor = await conn.execute(
        """
        SELECT id, date_local, channel_id, message_id, klatring_start_utc
        FROM attendance_session
        WHERE channel_id = ? AND date_local = ?
        """,
        (channel_id, today_local),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return AttendanceSession(
        id=row[0],
        date_local=row[1],
        channel_id=row[2],
        message_id=row[3],
        klatring_start_utc=datetime.fromisoformat(row[4]),
    )


async def record_event(
    conn: aiosqlite.Connection,
    *,
    session_id: int,
    user_id: int,
    status: str,
    timestamp_utc: datetime,
) -> None:
    if status not in ("yes", "no"):
        raise ValueError(f"invalid status: {status!r}")
    await conn.execute(
        """
        INSERT INTO attendance_reaction_event (session_id, user_id, status, timestamp_utc)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, user_id, status, timestamp_utc.isoformat()),
    )
    await conn.commit()


async def tally(conn: aiosqlite.Connection, *, session_id: int) -> tuple[list[User], list[User]]:
    """Return (yes_users, no_users) based on each user's LATEST event."""
    cursor = await conn.execute(
        """
        WITH latest AS (
            SELECT user_id, status,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp_utc DESC) AS rn
            FROM attendance_reaction_event
            WHERE session_id = ?
        )
        SELECT u.discord_user_id, u.display_name, u.is_admin, latest.status
        FROM latest
        JOIN users u ON u.discord_user_id = latest.user_id
        WHERE latest.rn = 1
        """,
        (session_id,),
    )
    rows = await cursor.fetchall()
    yes_users, no_users = [], []
    for r in rows:
        u = User(discord_user_id=r[0], display_name=r[1], is_admin=bool(r[2]))
        (yes_users if r[3] == "yes" else no_users).append(u)
    return yes_users, no_users


async def bailers(conn: aiosqlite.Connection, *, session_id: int) -> list[User]:
    """A user bailed iff they had a 'yes' before they said 'no' within the last hour before klatring start."""
    cursor = await conn.execute(
        """
        SELECT klatring_start_utc FROM attendance_session WHERE id = ?
        """,
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return []
    start = datetime.fromisoformat(row[0])
    bail_window_open = (start - timedelta(hours=1)).isoformat()
    bail_window_close = start.isoformat()

    cursor = await conn.execute(
        """
        SELECT DISTINCT e1.user_id, u.display_name, u.is_admin
        FROM attendance_reaction_event e1
        JOIN users u ON u.discord_user_id = e1.user_id
        WHERE e1.session_id = ?
          AND e1.status = 'no'
          AND e1.timestamp_utc >= ?
          AND e1.timestamp_utc < ?
          AND EXISTS (
              SELECT 1 FROM attendance_reaction_event e2
              WHERE e2.session_id = e1.session_id
                AND e2.user_id    = e1.user_id
                AND e2.status     = 'yes'
                AND e2.timestamp_utc < e1.timestamp_utc
          )
        """,
        (session_id, bail_window_open, bail_window_close),
    )
    rows = await cursor.fetchall()
    return [User(discord_user_id=r[0], display_name=r[1], is_admin=bool(r[2])) for r in rows]
