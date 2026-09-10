"""Admin commands for persisted user names and pronouns."""
import discord
from discord.ext import commands

from klatrebot_v2.db import user_aliases, user_pronouns, users
from klatrebot_v2.settings import get_settings


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def allowed(self, ctx: commands.Context) -> bool:
        if ctx.author.id == get_settings().admin_user_id:
            return True
        author = await users.get(self.bot.db_conn, ctx.author.id)
        if author and author.is_admin:
            return True
        await ctx.reply("Du har ikke adgang til denne kommando.")
        return False

    @commands.command(name="set_display_name")
    async def set_display_name(self, ctx: commands.Context, user_id: int, *, display_name: str) -> None:
        """Sæt navn/alias: !set_display_name BRUGER_ID Navn"""
        if not await self.allowed(ctx):
            return
        display_name = display_name.strip()
        if user_id <= 0 or not user_aliases.normalize_alias(display_name) or len(display_name) > 80:
            await ctx.reply("Brug et gyldigt bruger-ID og et navn på højst 80 tegn.")
            return
        await users.upsert(self.bot.db_conn, discord_user_id=user_id, display_name=display_name)
        await user_aliases.upsert_alias(self.bot.db_conn, discord_user_id=user_id,
                                       alias=display_name, source="config")
        await ctx.reply(f"Navn sat til {display_name} for bruger {user_id}.",
                        allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="set_pronouns")
    async def set_pronouns(self, ctx: commands.Context, user_id: int, *, pronouns: str) -> None:
        """Sæt pronominer: !set_pronouns BRUGER_ID han/ham|hun/hende|de/dem"""
        if not await self.allowed(ctx):
            return
        pronouns = pronouns.strip().lower()
        if user_id <= 0 or pronouns not in user_pronouns.PRONOUNS:
            await ctx.reply("Brug et gyldigt bruger-ID og han/ham, hun/hende eller de/dem.")
            return
        await user_pronouns.set_for_user(self.bot.db_conn, user_id, pronouns)
        await ctx.reply(f"Pronominer sat til {pronouns} for bruger {user_id}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
