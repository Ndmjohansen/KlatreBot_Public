"""Time/timezone helpers."""
from datetime import datetime, time, timedelta, timezone

import pytz


def next_klatretid_post(*, now: datetime, days: list[int], hour: int, tz: pytz.BaseTzInfo) -> datetime:
    """Return the next future post moment as a tz-aware datetime."""
    local_now = now.astimezone(tz)
    for offset in range(0, 8):
        candidate_date = (local_now + timedelta(days=offset)).date()
        if candidate_date.weekday() not in days:
            continue
        candidate = tz.localize(datetime.combine(candidate_date, time(hour=hour)))
        if candidate > local_now:
            return candidate
    raise RuntimeError("Unreachable: no klatretid in next 7 days")


def klatring_start_utc_for(*, post_time_local: datetime, start_hour: int) -> datetime:
    """Klatring starts at start_hour:00 local on the same date as the embed post."""
    local_dt = post_time_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return local_dt.astimezone(timezone.utc)


def since_5am_local(*, now: datetime, tz: pytz.BaseTzInfo) -> datetime:
    """Window start: today 05:00 local if now>=05:00 else yesterday 05:00 local."""
    local_now = now.astimezone(tz)
    today_5am = tz.localize(datetime.combine(local_now.date(), time(hour=5)))
    if local_now >= today_5am:
        return today_5am
    yesterday = local_now.date() - timedelta(days=1)
    return tz.localize(datetime.combine(yesterday, time(hour=5)))
