"""Generated social reflection documents built from durable memory."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from klatrebot_v2.db import user_aliases
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.memory import store


DEFAULT_REFLECTION_NAME = "social-reflections"
DEFAULT_REFLECTION_MODEL = "gpt-5.4-mini"
REFLECTION_PROMPT_PATH = Path(__file__).with_name("prompts") / "reflection.md"


@dataclass
class ReflectionUsage:
    responses_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add_response(self, resp: Any) -> None:
        self.responses_calls += 1
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.input_tokens += int(_usage_value(usage, "input_tokens") or 0)
        self.output_tokens += int(_usage_value(usage, "output_tokens") or 0)
        self.total_tokens += int(_usage_value(usage, "total_tokens") or 0)


@dataclass
class ReflectionInput:
    run_id: int
    run_name: str
    name: str
    from_time: datetime
    to_time: datetime
    previous_markdown: str
    soul: str
    alias_map: str
    identity_registry: list[dict[str, Any]]
    user_activity: list[dict[str, Any]]
    rollups: list[dict[str, Any]]
    daily_ambient: list[dict[str, Any]]
    memory_items: list[dict[str, Any]]


@dataclass
class ReflectionResult:
    document_id: int
    content_markdown: str


Reflector = Callable[[ReflectionInput], Awaitable[str]]


async def generate_reflection(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    run_name: str,
    name: str = DEFAULT_REFLECTION_NAME,
    from_time: datetime,
    to_time: datetime,
    model: str,
    reflector: Reflector | None = None,
    usage: ReflectionUsage | None = None,
) -> ReflectionResult:
    previous = await store.get_latest_reflection_document(conn, run_id=run_id, name=name)
    reflection_input = ReflectionInput(
        run_id=run_id,
        run_name=run_name,
        name=name,
        from_time=from_time,
        to_time=to_time,
        previous_markdown=str(previous["content_markdown"]) if previous else "",
        soul=load_soul(),
        alias_map=await user_aliases.format_alias_prompt_map(conn),
        identity_registry=await user_aliases.identity_registry_for_prompt(conn),
        user_activity=await store.reflection_user_activity_for_range(
            conn,
            from_time=from_time,
            to_time=to_time,
        ),
        rollups=await store.reflection_rollups_for_range(
            conn,
            run_id=run_id,
            from_time=from_time,
            to_time=to_time,
        ),
        daily_ambient=await store.reflection_daily_ambient_for_range(
            conn,
            run_id=run_id,
            from_time=from_time,
            to_time=to_time,
        ),
        memory_items=await store.reflection_memory_items_for_range(
            conn,
            run_id=run_id,
            from_time=from_time,
            to_time=to_time,
        ),
    )
    try:
        markdown = await (reflector or (lambda payload: summarize_reflection_with_llm(payload, model=model, usage=usage)))(
            reflection_input
        )
        markdown = _clean_markdown(markdown)
    except Exception as exc:
        await store.insert_reflection_document(
            conn,
            compiler_run_id=run_id,
            name=name,
            from_time=from_time,
            to_time=to_time,
            model=model,
            status="failed",
            error=str(exc),
            content_markdown="",
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )
        raise
    document_id = await store.insert_reflection_document(
        conn,
        compiler_run_id=run_id,
        name=name,
        from_time=from_time,
        to_time=to_time,
        model=model,
        status="completed",
        error=None,
        content_markdown=markdown,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
    )
    return ReflectionResult(document_id=document_id, content_markdown=markdown)


async def summarize_reflection_with_llm(
    reflection_input: ReflectionInput,
    *,
    model: str,
    usage: ReflectionUsage | None = None,
) -> str:
    client = get_client()
    resp = await client.responses.create(
        model=model,
        input=build_reflection_prompt(reflection_input),
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    if usage is not None:
        usage.add_response(resp)
    return resp.output_text or ""


def build_reflection_prompt(reflection_input: ReflectionInput) -> str:
    payload = {
        "run": reflection_input.run_name,
        "reflection_name": reflection_input.name,
        "range": {
            "from": reflection_input.from_time.isoformat(),
            "to": reflection_input.to_time.isoformat(),
        },
        "soul": reflection_input.soul,
        "known_user_aliases": reflection_input.alias_map,
        "identity_registry": reflection_input.identity_registry,
        "user_activity": _compact_rows(reflection_input.user_activity),
        "previous_reflection": reflection_input.previous_markdown or "(none)",
        "rollups": _compact_rows(reflection_input.rollups),
        "daily_ambient": _compact_rows(reflection_input.daily_ambient),
        "memory_items": _compact_rows(reflection_input.memory_items),
    }
    return f"{load_reflection_prompt()}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


@lru_cache(maxsize=1)
def load_reflection_prompt() -> str:
    return REFLECTION_PROMPT_PATH.read_text(encoding="utf-8").strip()


def export_markdown_with_metadata(
    *,
    content_markdown: str,
    document_id: int,
    run_name: str,
    name: str,
    from_time: datetime,
    to_time: datetime,
    model: str,
    generated_at: datetime,
) -> str:
    return (
        "<!--\n"
        f"memory_run: {run_name}\n"
        f"reflection_name: {name}\n"
        f"document_id: {document_id}\n"
        f"range: {from_time.isoformat()}..{to_time.isoformat()}\n"
        f"model: {model}\n"
        f"generated_at: {generated_at.isoformat()}\n"
        "-->\n\n"
        f"{content_markdown.rstrip()}\n"
    )


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for row in rows:
        compacted.append({key: _decode_jsonish(value) for key, value in row.items()})
    return compacted


def _decode_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _clean_markdown(markdown: str) -> str:
    return markdown.strip()


def _usage_value(usage: Any, key: str) -> Any:
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)
