"""Periodic Hermes health probe with Discord admin pings on state transitions."""
import logging
import time

import discord
from discord.ext import commands, tasks

from klatrebot_v2.llm import hermes_client
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)

_PROBE_INTERVAL_SECONDS = 60
_DOWN_ALERT_COOLDOWN_SECONDS = 30 * 60


class HermesHealthCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._was_up: bool | None = None
        self._last_down_alert_at: float = 0.0

    async def cog_load(self) -> None:
        s = get_settings()
        if not s.hermes_enabled:
            logger.info("hermes_health: skipped (HERMES_ENABLED=false)")
            return
        self.probe.start()

    async def cog_unload(self) -> None:
        self.probe.cancel()

    @tasks.loop(seconds=_PROBE_INTERVAL_SECONDS)
    async def probe(self) -> None:
        try:
            up = await hermes_client.health()
        except Exception as e:
            logger.warning("hermes_health.probe error: %s", e)
            up = False

        if self._was_up is None:
            self._was_up = up
            return

        if up and not self._was_up:
            await self._alert(":white_check_mark: Hermes oppe igen.")
        elif (not up) and self._was_up:
            await self._alert(":warning: Hermes nede.", down=True)

        self._was_up = up

    async def _alert(self, body: str, *, down: bool = False) -> None:
        s = get_settings()
        if down:
            now = time.monotonic()
            if now - self._last_down_alert_at < _DOWN_ALERT_COOLDOWN_SECONDS:
                logger.info("hermes_health: down-alert suppressed (cooldown)")
                return
            self._last_down_alert_at = now

        channel = self.bot.get_channel(s.discord_sandbox_channel_id)
        if channel is None:
            logger.warning("hermes_health: sandbox channel %d not found", s.discord_sandbox_channel_id)
            return

        msg = f"<@{s.admin_user_id}> {body}"
        try:
            await channel.send(
                msg,
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
            )
        except discord.HTTPException as e:
            logger.warning("hermes_health: failed to post alert: %s", e)

    @probe.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HermesHealthCog(bot))
