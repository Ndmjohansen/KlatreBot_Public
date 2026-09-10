"""Structured intent and immutable search proposals for the MemPalace path."""
import re
from datetime import datetime
from typing import Literal

import pytz

from pydantic import BaseModel, ConfigDict, Field, model_validator
from klatrebot_v2.llm.prompt import load_prompt
from klatrebot_v2.memory.tools import MEMORY_TOOL_DEFS

_RECALL_FIELDS = MEMORY_TOOL_DEFS[0]["parameters"]["properties"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Part(StrictModel):
    kind: Literal["general", "history", "ambiguous"]
    question: str
    query: str = Field(description=_RECALL_FIELDS["query"]["description"])
    reformulation: str = Field(description=load_prompt("memory_fields", "reformulation"))
    people_names: list[str] = Field(description=_RECALL_FIELDS["people_names"]["description"])
    channel_id: int | None = Field(description=_RECALL_FIELDS["channel_id"]["description"])
    date_start: str | None = Field(description=_RECALL_FIELDS["date_start"]["description"])
    date_end: str | None = Field(description=_RECALL_FIELDS["date_end"]["description"])
    authored_month: str | None = Field(description=load_prompt("memory_fields", "authored_month"))
    latest_authored: bool
    person_role: Literal["author", "subject"] = Field(description=_RECALL_FIELDS["person_role"]["description"])

    def arguments(self, channel_id):
        return dict(query=self.query or self.question, people_names=self.people_names or None,
                    channel_id=self.channel_id if self.channel_id is not None else channel_id,
                    date_start=self.date_start, date_end=self.date_end, memory_types=None,
                    order="latest" if self.latest_authored and self.people_names and self.person_role == "author" else "relevance",
                    person_role=self.person_role, limit=10, cursor=None)


class Route(StrictModel):
    kind: Literal["general", "history", "mixed", "ambiguous"]
    too_many_parts: bool
    parts: list[Part] = Field(max_length=3)

    @model_validator(mode="after")
    def consistent(self):
        if self.too_many_parts:
            return self
        kinds = {p.kind for p in self.parts}
        if not kinds or (self.kind != "mixed" and kinds != {self.kind}):
            raise ValueError("Inconsistent route")
        if self.kind == "mixed" and ("general" not in kinds or not kinds & {"history", "ambiguous"}):
            raise ValueError("Mixed route needs independent general and historical parts")
        return self


INSTRUCTIONS = load_prompt("routing")


_MONTHS = {name: number for number, name in enumerate(
    ("januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
     "september", "oktober", "november", "december"), 1)}
_BEFORE_DATE = re.compile(
    r"\b(?:før|inden|before)\s+(?:den\s+)?(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2})|"
    r"(?P<day>\d{1,2})\.?\s+(?P<month>" + "|".join(_MONTHS) + r")\s+(?P<year>\d{4}))\b"
    r"(?!\s*(?:kl(?:okken)?\.?|at)\s*\d)(?!\s+\d{1,2}[:.]\d{2})", re.I)


def explicit_cutoffs(question):
    """Only fully specified, unambiguous calendar cutoffs are normalized in code."""
    values = []
    for match in _BEFORE_DATE.finditer(question):
        if match['iso']:
            value = datetime.strptime(match['iso'], "%Y-%m-%d")
        else:
            value = datetime(int(match['year']), _MONTHS[match['month'].lower()], int(match['day']))
        values.append(value)
    return values


def preserve_cutoff(part, question, timezone):
    original = explicit_cutoffs(question)
    proposed = explicit_cutoffs(part.question)
    if proposed and any(value not in original for value in proposed):
        raise ValueError("Router changed an explicit cutoff in the question")
    if len(proposed) == 1:
        # The caller's calendar day, not a model-subtracted day, is the exclusive
        # boundary. Use the configured timezone, including summer-time offsets.
        cutoff = pytz.timezone(timezone).localize(proposed[0]).isoformat()
        return part.model_copy(update={"date_end": cutoff})
    return part


def preserve_authored_month(part, question, timezone, now=None):
    """Validate the copied constraint and preserve its calendar bounds in code."""
    if not part.authored_month:
        return part
    constraint = part.authored_month.strip().lower()
    matches = list(re.finditer(r"(?<!\w)(" + "|".join(_MONTHS) + r")(?:\s+(\d{4}))?(?!\w)", constraint))
    if len(matches) != 1 or not re.search(r"(?<!\w)" + re.escape(constraint) + r"(?!\w)", question, re.I):
        raise ValueError("Unrecognized or invented authored month")
    match = matches[0]
    zone = pytz.timezone(timezone)
    today = now or datetime.now(zone)
    month = _MONTHS[match[1]]
    year = int(match[2]) if match[2] else today.year - (month > today.month)
    start = zone.localize(datetime(year, month, 1))
    end = zone.localize(datetime(year + (month == 12), month % 12 + 1, 1))
    return part.model_copy(update={"date_start": start.isoformat(), "date_end": end.isoformat()})


_LATEST = re.compile(
    r"\b(?:seneste?|nyeste|sidst|latest|most recent)\b|"
    r"\b(?:sidste|last)\s+(?!(?:uge|måned|år|sommer|vinter|week|month|year|night)\b)\w+",
    re.I,
)
_LATE_PERIOD = re.compile(r"\bsidst\s+(?:i|på)\s+(?:" + "|".join(_MONTHS) +
                          r"|måneden|ugen|året|sommeren|vinteren)\b", re.I)


def explicitly_latest(question, recent, invoking_message_id):
    """A router flag cannot turn 'just said' or a date filter into latest paging.

    A person correction may inherit an explicit latest request from the most
    recent preceding human question. Bot prose cannot authorize this policy.
    """
    if _LATEST.search(_LATE_PERIOD.sub("", question)):
        return True
    if re.match(r"\s*(?:nej\b|jeg mente\b|no\b|I meant\b)", question, re.I):
        previous = [m for m in recent if not m.is_bot and m.discord_message_id != invoking_message_id]
        return bool(previous and _LATEST.search(_LATE_PERIOD.sub("", previous[-1].content)))
    return False


def fallback(question, alias_map):
    # Retain explicit mentions/known names even when structured output is broken.
    names = re.findall(r"<@!?\d+>|(?<!\w)@[\wæøåÆØÅ]+", question)
    for line in alias_map.splitlines():
        for alias in line.split(" -> ")[0].split(" / "):
            if alias and re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", question, re.I):
                names.append(alias)
    return Route(kind="ambiguous", too_many_parts=False, parts=[Part(
        kind="ambiguous", question=question, query=question, reformulation=question,
        people_names=list(dict.fromkeys(names)), channel_id=None, date_start=None,
        date_end=None, authored_month=None, latest_authored=False, person_role="author")])
