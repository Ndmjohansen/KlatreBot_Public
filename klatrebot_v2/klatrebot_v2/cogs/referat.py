"""!referat — summarizes today's chat (05:00 local → now)."""
import logging
from datetime import datetime, timezone

import pytz
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db
from klatrebot_v2.llm import chat
from klatrebot_v2.settings import get_settings
from klatrebot_v2.time_utils import since_5am_local


logger = logging.getLogger(__name__)


class RefereatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="referat")
    async def referat(self, ctx: commands.Context) -> None:
        s = get_settings()
        tz = pytz.timezone(s.timezone)
        now_utc = datetime.now(timezone.utc)
        window_start = since_5am_local(now=now_utc, tz=tz).astimezone(timezone.utc)

        async with ctx.typing():
            msgs = await msg_db.in_window(
                self.bot.db_conn,
                channel_id=ctx.channel.id,
                start=window_start,
                end=now_utc,
            )
            if not msgs:
                await ctx.reply("Ingen beskeder siden 05:00.")
                return
            summary = await chat.summarize(msgs)
        await ctx.reply(summary)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RefereatCog(bot))
