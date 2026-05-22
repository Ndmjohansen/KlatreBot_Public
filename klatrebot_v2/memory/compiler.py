"""Memory compiler pipeline."""
import asyncio
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
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


@dataclass
class TokenUsage:
    responses_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CompileStats:
    segments_existing: int = 0
    segments_missing: int = 0
    segments_retried: int = 0
    segments_summarized: int = 0
    segments_skipped: int = 0
    segments_failed: int = 0
    daily_ambient_completed: int = 0
    daily_ambient_failed: int = 0
    weekly_rollups_completed: int = 0
    weekly_rollups_failed: int = 0
    monthly_rollups_completed: int = 0
    monthly_rollups_failed: int = 0


class RollupSummary(BaseModel):
    title: str = ""
    summary: str = ""
    key_items: list[Any] = Field(default_factory=list)
    importance: str = "normal"
    tags: list[Any] = Field(default_factory=list)


@dataclass(frozen=True)
class RollupInput:
    period_type: str
    period_start: datetime
    period_end: datetime
    channel_id: int
    sources: list[dict[str, Any]]


@dataclass(frozen=True)
class CompilerConfig:
    name: str
    from_time: datetime | None = None
    to_time: datetime | None = None
    channel_ids: list[int] | None = None
    compiler_model: str | None = None
    source_db_label: str | None = None
    concurrency: int = 4
    resume: bool = False
    rebuild: bool = False
    segment: SegmentConfig = field(default_factory=SegmentConfig)


Summarizer = Callable[[SegmentCandidate], Awaitable[SegmentSummary]]
RollupSummarizer = Callable[[RollupInput], Awaitable[RollupSummary]]
ProgressCallback = Callable[[str], None]


async def compile_run(
    conn: aiosqlite.Connection,
    *,
    config: CompilerConfig,
    summarizer: Summarizer | None = None,
    rollup_summarizer: RollupSummarizer | None = None,
    progress: ProgressCallback | None = None,
) -> int:
    """Compile a time slice into summaries and memory items."""
    model = config.compiler_model or get_settings().memory_compiler_model
    segment_config = asdict(config.segment)
    config_hash = _stable_hash(segment_config)
    existing = await store.get_compiler_run_by_name(conn, config.name)
    if existing and not config.rebuild:
        _validate_config_hash(existing, config_hash)
    create_run = store.create_compiler_run if config.rebuild else store.resume_or_create_compiler_run
    run_id = await create_run(
        conn,
        name=config.name,
        compiler_model=model,
        from_time=config.from_time,
        to_time=config.to_time,
        channel_ids=config.channel_ids,
        config={"segment": segment_config},
        config_hash=config_hash,
        source_db_label=config.source_db_label,
    )
    usage = TokenUsage()
    stats = CompileStats()
    summarizer = summarizer or (lambda segment: summarize_segment_with_llm(segment, model=model, usage=usage))
    rollup_summarizer = rollup_summarizer or (
        lambda rollup: summarize_rollup_with_llm(rollup, model=model, usage=usage)
    )
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
        db_lock = asyncio.Lock()
        pending = []
        for index, segment in enumerate(segments):
            segment_key = _segment_key(segment)
            existing_segment = await store.get_segment_by_key(conn, run_id=run_id, segment_key=segment_key)
            if existing_segment and existing_segment["status"] in {"summarized", "skipped"}:
                stats.segments_existing += 1
                continue
            overlapping = await store.overlapping_segments_for_messages(
                conn,
                run_id=run_id,
                channel_id=segment.channel_id,
                message_ids=[m.discord_message_id for m in segment.messages],
            )
            existing_segment_id = int(existing_segment["id"]) if existing_segment else None
            for overlap in overlapping:
                overlap_id = int(overlap["id"])
                if overlap_id == existing_segment_id:
                    continue
                await store.delete_segment_tree(conn, overlap_id)
            retry_count = 0
            if existing_segment:
                retry_count = int(existing_segment.get("retry_count") or 0) + 1
                stats.segments_retried += 1
                await store.delete_segment_tree(conn, int(existing_segment["id"]))
            else:
                stats.segments_missing += 1
            if not is_meaningful(segment, config.segment):
                await _persist_skipped_segment(
                    conn,
                    run_id=run_id,
                    segment=segment,
                    segment_key=segment_key,
                    retry_count=retry_count,
                )
                stats.segments_skipped += 1
                continue
            pending.append((index, segment_key, retry_count))
        _progress(
            progress,
            "Segments: "
            f"existing={stats.segments_existing}, missing={stats.segments_missing}, "
            f"retry={stats.segments_retried}, pending={len(pending)}.",
        )
        await _summarize_segments(
            conn,
            run_id,
            segments,
            pending=pending,
            summarizer=summarizer,
            concurrency=config.concurrency,
            progress=progress,
            db_lock=db_lock,
            stats=stats,
        )
        await _build_daily_ambient_memory(
            conn,
            run_id=run_id,
            ambient_summarizer=rollup_summarizer,
            progress=progress,
            stats=stats,
        )
        await _build_rollups(
            conn,
            run_id=run_id,
            rollup_summarizer=rollup_summarizer,
            progress=progress,
            stats=stats,
        )
        await store.complete_compiler_run(conn, run_id)
        _report_counts(progress, stats)
        _report_usage(progress, usage)
        _progress(progress, f"Completed memory run '{config.name}'.")
    except Exception as exc:
        await store.fail_compiler_run(conn, run_id, str(exc))
        raise
    return run_id


