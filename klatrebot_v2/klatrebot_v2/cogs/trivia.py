"""Lightweight trivia commands."""
import asyncio
from datetime import datetime, timezone

import pytz
from discord.ext import commands

from klatrebot_v2.pelle import seconds_as_dt_string, where_the_fuck_is_pelle
from klatrebot_v2.settings import get_settings


class TriviaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="ugenr")
    async def ugenr(self, ctx: commands.Context) -> None:
        s = get_settings()
        tz = pytz.timezone(s.timezone)
        await ctx.send(f"Vi er i uge {datetime.now(tz).isocalendar()[1]}")

    @commands.command(name="uptime")
    async def uptime(self, ctx: commands.Context) -> None:
        if self.bot.start_time is None:
            await ctx.send("Lige startet.")
            return
        total_seconds = (datetime.now(timezone.utc) - self.bot.start_time).total_seconds()
        await ctx.send(f"Jeg har kørt i {seconds_as_dt_string(total_seconds)}")

    @commands.command(name="pelle")
    async def pelle(self, ctx: commands.Context, *, arg: str | None = None) -> None:
        result = await asyncio.to_thread(where_the_fuck_is_pelle, arg=arg)
        await ctx.reply(result)

    @commands.command(name="glar")
    async def glar(self, ctx: commands.Context) -> None:
        s = get_settings()
        tz = pytz.timezone(s.timezone)
        now_local = datetime.now(tz)
        if now_local.hour < 10:
            await ctx.send(f"Det er vist over din sengetid {ctx.author.name}")
            return
        if now_local.weekday() in s.klatretid_days and now_local.hour < s.klatretid_post_hour:
            await ctx.send("Ro på kaptajn, folket er på arbejde")
            return
        await ctx.send("@everyone Hva sker der? er i.. er i glar?")
        await ctx.send("https://imgur.com/CnRFnel")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TriviaCog(bot))
