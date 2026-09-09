"""Run with python -m klatrebot_v2.memory.worker {serve,estimate,sync,snapshot,status}."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import socket
import time
import uuid
import math
from email.utils import parsedate_to_datetime

import aiosqlite

from klatrebot_v2.memory.corpus import load_corpus
from klatrebot_v2.memory.cache import CorpusCache
from klatrebot_v2.memory.journal import pending_status
from klatrebot_v2.memory.palace import Palace, embed, token_count
from klatrebot_v2.memory.search import search
from klatrebot_v2.memory.transport import request
from klatrebot_v2.settings import get_settings

log = logging.getLogger(__name__)


def retry_delay(exc, failures):
    delay = min(300, 5 * 2 ** min(failures - 1, 6))
    response = getattr(exc, 'response', None)
    if response is None:
        return delay
    for header, divisor in [('retry-after', 1), ('retry-after-ms', 1000)]:
        value = response.headers.get(header)
        if value is None:
            continue
        try:
            try:
                requested = float(value) / divisor
            except ValueError:
                requested = parsedate_to_datetime(value).timestamp() - time.time() if divisor == 1 else 0
            if math.isfinite(requested):
                delay = max(delay, requested)
        except (ValueError, TypeError, OverflowError):
            pass
    return delay


async def finish_thread(function, *args):
    """Do not release the index lock while a cancelled write is still running."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


@asynccontextmanager
async def source_connection(path):
    async with aiosqlite.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        await conn.execute("BEGIN")
        yield conn


async def active_run(conn, settings):
    if settings.memory_active_run_name:
        rows = await conn.execute_fetchall("SELECT id FROM memory_compiler_runs WHERE name=?",
                                          (settings.memory_active_run_name,))
        return rows[0][0] if rows else 0
    return settings.memory_active_run_id or 0


