"""Responses API tool definitions and executors for memory recall."""
import json
from datetime import datetime
from typing import Any

import aiosqlite

from klatrebot_v2.db import user_aliases
from klatrebot_v2.llm.prompt import load_prompt
from klatrebot_v2.memory.retrieval import get_memory_sources, recall_community_memory
from klatrebot_v2.memory.retrieval import RecallResult
from klatrebot_v2.memory.search import search
from klatrebot_v2.memory.transport import request


MEMORY_TOOL_DEFS = [
    {
        "type": "function",
        "name": "recall_community_memory",
        "strict": True,
        "description": load_prompt("memory_fields", "recall"),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": load_prompt("memory_fields", "query")},
                "channel_id": {"type": ["integer", "null"], "description": load_prompt("memory_fields", "channel_id")},
                "people": {"type": ["array", "null"], "items": {"type": "integer"}, "description": load_prompt("memory_fields", "people")},
                "people_names": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": load_prompt("memory_fields", "people_names"),
                },
                "date_start": {"type": ["string", "null"], "description": load_prompt("memory_fields", "date_start")},
                "date_end": {"type": ["string", "null"], "description": load_prompt("memory_fields", "date_end")},
                "memory_types": {
                    "type": ["array", "null"],
                    "description": load_prompt("memory_fields", "memory_types"),
                    "items": {
                        "type": "string",
                        "enum": ["raw_message", "decision", "plan", "preference", "fact", "opinion", "open_question", "lore"],
                    },
                },
                "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10, "description": load_prompt("memory_fields", "limit")},
                "order": {"type": ["string", "null"], "enum": ["relevance", "latest", None], "description": load_prompt("memory_fields", "order")},
                "person_role": {"type": ["string", "null"], "enum": ["author", "subject", None], "description": load_prompt("memory_fields", "person_role")},
                "cursor": {"type": ["string", "null"], "description": load_prompt("memory_fields", "cursor")},
            },
            "required": ["query", "channel_id", "people", "people_names", "date_start", "date_end", "memory_types", "limit", "order", "person_role", "cursor"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_memory_sources",
        "strict": True,
        "description": load_prompt("memory_fields", "sources"),
        "parameters": {
            "type": "object",
            "properties": {
                "source_handles": {"type": "array", "items": {"type": "string"}},
                "context_radius": {"type": ["integer", "null"], "minimum": 0, "maximum": 10, "description": load_prompt("memory_fields", "context_radius")},
            },
            "required": ["source_handles", "context_radius"],
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
    settings=None,
) -> str:
    if name == "recall_community_memory":
        try:
            start = _parse_dt(arguments.get("date_start"))
            end = _parse_dt(arguments.get("date_end"))
        except (ValueError, TypeError):
            return json.dumps({"answerable": False, "status": "invalid_arguments", "results": [],
                "source_handles": [], "coverage": {"instruction": load_prompt("tool_feedback", "invalid_dates")}})
        people_resolution = await user_aliases.resolve_people_names(conn, arguments.get("people_names"))
        people = _merge_people(arguments.get("people"), people_resolution.resolved_ids)
        unknown_ids = []
        for person in people or []:
            known = await conn.execute_fetchall(
                "SELECT discord_user_id FROM users WHERE discord_user_id=? UNION SELECT discord_user_id FROM user_aliases WHERE discord_user_id=?",
                (person, person))
            if not known:
                unknown_ids.append(person)
        if unknown_ids:
            return json.dumps({"answerable": False, "status": "clarification_required", "results": [],
                               "source_handles": [], "unknown_people": unknown_ids})
        if people_resolution.ambiguous or people_resolution.unmatched:
            return json.dumps({"answerable": False, "status": "clarification_required", "results": [],
                               "source_handles": [], "resolved_people": {
                                   "ids": people_resolution.resolved_ids,
                                   "ambiguous": people_resolution.ambiguous,
                                   "unmatched": people_resolution.unmatched}}, ensure_ascii=False)
        mode = getattr(settings, "memory_backend", "legacy")
        retrieval_request = dict(run_id=run_id, query=arguments["query"], people=people,
                                 channel_id=arguments.get("channel_id"),
                                 date_start=start.isoformat() if start else None,
                                 date_end=end.isoformat() if end else None,
                                 memory_types=arguments.get("memory_types"),
                                 limit=max(1, min(10, int(arguments.get("limit") or 10))),
                                 order=arguments.get("order") or "relevance",
                                 person_role=arguments.get("person_role") or "author",
                                 cursor=arguments.get("cursor"))
        candidate = None
        if mode == "mempalace":
            try:
                candidate = RecallResult.model_validate(await request(settings.memory_socket_path, retrieval_request))
            except Exception:
                candidate = await search(conn, retrieval_request)
        if mode == "mempalace":
            result = candidate
        else:
            result = await recall_community_memory(
                conn,
                run_id=run_id,
                query=arguments["query"],
                channel_id=arguments.get("channel_id"),
                people=people,
                date_range=(start, end) if start or end else None,
                memory_types=arguments.get("memory_types"),
                limit=retrieval_request["limit"],
            )
        payload = result.model_dump(mode="json")
        if mode == "mempalace":
            payload["search_scope"] = retrieval_request
        if arguments.get("people_names"):
            payload["resolved_people"] = {
                "ids": people_resolution.resolved_ids,
                "ambiguous": people_resolution.ambiguous,
                "unmatched": people_resolution.unmatched,
            }
        return json.dumps(payload, ensure_ascii=False)

    if name == "get_memory_sources":
        result = await get_memory_sources(
            conn,
            source_handles=arguments.get("source_handles", []),
            context_radius=max(0, min(10, int(5 if arguments.get("context_radius") is None else arguments['context_radius']))),
        )
        return json.dumps([m.model_dump(mode="json") for m in result], ensure_ascii=False)

    return json.dumps({"error": f"Unknown memory tool: {name}"})


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _merge_people(raw_people: list[int] | None, resolved_people: list[int]) -> list[int] | None:
    merged = {int(person) for person in raw_people or []}
    merged.update(resolved_people)
    return sorted(merged) if merged else None
