"""!gpt command. Thin adapter over llm.chat.reply."""
import logging
import time

import discord
from discord.ext import commands

from klatrebot_v2.llm import chat, ratelimit


logger = logging.getLogger(__name__)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="gpt")
    async def gpt(self, ctx: commands.Context, *, question: str) -> None:
        if not ratelimit.check_and_record(ctx.author.id):
            logger.info("ratelimit.blocked user_id=%d", ctx.author.id)
            await ctx.reply("Slap af, du har spurgt for meget.")
            return
        start = time.monotonic()
        async with ctx.typing():
            result = await chat.reply(
                question=question,
                asking_user_id=ctx.author.id,
                channel_id=ctx.channel.id,
            )
        elapsed = time.monotonic() - start
        logger.info("llm.reply duration=%.2fs", elapsed)

        text = result.text
        if result.sources:
            text += f"\n\n_Kilder: {', '.join(result.sources[:3])}_"
        await ctx.reply(text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
