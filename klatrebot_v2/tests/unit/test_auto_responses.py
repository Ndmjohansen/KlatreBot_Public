def test_first_match_wins_and_patterns_compile():
    from klatrebot_v2.cogs.auto_responses import RESPONSES, first_match

    for ar in RESPONSES:
        assert ar.pattern.search("just any string here") is None or hasattr(ar.pattern, "search")

    m = first_match("Det her var bare en fail tbh")
    assert m is not None and m.name == "downus"

    m = first_match("https://www.ekstrabladet.dk/blah")
    assert m is not None and m.name == "ekstrabladet"

    m = first_match("klatrebot kommer Magnus i morgen?")
    assert m is not None and m.name == "klatrebot_question"

    assert first_match("helt almindelig sætning") is None


def test_no_ugenr_match_in_responses():
    """ugenr_match removed: silent no-op handler would block downstream matches."""
    from klatrebot_v2.cogs.auto_responses import RESPONSES
    assert all(ar.name != "ugenr_match" for ar in RESPONSES)
