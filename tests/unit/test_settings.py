import pytest


def test_settings_loads_from_env(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("test soul")
    monkeypatch.setenv("DISCORD_KEY", "fake_discord")
    monkeypatch.setenv("OPENAI_KEY", "fake_openai")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "111")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "222")
    monkeypatch.setenv("ADMIN_USER_ID", "333")
    monkeypatch.setenv("SOUL_PATH", str(soul))

    from klatrebot_v2.settings import Settings
    s = Settings(_env_file=None)

    assert s.discord_key == "fake_discord"
    assert s.openai_key == "fake_openai"
    assert s.discord_main_channel_id == 111
    assert s.model == "gpt-5.4"
    assert s.timezone == "Europe/Copenhagen"
    assert s.klatretid_days == [0, 3]


def test_settings_missing_required_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_KEY", raising=False)
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    from pydantic import ValidationError
    from klatrebot_v2.settings import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
