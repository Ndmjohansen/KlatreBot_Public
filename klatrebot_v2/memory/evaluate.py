"""Evaluate a fixed JSON question set against the worker and legacy retrieval.

python -m klatrebot_v2.memory.evaluate --db SOURCE --questions questions.json --run-id ID
No message bodies are included in the report. Use --seed NEW_DB to create the
anonymized fixture database; it refuses to overwrite an existing file.
"""
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import time

import aiosqlite

from klatrebot_v2.db import migrations, messages, users
from klatrebot_v2.memory.retrieval import recall_community_memory, get_memory_sources
from klatrebot_v2.memory.transport import request
from klatrebot_v2.memory.worker import source_connection


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


async def seed(path, cases):
    # Exclusive creation protects production and previous test data.
    with Path(path).open("x"):
        pass
    async with aiosqlite.connect(path) as conn:
        await migrations.run(conn)
        for case in cases:
            for msg in case.get("messages", []):
                await users.upsert(conn, discord_user_id=msg["user_id"], display_name=f"Person {msg['user_id']}")
                from klatrebot_v2.memory.corpus import utc
                await messages.insert(conn, **dict(msg, timestamp_utc=utc(msg["timestamp_utc"])))


async def evaluate(db_path, socket_path, cases, run_id):
    if not cases or any(not case['id'] for case in cases) or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Question IDs must be nonempty and unique')
    report = []
    async with source_connection(db_path) as conn:
        # Freeze expected evidence before searching; an edited source invalidates
        # the gold label rather than silently changing what a passing hit means.
        for case in cases:
            for mid in case['expected_source_ids']:
                rows = await conn.execute_fetchall(
                    'SELECT content FROM messages WHERE discord_message_id=? AND deleted=0', (mid,))
                if not rows:
                    raise ValueError(f"Missing expected evidence for {case['id']}")
                if case.get('evidence_sha256') and (
                    len(case['expected_source_ids']) != 1 or
                    hashlib.sha256(rows[0][0].encode()).hexdigest() != case['evidence_sha256']
                ):
                    raise ValueError(f"Changed expected evidence for {case['id']}")
        for case in cases:
            query = dict(case["request"], run_id=run_id, limit=10)
            start = time.perf_counter()
            response = await request(socket_path, query, timeout=10)
            elapsed = (time.perf_counter() - start) * 1000
            # Recall@10 uses ranked results, not extra chronological context.
            matched = {mid for r in response["results"][:10] for mid in r["source_ids"]}
            expected = set(case["expected_source_ids"])
            from klatrebot_v2.memory.corpus import utc
            date_range = tuple(utc(query[k]) if query.get(k) else None for k in ["date_start", "date_end"])
            legacy = await recall_community_memory(conn, run_id=run_id, query=query["query"],
                people=query.get("people"), channel_id=query.get("channel_id"),
                date_range=date_range, memory_types=query.get("memory_types"), limit=10)
            legacy_sources = await get_memory_sources(conn, source_handles=legacy.source_handles, context_radius=0)
            legacy_ids = {s.discord_message_id for s in legacy_sources}
            ranked_handles = [r['source_handle'] for r in response['results'][:10]]
            expanded = await get_memory_sources(conn, source_handles=ranked_handles, context_radius=0)
            expanded_ids = {s.discord_message_id for s in expanded}
            report.append(dict(id=case["id"], category=case.get('category', 'unspecified'),
                candidate_ids=ranked_handles, legacy_candidate_ids=legacy.source_handles,
                expected_source_ids=sorted(expected), matched_expected_source_ids=sorted(expected & matched),
                legacy_matched_expected_source_ids=sorted(expected & legacy_ids),
                source_expansion_correct=expected & matched <= expanded_ids,
                first_expected_rank=next((i for i, r in enumerate(response['results'][:10], 1)
                                          if expected.intersection(r['source_ids'])), None),
                recall_at_10=len(expected & matched) / len(expected) if expected else float(not matched),
                legacy_recall_at_10=len(expected & legacy_ids) / len(expected) if expected else float(not legacy_ids),
                forbidden_match=bool(set(case.get("forbidden_source_ids", [])) & matched),
                first_source_correct=not case.get("expected_first_source_id") or (
                    bool(response["results"]) and case["expected_first_source_id"] in response["results"][0]["source_ids"]),
                elapsed_ms=elapsed, status=response["status"], **response["coverage"]))
    # Never copy chronological message bodies/instructions into benchmark reports.
    for row in report:
        row.pop("chronological_page", None)
        row.pop("instruction", None)
    recall = sum(r["recall_at_10"] for r in report) / len(report)
    legacy_recall = sum(r["legacy_recall_at_10"] for r in report) / len(report)
    latency = percentile([r["elapsed_ms"] for r in report], .95)
    local = percentile([r["local_search_ms"] for r in report if r.get("local_search_ms") is not None], .95)
    rss = max((r.get("worker_peak_rss_mb", 0) for r in report), default=0)
    quality_passed = len(report) >= 30 and recall >= .9 and recall > legacy_recall and all(
        not r['forbidden_match'] and r['first_source_correct'] and r['source_expansion_correct']
        and r['status'] == 'ok' for r in report)
    performance_passed = latency < 3000 and local is not None and local < 500 and 0 < rss < 600
    return dict(cases=report, recall_at_10=recall, legacy_recall_at_10=legacy_recall,
                ordinary_p95_ms=latency, local_p95_ms=local, worker_peak_rss_mb=rss,
                quality_passed=quality_passed, performance_passed=performance_passed,
                passed=quality_passed and performance_passed)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--db")
    parser.add_argument("--socket", default="/run/klatrebot-retrieval/worker.sock")
    parser.add_argument("--run-id", type=int, default=0)
    parser.add_argument("--seed")
    parser.add_argument("--output")
    args = parser.parse_args()
    cases = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.seed:
        await seed(args.seed, cases)
        return
    if not args.db:
        parser.error("--db is required without --seed")
    report = await evaluate(args.db, args.socket, cases, args.run_id)
    report['questions_sha256'] = hashlib.sha256(Path(args.questions).read_bytes()).hexdigest()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
