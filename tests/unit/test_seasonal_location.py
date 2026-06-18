def _enable_seasonal(monkeypatch, *, enabled):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    if enabled:
        monkeypatch.setenv("SEASONAL_ENABLED", "true")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()


def test_seasonal_off_by_default(monkeypatch):
    _enable_seasonal(monkeypatch, enabled=False)
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.tasks import seasonal_location_for
    assert get_settings().seasonal_enabled is False
    assert seasonal_location_for(0) is None


def test_seasonal_location_when_enabled(monkeypatch):
    _enable_seasonal(monkeypatch, enabled=True)
    from klatrebot_v2.tasks import seasonal_location_for
    assert seasonal_location_for(0) == "Sydhavn"   # Monday
    assert seasonal_location_for(3) == "Vanløse"   # Thursday
    assert seasonal_location_for(1) is None         # Tuesday (unmapped)


def test_embed_appends_lokation_line():
    from klatrebot_v2.tasks import build_klatretid_embed
    embed = build_klatretid_embed(location="Sydhavn")
    assert "Lokation: Sydhavn" in embed.description
    assert not embed.fields


def test_embed_no_lokation_line_when_location_none():
    from klatrebot_v2.tasks import build_klatretid_embed
    embed = build_klatretid_embed()
    assert "Lokation" not in (embed.description or "")


def test_location_for_session_date_parses_weekday(monkeypatch):
    _enable_seasonal(monkeypatch, enabled=True)
    from klatrebot_v2.cogs.attendance import _location_for_session_date
    assert _location_for_session_date("2026-06-15") == "Sydhavn"  # Monday
    assert _location_for_session_date("2026-06-16") is None        # Tuesday
