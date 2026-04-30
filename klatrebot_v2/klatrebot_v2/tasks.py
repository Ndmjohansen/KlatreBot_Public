"""Background tasks. Created by bot.setup_hook."""
import asyncio
import logging
from datetime import datetime, timezone

import discord
import pytz
from discord.ext import commands

from klatrebot_v2.db import attendance as att_db
from klatrebot_v2.settings import get_settings
from klatrebot_v2.time_utils import klatring_start_utc_for, next_klatretid_post


logger = logging.getLogger(__name__)


async def klatretid_scheduler(bot: commands.Bot) -> None:
    """Loop: sleep until next post moment; post; loop."""
    s = get_settings()
    tz = pytz.timezone(s.timezone)
    while True:
        now = datetime.now(timezone.utc)
        nxt = next_klatretid_post(
            now=now,
            days=s.klatretid_days,
            hour=s.klatretid_post_hour,
            tz=tz,
        )
        delay = (nxt - now.astimezone(tz)).total_seconds()
        logger.info("klatretid_scheduler.sleep_until=%s delay_seconds=%.0f", nxt.isoformat(), delay)
        await asyncio.sleep(max(delay, 1.0))
        try:
            await _post_klatretid_embed(bot, post_time_local=nxt)
        except Exception:
            logger.exception("klatretid_scheduler.post_failed")
        await asyncio.sleep(60)


async def _post_klatretid_embed(bot: commands.Bot, *, post_time_local: datetime) -> None:
    s = get_settings()
    channel = bot.get_channel(s.discord_main_channel_id)
    if channel is None:
        logger.error("klatretid: main channel %d not found", s.discord_main_channel_id)
        return
    await post_klatretid_embed_in(bot, channel=channel, post_time_local=post_time_local)


async def post_klatretid_embed_in(
    bot: commands.Bot,
    *,
    channel: discord.abc.Messageable,
    post_time_local: datetime,
) -> None:
    """Post klatretid embed + create attendance session in `channel`."""
    s = get_settings()
    embed = discord.Embed(
        title="Klatretid 🧗",
        description=f"Hvem kommer kl. {s.klatretid_start_hour}? React med ✅ / ❌.",
        color=0x6E1FFF,
    )
    msg = await channel.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    klatring_start = klatring_start_utc_for(
        post_time_local=post_time_local, start_hour=s.klatretid_start_hour
    )
    await att_db.create_session(
        bot.db_conn,
        date_local=post_time_local.strftime("%Y-%m-%d"),
        channel_id=channel.id,
        message_id=msg.id,
        klatring_start_utc=klatring_start,
    )
    logger.info("klatretid_session.created date=%s msg=%d", post_time_local.date(), msg.id)
