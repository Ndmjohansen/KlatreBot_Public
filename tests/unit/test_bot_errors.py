from unittest.mock import AsyncMock

from discord.ext import commands

from klatrebot_v2.bot import KlatreBot


async def test_unknown_command_is_ignored() -> None:
    ctx = AsyncMock()

    await KlatreBot.on_command_error(None, ctx, commands.CommandNotFound('Command "nicklas" is not found'))

    ctx.reply.assert_not_awaited()