async def _summarize_segments(
    conn: aiosqlite.Connection,
    run_id: int,
    segments: list[SegmentCandidate],
    *,
    pending: list[tuple[int, str, int]],
    summarizer: Summarizer,
    concurrency: int,
    progress: ProgressCallback | None,
    db_lock: asyncio.Lock,
    stats: CompileStats,
) -> None:
    total = len(pending)
    if total == 0:
        return
    concurrency = max(1, concurrency)
    _progress(progress, f"Summarizing {total} meaningful segments with concurrency {concurrency}.")
    semaphore = asyncio.Semaphore(concurrency)
    completed = 0

    async def run_one(index: int, segment_key: str, retry_count: int) -> None:
        nonlocal completed
        segment = segments[index]
        async with semaphore:
            try:
                summary = await summarizer(segment)
            except Exception as exc:
                async with db_lock:
                    await _persist_failed_segment(
                        conn,
                        run_id=run_id,
                        segment=segment,
                        segment_key=segment_key,
                        error=str(exc),
                        retry_count=max(1, retry_count),
                    )
                    stats.segments_failed += 1
                completed += 1
                if completed == 1 or completed == total or completed % 10 == 0:
                    _progress(progress, f"Summarized {completed}/{total} meaningful segments.")
                return
        async with db_lock:
            await _persist_summary(
                conn,
                run_id=run_id,
                segment=segment,
                segment_key=segment_key,
                summary=summary,
                retry_count=retry_count,
            )
            stats.segments_summarized += 1
        completed += 1
        if completed == 1 or completed == total or completed % 10 == 0:
            _progress(progress, f"Summarized {completed}/{total} meaningful segments.")

    await asyncio.gather(*(run_one(index, segment_key, retry_count) for index, segment_key, retry_count in pending))


async def _persist_skipped_segment(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    segment: SegmentCandidate,
    segment_key: str,
    retry_count: int,
) -> None:
    await store.insert_segment(
        conn,
        compiler_run_id=run_id,
        segment=segment,
        segment_key=segment_key,
        topic_title="",
        summary="",
        importance="low",
        tags=[],
        status="skipped",
        skip_reason="Segmentet var for kort til holdbar hukommelse.",
        retry_count=retry_count,
    )


async def _persist_failed_segment(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    segment: SegmentCandidate,
    segment_key: str,
    error: str,
    retry_count: int,
) -> None:
    await store.insert_segment(
        conn,
        compiler_run_id=run_id,
        segment=segment,
        segment_key=segment_key,
        topic_title="",
        summary="",
        importance="low",
        tags=[],
        status="failed",
        skip_reason=None,
        error=error,
        retry_count=retry_count,
    )


