"""Persistent source snapshot with commit detection and incremental preparation."""
import asyncio
from pathlib import Path

import aiosqlite

from klatrebot_v2.memory.corpus import CorpusState, load_corpus, apply_message_changes
from klatrebot_v2.memory.journal import boundary


def prepare(docs):
    for doc in docs:
        # cached_property ensures unchanged documents are prepared only once.
        doc.digest
        doc.terms
        doc.source_start
        doc.source_end


class CorpusCache:
    def __init__(self, path):
        self.path = path
        self.conn = None
        self.lock = asyncio.Lock()
        self.state = CorpusState()
        self.version = None
        self.run_id = None
        self.docs = []
        self.sequence = 0

    async def get(self, resolve_run, *, reconcile=False):
        async with self.lock:
            if self.conn is None:
                self.conn = await aiosqlite.connect(Path(self.path).resolve().as_uri() + "?mode=ro", uri=True)
            await self.conn.execute("BEGIN")
            try:
                # Sequence and source reads belong to the same committed snapshot.
                version = await boundary(self.conn)
                run_id = await resolve_run(self.conn) if callable(resolve_run) else resolve_run
                if reconcile or (version, run_id) != (self.version, self.run_id):
                    changes = await self.conn.execute_fetchall(
                        "SELECT kind, entity_id FROM memory_changes WHERE seq>? AND seq<=?", (self.sequence, version))
                    if reconcile or self.version is None or run_id != self.run_id or any(c[0] != 'message' for c in changes):
                        # Build separately so a failed refresh leaves the last published state intact.
                        state = CorpusState()
                        state.__dict__.update(self.state.__dict__)
                        docs = await load_corpus(self.conn, run_id, state)
                    else:
                        state = CorpusState()
                        state.__dict__.update(self.state.__dict__)
                        state.messages = dict(state.messages)
                        state.documents = dict(state.documents)
                        state.specs = dict(state.specs)
                        docs = await apply_message_changes(self.conn, state, {c[1] for c in changes})
                    await asyncio.to_thread(prepare, docs)
                    self.state = state
                    self.docs, self.version, self.run_id = docs, version, run_id
                    self.sequence = version
                return self.docs, run_id
            finally:
                await self.conn.rollback()

    async def close(self):
        async with self.lock:
            if self.conn is not None:
                await self.conn.close()
                self.conn = None
                self.version = None

    async def reconcile(self, resolve_run):
        """Build off the serving lock; publish only if its snapshot is not older."""
        base = self.state

        async def build():
            state = CorpusState()
            state.__dict__.update(base.__dict__)
            async with aiosqlite.connect(Path(self.path).resolve().as_uri() + '?mode=ro', uri=True) as conn:
                await conn.execute('BEGIN')
                sequence = await boundary(conn)
                run_id = await resolve_run(conn) if callable(resolve_run) else resolve_run
                docs = await load_corpus(conn, run_id, state)
                prepare(docs)
                await conn.rollback()
            return state, docs, sequence, run_id

        state, docs, sequence, run_id = await asyncio.to_thread(lambda: asyncio.run(build()))
        async with self.lock:
            if sequence >= self.sequence and (self.run_id is None or self.run_id == run_id):
                self.state, self.docs = state, docs
                self.sequence = self.version = sequence
                self.run_id = run_id
