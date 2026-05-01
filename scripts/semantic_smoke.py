"""Quick smoke test: embed a query, run vec search, print top-k matches."""
import asyncio
import sys

from klatrebot_v2.db import connection as conn_mod, embeddings as emb_db
from klatrebot_v2.llm import embeddings as emb_llm
from klatrebot_v2.settings import get_settings


async def main(queries: list[str]) -> None:
    s = get_settings()
    conn = await conn_mod.open(s.db_path)
    try:
        for q in queries:
            vecs = await emb_llm.embed([q])
            if vecs[0] is None:
                print(f"\nQUERY: {q!r} -> empty/skipped")
                continue
            results = await emb_db.search(conn, query_vector=vecs[0], k=3)
            print(f"\nQUERY: {q!r}")
            for mid, dist in results:
                cur = await conn.execute(
                    "SELECT substr(content,1,80) FROM messages WHERE discord_message_id=?",
                    (mid,),
                )
                row = await cur.fetchone()
                snippet = row[0] if row else "<missing>"
                print(f"  {dist:.3f}  {snippet}")
    finally:
        await conn_mod.close(conn)


if __name__ == "__main__":
    qs = sys.argv[1:] or [
        "hvor mange beskeder",
        "klatring og uptime",
        "hej",
        "bot status",
    ]
    asyncio.run(main(qs))