async def _persist_summary(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    segment: SegmentCandidate,
    segment_key: str,
    summary: SegmentSummary,
    retry_count: int,
) -> None:
    summary = _normalize_summary(summary, segment)
    status = "skipped" if summary.skip_reason else "summarized"
    segment_id = await store.insert_segment(
        conn,
        compiler_run_id=run_id,
        segment=segment,
        segment_key=segment_key,
        topic_title=summary.topic_title,
        summary=summary.summary,
        importance=summary.importance,
        tags=summary.tags,
        status=status,
        skip_reason=summary.skip_reason,
        retry_count=retry_count,
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


async def _build_rollups(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    rollup_summarizer: RollupSummarizer,
    progress: ProgressCallback | None,
    stats: CompileStats,
) -> None:
    segments = await store.completed_segments_for_rollups(conn, run_id)
    weekly_groups: dict[tuple[int, datetime, datetime], list[dict[str, Any]]] = {}
    for segment in segments:
        start = datetime.fromisoformat(segment["start_time_utc"])
        period_start, period_end = _week_bounds(start)
        weekly_groups.setdefault((int(segment["channel_id"]), period_start, period_end), []).append(segment)
    if weekly_groups:
        _progress(progress, f"Building {len(weekly_groups)} weekly rollups.")
    for (channel_id, period_start, period_end), group in sorted(weekly_groups.items(), key=lambda entry: (entry[0][1], entry[0][0])):
        segment_ids = [int(row["id"]) for row in group]
        items = await store.memory_items_for_segments(conn, segment_ids)
        sources = [_segment_source(row) for row in group] + [_memory_item_source(row) for row in items]
        await _build_one_rollup(
            conn,
            run_id=run_id,
            channel_id=channel_id,
            period_type="week",
            period_start=period_start,
            period_end=period_end,
            sources=sources,
            source_segments=segment_ids,
            source_memory_items=[int(item["id"]) for item in items],
            source_rollups=[],
            rollup_summarizer=rollup_summarizer,
            stats=stats,
        )

    weekly_rollups = await store.completed_rollups_for_months(conn, run_id)
    monthly_groups: dict[tuple[int, datetime, datetime], list[dict[str, Any]]] = {}
    for rollup in weekly_rollups:
        start = datetime.fromisoformat(rollup["period_start_utc"])
        period_start, period_end = _month_bounds(start)
        monthly_groups.setdefault((int(rollup["channel_id"]), period_start, period_end), []).append(rollup)
    if monthly_groups:
        _progress(progress, f"Building {len(monthly_groups)} monthly rollups.")
    for (channel_id, period_start, period_end), group in sorted(monthly_groups.items(), key=lambda entry: (entry[0][1], entry[0][0])):
        sources = [_rollup_source(row) for row in group]
        await _build_one_rollup(
            conn,
            run_id=run_id,
            channel_id=channel_id,
            period_type="month",
            period_start=period_start,
            period_end=period_end,
            sources=sources,
            source_segments=[],
            source_memory_items=[],
            source_rollups=[int(row["id"]) for row in group],
            rollup_summarizer=rollup_summarizer,
            stats=stats,
        )


async def _build_daily_ambient_memory(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    ambient_summarizer: RollupSummarizer,
    progress: ProgressCallback | None,
    stats: CompileStats,
) -> None:
    skipped_segments = await store.skipped_segments_for_daily_ambient(conn, run_id)
    groups: dict[tuple[int, datetime, datetime], list[dict[str, Any]]] = {}
    for segment in skipped_segments:
        start = datetime.fromisoformat(segment["start_time_utc"])
        day_start, day_end = _day_bounds(start)
        groups.setdefault((int(segment["channel_id"]), day_start, day_end), []).append(segment)
    if groups:
        _progress(progress, f"Building {len(groups)} daily ambient memories.")
    for (channel_id, day_start, day_end), group in sorted(groups.items(), key=lambda entry: (entry[0][1], entry[0][0])):
        await _build_one_daily_ambient_memory(
            conn,
            run_id=run_id,
            channel_id=channel_id,
            day_start=day_start,
            day_end=day_end,
            segments=group,
            ambient_summarizer=ambient_summarizer,
            stats=stats,
        )


async def _build_one_daily_ambient_memory(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    day_start: datetime,
    day_end: datetime,
    segments: list[dict[str, Any]],
    ambient_summarizer: RollupSummarizer,
    stats: CompileStats,
) -> None:
    sources = [_skipped_segment_source(row) for row in segments]
    fingerprint = _stable_hash(
        {
            "sources": [
                {
                    "kind": source["kind"],
                    "id": source["id"],
                    "summary": source.get("summary", ""),
                    "message_count": source.get("message_count", 0),
                }
                for source in sources
            ]
        }
    )
    existing = await store.get_daily_ambient_by_day(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        day_start_utc=day_start.isoformat(),
        day_end_utc=day_end.isoformat(),
    )
    if existing and existing["status"] == "completed" and existing["source_fingerprint"] == fingerprint:
        return
    ambient_input = RollupInput(
        period_type="daily_ambient",
        period_start=day_start,
        period_end=day_end,
        channel_id=channel_id,
        sources=sources,
    )
    source_segment_ids = [int(segment["id"]) for segment in segments]
    try:
        summary = _normalize_rollup_summary(await ambient_summarizer(ambient_input))
    except Exception as exc:
        await store.upsert_daily_ambient_memory(
            conn,
            run_id=run_id,
            channel_id=channel_id,
            day_start_utc=day_start.isoformat(),
            day_end_utc=day_end.isoformat(),
            title="",
            summary="",
            key_items=[],
            tags=[],
            importance="low",
            status="failed",
            error=str(exc),
            source_fingerprint=fingerprint,
            source_segments=source_segment_ids,
        )
        stats.daily_ambient_failed += 1
        return
    await store.upsert_daily_ambient_memory(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        day_start_utc=day_start.isoformat(),
        day_end_utc=day_end.isoformat(),
        title=summary.title,
        summary=summary.summary,
        key_items=summary.key_items,
        tags=summary.tags,
        importance="low",
        status="completed",
        error=None,
        source_fingerprint=fingerprint,
        source_segments=source_segment_ids,
    )
    stats.daily_ambient_completed += 1


async def _build_one_rollup(
    conn: aiosqlite.Connection,
    *,
    run_id: int,
    channel_id: int,
    period_type: str,
    period_start: datetime,
    period_end: datetime,
    sources: list[dict[str, Any]],
    source_segments: list[int],
    source_memory_items: list[int],
    source_rollups: list[int],
    rollup_summarizer: RollupSummarizer,
    stats: CompileStats,
) -> None:
    fingerprint = _stable_hash(
        {
            "sources": [
                {
                    "kind": source["kind"],
                    "id": source["id"],
                    "summary": source.get("summary", ""),
                    "text": source.get("text", ""),
                }
                for source in sources
            ]
        }
    )
    existing = await store.get_rollup_by_period(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        period_type=period_type,
        period_start_utc=period_start.isoformat(),
        period_end_utc=period_end.isoformat(),
    )
    if existing and existing["status"] == "completed" and existing["source_fingerprint"] == fingerprint:
        return
    rollup_input = RollupInput(
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        channel_id=channel_id,
        sources=sources,
    )
    try:
        summary = _normalize_rollup_summary(await rollup_summarizer(rollup_input))
    except Exception as exc:
        await store.upsert_rollup(
            conn,
            run_id=run_id,
            channel_id=channel_id,
            period_type=period_type,
            period_start_utc=period_start.isoformat(),
            period_end_utc=period_end.isoformat(),
            title="",
            summary="",
            key_items=[],
            tags=[],
            importance="low",
            status="failed",
            error=str(exc),
            source_fingerprint=fingerprint,
            source_segments=source_segments,
            source_memory_items=source_memory_items,
            source_rollups=source_rollups,
        )
        if period_type == "week":
            stats.weekly_rollups_failed += 1
        else:
            stats.monthly_rollups_failed += 1
        return
    await store.upsert_rollup(
        conn,
        run_id=run_id,
        channel_id=channel_id,
        period_type=period_type,
        period_start_utc=period_start.isoformat(),
        period_end_utc=period_end.isoformat(),
        title=summary.title,
        summary=summary.summary,
        key_items=summary.key_items,
        tags=summary.tags,
        importance=summary.importance,
        status="completed",
        error=None,
        source_fingerprint=fingerprint,
        source_segments=source_segments,
        source_memory_items=source_memory_items,
        source_rollups=source_rollups,
    )
    if period_type == "week":
        stats.weekly_rollups_completed += 1
    else:
        stats.monthly_rollups_completed += 1


async def summarize_segment_with_llm(
    segment: SegmentCandidate,
    *,
    model: str,
    usage: TokenUsage | None = None,
) -> SegmentSummary:
    """Summarize one segment through the configured OpenAI client."""
    client = get_client()
    resp = await client.responses.create(
        model=model,
        input=_build_summary_prompt(segment),
        text={"format": {"type": "json_object"}, "verbosity": "low"},
    )
    if usage is not None:
        _add_usage(usage, resp)
    return SegmentSummary.model_validate_json(resp.output_text or "{}")


async def summarize_rollup_with_llm(
    rollup: RollupInput,
    *,
    model: str,
    usage: TokenUsage | None = None,
) -> RollupSummary:
    client = get_client()
    resp = await client.responses.create(
        model=model,
        input=_build_rollup_prompt(rollup),
        text={"format": {"type": "json_object"}, "verbosity": "low"},
    )
    if usage is not None:
        _add_usage(usage, resp)
    return RollupSummary.model_validate_json(resp.output_text or "{}")


def _build_rollup_prompt(rollup: RollupInput) -> str:
    if rollup.period_type == "daily_ambient":
        return _build_daily_ambient_prompt(rollup)
    schema = {
        "title": "kort dansk titel",
        "summary": "komprimeret dansk opsummering med eksplicit periode og vigtige konkurrerende minder holdt adskilt",
        "key_items": ["kort dansk punkt med dato/status når relevant"],
        "importance": "low|normal|high",
        "tags": ["dansk tag", "pelle", "julefrokost"],
    }
    return (
        "Du laver en højere-niveau dansk hukommelses-rollup for KlatreBot.\n"
        f"Periode: {rollup.period_type} {rollup.period_start.isoformat()} til {rollup.period_end.isoformat()}.\n"
        "Komprimer hårdt, men bevar tidslig orden, vigtige personer, steder, planer, beslutninger, præferencer og social lore. "
        "Sammenbland ikke lignende minder: nævn konkurrerende datoer/perioder separat. "
        "Skriv tydeligt planned/proposed/confirmed/uncertain på dansk når evidensen er uklar. "
        "Output skal være gyldig JSON og på dansk.\n\n"
        f"Returner denne form:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"KILDER:\n{json.dumps(rollup.sources, ensure_ascii=False)}"
    )


def _build_daily_ambient_prompt(rollup: RollupInput) -> str:
    schema = {
        "title": "kort dansk titel",
        "summary": "kort dansk opsummering af løs daglig chat",
        "key_items": ["kort dansk punkt med usikkerhed/status når relevant"],
        "importance": "low",
        "tags": ["dansk tag", "peak", "social lore"],
    }
    return (
        "Du laver daglig ambient hukommelse for KlatreBot ud fra små/skippede chatstumper.\n"
        f"Dag: {rollup.period_start.isoformat()} til {rollup.period_end.isoformat()}.\n"
        "Dette er lav-prioritets baggrundshukommelse, ikke en egentlig samtaleopsummering. "
        "Bevar løs social tekstur, små links/emner, jokes/lore, lette præferencer og åbne løkker, "
        "men gør ikke uklare bemærkninger til sikre fakta. "
        "Skriv tydeligt hvis noget kun er nævnt løst eller usikkert. "
        "Output skal være gyldig JSON og på dansk.\n\n"
        f"Returner denne form:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"KILDER:\n{json.dumps(rollup.sources, ensure_ascii=False)}"
    )


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


def _valid_ids(raw_ids: list[Any] | None, allowed_ids: set[int]) -> list[int]:
    out: list[int] = []
    if not isinstance(raw_ids, list):
        return out
    for raw_id in raw_ids:
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            continue
        if parsed in allowed_ids:
            out.append(parsed)
    return out


def _normalize_rollup_summary(summary: RollupSummary) -> RollupSummary:
    importance = summary.importance if summary.importance in IMPORTANCE_VALUES else "normal"
    key_items = [str(item).strip() for item in summary.key_items if str(item).strip()]
    return RollupSummary(
        title=summary.title.strip(),
        summary=summary.summary.strip(),
        key_items=key_items,
        importance=importance,
        tags=normalize_tags(summary.tags),
    )


def _segment_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "segment",
        "id": int(row["id"]),
        "time_range": f"{row['start_time_utc']} - {row['end_time_utc']}",
        "title": row["topic_title"],
        "summary": row["summary"],
        "importance": row["importance"],
    }


