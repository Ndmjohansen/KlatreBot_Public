"""!gpt command. Routes between fast chat path and Hermes agent."""
import logging
import time

import discord
from discord.ext import commands

from klatrebot_v2.llm import chat, hermes_client, ratelimit, router


logger = logging.getLogger(__name__)


def _parse_overrides(question: str) -> tuple[str, str | None]:
    """Strip --fast / --agent flags. Returns (cleaned_question, override or None)."""
    parts = question.split()
    override: str | None = None
    keep: list[str] = []
    for p in parts:
        if p == "--fast" and override is None:
            override = "chat"
        elif p == "--agent" and override is None:
            override = "agent"
        else:
            keep.append(p)
    return " ".join(keep), override


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="gpt")
    async def gpt(self, ctx: commands.Context, *, question: str) -> None:
        if not ratelimit.check_and_record(ctx.author.id):
            logger.info("ratelimit.blocked user_id=%d", ctx.author.id)
            await ctx.reply("Nu slapper du fandme lige lidt af med de spørgsmål")
            return

        cleaned, override = _parse_overrides(question)
        if not cleaned:
            await ctx.reply("Spørg om noget.")
            return

        start = time.monotonic()
        async with ctx.typing():
            if override is not None:
                route = override
                logger.info("router.override route=%s user_id=%d", route, ctx.author.id)
            else:
                route = await router.classify(cleaned)
                logger.info("router.classify route=%s user_id=%d", route, ctx.author.id)

            mentions = {u.id: u.display_name for u in ctx.message.mentions}
            result, used_route = await self._dispatch(
                route=route,
                explicit_agent=(override == "agent"),
                question=cleaned,
                ctx=ctx,
                mentions=mentions,
            )

        elapsed = time.monotonic() - start
        logger.info("llm.reply duration=%.2fs route=%s", elapsed, used_route)

        text = result.text
        if used_route == "chat" and route == "agent" and override != "agent":
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
        route: str,
        explicit_agent: bool,
        question: str,
        ctx: commands.Context,
        mentions: dict[int, str],
    ) -> tuple[chat.ChatReply, str]:
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
                    msg = "Hermes er nede lige nu. Prøv igen senere eller drop `--agent`."
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
