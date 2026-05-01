"""Classifier that routes !gpt questions to either fast chat path or Hermes agent.

Uses a small/cheap model (gpt-5.4-nano by default) with JSON schema structured
output. On any failure (timeout, malformed JSON, exception) returns "chat" — the
safe default keeps existing behavior.
"""
import asyncio
import json
import logging
from typing import Literal

from klatrebot_v2.llm.client import get_client
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)

Route = Literal["chat", "agent"]

_SYSTEM = """Du klassificerer beskeder fra en dansk Discord-klatreklub.

Returnér JSON: {"route": "chat" | "agent"}.

"agent" = spørgsmål der kræver opslag i historik, statistik, eller flere trin:
- "hvem var med til klatretid sidste uge"
- "hvor mange gange har Magnus meldt afbud i år"
- "hvornår snakkede vi sidst om skader"
- "lav et resumé af de sidste 3 dages chat"
- "find beskeder hvor nogen nævner sektor X"

"chat" = alt andet — almindelig samtale, vittigheder, fakta-spørgsmål, kodning,
forklaringer, generelle råd, kort svar:
- "hvad er hovedstaden i Frankrig"
- "fortæl en vittighed"
- "hvad betyder onsight"
- "hvordan binder jeg en figure-8"
- "godmorgen"

Svar kun med JSON. Ingen forklaring."""


_SCHEMA = {
    "type": "object",
    "properties": {"route": {"type": "string", "enum": ["chat", "agent"]}},
    "required": ["route"],
    "additionalProperties": False,
}


async def classify(question: str) -> Route:
    s = get_settings()
    client = get_client()
    try:
        resp = await asyncio.wait_for(
            client.responses.create(
                model=s.classifier_model,
                input=f"{_SYSTEM}\n\nMESSAGE: {question}",
                reasoning={"effort": "none"},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "route",
                        "schema": _SCHEMA,
                        "strict": True,
                    }
                },
                max_output_tokens=20,
            ),
            timeout=s.classifier_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning("router.classify timeout, defaulting to chat")
        return "chat"
    except Exception as e:
        logger.warning("router.classify error: %s, defaulting to chat", e)
        return "chat"

    raw = resp.output_text or ""
    try:
        data = json.loads(raw)
        route = data.get("route")
    except (json.JSONDecodeError, AttributeError):
        logger.warning("router.classify malformed json: %r, defaulting to chat", raw)
        return "chat"

    if route in ("chat", "agent"):
        return route
    logger.warning("router.classify unexpected route %r, defaulting to chat", route)
    return "chat"
