import datetime as dt


def test_seconds_string_zero():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert seconds_as_dt_string(0) == ""


def test_seconds_string_minutes_only():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert seconds_as_dt_string(120).strip() == "2 minutter".strip()


def test_seconds_string_singular_plural():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert "1 minut" in seconds_as_dt_string(60)
    assert "2 minutter" in seconds_as_dt_string(120)
    assert "1 time" in seconds_as_dt_string(3600)
    assert "2 timer" in seconds_as_dt_string(7200)
    assert "1 dag" in seconds_as_dt_string(86400)
    assert "2 dage" in seconds_as_dt_string(2 * 86400)