def _skipped_segment_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "skipped_segment",
        "id": int(row["id"]),
        "time_range": f"{row['start_time_utc']} - {row['end_time_utc']}",
        "message_count": int(row["message_count"]),
        "human_message_count": int(row["human_message_count"]),
        "total_chars": int(row["total_chars"]),
        "participants": json.loads(row.get("participant_ids_json") or "[]"),
        "skip_reason": row.get("skip_reason"),
    }


def _memory_item_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "memory_item",
        "id": int(row["id"]),
        "time_range": f"{row.get('created_at_source')} - {row.get('last_seen_at_source')}",
        "type": row["type"],
        "subject": row["subject"],
        "text": row["text"],
        "confidence": row["confidence"],
        "importance": row["importance"],
    }


def _rollup_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "rollup",
        "id": int(row["id"]),
        "period_type": row["period_type"],
        "time_range": f"{row['period_start_utc']} - {row['period_end_utc']}",
        "title": row["title"],
        "summary": row["summary"],
        "key_items": json.loads(row.get("key_items_json") or "[]"),
        "importance": row["importance"],
        "source_fingerprint": row["source_fingerprint"],
    }


def _segment_key(segment: SegmentCandidate) -> str:
    return _stable_hash([message.discord_message_id for message in segment.messages])


