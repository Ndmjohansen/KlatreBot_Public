from datetime import datetime
import pytz


def test_since_5am_local_after_5am():
    from klatrebot_v2.time_utils import since_5am_local

    tz = pytz.timezone("Europe/Copenhagen")
    now = tz.localize(datetime(2026, 4, 30, 12, 0, 0))
    start = since_5am_local(now=now, tz=tz)
    assert start.hour == 5
    assert start.day == 30
    assert start.month == 4


def test_since_5am_local_before_5am_returns_yesterday():
    from klatrebot_v2.time_utils import since_5am_local

    tz = pytz.timezone("Europe/Copenhagen")
    now = tz.localize(datetime(2026, 4, 30, 3, 0, 0))
    start = since_5am_local(now=now, tz=tz)
    assert start.hour == 5
    assert start.day == 29
