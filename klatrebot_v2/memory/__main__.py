"""Offline memory compiler and chat CLI."""
import argparse
import asyncio
import json
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from klatrebot_v2.db import connection, migrations, user_aliases
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.memory.compiler import CompilerConfig, compile_run
from klatrebot_v2.memory.reflections import (
    DEFAULT_REFLECTION_MODEL,
    DEFAULT_REFLECTION_NAME,
    ReflectionUsage,
    export_markdown_with_metadata,
    generate_reflection,
)
from klatrebot_v2.memory.segmentation import SegmentConfig
from klatrebot_v2.memory import store
from klatrebot_v2.memory.store import get_compiler_run_by_name
from klatrebot_v2.memory.tools import MEMORY_TOOL_DEFS, execute_memory_tool
from klatrebot_v2.settings import get_settings


async def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "compile":
        return await _compile(args)
    if args.command == "compile-rolling":
        return await _compile_rolling()
    if args.command == "reflect":
        return await _reflect(args)
    if args.command == "chat":
        return await _chat(args)
    parser.print_help()
    return 2


async def chat_once(
    conn,
    *,
    run_id: int,
    question: str,
    recent_context: list[str] | None = None,
    show_memory: bool = False,
    show_sources: bool = False,
    show_usage: bool = False,
    show_agent: bool = False,
    channel_id: int | None = None,
    recent_limit: int = 0,
) -> str:
    s = get_settings()
    effective_channel_id = channel_id or s.discord_main_channel_id
    alias_map = await user_aliases.format_alias_prompt_map(conn)
    client = get_client()
    prompt = (
        f"{load_soul()}\n\n"
        "Du kører i offline memory-test. Brug memory tools ved historiske spørgsmål. "
        "Vis ikke kilder medmindre brugeren spørger. "
        "Når et spørgsmål nævner personer, brug people_names i memory tool-kaldet.\n\n"
        f"CHANNEL_ID: {effective_channel_id}\n"
        f"KNOWN_USER_ALIASES:\n{alias_map}\n"
        f"RECENT_LIMIT: {recent_limit}\n"
        f"RECENT CLI CHAT:\n{_format_recent_context(recent_context)}\n\n"
        f"QUESTION: {question}"
    )
    resp = await client.responses.create(
        model=s.model,
        input=prompt,
        tools=MEMORY_TOOL_DEFS,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    usage_total = _empty_usage()
    _add_usage(usage_total, resp)
    response_calls = 1
    for _ in range(4):
        calls = _extract_function_calls(resp)
        call_traces = []
        tool_outputs = []
        debug_outputs = []
        for call in calls:
            raw_arguments = dict(call["arguments"])
            arguments = dict(call["arguments"])
            if call["name"] == "recall_community_memory" and "channel_id" not in arguments:
                arguments["channel_id"] = effective_channel_id
            call_traces.append(
                {
                    "name": call["name"],
                    "call_id": call["call_id"],
                    "raw_arguments": raw_arguments,
                    "effective_arguments": arguments,
                }
            )
            output = await execute_memory_tool(
                conn,
                run_id=run_id,
                name=call["name"],
                arguments=arguments,
            )
            debug_outputs.append((call["name"], output))
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": output,
                }
            )
        if not tool_outputs:
            if show_agent:
                _print_agent_response(response_calls, resp, call_traces)
            break
        if show_agent:
            _print_agent_response(response_calls, resp, call_traces)
        if show_memory:
            for name, output in debug_outputs:
                print(f"\n[{name}]\n{_pretty_json(output)}")
        resp = await client.responses.create(
            model=s.model,
            input=tool_outputs,
            tools=MEMORY_TOOL_DEFS,
            previous_response_id=getattr(resp, "id"),
            reasoning={"effort": "medium"},
            text={"verbosity": "medium"},
        )
        _add_usage(usage_total, resp)
        response_calls += 1
    if show_sources:
        print("[sources requested through tool when model asks]")
    if show_usage:
        print(
            "\n[usage]\n"
            f"responses_calls: {response_calls}\n"
            f"input_tokens: {usage_total['input_tokens']}\n"
            f"output_tokens: {usage_total['output_tokens']}\n"
            f"total_tokens: {usage_total['total_tokens']}"
        )
    return resp.output_text or ""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m klatrebot_v2.memory")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--db", required=True)
    compile_parser.add_argument("--from", dest="from_time")
    compile_parser.add_argument("--to", dest="to_time")
    compile_parser.add_argument("--channel-id", action="append", type=int, default=[])
    compile_parser.add_argument("--name", required=True)
    compile_parser.add_argument("--model")
    compile_parser.add_argument("--concurrency", type=int, default=4)
    compile_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete and rebuild an existing memory run instead of updating it",
    )

    sub.add_parser("compile-rolling")

    reflect_parser = sub.add_parser("reflect")
    reflect_parser.add_argument("--db", required=True)
    reflect_parser.add_argument("--run", required=True)
    reflect_parser.add_argument("--from", dest="from_time", required=True)
    reflect_parser.add_argument("--to", dest="to_time", required=True)
    reflect_parser.add_argument("--name", default=DEFAULT_REFLECTION_NAME)
    reflect_parser.add_argument("--model")
    reflect_parser.add_argument("--output")
    reflect_parser.add_argument("--chunk-days", type=int, default=7)
    reflect_parser.add_argument(
        "--rebuild",
        "--revuild",
        action="store_true",
        help="Delete existing reflection documents for this run/name before generating.",
    )

    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--db", required=True)
    chat_parser.add_argument("--run", required=True)
    chat_parser.add_argument("--show-memory", action="store_true")
    chat_parser.add_argument("--show-sources", action="store_true")
    chat_parser.add_argument("--show-usage", action="store_true")
    chat_parser.add_argument("--show-agent", action="store_true")
    chat_parser.add_argument("--channel-id", type=int)
    chat_parser.add_argument("--recent-limit", type=int, default=8)
    return parser


