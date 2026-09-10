"""Opt-in, credentialed evidence generalization check using synthetic fixtures.

Example: poetry run python -m klatrebot_v2.memory.evaluate_evidence --report new.json
Runs real model calls, without touching a database/index or sending Discord messages.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from klatrebot_v2.llm.client import get_client
from klatrebot_v2.memory.adjudication import INSTRUCTIONS, classify
from klatrebot_v2.settings import get_settings


def source(row):
    return dict(source_handle=f"msg:{row['id']}", discord_message_id=row["id"],
                user_id=row.get("author", 1), user_display_name=f"Person {row.get('author', 1)}",
                channel_id=4, content=row["text"], is_bot=False,
                timestamp_utc=f"2026-09-{row['day']:02}T12:00:00+00:00")


async def evaluate(fixture, report):
    raw = fixture.read_bytes()
    cases = json.loads(raw)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    for c in cases:
        if {str(m["id"]) for m in c["messages"]} != c["expected"].keys():
            raise ValueError("Every candidate needs a frozen expected judgment")
    settings = get_settings()
    client = get_client()
    result = dict(model=settings.model, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                  instructions_sha256=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(), cases=[])
    # Reserve the output before making any billable calls; never overwrite a run.
    with report.open("x", encoding="utf-8") as out:
        json.dump(result, out)
    try:
        for case in cases:
            for reverse in (False, True):
                candidates = [source(m) for m in case["messages"]]
                context = sorted(candidates + [source(m) for m in case.get("context", [])],
                                 key=lambda m: (m["timestamp_utc"], m["discord_message_id"]))
                if reverse:
                    candidates.reverse()
                scope = dict(people=[1], channel_id=4, person_role="author", order=case.get("order", "relevance"))
                started = time.monotonic()
                error, observed = None, {}
                try:
                    async with asyncio.timeout(45):
                        verdicts = await classify(client, settings.model, case["question"], scope, candidates, context)
                    observed = {h.removeprefix("msg:"): v.relevance for h, v in verdicts.items()}
                except Exception as exc:
                    error = type(exc).__name__
                row = dict(id=case["id"], reversed=reverse, error=error,
                           passed=observed == case["expected"], observed=observed,
                           seconds=round(time.monotonic() - started, 3))
                result["cases"].append(row)
                report.write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(row), flush=True)
    finally:
        await client.close()
    return all(c["passed"] for c in result["cases"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/evidence_generalization.json"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(evaluate(args.fixture, args.report)) else 1)


if __name__ == "__main__":
    main()
