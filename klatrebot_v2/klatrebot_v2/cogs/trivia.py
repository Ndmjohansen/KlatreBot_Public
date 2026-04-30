"""Lightweight trivia commands."""
import asyncio
from datetime import datetime, timezone

from discord.ext import commands

from klatrebot_v2.pelle import where_the_fuck_is_pelle


class TriviaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="ugenr")
    async def ugenr(self, ctx: commands.Context) -> None:
        await ctx.reply(f"Vi er i uge {datetime.now().isocalendar()[1]}")

    @commands.command(name="uptime")
    async def uptime(self, ctx: commands.Context) -> None:
        if self.bot.start_time is None:
            await ctx.reply("Lige startet.")
            return
        delta = datetime.now(timezone.utc) - self.bot.start_time
        await ctx.reply(f"Uppe i {delta}")

    @commands.command(name="pelle")
    async def pelle(self, ctx: commands.Context, *, arg: str | None = None) -> None:
        result = await asyncio.to_thread(where_the_fuck_is_pelle, arg=arg)
        await ctx.reply(result)

    @commands.command(name="glar")
    async def glar(self, ctx: commands.Context) -> None:
        await ctx.reply("https://imgur.com/CnRFnel")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TriviaCog(bot))
