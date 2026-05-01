from datetime import datetime
import pytz


def test_next_klatretid_post_skips_past():
    """If today is Monday at 18:00 local, the next post is Thursday 17:00 local."""
    from klatrebot_v2.time_utils import next_klatretid_post

    tz = pytz.timezone("Europe/Copenhagen")
    monday_18 = tz.localize(datetime(2026, 5, 4, 18, 0, 0))
    nxt = next_klatretid_post(now=monday_18, days=[0, 3], hour=17, tz=tz)
    assert nxt.weekday() == 3
    assert nxt.hour == 17


def test_next_klatretid_post_today_if_before_hour():
    from klatrebot_v2.time_utils import next_klatretid_post

    tz = pytz.timezone("Europe/Copenhagen")
    monday_10 = tz.localize(datetime(2026, 5, 4, 10, 0, 0))
    nxt = next_klatretid_post(now=monday_10, days=[0, 3], hour=17, tz=tz)
    assert nxt.weekday() == 0
    assert nxt.hour == 17
    assert nxt.day == 4


def test_klatring_start_utc_for_post_date():
    """Klatring start = same date, 20:00 local → UTC."""
    from klatrebot_v2.time_utils import klatring_start_utc_for

    tz = pytz.timezone("Europe/Copenhagen")
    nxt_post = tz.localize(datetime(2026, 5, 4, 17, 0, 0))
    start = klatring_start_utc_for(post_time_local=nxt_post, start_hour=20)
    assert start.tzinfo is not None
    assert start.utcoffset().total_seconds() == 0
    assert start.hour in (18, 19)