def _week_bounds(value: datetime) -> tuple[datetime, datetime]:
    start_date = value.date() - timedelta(days=value.weekday())
    start = datetime.combine(start_date, time.min, tzinfo=value.tzinfo)
    return start, start + timedelta(days=7)


def _month_bounds(value: datetime) -> tuple[datetime, datetime]:
    start = datetime(value.year, value.month, 1, tzinfo=value.tzinfo)
    if value.month == 12:
        end = datetime(value.year + 1, 1, 1, tzinfo=value.tzinfo)
    else:
        end = datetime(value.year, value.month + 1, 1, tzinfo=value.tzinfo)
    return start, end


def _day_bounds(value: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(value.date(), time.min, tzinfo=value.tzinfo)
    return start, start + timedelta(days=1)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_config_hash(existing: dict[str, Any], expected_hash: str) -> None:
    found = existing.get("config_hash")
    if found is None:
        try:
            found = _stable_hash(json.loads(existing.get("config_json") or "{}").get("segment", {}))
        except (TypeError, json.JSONDecodeError):
            found = expected_hash
    if found != expected_hash:
        raise ValueError("Segment config changed for existing memory run; use --rebuild to rebuild.")


def _progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _report_usage(progress: ProgressCallback | None, usage: TokenUsage) -> None:
    _progress(progress, "[compile usage]")
    _progress(progress, f"responses_calls: {usage.responses_calls}")
    _progress(progress, f"input_tokens: {usage.input_tokens}")
    _progress(progress, f"output_tokens: {usage.output_tokens}")
    _progress(progress, f"total_tokens: {usage.total_tokens}")


def _report_counts(progress: ProgressCallback | None, stats: CompileStats) -> None:
    _progress(progress, "[compile counts]")
    _progress(
        progress,
        "segments: "
        f"existing={stats.segments_existing}, missing={stats.segments_missing}, "
        f"retry={stats.segments_retried}, summarized={stats.segments_summarized}, "
        f"skipped={stats.segments_skipped}, failed={stats.segments_failed}",
    )
    _progress(
        progress,
        "rollups: "
        f"daily_ambient_completed={stats.daily_ambient_completed}, daily_ambient_failed={stats.daily_ambient_failed}, "
        f"weekly_completed={stats.weekly_rollups_completed}, weekly_failed={stats.weekly_rollups_failed}, "
        f"monthly_completed={stats.monthly_rollups_completed}, monthly_failed={stats.monthly_rollups_failed}",
    )


def _add_usage(total: TokenUsage, resp) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    total.responses_calls += 1
    total.input_tokens += int(_usage_value(usage, "input_tokens") or 0)
    total.output_tokens += int(_usage_value(usage, "output_tokens") or 0)
    total.total_tokens += int(_usage_value(usage, "total_tokens") or 0)


def _usage_value(usage, key: str):
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)
