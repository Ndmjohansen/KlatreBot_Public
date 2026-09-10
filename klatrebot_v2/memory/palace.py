"""Persistent explicit-embedding adapter. Only the memory worker owns this index."""
import asyncio
from collections import OrderedDict
import json
from pathlib import Path
import time
import hashlib
import sqlite3
import re
from contextlib import closing

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


class Palace:
    def __init__(self, path):
        from mempalace.backends.sqlite_exact import SQLiteExactBackend
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.config = self.path / "index.json"
        expected = dict(model=MODEL, dimensions=DIMENSIONS, schema=1, backend="sqlite_exact")
        if not self.config.exists() and (self.path / "sqlite_exact.sqlite3").exists():
            raise ValueError("Missing embedding configuration; rebuild in a new directory")
        if self.config.exists() and json.loads(self.config.read_text()) != expected:
            raise ValueError("Embedding model/schema mismatch; rebuild in a new directory")
        if not self.config.exists():
            self.config.write_text(json.dumps(expected), encoding="utf-8")
        self.backend = SQLiteExactBackend()
        self.collection = self.backend.get_collection(str(self.path), "discord", create=True)
        self.manifest_path = self.path / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.watermark = self.manifest.get("watermark")
        self.lexical_cache = OrderedDict()
        self.index_ids = None
        self.last_timings = {}
        from klatrebot_v2.memory.vectors import VectorCache
        self.vectors = VectorCache(DIMENSIONS)
        self.save()

    def save(self):
        temp = self.manifest_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.manifest), encoding="utf-8")
        temp.replace(self.manifest_path)

    def pending(self, docs):
        hashes = self.manifest.get("hashes", {})
        return [d for d in docs if hashes.get(d.id) != d.digest]

    def commit_batch(self, docs, vectors):
        if len(vectors) != len(docs) or any(len(v) != DIMENSIONS for v in vectors):
            raise ValueError("Embedding dimension/count mismatch")
        self.collection.upsert(ids=[d.id for d in docs], documents=[d.text for d in docs],
                               embeddings=vectors, metadatas=[dict(doc_id=d.id, digest=d.digest,
                                   source_handle=d.handle, kind=d.kind, channel_id=d.channel,
                                   timestamp_utc=d.timestamp, source_ids=json.dumps(d.sources),
                                   authors=json.dumps(d.authors), subjects=json.dumps(d.subjects)) for d in docs])
        self.manifest.setdefault("hashes", {}).update({d.id: d.digest for d in docs})
        if self.index_ids is not None:
            self.index_ids.update(d.id for d in docs)
        if self.vectors.loaded:
            try:
                self.vectors.upsert([d.id for d in docs], vectors)
            except BaseException:
                self.vectors.loaded = False
                raise
        self.manifest.setdefault("embedding_keys", {}).update({d.id: self.embedding_key(d) for d in docs})
        self.lexical_cache.clear()
        self.save()

    @staticmethod
    def embedding_key(doc):
        return hashlib.sha256(json.dumps([MODEL, DIMENSIONS, doc.text], ensure_ascii=False).encode()).hexdigest()

    def reuse_vectors(self, docs):
        keys = self.manifest.setdefault('embedding_keys', {})
        hashes = self.manifest.get('hashes', {})
        changed = []
        seeded = False
        for doc in docs:
            if hashes.get(doc.id) == doc.digest:
                if doc.id not in keys:
                    keys[doc.id] = self.embedding_key(doc)
                    seeded = True
            elif keys.get(doc.id) == self.embedding_key(doc):
                changed.append(doc)
        for offset in range(0, len(changed), 32):
            batch = changed[offset:offset + 32]
            result = self.collection.get(ids=[d.id for d in batch], include=['embeddings'])
            vectors = dict(zip(result['ids'], result['embeddings']))
            available = [d for d in batch if d.id in vectors]
            if available:
                self.commit_batch(available, [vectors[d.id] for d in available])
        if seeded:
            self.save()

    def reconcile(self, docs, full_scan=True):
        wanted = {d.id for d in docs}
        # Read actual IDs too: a crash may have committed an upsert before its manifest.
        if full_scan or self.index_ids is None:
            self.index_ids = set(self.collection.get(include=[])["ids"])
        stale = self.index_ids - wanted
        if stale:
            self.collection.delete(ids=sorted(stale))
            self.index_ids.difference_update(stale)
            self.vectors.delete(stale)
            self.lexical_cache.clear()
        missing = set(self.manifest.get('hashes', {})) - self.index_ids
        self.vectors.delete(missing)
        removed = (set(self.manifest.get('hashes', {})) - wanted) | missing
        for did in removed:
            self.manifest['hashes'].pop(did, None)
            self.manifest.get('embedding_keys', {}).pop(did, None)
        old_watermark = self.watermark
        if not self.pending(docs):
            self.watermark = max((d.timestamp for d in docs if d.kind == "raw_message"), default=None)
            self.manifest["watermark"] = self.watermark
        if stale or removed or self.watermark != old_watermark:
            self.save()
        if full_scan and self.vectors.loaded and len(self.vectors.ids) - len(self.vectors.positions) > max(1024, len(self.vectors.ids) // 8):
            self.prepare_vectors()

    def candidates(self, docs, query, vector=None):
        started = time.perf_counter()
        self.last_timings = {}
        # Check current content hashes so edited/deleted/stale sources cannot leak.
        ids = [d.id for d in docs if self.manifest.get("hashes", {}).get(d.id) == d.digest]
        if not ids:
            return [], []
        eligible = set(ids)
        selected_at = time.perf_counter()
        if vector is not None and not self.vectors.loaded:
            self.prepare_vectors()
        lexical = self.lexical_candidates(query, eligible)
        lexical_at = time.perf_counter()
        # Rank the cached matrix without materializing another filtered matrix.
        # Keep enough semantic candidates for reciprocal-rank fusion to recognize
        # corroborating lexical hits below rank 30. Final results remain capped
        # at ten; filtering still happens before this bounded candidate limit.
        semantic = self.vectors.query(vector, eligible, limit=60) if vector is not None else []
        self.last_timings = dict(eligibility_ms=(selected_at - started) * 1000,
                                 lexical_ms=(lexical_at - selected_at) * 1000,
                                 vector_ms=(time.perf_counter() - lexical_at) * 1000)
        return semantic, lexical

    def lexical_candidates(self, query, eligible):
        # MemPalace 3.9's lexical API hydrates all matching text/metadata before
        # applying metadata filters. The pinned sqlite_exact FTS table exposes
        # exactly the same native BM25 ranks without that materialization.
        # Read-only access only; all index writes remain collection operations.
        tokens = [t for t in re.findall(r'\w+', query.lower()) if len(t) >= 2]
        if tokens:
            cache_key = ('fts', tuple(tokens))
            ranked = self.lexical_cache.get(cache_key)
            if ranked is None:
                try:
                    uri = (self.path / 'sqlite_exact.sqlite3').resolve().as_uri() + '?mode=ro'
                    with closing(sqlite3.connect(uri, uri=True)) as conn:
                        ranked = [row[0] for row in conn.execute(
                            """SELECT doc_id FROM docs_fts
                            WHERE docs_fts MATCH ? AND collection_id=(SELECT id FROM collections WHERE name='discord')
                            ORDER BY bm25(docs_fts)""", (' OR '.join(tokens),))]
                except sqlite3.Error:
                    return self._collection_lexical_candidates(query, eligible)
                self.lexical_cache[cache_key] = ranked
                # Bound retained IDs as well as the number of queries.
                while len(self.lexical_cache) > 64 or sum(len(v) for v in self.lexical_cache.values()) > 100000:
                    self.lexical_cache.popitem(last=False)
            if cache_key in self.lexical_cache:
                self.lexical_cache.move_to_end(cache_key)
            return [did for did in ranked if did in eligible][:30]
        return self._collection_lexical_candidates(query, eligible)

    def _collection_lexical_candidates(self, query, eligible):
        # Fetch native global BM25 ranks progressively until 30 ELIGIBLE hits
        # are known. Never limit after an unrestricted fixed top-30. This avoids
        # hydrating every common-word occurrence after each index update.
        ranked, exhausted, fetched = [], False, 0
        while True:
            selected = [did for did in ranked if did in eligible][:30]
            if len(selected) == 30 or exhausted:
                break
            fetched = max(30, fetched * 2)
            hits = self.collection.lexical_search(query=query, n_results=fetched).hits
            ranked = [hit.id for hit in hits]
            exhausted = len(ranked) < fetched
        return selected

    def warm(self, docs=()):
        if self.collection.count():
            self.prepare_vectors()

    def prepare_vectors(self):
        self.vectors.load(self.collection)
        from klatrebot_v2.memory.heap import release_unused
        release_unused()


async def embed(client, texts, timeout=2.5):
    async with asyncio.timeout(timeout):
        response = await client.embeddings.create(model=MODEL, dimensions=DIMENSIONS,
                                                   input=texts, encoding_format="float")
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)], response.usage.total_tokens


def token_count(docs):
    import tiktoken
    encoding = tiktoken.get_encoding("cl100k_base")
    return sum(len(encoding.encode(d.text, disallowed_special=())) for d in docs)
