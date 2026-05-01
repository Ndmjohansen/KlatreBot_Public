"""Backfill embeddings for all messages missing them.

Idempotent: skips messages that already have an embedding row. Run on dev / prod
DB after deploying the vec table migration.

Usage:
    poetry run python scripts/backfill_embeddings.py [--batch 100] [--limit N]
"""
import argparse
import asyncio
import logging

from klatrebot_v2.db import connection as conn_mod, embeddings as emb_db
from klatrebot_v2.llm import embeddings as emb_llm
from klatrebot_v2.settings import get_settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=100, help="messages per OpenAI call")
    parser.add_argument("--limit", type=int, default=None, help="stop after N total embedded")
    args = parser.parse_args()

    s = get_settings()
    conn = await conn_mod.open(s.db_path)
    try:
        total_done = 0
        last_id = 0
        while True:
            cursor = await conn.execute(
                "SELECT discord_message_id, content FROM messages "
                "WHERE discord_message_id > ? AND content != '' "
                "ORDER BY discord_message_id ASC LIMIT ?",
                (last_id, args.batch),
            )
            rows = await cursor.fetchall()
            if not rows:
                break

            ids = [r[0] for r in rows]
            already = await emb_db.existing_ids(conn, ids)
            todo = [(mid, content) for mid, content in rows if mid not in already]

            if todo:
                vectors = await emb_llm.embed([c for _, c in todo])
                pairs = [
                    (mid, vec) for (mid, _), vec in zip(todo, vectors) if vec is not None
                ]
                await emb_db.upsert_many(conn, pairs)
                total_done += len(pairs)
                logger.info(
                    "batch: %d new embeddings (skipped %d already done). total=%d",
                    len(pairs), len(rows) - len(todo), total_done,
                )
            else:
                logger.info("batch: all %d already embedded, skipping", len(rows))

            last_id = ids[-1]
            if args.limit and total_done >= args.limit:
                logger.info("hit --limit %d, stopping", args.limit)
                break

        logger.info("done. total embedded this run: %d", total_done)
    finally:
        await conn_mod.close(conn)


if __name__ == "__main__":
    asyncio.run(main())