async def _compile(args) -> int:
    conn = await connection.open(args.db)
    try:
        await migrations.run(conn)
        await user_aliases.sync_config_aliases(conn, get_settings().user_aliases_config_path)
        run_id = await compile_run(
            conn,
            config=CompilerConfig(
                name=args.name,
                from_time=_parse_dt(args.from_time),
                to_time=_parse_dt(args.to_time),
                channel_ids=args.channel_id or None,
                compiler_model=args.model,
                source_db_label=args.db,
                concurrency=args.concurrency,
                rebuild=args.rebuild,
                segment=_segment_config_from_settings(),
            ),
            progress=lambda message: print(message, flush=True),
        )
        print(f"compiled run {run_id}: {args.name}")
        return 0
    finally:
        await connection.close(conn)


async def _compile_rolling() -> int:
    s = get_settings()
    if not s.memory_rolling_enabled:
        print("Rolling memory disabled.")
        return 0

    conn = await connection.open(s.db_path)
    run_name = s.memory_rolling_run_name
    lock_owner = f"{socket.gethostname()}:{uuid.uuid4()}"
    now = _utcnow()
    try:
        await migrations.run(conn)
        await user_aliases.sync_config_aliases(conn, s.user_aliases_config_path)
        locked = await store.acquire_rolling_lock(
            conn,
            run_name=run_name,
            owner=lock_owner,
            now=now,
            lock_expires_at=now + timedelta(minutes=s.memory_rolling_lock_ttl_minutes),
        )
        if not locked:
            print(f"Rolling memory compile already active for '{run_name}'.")
            return 0

        state = await store.get_rolling_state(conn, run_name)
        from_time, to_time = _rolling_window(now=now, state=state, settings=s)
        if to_time <= from_time:
            await store.release_rolling_lock(conn, run_name=run_name)
            print(f"Nothing to compile for rolling memory run '{run_name}'.")
            return 0

        print(
            "Rolling memory window: "
            f"{from_time.isoformat()} -> {to_time.isoformat()} "
            f"(run '{run_name}').",
            flush=True,
        )
        run_id = await compile_run(
            conn,
            config=CompilerConfig(
                name=run_name,
                from_time=from_time,
                to_time=to_time,
                channel_ids=[s.discord_main_channel_id],
                compiler_model=s.memory_compiler_model,
                source_db_label=s.db_path,
                concurrency=s.memory_rolling_concurrency,
                rebuild=False,
                segment=_segment_config_from_settings(),
            ),
            progress=lambda message: print(message, flush=True),
        )
        await store.complete_rolling_compile(
            conn,
            run_name=run_name,
            completed_to=to_time,
            completed_at=_utcnow(),
        )
        print(f"rolling compiled run {run_id}: {run_name}")
        return 0
    except Exception as exc:
        await store.fail_rolling_compile(conn, run_name=run_name, error=str(exc))
        print(f"Rolling memory compile failed for '{run_name}': {exc}")
        return 1
    finally:
        await connection.close(conn)


async def _reflect(args) -> int:
    s = get_settings()
    conn = await connection.open(args.db)
    usage = ReflectionUsage()
    try:
        await migrations.run(conn)
        await user_aliases.sync_config_aliases(conn, s.user_aliases_config_path)
        run_id = await resolve_run_id(conn, args.run)
        run_row = await store.get_compiler_run(conn, run_id)
        run_name = str(run_row["name"]) if run_row else args.run
        model = args.model or DEFAULT_REFLECTION_MODEL
        from_time = _parse_dt(args.from_time)
        to_time = _parse_dt(args.to_time)
        windows = _reflection_windows(from_time=from_time, to_time=to_time, chunk_days=args.chunk_days)
        if args.rebuild:
            deleted = await store.delete_reflection_documents(conn, run_id=run_id, name=args.name)
            print(f"Deleted {deleted} existing reflection document(s) for '{args.name}'.", flush=True)
        result = None
        for index, (window_from, window_to) in enumerate(windows, start=1):
            print(
                f"Reflecting window {index}/{len(windows)}: "
                f"{window_from.isoformat()} -> {window_to.isoformat()}",
                flush=True,
            )
            result = await generate_reflection(
                conn,
                run_id=run_id,
                run_name=run_name,
                name=args.name,
                from_time=window_from,
                to_time=window_to,
                model=model,
                usage=usage,
            )
        if result is None:
            raise ValueError("Reflection time range produced no windows")
        if args.output:
            export = export_markdown_with_metadata(
                content_markdown=result.content_markdown,
                document_id=result.document_id,
                run_name=run_name,
                name=args.name,
                from_time=from_time,
                to_time=to_time,
                model=model,
                generated_at=_utcnow(),
            )
            Path(args.output).write_text(export, encoding="utf-8")
        print(f"reflected document {result.document_id}: {args.name}")
        print(
            "[reflection usage]\n"
            f"responses_calls: {usage.responses_calls}\n"
            f"input_tokens: {usage.input_tokens}\n"
            f"output_tokens: {usage.output_tokens}\n"
            f"total_tokens: {usage.total_tokens}"
        )
        return 0
    finally:
        await connection.close(conn)