class Worker:
    def __init__(self, settings, palace, client):
        self.settings, self.palace, self.client = settings, palace, client
        self.lock = asyncio.Lock()
        self.sync_lock = asyncio.Lock()
        self.cache = CorpusCache(settings.db_path)
        self.last_reconcile = 0
        self.indexed_sequence = palace.manifest.get('indexed_sequence', 0)
        self.maintained_sequence = None
        self.retry_at = 0
        self.last_sync_error = None

    async def corpus(self):
        docs, _ = await self.cache.get(lambda conn: active_run(conn, self.settings))
        return docs

    async def sync(self):
        async with self.sync_lock:
            docs = await self.corpus()
            target_sequence = self.cache.sequence
            async with self.lock:
                await finish_thread(self.palace.reuse_vectors, docs)
                await finish_thread(self.palace.reconcile, docs, False)
                pending = self.palace.pending(docs)
            tokens = await asyncio.to_thread(token_count, pending)
            log.info("memory_backfill documents=%d input_tokens=%d", len(pending), tokens)
            started = time.monotonic()
            already_done = len(docs) - len(pending)
            for offset in range(0, len(pending), 32):
                batch = pending[offset:offset + 32]
                vectors, used = await embed(self.client, [d.text for d in batch], timeout=30)
                current = {d.id: d.digest for d in await self.corpus()}
                valid = [(doc, vector) for doc, vector in zip(batch, vectors) if current.get(doc.id) == doc.digest]
                async with self.lock:
                    if valid:
                        await finish_thread(self.palace.commit_batch, [v[0] for v in valid], [v[1] for v in valid])
                processed = offset + len(batch)
                completed = already_done + processed
                remaining = len(pending) - processed
                eta = (time.monotonic() - started) / processed * remaining
                log.info("memory_progress completed=%d/%d percent=%.1f remaining=%d eta_seconds=%.0f batch_tokens=%d",
                         completed, len(docs), 100 * completed / len(docs), remaining, eta, used)
            docs = await self.corpus()
            async with self.lock:
                await finish_thread(self.palace.reconcile, docs, False)
                # A successful captured batch acknowledges its input boundary,
                # even if newer arrivals are pending. Superseded inputs have a
                # later journal event and must not hold the entire prefix back.
                self.indexed_sequence = target_sequence
                self.palace.manifest.update(indexed_sequence=target_sequence, last_successful_sync=time.time())
                await finish_thread(self.palace.save)
            # The durable index checkpoint precedes journal pruning. A crash in
            # between merely repeats harmless work; cache reconstruction is full.
            async with aiosqlite.connect(self.settings.db_path) as conn:
                await conn.execute('DELETE FROM memory_changes WHERE seq<=?',
                                   (min(self.indexed_sequence, self.cache.sequence),))
                await conn.commit()
            remaining = len(self.palace.pending(docs))
            log.info("memory_checkpoint completed=%d/%d pending=%d indexed_sequence=%d watermark=%s",
                     len(docs) - remaining, len(docs), remaining, self.indexed_sequence, self.palace.watermark)

    async def periodic(self):
        retry_at, failures = 0, 0
        while True:
            if self.settings.memory_sync_enabled:
                try:
                    now = time.monotonic()
                    if now >= retry_at:
                        reconcile = now - self.last_reconcile >= 300
                        if reconcile:
                            await self.cache.reconcile(lambda conn: active_run(conn, self.settings))
                            self.last_reconcile = now
                        docs = await self.corpus()
                        async with source_connection(self.settings.db_path) as conn:
                            status = await pending_status(conn, self.indexed_sequence)
                        async with self.lock:
                            # Deletions and metadata updates need no debounce/API.
                            if self.cache.sequence != self.maintained_sequence or reconcile:
                                await finish_thread(self.palace.reuse_vectors, docs)
                                await finish_thread(self.palace.reconcile, docs, reconcile)
                                self.maintained_sequence = self.cache.sequence
                            count = len(self.palace.pending(docs))
                        if reconcile or count >= 32 or status['oldest_pending_age_seconds'] >= 30 or (not count and status['pending_changes']):
                            await self.sync()
                            failures = 0
                            self.last_sync_error = None
                            self.retry_at = 0
                except Exception as exc:
                    # Exception messages from providers may contain request content.
                    failures += 1
                    delay = retry_delay(exc, failures)
                    retry_at = time.monotonic() + delay
                    self.retry_at, self.last_sync_error = retry_at, type(exc).__name__
                    log.warning("memory_sync_failed error_type=%s retry_seconds=%.1f", type(exc).__name__, delay)
            await asyncio.sleep(1)

    async def status(self):
        await self.corpus()
        async with source_connection(self.settings.db_path) as conn:
            status = await pending_status(conn, self.indexed_sequence)
        async with self.lock:
            status.update(source_sequence=self.cache.sequence, indexed_sequence=self.indexed_sequence,
                          pending_documents=len(self.palace.pending(self.cache.docs)),
                          last_successful_sync=self.palace.manifest.get('last_successful_sync'),
                          last_sync_error=self.last_sync_error,
                          retry_after_seconds=max(0, self.retry_at - time.monotonic()),
                          indexing_watermark=self.palace.watermark,
                          synchronization_enabled=self.settings.memory_sync_enabled)
        return status

    async def handle(self, reader, writer):
        try:
            async with asyncio.timeout(60):
                payload = json.loads(await reader.readline())
                operation = payload.pop("operation", "search")
                if operation == "search":
                    prepared_at = time.perf_counter()
                    docs, payload["run_id"] = await self.cache.get(lambda conn: active_run(conn, self.settings))
                    preparation_ms = (time.perf_counter() - prepared_at) * 1000
                    sequence = self.cache.sequence
                    result = (await search(None, payload, self.palace, self.client, prepared_docs=docs, index_lock=self.lock)).model_dump(mode="json")
                    async with source_connection(self.settings.db_path) as conn:
                        result['coverage'].update(await pending_status(conn, self.indexed_sequence))
                    result['coverage'].update(source_sequence=sequence, indexed_sequence=self.indexed_sequence,
                        last_successful_sync=self.palace.manifest.get('last_successful_sync'))
                    result["coverage"]["source_refresh_ms"] = preparation_ms
                    if "local_search_ms" in result["coverage"]:
                        result["coverage"]["local_search_ms"] += preparation_ms
                    import resource
                    result["coverage"]["worker_peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                elif operation == "snapshot":
                    async with self.lock:
                        result = await finish_thread(self.snapshot)
                elif operation == 'status':
                    result = await self.status()
                else:
                    raise ValueError("Unknown operation")
            writer.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")
        except Exception as exc:
            writer.write(json.dumps({"error": type(exc).__name__}).encode() + b"\n")
        finally:
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

    def snapshot(self):
        dest = self.palace.path.parent / "snapshots" / uuid.uuid4().hex
        dest.mkdir(parents=True, mode=0o700)
        for source, name in [(Path(self.settings.db_path), "source.db"),
                             (self.palace.path / "sqlite_exact.sqlite3", "sqlite_exact.sqlite3")]:
            with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
                with sqlite3.connect(dest / name) as target:
                    src.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Snapshot integrity check failed")
        for name in ["index.json", "manifest.json"]:
            path = self.palace.path / name
            if path.exists():
                shutil.copy2(path, dest / name)
        return {"snapshot_path": str(dest)}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "estimate", "sync", "snapshot", "status"])
    args = parser.parse_args()
    settings = get_settings()
    if args.command in {'snapshot', 'status'}:
        print(json.dumps(await request(settings.memory_socket_path, {"operation": args.command}, timeout=60), indent=2))
        return
    path = settings.memory_index_path or str(Path(settings.db_path).parent / "mempalace")
    if args.command == "estimate":
        async with source_connection(settings.db_path) as conn:
            docs = await load_corpus(conn, await active_run(conn, settings))
        print(json.dumps(dict(documents=len(docs), input_tokens=await asyncio.to_thread(token_count, docs))))
        return
    # flock prevents two processes owning the same index, including manual sync.
    import fcntl
    Path(path).mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(Path(path) / "worker.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from klatrebot_v2.db import migrations
        async with aiosqlite.connect(settings.db_path) as conn:
            await migrations.run(conn, pronoun_seeds=getattr(settings, "user_pronoun_seeds", {}))
        from klatrebot_v2.llm.client import get_client
        palace = await asyncio.to_thread(Palace, path)
        worker = Worker(settings, palace, get_client())
        try:
            if args.command == "sync":
                await worker.sync()
                return
            started = time.monotonic()
            docs = await worker.corpus()
            await asyncio.to_thread(palace.warm, docs)
            log.info("memory_worker_prepared seconds=%.2f", time.monotonic() - started)
            socket_path = Path(settings.memory_socket_path)
            socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            socket_path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(worker.handle, path=str(socket_path), limit=65536)
            os.chmod(socket_path, 0o600)
            notify_socket = os.environ.get('NOTIFY_SOCKET')
            if notify_socket:
                address = '\0' + notify_socket[1:] if notify_socket.startswith('@') else notify_socket
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
                    notifier.connect(address)
                    notifier.sendall(b'READY=1')
            task = asyncio.create_task(worker.periodic())
            try:
                async with server:
                    await server.serve_forever()
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                socket_path.unlink(missing_ok=True)
        finally:
            await worker.cache.close()
            await asyncio.to_thread(palace.backend.close)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
