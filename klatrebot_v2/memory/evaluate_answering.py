"""Opt-in model acceptance with frozen synthetic candidates, not a retrieval score.

Runs actual chat.reply and models with deterministic source-tool responses. Gold
labels never enter model input. Use the private full-flow suite for real retrieval.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import aiosqlite

from klatrebot_v2.db import migrations, user_aliases, users
from klatrebot_v2.llm import chat
from klatrebot_v2.memory import answering, tools
from klatrebot_v2.memory.evaluate import percentile


async def evaluate(fixture, report):
    raw = fixture.read_bytes()
    cases = json.loads(raw)
    if not cases or any(not c["id"] for c in cases) or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Question IDs must be nonempty and unique")
    settings = chat.get_settings().model_copy(update=dict(memory_enabled=True,
        memory_backend="mempalace", memory_active_run_name=None, memory_active_run_id=0))
    output = dict(fixture_sha256=hashlib.sha256(raw).hexdigest(), model=settings.model,
                  implementation_sha256=implementation_hash(),
                  scope="model answering with frozen candidate tools", cases=[])
    with report.open("x", encoding="utf-8") as stream:
        json.dump(output, stream)
    answers = report.with_suffix(".answers.jsonl")
    # A separate artifact permits final-answer review without bodies in metrics.
    answer_stream = answers.open("x", encoding="utf-8")
    originals = chat.get_settings, chat._get_db_conn, tools.execute_memory_tool, answering.AnswerSession
    real_client = chat.get_client()
    sessions = []

    class CapturedSession(originals[3]):
        def __init__(self):
            super().__init__()
            sessions.append(self)

    answering.AnswerSession = CapturedSession
    chat.get_settings = lambda: settings
    try:
        for case in cases:
            async with aiosqlite.connect(":memory:") as conn:
                await migrations.run(conn)
                for uid, name in [(1, "Anna"), (2, "Bo"), (3, "Spørger")]:
                    await users.upsert(conn, discord_user_id=uid, display_name=name)
                    await user_aliases.upsert_alias(conn, discord_user_id=uid, alias=name, source="config")
                author = case.get("author", 1)
                rows = [dict(discord_message_id=i + 1, channel_id=4, user_id=author,
                    user_display_name="Anna" if author == 1 else "Bo", is_bot=False,
                    timestamp_utc=f"2026-09-{1 if case.get('same_time') else i + 1:02}T12:00:00+00:00", content=text)
                    for i, text in enumerate(case["messages"])]
                for i, text in enumerate(case.get("recent", [])):
                    await conn.execute("INSERT INTO messages(discord_message_id,channel_id,user_id,content,timestamp_utc,is_bot) VALUES(?,?,?,?,?,0)",
                        (100 + i, 4, 1, text, "2026-09-09T11:00:00+00:00"))
                if case.get("context"):
                    await conn.execute("INSERT INTO messages(discord_message_id,channel_id,user_id,content,timestamp_utc,is_bot) VALUES(98,4,3,?,'2026-09-09T10:00:00+00:00',0)", (case["context"],))
                await conn.execute("INSERT INTO messages(discord_message_id,channel_id,user_id,content,timestamp_utc,is_bot) VALUES(999,4,3,?,'2026-09-09T12:00:00+00:00',0)", (case["question"],))
                chat._get_db_conn = lambda: conn
                calls = []

                async def tool(connection, *, name, arguments, **kwargs):
                    calls.append(name)
                    if case.get("failure") == "deadline":
                        await asyncio.sleep(120)
                    if case.get("failure") == "unavailable":
                        return json.dumps(dict(status="unavailable", results=[]))
                    if name == "get_memory_sources":
                        return json.dumps(rows)
                    resolution = await user_aliases.resolve_people_names(conn, arguments.get("people_names"))
                    if resolution.unmatched or resolution.ambiguous:
                        return json.dumps(dict(status="clarification_required", results=[]))
                    scope = dict(arguments, people=resolution.resolved_ids or arguments.get("people"))
                    hits = [dict(source_handle=f"msg:{r['discord_message_id']}", kind="raw_message",
                                 created_at_source=r["timestamp_utc"]) for r in rows]
                    return json.dumps(dict(status="ok", answerable=bool(hits), results=hits,
                        search_scope=scope, coverage=dict(chronological_page=hits), continuation_cursor=None))

                tools.execute_memory_tool = tool
                started = time.monotonic()
                error = None
                try:
                    result = await chat.reply(question=case["question"], asking_user_id=3,
                                              channel_id=4, invoking_message_id=999)
                    answer_text = result.text
                except Exception as exc:
                    error, answer_text = type(exc).__name__, ""
                session = sessions[-1]
                observed = [p.record.assessment.status for p in session.parts if p.kind != "general"]
                category = "latest" if any(p.latest for p in session.parts) else session.route
                row = dict(id=case["id"], route=session.route, category=category, evidence=observed,
                    route_passed=session.route == case["expected_route"],
                    evidence_passed=observed == case["expected_evidence"],
                    retrieved="recall_community_memory" in calls, calls=calls, error=error,
                    seconds=round(time.monotonic() - started, 3),
                    coverage=[p.record.coverage for p in session.parts if p.kind != "general"],
                    tokens=sum(e.get("total_tokens", 0) for e in session.events),
                    failures=session.failures + [f for p in session.parts for f in p.record.failures])
                output["cases"].append(row)
                answer_stream.write(json.dumps(dict(id=case["id"], answer=answer_text), ensure_ascii=False) + "\n")
                answer_stream.flush()
                report.write_text(json.dumps(output, indent=2), encoding="utf-8")
                print(json.dumps(row), flush=True)
        general = [r for r in output["cases"] if r["id"].endswith("-general")]
        output["unnecessary_memory_rate"] = sum(r["retrieved"] for r in general) / len(general)
        output["metrics"] = {category: dict(count=len(group),
            p95_seconds=percentile([r["seconds"] for r in group], .95),
            total_tokens=sum(r["tokens"] for r in group))
            for category in {r["category"] for r in output["cases"]}
            if (group := [r for r in output["cases"] if r["category"] == category])}
        output["passed"] = output["unnecessary_memory_rate"] <= .05 and all(
            r["route_passed"] and r["evidence_passed"] and not r["error"] and r["seconds"] < 61
            and (r["retrieved"] or r["route"] == "general") for r in output["cases"])
        report.write_text(json.dumps(output, indent=2), encoding="utf-8")
        return output["passed"]
    finally:
        chat.get_settings, chat._get_db_conn, tools.execute_memory_tool, answering.AnswerSession = originals
        answer_stream.close()
        await real_client.close()


def implementation_hash():
    from klatrebot_v2.memory import adjudication, routing, latest, pronouns, palace, search
    from klatrebot_v2.db import migrations, user_pronouns
    digest = hashlib.sha256()
    for module in (chat, answering, adjudication, routing, latest, pronouns, migrations, user_pronouns, tools, palace, search):
        digest.update(Path(module.__file__).read_bytes())
    from klatrebot_v2.llm.prompt import prompt_fingerprint
    digest.update(prompt_fingerprint().encode())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/history_routing.json"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(evaluate(args.fixture, args.report)) else 1)


if __name__ == "__main__":
    main()
