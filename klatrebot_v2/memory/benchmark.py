"""Full-corpus latency benchmark; does not claim source-recall quality.

Uses the Danish fixture's questions with real channel/person filters inferred
from source metadata. Saves no source message bodies. The first query is cold.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time

from klatrebot_v2.memory.evaluate import percentile
from klatrebot_v2.memory.retrieval import recall_community_memory
from klatrebot_v2.memory.transport import request
from klatrebot_v2.memory.worker import source_connection


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    rows = []
    async with source_connection(args.db) as conn:
        channel = (await conn.execute_fetchall(
            "SELECT channel_id FROM messages WHERE is_bot=0 GROUP BY channel_id ORDER BY count(*) DESC LIMIT 1"
        ))[0][0]
        people = [r[0] for r in await conn.execute_fetchall(
            "SELECT user_id FROM messages WHERE is_bot=0 AND channel_id=? GROUP BY user_id ORDER BY count(*) DESC LIMIT 5", (channel,))]
        run = (await conn.execute_fetchall("SELECT id FROM memory_compiler_runs WHERE name='production'"))[0][0]
        for i, case in enumerate(questions):
            query = case["request"]["query"].replace("Annas", "personens").replace("Anna", "personen")
            payload = dict(query=query, channel_id=channel, run_id=run, limit=10)
            scope = ["channel", "author", "latest"][i % 3]
            if scope != "channel":
                payload["people"] = [people[i % len(people)]]
            if scope == "latest":
                payload["order"] = "latest"
            started = time.perf_counter()
            try:
                response = await request(args.socket, payload, timeout=65)
                elapsed = (time.perf_counter() - started) * 1000
                coverage = response.get("coverage", {})
                evidence = response.get("results", []) + coverage.get("chronological_page", [])
                authors_ok = all(r["participants"] == payload["people"] for r in evidence) if payload.get("people") else True
                channels_ok = all(e["channel_id"] == channel for r in evidence for e in r.get("source_excerpts", []))
                row = dict(id=case["id"], scope=scope, elapsed_ms=elapsed,
                           local_ms=coverage.get("local_search_ms"),
                           source_refresh_ms=coverage.get("source_refresh_ms"),
                           index_timings=coverage.get("index_timings"),
                           rss_mb=coverage.get("worker_peak_rss_mb"),
                           status=response["status"], author_filter_ok=authors_ok,
                           channel_filter_ok=channels_ok, candidate_ids=response["source_handles"])
            except Exception as exc:
                row = dict(id=case["id"], scope=scope, elapsed_ms=(time.perf_counter() - started) * 1000,
                           status=type(exc).__name__)
            started = time.perf_counter()
            legacy = await recall_community_memory(conn, run_id=run, query=query,
                                                   channel_id=channel, people=payload.get("people"), limit=10)
            row["legacy_ms"] = (time.perf_counter() - started) * 1000
            row["legacy_candidate_ids"] = legacy.source_handles
            rows.append(row)
            Path(args.output).write_text(json.dumps({"completed": len(rows), "total": len(questions), "cases": rows}, indent=2))
            print(f"{len(rows)}/{len(questions)} {scope}: total={row['elapsed_ms']:.0f}ms local={row.get('local_ms', 0) or 0:.0f}ms status={row['status']}", flush=True)
    warm = rows[1:]
    summary = dict(cases=len(rows), cold_ms=rows[0]["elapsed_ms"],
                   warm_p50_ms=percentile([r["elapsed_ms"] for r in warm], .5),
                   warm_p95_ms=percentile([r["elapsed_ms"] for r in warm], .95),
                   local_p95_ms=percentile([r["local_ms"] for r in rows if r.get("local_ms") is not None], .95),
                   peak_rss_mb=max((r.get("rss_mb") or 0 for r in rows), default=0),
                   legacy_p95_ms=percentile([r["legacy_ms"] for r in rows], .95),
                   degraded_or_failed=sum(r["status"] != "ok" for r in rows),
                   author_filter_failures=sum(not r.get("author_filter_ok", True) for r in rows),
                   channel_filter_failures=sum(not r.get("channel_filter_ok", True) for r in rows),
                   quality_recall_at_10=None)
    Path(args.output).write_text(json.dumps({"summary": summary, "cases": rows}, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
