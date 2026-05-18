"""Memory compiler pipeline."""
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from typing import Any, Awaitable, Callable

import aiosqlite
from pydantic import BaseModel, Field

from klatrebot_v2.llm.client import get_client
from klatrebot_v2.memory import store
from klatrebot_v2.memory.segmentation import (
    SegmentCandidate,
    SegmentConfig,
    build_segments,
    is_meaningful,
)
from klatrebot_v2.memory.tags import normalize_tags
from klatrebot_v2.settings import get_settings


MEMORY_ITEM_TYPES = {"decision", "plan", "preference", "fact", "opinion", "open_question", "lore"}
CONFIDENCE_VALUES = {"low", "medium", "high"}
IMPORTANCE_VALUES = {"low", "normal", "high"}


class SegmentSummary(BaseModel):
    topic_title: str = ""
    summary: str = ""
    importance: str = "normal"
    skip_reason: str | None = None
    tags: list[Any] = Field(default_factory=list)
    memory_items: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class CompilerConfig:
    name: str
    from_time: datetime | None = None
    to_time: datetime | None = None
    channel_ids: list[int] | None = None
    compiler_model: str | None = None
    source_db_label: str | None = None
    concurrency: int = 4
    segment: SegmentConfig = field(default_factory=SegmentConfig)


Summarizer = Callable[[SegmentCandidate], Awaitable[SegmentSummary]]
ProgressCallback = Callable[[str], None]


async def compile_run(
    conn: aiosqlite.Connection,
    *,
    config: CompilerConfig,
    summarizer: Summarizer | None = None,
    progress: ProgressCallback | None = None,
) -> int:
    """Compile a time slice into summaries and memory items."""
    model = config.compiler_model or get_settings().memory_compiler_model
    run_id = await store.create_compiler_run(
        conn,
        name=config.name,
        compiler_model=model,
        from_time=config.from_time,
        to_time=config.to_time,
        channel_ids=config.channel_ids,
        config={"segment": asdict(config.segment)},
        source_db_label=config.source_db_label,
    )
    summarizer = summarizer or (lambda segment: summarize_segment_with_llm(segment, model=model))
    try:
        messages = await store.load_messages(
            conn,
            from_time=config.from_time,
            to_time=config.to_time,
            channel_ids=config.channel_ids,
        )
        _progress(progress, f"Loaded {len(messages)} messages.")
        segments = build_segments(messages, config.segment)
        _progress(progress, f"Built {len(segments)} segments.")
        meaningful_indexes = [
            index for index, segment in enumerate(segments) if is_meaningful(segment, config.segment)
        ]
        summaries = await _summarize_segments(
            segments,
            meaningful_indexes=meaningful_indexes,
            summarizer=summarizer,
            concurrency=config.concurrency,
            progress=progress,
        )
        for index, segment in enumerate(segments):
            if not is_meaningful(segment, config.segment):
                await store.insert_segment(
                    conn,
                    compiler_run_id=run_id,
                    segment=segment,
                    topic_title="",
                    summary="",
                    importance="low",
                    tags=[],
                    status="skipped",
                    skip_reason="Segmentet var for kort til holdbar hukommelse.",
                )
                continue

            summary = _normalize_summary(summaries[index], segment)
            status = "skipped" if summary.skip_reason else "summarized"
            segment_id = await store.insert_segment(
                conn,
                compiler_run_id=run_id,
                segment=segment,
                topic_title=summary.topic_title,
                summary=summary.summary,
                importance=summary.importance,
                tags=summary.tags,
                status=status,
                skip_reason=summary.skip_reason,
            )
            if status == "summarized":
                for item in summary.memory_items:
                    await store.insert_memory_item(
                        conn,
                        compiler_run_id=run_id,
                        segment_id=segment_id,
                        item=item,
                        segment=segment,
                    )
        await store.complete_compiler_run(conn, run_id)
        _progress(progress, f"Completed memory run '{config.name}'.")
    except Exception as exc:
        await store.fail_compiler_run(conn, run_id, str(exc))
        raise
    return run_id


async def _summarize_segments(
    segments: list[SegmentCandidate],
    *,
    meaningful_indexes: list[int],
    summarizer: Summarizer,
    concurrency: int,
    progress: ProgressCallback | None,
) -> dict[int, SegmentSummary]:
    total = len(meaningful_indexes)
    if total == 0:
        return {}
    concurrency = max(1, concurrency)
    _progress(progress, f"Summarizing {total} meaningful segments with concurrency {concurrency}.")
    semaphore = asyncio.Semaphore(concurrency)
    completed = 0

    async def run_one(index: int) -> tuple[int, SegmentSummary]:
        nonlocal completed
        async with semaphore:
            summary = await summarizer(segments[index])
        completed += 1
        if completed == 1 or completed == total or completed % 10 == 0:
            _progress(progress, f"Summarized {completed}/{total} meaningful segments.")
        return index, summary

    pairs = await asyncio.gather(*(run_one(index) for index in meaningful_indexes))
    return dict(pairs)


