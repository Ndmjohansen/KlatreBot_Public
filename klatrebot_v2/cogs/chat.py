"""!gpt command. Thin adapter over llm.chat.reply."""
import logging
import time

import discord
from discord.ext import commands

from klatrebot_v2.llm import chat, ratelimit
from klatrebot_v2.db import messages as msg_db, users as users_db


logger = logging.getLogger(__name__)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="gpt")
    async def gpt(self, ctx: commands.Context, *, question: str) -> None:
        if not ratelimit.check_and_record(ctx.author.id):
            logger.info("ratelimit.blocked user_id=%d", ctx.author.id)
            await ctx.reply("Nu slapper du fandme lige lidt af med de spørgsmål")
            return
        start = time.monotonic()
        # Command dispatch and listeners run independently. Commit the invoking
        # message before reading context; duplicate listener inserts are harmless.
        await users_db.upsert(self.bot.db_conn, discord_user_id=ctx.author.id,
                              display_name=ctx.author.display_name)
        await msg_db.insert(self.bot.db_conn, discord_message_id=ctx.message.id,
                            channel_id=ctx.channel.id, user_id=ctx.author.id,
                            content=ctx.message.content, timestamp_utc=ctx.message.created_at,
                            is_bot=ctx.author.bot)
        async with ctx.typing():
            mentions = {u.id: u.display_name for u in ctx.message.mentions}
            result = await chat.reply(
                question=question,
                asking_user_id=ctx.author.id,
                channel_id=ctx.channel.id,
                mentions=mentions,
                invoking_message_id=ctx.message.id,
            )
        elapsed = time.monotonic() - start
        logger.info("llm.reply duration=%.2fs", elapsed)

        text = result.text
        if result.sources:
            text += f"\n\n_Kilder: {', '.join(result.sources[:3])}_"
        if not text.strip():
            logger.warning("llm.reply empty text user_id=%d", ctx.author.id)
            text = "Jeg kunne ikke finde på et svar. Prøv igen."
        await ctx.reply(
            text,
            suppress_embeds=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, everyone=False, roles=False, replied_user=True
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
