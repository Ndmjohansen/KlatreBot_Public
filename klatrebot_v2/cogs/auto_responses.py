"""on_message listener — DB log + data-driven trigger table."""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import discord
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db, users as users_db


logger = logging.getLogger(__name__)


# ─── Trigger registry ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AutoResponse:
    name: str
    pattern: re.Pattern
    handler: Callable[[discord.Message], Awaitable[str | None]]


_SVAR = [
    "Det er sikkert", "Uden tvivl", "Ja helt sikkert", "Som jeg ser det, ja",
    "Højst sandsynligt", "Ja", "Nej", "Nok ikke", "Regn ikke med det",
    "Mine kilder siger nej", "Meget tvivlsomt", "Mit svar er nej",
]

_EB_ROAST = (
    "I - især Magnus - skal til at holde op med at læse Ekstra Bladet, som om I var barbarer.\n"
    "Jeg ved godt, at I høfligt forsøger at integrere jer i Sydhavnen, men få lige skubbet "
    "lidt på den gentrificering og læs et rigtigt medie"
)


async def _static(text: str) -> str:
    return text


_UGE_RE = re.compile(r"\buge\s?(\d{1,2})\b", re.I)


def _number_of_weeks(year: int) -> int:
    return datetime(year, 12, 28).isocalendar()[1]


def _dates_of_week(year: int, week: int) -> tuple[str, str]:
    monday = datetime.strptime(f"{year}-{week}-1", "%G-%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


async def _handle_uge(msg: discord.Message) -> str | None:
    matches = _UGE_RE.findall(msg.content)
    if not matches:
        return None
    now = datetime.now()
    year = now.year
    weeks_in_year = _number_of_weeks(year)
    current_week = now.isocalendar()[1]
    parts: list[str] = []
    for raw in matches:
        try:
            requested = int(raw)
        except ValueError:
            continue
        if not 1 <= requested <= 53:
            continue
        target_year = year if current_week <= requested <= weeks_in_year else year + 1
        try:
            start, end = _dates_of_week(target_year, requested)
        except ValueError:
            continue
        parts.append(f"Uge {requested}, {start} til {end}")
    if not parts:
        return None
    return " - ".join(parts)


RESPONSES: list[AutoResponse] = [
    AutoResponse(
        name="ugenr_match",
        pattern=_UGE_RE,
        handler=_handle_uge,
    ),
    AutoResponse(
        name="downus",
        pattern=re.compile(r"^!downus|fail", re.I),
        handler=lambda m: _static(
            "https://cdn.discordapp.com/attachments/1003718776430268588/1153668006728192101/downus_on_wall.gif"
        ),
    ),
    AutoResponse(
        name="klatrebot_question",
        pattern=re.compile(r"^klatrebot.*\?$", re.I),
        handler=lambda m: _static(random.choice(_SVAR)),
    ),
    AutoResponse(
        name="det_kan_man_ik",
        pattern=re.compile(r"det\skan\sman\s(\w+\s)?ik", re.I),
        handler=lambda m: _static(
            "https://cdn.discordapp.com/attachments/1049312345068933134/1049363489354952764/pellememetekst.gif"
        ),
    ),
    AutoResponse(
        name="elmo",
        pattern=re.compile(r"\b(elmo|elon)\b", re.I),
        handler=lambda m: _static("https://imgur.com/LNVCB8g"),
    ),
    AutoResponse(
        name="ekstrabladet",
        pattern=re.compile(r"ekstrabladet\.dk|eb\.dk", re.I),
        handler=lambda m: _static(_EB_ROAST),
    ),
    AutoResponse(
        name="glar_midsentence",
        pattern=re.compile(r"(?<=.)!glar", re.I),
        handler=lambda m: _static("https://imgur.com/CnRFnel"),
    ),
]


def first_match(text: str) -> AutoResponse | None:
    for ar in RESPONSES:
        if ar.pattern.search(text):
            return ar
    return None


def matching_responses(text: str) -> list[AutoResponse]:
    return [ar for ar in RESPONSES if ar.pattern.search(text)]


# ─── Cog ─────────────────────────────────────────────────────────────────────


class AutoResponsesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
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
            is_bot=message.author.bot,
        )

        if message.author.bot:
            return

        for ar in matching_responses(message.content):
            try:
                reply = await ar.handler(message)
            except Exception:
                logger.exception("auto_response.handler_failed name=%s", ar.name)
                continue
            if reply:
                logger.info("auto_response.fired name=%s", ar.name)
                await message.channel.send(reply)


def _display_name(member) -> str:
    return (
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", "")
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoResponsesCog(bot))
