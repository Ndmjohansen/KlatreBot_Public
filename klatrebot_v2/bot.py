"""discord.py Bot subclass. Owns DB connection + cog registration."""
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands

from klatrebot_v2.db import connection, migrations
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)


class KlatreBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(intents=intents, command_prefix="!")
        self.db_conn = None
        self.start_time: datetime | None = None

    async def setup_hook(self) -> None:
        s = get_settings()
        # Fail loudly if SOUL.MD is missing
        Path(s.soul_path).read_text(encoding="utf-8")
        # Open DB and run migrations
        self.db_conn = await connection.open(s.db_path)
        await migrations.run(self.db_conn)
        from klatrebot_v2.llm import chat as llm_chat
        llm_chat.set_db_conn_provider(lambda: self.db_conn)
        # Register cogs
        await self.load_extension("klatrebot_v2.cogs.chat")
        await self.load_extension("klatrebot_v2.cogs.auto_responses")
        await self.load_extension("klatrebot_v2.cogs.attendance")
        await self.load_extension("klatrebot_v2.cogs.referat")
        await self.load_extension("klatrebot_v2.cogs.trivia")
        from klatrebot_v2.tasks import klatretid_scheduler
        self.loop.create_task(klatretid_scheduler(self))
        self.start_time = datetime.now(timezone.utc)
        logger.info("Bot startup completed")

    async def on_ready(self) -> None:
        logger.info("Bot connected to Discord as %s", self.user)

    async def close(self) -> None:
        if self.db_conn is not None:
            await connection.close(self.db_conn)
        await super().close()

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply("Slap af.")
            return
        logger.exception("Command %s failed", ctx.command, exc_info=error)
        original = getattr(error, "original", error)
        await ctx.reply(f"Det kan jeg desværre ikke svare på. ({original})")
