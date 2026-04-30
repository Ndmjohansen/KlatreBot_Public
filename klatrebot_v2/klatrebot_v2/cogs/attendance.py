"""Klatretid reaction handler + !klatring status command."""
import logging
from datetime import datetime, timezone

import discord
import pytz
from discord.ext import commands

from klatrebot_v2.db import attendance as att_db, users as users_db
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)


def _today_local_str() -> str:
    s = get_settings()
    tz = pytz.timezone(s.timezone)
    return datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")


class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, retract=False)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, retract=True)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, *, retract: bool) -> None:
        if payload.user_id == (self.bot.user.id if self.bot.user else 0):
            return
        sess = await att_db.active_session(
            self.bot.db_conn, channel_id=payload.channel_id, today_local=_today_local_str()
        )
        if sess is None or sess.message_id != payload.message_id:
            return
        emoji = payload.emoji.name
        if emoji == "✅":
            status = "no" if retract else "yes"
        elif emoji == "❌":
            status = "yes" if retract else "no"
        else:
            return
        await users_db.upsert(self.bot.db_conn, discord_user_id=payload.user_id, display_name=str(payload.user_id))
        await att_db.record_event(
            self.bot.db_conn,
            session_id=sess.id,
            user_id=payload.user_id,
            status=status,
            timestamp_utc=datetime.now(timezone.utc),
        )

    @commands.command(name="klatring")
    async def klatring(self, ctx: commands.Context) -> None:
        sess = await att_db.active_session(
            self.bot.db_conn, channel_id=ctx.channel.id, today_local=_today_local_str()
        )
        if sess is None:
            await ctx.reply("Ingen klatretid lige nu.")
            return
        yes, no = await att_db.tally(self.bot.db_conn, session_id=sess.id)
        bailers = await att_db.bailers(self.bot.db_conn, session_id=sess.id)
        bailer_ids = {u.discord_user_id for u in bailers}
        yes_names = ", ".join(u.display_name for u in yes) or "ingen"
        no_names = ", ".join(
            (f"{u.display_name} 🐔" if u.discord_user_id in bailer_ids else u.display_name) for u in no
        ) or "ingen"
        await ctx.reply(f"Klatretid status:\n✅ {yes_names}\n❌ {no_names}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttendanceCog(bot))
