"""on_message listener — logs each user message to sqlite. Trigger table is filled in slice 6."""
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db, users as users_db


logger = logging.getLogger(__name__)


class AutoResponsesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Persist user + message
        await users_db.upsert(
            self.bot.db_conn,
            discord_user_id=message.author.id,
            display_name=_display_name(message.author),
        )
        await msg_db.insert(
            self.bot.db_conn,
            discord_message_id=message.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            content=message.content,
            timestamp_utc=message.created_at.replace(tzinfo=timezone.utc) if message.created_at.tzinfo is None else message.created_at,
            is_bot=False,
        )
        # process_commands not needed here — discord.py routes commands itself when prefix matches.


def _display_name(member) -> str:
    nick = getattr(member, "nick", None)
    if nick:
        return nick
    return getattr(member, "global_name", None) or member.name


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoResponsesCog(bot))
