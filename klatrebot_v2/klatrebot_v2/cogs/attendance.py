"""Klatretid reaction handler + !klatring status command."""
import logging
from datetime import datetime, timezone

import discord
import pytz
from discord.ext import commands

from klatrebot_v2.db import attendance as att_db, users as users_db
from klatrebot_v2.settings import get_settings
from klatrebot_v2.tasks import (
    DEFAULT_KLATRETID_DESCRIPTION,
    build_klatretid_embed,
    post_klatretid_embed_in,
)


logger = logging.getLogger(__name__)


def _today_local_str() -> str:
    s = get_settings()
    tz = pytz.timezone(s.timezone)
    return datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")


def _resolve_display_name(user_obj) -> str:
    if user_obj is None:
        return ""
    nick = getattr(user_obj, "nick", None)
    if nick:
        return nick
    return getattr(user_obj, "global_name", None) or getattr(user_obj, "name", "") or ""


class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == (self.bot.user.id if self.bot.user else 0):
            return
        sess = await att_db.active_session(
            self.bot.db_conn, channel_id=payload.channel_id, today_local=_today_local_str()
        )
        if sess is None or sess.message_id != payload.message_id:
            return
        emoji = payload.emoji.name
        if emoji == "✅":
            status = "yes"
        elif emoji == "❌":
            status = "no"
        else:
            return

        existing = await users_db.get(self.bot.db_conn, payload.user_id)
        display_name = _resolve_display_name(payload.member)
        if not display_name:
            user_obj = self.bot.get_user(payload.user_id)
            if user_obj is None:
                try:
                    user_obj = await self.bot.fetch_user(payload.user_id)
                except discord.HTTPException:
                    user_obj = None
            display_name = _resolve_display_name(user_obj)
        if not display_name:
            display_name = existing.display_name if existing is not None else str(payload.user_id)
        await users_db.upsert(
            self.bot.db_conn, discord_user_id=payload.user_id, display_name=display_name
        )
        await att_db.record_event(
            self.bot.db_conn,
            session_id=sess.id,
            user_id=payload.user_id,
            status=status,
            timestamp_utc=datetime.now(timezone.utc),
        )
        await self._refresh_embed(payload.channel_id, sess)

    async def _refresh_embed(self, channel_id: int, sess) -> None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            msg = await channel.fetch_message(sess.message_id)
        except discord.HTTPException:
            logger.exception("klatretid: fetch_message failed for %d", sess.message_id)
            return
        yes, no = await att_db.tally(self.bot.db_conn, session_id=sess.id)
        bailers = await att_db.bailers(self.bot.db_conn, session_id=sess.id)
        bailer_ids = {u.discord_user_id for u in bailers}
        if not yes and not no:
            embed = build_klatretid_embed()
        else:
            yes_names = ", ".join(u.display_name for u in yes)
            no_names = ", ".join(
                (f"{u.display_name} 🐔" if u.discord_user_id in bailer_ids else u.display_name)
                for u in no
            )
            description = (
                f"{DEFAULT_KLATRETID_DESCRIPTION}"
                f"\n✅: {yes_names}"
                f"\n❌: {no_names}"
            )
            embed = build_klatretid_embed(description=description)
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            logger.exception("klatretid: edit message %d failed", sess.message_id)

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

    @commands.command(name="debug_klatretid")
    async def debug_klatretid(self, ctx: commands.Context) -> None:
        """Admin-only: spawn a klatretid session in the current channel right now."""
        s = get_settings()
        if ctx.author.id != s.admin_user_id:
            await ctx.reply("Kun admin.")
            return
        tz = pytz.timezone(s.timezone)
        now_local = datetime.now(timezone.utc).astimezone(tz)
        existing = await att_db.active_session(
            self.bot.db_conn, channel_id=ctx.channel.id, today_local=now_local.strftime("%Y-%m-%d")
        )
        if existing is not None:
            await ctx.reply("Der er allerede en klatretid-session i denne kanal i dag.")
            return
        await post_klatretid_embed_in(self.bot, channel=ctx.channel, post_time_local=now_local)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttendanceCog(bot))
