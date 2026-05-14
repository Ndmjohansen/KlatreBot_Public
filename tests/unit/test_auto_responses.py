def test_first_match_wins_and_patterns_compile():
    from klatrebot_v2.cogs.auto_responses import RESPONSES, first_match, matching_responses

    for ar in RESPONSES:
        assert ar.pattern.search("just any string here") is None or hasattr(ar.pattern, "search")

    m = first_match("Det her var bare en fail tbh")
    assert m is not None and m.name == "downus"

    assert first_match("foo !downus") is None
    assert [m.name for m in matching_responses("klatrebot fail?")] == [
        "downus",
        "klatrebot_question",
    ]

    m = first_match("https://www.ekstrabladet.dk/blah")
    assert m is not None and m.name == "ekstrabladet"

    m = first_match("klatrebot kommer Magnus i morgen?")
    assert m is not None and m.name == "klatrebot_question"

    assert first_match("helt almindelig sætning") is None


def test_uge_pattern_requires_word_boundary():
    from klatrebot_v2.cogs.auto_responses import RESPONSES
    pat = next(ar.pattern for ar in RESPONSES if ar.name == "ugenr_match")
    assert pat.search("hvad sker der i uge 35?")
    assert pat.search("uge 35")
    assert pat.search("uge35")  # \s? makes space optional
    assert pat.search("luge 35") is None  # word boundary blocks "luge"


import pytest


def test_reaction_gifs_have_individual_two_minute_cooldowns():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    from klatrebot_v2.cogs.auto_responses import AutoResponsesCog, RESPONSES

    responses = {ar.name: ar for ar in RESPONSES}
    for name in ["downus", "det_kan_man_ik", "elmo", "glar_midsentence"]:
        assert responses[name].cooldown_seconds == 120

    cog = AutoResponsesCog(MagicMock())
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)

    cog._mark_cooldown(responses["elmo"], now)

    assert cog._is_on_cooldown(responses["elmo"], now + timedelta(seconds=119))
    assert not cog._is_on_cooldown(responses["downus"], now + timedelta(seconds=119))
    assert not cog._is_on_cooldown(responses["elmo"], now + timedelta(seconds=120))


@pytest.mark.asyncio
async def test_handle_uge_returns_date_range():
    from unittest.mock import MagicMock
    from klatrebot_v2.cogs.auto_responses import _handle_uge

    msg = MagicMock()
    msg.content = "uge 35"
    out = await _handle_uge(msg)
    assert out is not None
    assert "Uge 35" in out and " til " in out


@pytest.mark.asyncio
async def test_handle_uge_skips_invalid_week():
    from unittest.mock import MagicMock
    from klatrebot_v2.cogs.auto_responses import _handle_uge

    msg = MagicMock()
    msg.content = "uge 99"
    out = await _handle_uge(msg)
    assert out is None
