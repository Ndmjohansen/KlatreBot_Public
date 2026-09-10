"""Concurrent Pi benchmark on isolated SQLite/index copies; never writes live data."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import aiosqlite

from klatrebot_v2.db import migrations, messages
from klatrebot_v2.memory.evaluate import percentile
from klatrebot_v2.memory.journal import boundary
from klatrebot_v2.memory.transport import request


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True)
    parser.add_argument('--source-index', required=True)
    parser.add_argument('--workdir', required=True)
    parser.add_argument('--duration', type=int, default=1800)
    args = parser.parse_args()
    work = Path(args.workdir).resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    index = work / 'index'
    index.mkdir(mode=0o700)
    # Snapshot only while no process owns the source index.
    import fcntl
    with open(Path(args.source_index) / 'worker.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for source, target in [(Path(args.source_db), work / 'source.db'),
                               (Path(args.source_index) / 'sqlite_exact.sqlite3', index / 'sqlite_exact.sqlite3')]:
            with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
        for name in ['manifest.json', 'index.json']:
            shutil.copy2(Path(args.source_index) / name, index / name)
    source = str(work / 'source.db')
    socket = str(work / 'worker.sock')
    async with aiosqlite.connect(source) as conn:
        await conn.execute('PRAGMA journal_mode=WAL')
        await migrations.run(conn)
        channel, author = (await conn.execute_fetchall(
            'SELECT channel_id, user_id FROM messages WHERE is_bot=0 GROUP BY channel_id, user_id ORDER BY count(*) DESC LIMIT 1'))[0]
    env = dict(os.environ, DB_PATH=source, MEMORY_INDEX_PATH=str(index), MEMORY_SOCKET_PATH=socket,
               MEMORY_SYNC_ENABLED='true', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    rows, changes, lags = [], [], []
    started = time.monotonic()
    with open(work / 'worker.log', 'w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'klatrebot_v2.memory.worker', 'serve'], env=env, stdout=log, stderr=log)
        try:
            while not Path(socket).exists():
                if process.poll() is not None or time.monotonic() - started > 120:
                    raise RuntimeError('Worker failed readiness')
                await asyncio.sleep(.25)
            ready_seconds = time.monotonic() - started
            started = time.monotonic()

            async def write_load():
                async with aiosqlite.connect(source) as conn:
                    mid = 8000000000000000000
                    next_regular, burst = 0, 0
                    edited = published = False
                    while time.monotonic() - started < args.duration:
                        elapsed = time.monotonic() - started
                        regular = elapsed >= next_regular
                        in_burst = 60 <= elapsed < 120 and burst < int(elapsed - 60) + 1
                        if regular or in_burst:
                            mid += 1
                            await messages.insert(conn, discord_message_id=mid, channel_id=channel, user_id=author,
                                content=f'Benchmark {mid}: Jeg aflyser klatring, skal passe katten.', timestamp_utc=datetime.now(timezone.utc))
                            changes.append((await boundary(conn), time.monotonic()))
                            if regular:
                                next_regular += 10
                            if in_burst:
                                burst += 1
                        if elapsed >= 125 and not edited:
                            await messages.edit(conn, 8000000000000000001, 'Benchmark: Jeg kommer alligevel til klatring.')
                            changes.append((await boundary(conn), time.monotonic()))
                            await messages.delete(conn, [8000000000000000002])
                            changes.append((await boundary(conn), time.monotonic()))
                            edited = True
                        if elapsed >= 150 and not published:
                            # Publication of a compiler record exercises structural refresh.
                            # All mutations are confined to this isolated source copy.
                            await conn.execute("UPDATE conversation_segments SET summary=summary || char(10) || 'Benchmark publication' WHERE id=(SELECT max(id) FROM conversation_segments WHERE status='summarized')")
                            await conn.commit()
                            changes.append((await boundary(conn), time.monotonic()))
                            published = True
                        await asyncio.sleep(.2)

            async def search_load():
                step = 0
                while time.monotonic() - started < args.duration:
                    due = started + step * 10
                    await asyncio.sleep(max(0, due - time.monotonic()))
                    payload = dict(query=['Hvem aflyste klatring?', 'Hvorfor kunne personen ikke komme?', 'Hvad aftalte vi om transport?'][step % 3], channel_id=channel, limit=10)
                    if step % 3:
                        payload['people'] = [author]
                    if step % 3 == 2:
                        payload['order'] = 'latest'
                    begin = time.monotonic()
                    try:
                        result = await request(socket, payload, timeout=60)
                        coverage = result['coverage']
                        evidence = result['results'] + coverage.get('chronological_page', [])
                        rows.append(dict(elapsed_ms=(time.monotonic() - begin) * 1000,
                            local_ms=coverage['local_search_ms'], refresh_ms=coverage['source_refresh_ms'],
                            index_timings=coverage.get('index_timings'),
                            rss_mib=coverage['worker_peak_rss_mb'], status=result['status'],
                            filters_ok=all((not payload.get('people') or r['participants'] == [author]) and
                                all(e['channel_id'] == channel for e in r['source_excerpts']) for r in evidence)))
                    except Exception as exc:
                        rows.append(dict(status=type(exc).__name__, elapsed_ms=(time.monotonic() - begin) * 1000))
                    step += 1

            async def observe():
                observed, last_report = set(), 0
                while time.monotonic() - started < args.duration + 120:
                    manifest = json.loads((index / 'manifest.json').read_text())
                    seq = manifest.get('indexed_sequence', 0)
                    for i, (change, when) in enumerate(changes):
                        if i not in observed and change <= seq:
                            observed.add(i)
                            lags.append(time.monotonic() - when)
                    elapsed = time.monotonic() - started
                    if elapsed - last_report >= 30:
                        progress = dict(elapsed_seconds=round(elapsed), requests=len(rows), changes=len(changes), indexed=len(observed),
                            max_lag_seconds=round(max(lags, default=0), 2),
                            local_p95_ms=percentile([r['local_ms'] for r in rows if 'local_ms' in r], .95),
                            total_p95_ms=percentile([r['elapsed_ms'] for r in rows], .95),
                            peak_rss_mib=max((r.get('rss_mib', 0) for r in rows), default=0))
                        (work / 'progress.json').write_text(json.dumps(dict(summary=progress, requests=rows), indent=2))
                        print(json.dumps(progress), flush=True)
                        last_report = elapsed
                    if elapsed >= args.duration and len(observed) == len(changes):
                        break
                    await asyncio.sleep(1)
                return len(changes) - len(observed)

            _, _, outstanding = await asyncio.gather(write_load(), search_load(), observe())
            summary = dict(duration_seconds=args.duration, startup_seconds=ready_seconds, requests=len(rows),
                retrieval_p95_ms=percentile([r['elapsed_ms'] for r in rows], .95),
                local_p95_ms=percentile([r['local_ms'] for r in rows if 'local_ms' in r], .95),
                peak_rss_mib=max((r.get('rss_mib', 0) for r in rows), default=0),
                max_index_lag_seconds=max(lags, default=0), unindexed_changes=outstanding,
                errors=sum(r['status'] != 'ok' for r in rows), filter_failures=sum(not r.get('filters_ok', True) for r in rows))
            (work / 'report.json').write_text(json.dumps(dict(summary=summary, requests=rows, indexing_lags=lags), indent=2))
            print(json.dumps(summary, indent=2), flush=True)
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 15)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


if __name__ == '__main__':
    asyncio.run(main())