async def _chat(args) -> int:
    conn = await connection.open(args.db)
    try:
        await migrations.run(conn)
        await user_aliases.sync_config_aliases(conn, get_settings().user_aliases_config_path)
        recent_context: list[str] = []
        while True:
            try:
                question = input("!gpt> ").strip()
            except EOFError:
                break
            if not question or question.lower() in {"exit", "quit"}:
                break
            answer = await chat_once(
                conn,
                run_id=await resolve_run_id(conn, args.run),
                question=question,
                recent_context=recent_context[-args.recent_limit :] if args.recent_limit > 0 else [],
                show_memory=args.show_memory,
                show_sources=args.show_sources,
                show_usage=args.show_usage,
                show_agent=args.show_agent,
                channel_id=args.channel_id,
                recent_limit=args.recent_limit,
            )
            print(f"KlatreBot> {answer}")
            if args.recent_limit > 0:
                recent_context.extend([f"User: {question}", f"KlatreBot: {answer}"])
                recent_context = recent_context[-args.recent_limit :]
        return 0
    finally:
        await connection.close(conn)


def _extract_function_calls(resp) -> list[dict]:
    calls = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) != "function_call":
            continue
        raw_args = getattr(item, "arguments", "{}") or "{}"
        arguments = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        calls.append(
            {
                "name": getattr(item, "name"),
                "call_id": getattr(item, "call_id"),
                "arguments": arguments,
            }
        )
    return calls


async def resolve_run_id(conn, run: str) -> int:
    if run.isdigit():
        return int(run)
    found = await get_compiler_run_by_name(conn, run)
    if not found:
        raise ValueError(f"Unknown memory compiler run: {run}")
    return int(found["id"])


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _reflection_windows(
    *,
    from_time: datetime,
    to_time: datetime,
    chunk_days: int,
) -> list[tuple[datetime, datetime]]:
    if chunk_days <= 0:
        raise ValueError("--chunk-days must be positive")
    windows: list[tuple[datetime, datetime]] = []
    cursor = from_time
    step = timedelta(days=chunk_days)
    while cursor < to_time:
        next_time = min(cursor + step, to_time)
        windows.append((cursor, next_time))
        cursor = next_time
    return windows


def _rolling_window(*, now: datetime, state: dict | None, settings) -> tuple[datetime, datetime]:
    to_time = now - timedelta(minutes=settings.memory_rolling_settle_minutes)
    last_to = None
    if state and state.get("last_successful_to_utc"):
        last_to = datetime.fromisoformat(state["last_successful_to_utc"])
    if last_to is None:
        from_time = now - timedelta(hours=settings.memory_rolling_initial_lookback_hours)
    else:
        from_time = last_to - timedelta(minutes=settings.memory_rolling_tail_buffer_minutes)
    return from_time, to_time


def _format_recent_context(recent_context: list[str] | None) -> str:
    if not recent_context:
        return "(none)"
    return "\n".join(recent_context)


def _segment_config_from_settings() -> SegmentConfig:
    s = get_settings()
    return SegmentConfig(
        gap_minutes=s.memory_segment_gap_minutes,
        min_human_messages=s.memory_segment_min_human_messages,
        min_total_chars=s.memory_segment_min_total_chars,
        min_participants=s.memory_segment_min_participants,
        max_messages=s.memory_segment_max_messages,
        max_duration_minutes=s.memory_segment_max_duration_minutes,
    )


def _pretty_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return raw


def _print_agent_response(index: int, resp, function_calls: list[dict]) -> None:
    payload = {
        "response_id": getattr(resp, "id", None),
        "output_text": getattr(resp, "output_text", "") or "",
        "function_calls": function_calls,
    }
    print(f"\n[agent response {index}]\n{json.dumps(payload, ensure_ascii=False, indent=2)}")


def _empty_usage() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _add_usage(total: dict[str, int], resp) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    for key in total:
        total[key] += int(_usage_value(usage, key) or 0)


def _usage_value(usage, key: str):
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
