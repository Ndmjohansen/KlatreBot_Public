"""Offline memory compiler and chat CLI."""
import argparse
import asyncio
import json
from datetime import datetime

from klatrebot_v2.db import connection, migrations
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.memory.compiler import CompilerConfig, compile_run
from klatrebot_v2.memory.segmentation import SegmentConfig
from klatrebot_v2.memory.store import get_compiler_run_by_name
from klatrebot_v2.memory.tools import MEMORY_TOOL_DEFS, execute_memory_tool
from klatrebot_v2.settings import get_settings


async def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "compile":
        return await _compile(args)
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
    channel_id: int | None = None,
    recent_limit: int = 0,
) -> str:
    s = get_settings()
    client = get_client()
    prompt = (
        f"{load_soul()}\n\n"
        "Du kører i offline memory-test. Brug memory tools ved historiske spørgsmål. "
        "Vis ikke kilder medmindre brugeren spørger.\n\n"
        f"CHANNEL_ID: {channel_id or '(none)'}\n"
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
        tool_outputs = []
        debug_outputs = []
        for call in _extract_function_calls(resp):
            output = await execute_memory_tool(
                conn,
                run_id=run_id,
                name=call["name"],
                arguments=call["arguments"],
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
            break
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
    compile_parser.add_argument("--yes", action="store_true", help="Overwrite existing run without prompting")

    chat_parser = sub.add_parser("chat")
    chat_parser.add_argument("--db", required=True)
    chat_parser.add_argument("--run", required=True)
    chat_parser.add_argument("--show-memory", action="store_true")
    chat_parser.add_argument("--show-sources", action="store_true")
    chat_parser.add_argument("--show-usage", action="store_true")
    chat_parser.add_argument("--channel-id", type=int)
    chat_parser.add_argument("--recent-limit", type=int, default=8)
    return parser


async def _compile(args) -> int:
    conn = await connection.open(args.db)
    try:
        await migrations.run(conn)
        existing = await get_compiler_run_by_name(conn, args.name)
        if existing and not args.yes:
            answer = input(f"Memory run '{args.name}' exists. Overwrite? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("aborted")
                return 1
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
                segment=_segment_config_from_settings(),
            ),
            progress=lambda message: print(message, flush=True),
        )
        print(f"compiled run {run_id}: {args.name}")
        return 0
    finally:
        await connection.close(conn)


async def _chat(args) -> int:
    conn = await connection.open(args.db)
    try:
        await migrations.run(conn)
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
