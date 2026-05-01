"""!gpt + !agent commands. !gpt routes via classifier; !agent forces Hermes path."""
import logging
import time
from typing import Literal

import discord
from discord.ext import commands

from klatrebot_v2.llm import chat, hermes_client, ratelimit, router


logger = logging.getLogger(__name__)

Route = Literal["chat", "agent"]
UsedRoute = Literal["chat", "agent", "agent_failed"]


def _strip_fast_flag(question: str) -> tuple[str, bool]:
    """Strip a single --fast flag. Returns (cleaned, force_chat)."""
    parts = question.split()
    keep: list[str] = []
    force_chat = False
    for p in parts:
        if p == "--fast" and not force_chat:
            force_chat = True
        else:
            keep.append(p)
    return " ".join(keep), force_chat


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="gpt")
    async def gpt(self, ctx: commands.Context, *, question: str) -> None:
        cleaned, force_chat = _strip_fast_flag(question)
        await self._run(ctx, cleaned, forced_route="chat" if force_chat else None)

    @commands.command(name="agent")
    async def agent(self, ctx: commands.Context, *, question: str) -> None:
        await self._run(ctx, question.strip(), forced_route="agent")

    async def _run(
        self, ctx: commands.Context, question: str, *, forced_route: Route | None
    ) -> None:
        if not ratelimit.check_and_record(ctx.author.id):
            logger.info("ratelimit.blocked user_id=%d", ctx.author.id)
            await ctx.reply("Nu slapper du fandme lige lidt af med de spørgsmål")
            return
        if not question:
            await ctx.reply("Spørg om noget.")
            return

        start = time.monotonic()
        async with ctx.typing():
            if forced_route is not None:
                route: Route = forced_route
                logger.info("router.forced route=%s user_id=%d", route, ctx.author.id)
            else:
                route = await router.classify(question)
                logger.info("router.classify route=%s user_id=%d", route, ctx.author.id)

            mentions = {u.id: u.display_name for u in ctx.message.mentions}
            result, used_route = await self._dispatch(
                route=route,
                explicit_agent=(forced_route == "agent"),
                question=question,
                ctx=ctx,
                mentions=mentions,
            )

        logger.info("llm.reply duration=%.2fs route=%s", time.monotonic() - start, used_route)
        await self._send_reply(ctx, result, route, used_route)

    async def _send_reply(
        self,
        ctx: commands.Context,
        result: chat.ChatReply,
        route: Route,
        used_route: UsedRoute,
    ) -> None:
        text = result.text
        if route == "agent" and used_route == "chat":
            text += "\n\n_(hurtigt svar — agent utilgængelig)_"
        if result.sources:
            text += f"\n\n_Kilder: {', '.join(result.sources[:3])}_"
        await ctx.reply(
            text,
            allowed_mentions=discord.AllowedMentions(
                users=True, everyone=False, roles=False, replied_user=True
            ),
        )

    async def _dispatch(
        self,
        *,
        route: Route,
        explicit_agent: bool,
        question: str,
        ctx: commands.Context,
        mentions: dict[int, str],
    ) -> tuple[chat.ChatReply, UsedRoute]:
        if route == "agent":
            try:
                result = await hermes_client.ask(
                    question=question,
                    asking_user_id=ctx.author.id,
                    channel_id=ctx.channel.id,
                    username=ctx.author.display_name,
                    mentions=mentions,
                )
                return result, "agent"
            except hermes_client.HermesUnavailable as e:
                logger.warning("hermes unavailable: %s", e)
                if explicit_agent:
                    msg = "Hermes er nede lige nu. Prøv `!gpt` i stedet."
                    return chat.ChatReply(text=msg), "agent_failed"

        result = await chat.reply(
            question=question,
            asking_user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            mentions=mentions,
        )
        return result, "chat"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
