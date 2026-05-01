import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    from klatrebot_v2.settings import get_settings
    get_settings.cache_clear()
    from klatrebot_v2.llm import hermes_client
    hermes_client.set_available(False)
    hermes_client.reset_client()


async def test_ask_disabled_raises(monkeypatch):
    monkeypatch.setenv("HERMES_ENABLED", "false")
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client
    get_settings.cache_clear()
    with pytest.raises(hermes_client.HermesUnavailable):
        await hermes_client.ask(
            question="x", asking_user_id=1, channel_id=1, username="u"
        )


async def test_ask_cached_unavailable_raises(monkeypatch):
    monkeypatch.setenv("HERMES_ENABLED", "true")
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client
    get_settings.cache_clear()
    hermes_client.set_available(False)
    with pytest.raises(hermes_client.HermesUnavailable):
        await hermes_client.ask(
            question="x", asking_user_id=1, channel_id=1, username="u"
        )


async def test_ask_success(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Du er klatrebot.")
    monkeypatch.setenv("HERMES_ENABLED", "true")
    monkeypatch.setenv("SOUL_PATH", str(soul))
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client, prompt
    get_settings.cache_clear()
    prompt.load_soul.cache_clear()
    hermes_client.set_available(True)

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="svar fra hermes"))]
    fake_client = MagicMock()
    fake_client.chat = MagicMock()
    fake_client.chat.completions = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with patch.object(hermes_client, "_get_hermes_client", return_value=fake_client):
        result = await hermes_client.ask(
            question="hvor mange msgs", asking_user_id=42, channel_id=99, username="nick"
        )

    assert result.text == "svar fra hermes"
    kwargs = fake_client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == "hermes-agent"
    assert kwargs["messages"][0]["role"] == "system"
    assert "Du er klatrebot." in kwargs["messages"][0]["content"]
    assert "QUESTION: hvor mange msgs" in kwargs["messages"][1]["content"]


async def test_ask_api_error_marks_unavailable(monkeypatch, tmp_path):
    from openai import APIError
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("HERMES_ENABLED", "true")
    monkeypatch.setenv("SOUL_PATH", str(soul))
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client, prompt
    get_settings.cache_clear()
    prompt.load_soul.cache_clear()
    hermes_client.set_available(True)

    fake_client = MagicMock()
    fake_client.chat = MagicMock()
    fake_client.chat.completions = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=APIError("boom", request=MagicMock(), body=None)
    )

    with patch.object(hermes_client, "_get_hermes_client", return_value=fake_client):
        with pytest.raises(hermes_client.HermesUnavailable):
            await hermes_client.ask(
                question="x", asking_user_id=1, channel_id=1, username="u"
            )
    assert hermes_client.is_available() is False


async def test_health_probe_ok(monkeypatch):
    monkeypatch.setenv("HERMES_ENABLED", "true")
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client
    get_settings.cache_clear()

    fake_resp = MagicMock(status_code=200)
    fake_http = MagicMock()
    fake_http.get = AsyncMock(return_value=fake_resp)
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)

    with patch("klatrebot_v2.llm.hermes_client.httpx.AsyncClient", return_value=fake_http):
        ok = await hermes_client.health()
    assert ok is True
    assert hermes_client.is_available() is True


async def test_health_probe_fails_marks_unavailable(monkeypatch):
    import httpx
    monkeypatch.setenv("HERMES_ENABLED", "true")
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client
    get_settings.cache_clear()

    fake_http = MagicMock()
    fake_http.get = AsyncMock(side_effect=httpx.ConnectError("nope"))
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)

    with patch("klatrebot_v2.llm.hermes_client.httpx.AsyncClient", return_value=fake_http):
        ok = await hermes_client.health()
    assert ok is False
    assert hermes_client.is_available() is False


async def test_health_disabled_short_circuits(monkeypatch):
    monkeypatch.setenv("HERMES_ENABLED", "false")
    from klatrebot_v2.settings import get_settings
    from klatrebot_v2.llm import hermes_client
    get_settings.cache_clear()
    ok = await hermes_client.health()
    assert ok is False


def test_strip_fast_flag_present():
    from klatrebot_v2.cogs.chat import _strip_fast_flag
    cleaned, force = _strip_fast_flag("--fast hvad så")
    assert cleaned == "hvad så"
    assert force is True


def test_strip_fast_flag_agent_token_left_intact():
    """--agent is no longer a flag; !agent is its own command. Treated as plain text."""
    from klatrebot_v2.cogs.chat import _strip_fast_flag
    cleaned, force = _strip_fast_flag("hvem klatrede sidst --agent")
    assert cleaned == "hvem klatrede sidst --agent"
    assert force is False


def test_strip_fast_flag_absent():
    from klatrebot_v2.cogs.chat import _strip_fast_flag
    cleaned, force = _strip_fast_flag("hvad så brormand")
    assert cleaned == "hvad så brormand"
    assert force is False
