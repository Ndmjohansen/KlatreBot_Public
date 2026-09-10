"""Offline native-ranking parity check. Use a stopped worker's isolated snapshot."""
import argparse
import asyncio
import json
from pathlib import Path

import aiosqlite

from klatrebot_v2.memory.corpus import load_corpus
from klatrebot_v2.memory.palace import Palace


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--index', required=True)
    parser.add_argument('--questions', default='tests/fixtures/danish_recall.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import fcntl
    with open(Path(args.index) / 'worker.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        async with aiosqlite.connect(Path(args.db).resolve().as_uri() + '?mode=ro', uri=True) as conn:
            run = (await conn.execute_fetchall("SELECT id FROM memory_compiler_runs WHERE name='production'"))[0][0]
            docs = await load_corpus(conn, run)
        palace = Palace(args.index)
        try:
            docs = [d for d in docs if palace.manifest.get('hashes', {}).get(d.id) == d.digest]
            from collections import Counter
            channel = Counter(d.channel for d in docs).most_common(1)[0][0]
            author = Counter(d.authors[0] for d in docs if d.channel == channel and len(d.authors) == 1).most_common(1)[0][0]
            scopes = [[d for d in docs if d.channel == channel],
                      [d for d in docs if d.channel == channel and d.authors == [author]],
                      sorted([d for d in docs if d.channel == channel and d.authors == [author] and d.kind == 'raw_message'], key=lambda d: d.timestamp)[-25:]]
            lexical = semantic = 0
            cases = json.loads(Path(args.questions).read_text(encoding='utf-8'))
            for i, case in enumerate(cases):
                eligible = {d.id for d in scopes[i % 3]}
                query = case['request']['query']
                actual = palace.lexical_candidates(query, eligible)
                expected = [h.id for h in palace.collection.lexical_search(query=query, n_results=30,
                            where={'doc_id': {'$in': sorted(eligible)}}).hits]
                if actual != expected:
                    raise AssertionError(f'Lexical ranking mismatch in case {i}')
                lexical += 1
            palace.prepare_vectors()
            for scope in scopes:
                eligible = {d.id for d in scope}
                vector = palace.collection.get(ids=[scope[-1].id], include=['embeddings'])['embeddings'][0]
                actual = palace.vectors.query(vector, eligible, limit=60)
                expected = palace.collection.query(query_embeddings=[vector], n_results=60,
                    where={'doc_id': {'$in': sorted(eligible)}}, include=[])['ids'][0]
                if actual != expected:
                    raise AssertionError('Semantic ranking mismatch')
                semantic += 1
            result = dict(lexical_cases=lexical, semantic_cases=semantic, mismatches=0,
                          indexed_documents=len(docs), semantic_quality_evaluated=False)
            Path(args.output).write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            palace.backend.close()


if __name__ == '__main__':
    asyncio.run(main())
