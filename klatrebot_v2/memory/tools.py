"""Responses API tool definitions and executors for memory recall."""
import json
from datetime import datetime
from typing import Any

import aiosqlite

from klatrebot_v2.memory.retrieval import get_memory_sources, recall_community_memory


MEMORY_TOOL_DEFS = [
    {
        "type": "function",
        "name": "recall_community_memory",
        "description": "Søg i KlatreBot's holdbare fællesskabshukommelse for historiske samtaler, planer, præferencer, beslutninger og lore.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "channel_id": {"type": "integer"},
                "people": {"type": "array", "items": {"type": "integer"}},
                "date_start": {"type": "string", "description": "ISO timestamp, inclusive"},
                "date_end": {"type": "string", "description": "ISO timestamp, exclusive"},
                "memory_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["decision", "plan", "preference", "fact", "opinion", "open_question", "lore"],
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_memory_sources",
        "description": "Hent rå kildebeskeder for tidligere memory-resultater. Brug kun når brugeren spørger efter kilder eller ved debug.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_handles": {"type": "array", "items": {"type": "string"}},
                "context_radius": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "required": ["source_handles"],
            "additionalProperties": False,
        },
    },
]


async def execute_memory_tool(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    name: str,
    arguments: dict[str, Any],
) -> str:
    if name == "recall_community_memory":
        start = _parse_dt(arguments.get("date_start"))
        end = _parse_dt(arguments.get("date_end"))
        result = await recall_community_memory(
            conn,
            run_id=run_id,
            query=arguments["query"],
            channel_id=arguments.get("channel_id"),
            people=arguments.get("people"),
            date_range=(start, end) if start or end else None,
            memory_types=arguments.get("memory_types"),
            limit=int(arguments.get("limit") or 6),
        )
        return result.model_dump_json()

    if name == "get_memory_sources":
        result = await get_memory_sources(
            conn,
            source_handles=arguments.get("source_handles", []),
            context_radius=int(arguments.get("context_radius") or 5),
        )
        return json.dumps([m.model_dump(mode="json") for m in result], ensure_ascii=False)

    return json.dumps({"error": f"Unknown memory tool: {name}"})


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