async def summarize_segment_with_llm(segment: SegmentCandidate, *, model: str) -> SegmentSummary:
    """Summarize one segment through the configured OpenAI client."""
    client = get_client()
    resp = await client.responses.create(
        model=model,
        input=_build_summary_prompt(segment),
        text={"format": {"type": "json_object"}, "verbosity": "low"},
    )
    return SegmentSummary.model_validate_json(resp.output_text or "{}")


def _build_summary_prompt(segment: SegmentCandidate) -> str:
    body = "\n".join(
        f"[{m.discord_message_id}] {m.timestamp_utc.isoformat()} {m.user_display_name}: {m.content}"
        for m in segment.messages
        if not m.is_bot
    )
    schema = {
        "topic_title": "kort dansk titel",
        "summary": "dansk opsummering af samtalen",
        "importance": "low|normal|high",
        "skip_reason": None,
        "memory_items": [
            {
                "type": "decision|plan|preference|fact|opinion|open_question|lore",
                "subject": "person, emne eller gruppe",
                "text": "dansk holdbar hukommelse",
                "confidence": "low|medium|high",
                "importance": "low|normal|high",
                "tags": ["dansk tag", "kjugekull", "udendørs klatring"],
                "speaker_ids": [123],
                "source_message_ids": [456],
            }
        ],
    }
    return (
        "Du komprimerer Discord-chat for KlatreBot til holdbar dansk hukommelse.\n"
        "Bevar praktiske planer, beslutninger, præferencer, fakta, åbne spørgsmål og vigtig social/lore-kontekst. "
        "Spring kun over hvis segmentet er klart tomt, usammenhængende eller uden brugbar hukommelse. "
        "Lav tags som rene danske hukommelsesnøgler, også når chatten bruger engelsk/blandet sprog. "
        "Tags skal være lowercase, korte, konkrete begreber i ental hvor naturligt, fx kjugekull, tobi, udendørs klatring, klatretur. "
        "Undgå sætninger, datoer som tags, emojis og jokes medmindre joken/lore er selve emnet. "
        "Brug kun de givne beskeder som grundlag, og referer til message ids i source_message_ids.\n\n"
        f"Returner gyldig JSON med denne form:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"BESKEDER:\n{body}"
    )


def _normalize_summary(summary: SegmentSummary, segment: SegmentCandidate) -> SegmentSummary:
    importance = summary.importance if summary.importance in IMPORTANCE_VALUES else "normal"
    source_ids = {m.discord_message_id for m in segment.messages}
    participant_ids = set(segment.participant_ids)
    segment_tags = normalize_tags(summary.tags)
    items = []
    for item in summary.memory_items:
        item_type = item.get("type")
        text = str(item.get("text", "")).strip()
        if item_type not in MEMORY_ITEM_TYPES or not text:
            continue
        normalized_sources = _valid_ids(item.get("source_message_ids", []), source_ids)
        if not normalized_sources:
            normalized_sources = [m.discord_message_id for m in segment.human_messages[:3]]
        normalized_speakers = _valid_ids(item.get("speaker_ids", []), participant_ids)
        items.append(
            {
                "type": item_type,
                "subject": str(item.get("subject", "")).strip() or "fællesskabet",
                "text": text,
                "confidence": item.get("confidence") if item.get("confidence") in CONFIDENCE_VALUES else "medium",
                "importance": item.get("importance") if item.get("importance") in IMPORTANCE_VALUES else "normal",
                "tags": normalize_tags(item.get("tags", [])),
                "speaker_ids": normalized_speakers,
                "source_message_ids": normalized_sources,
            }
        )
    return SegmentSummary(
        topic_title=summary.topic_title.strip(),
        summary=summary.summary.strip(),
        importance=importance,
        skip_reason=summary.skip_reason,
        tags=segment_tags,
        memory_items=items,
    )


def _valid_ids(raw_ids: list[Any], allowed_ids: set[int]) -> list[int]:
    out: list[int] = []
    for raw_id in raw_ids:
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            continue
        if parsed in allowed_ids:
            out.append(parsed)
    return out


def _progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
