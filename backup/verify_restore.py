"""Verify a worker-coordinated ZIP snapshot in a new private directory.

Run through Poetry from the repository root. Never restores over live files.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zipfile

import aiosqlite

from klatrebot_v2.db import messages
from klatrebot_v2.memory.palace import Palace
from klatrebot_v2.memory.transport import request
from klatrebot_v2.memory.worker import Worker

FILES = ('source.db', 'sqlite_exact.sqlite3', 'index.json', 'manifest.json')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    requested_db = Path(args.db).resolve(strict=True)
    directory = Path(args.directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = await request(args.socket, {'operation': 'snapshot', 'db_path': str(requested_db)}, timeout=60)
    if not result.get('source_db_path') or not requested_db.samefile(result['source_db_path']):
        raise RuntimeError('Worker did not confirm the requested database')
    snapshot = Path(result['snapshot_path'])
    archive = directory / 'snapshot.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(snapshot / name, name)
    restored = directory / 'restored'
    restored.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != set(FILES):
            raise ValueError('Unexpected archive members')
        for name in FILES:
            data = bundle.read(name)
            if hashlib.sha256(data).digest() != hashlib.sha256((snapshot / name).read_bytes()).digest():
                raise ValueError('Archive round-trip mismatch')
            (restored / name).write_bytes(data)
    for name in FILES[:2]:
        with sqlite3.connect((restored / name).as_uri() + '?mode=ro', uri=True) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Restored SQLite integrity check failed')
    settings = SimpleNamespace(db_path=str(restored / 'source.db'), memory_active_run_name='production',
                               memory_active_run_id=0, memory_sync_enabled=False)
    palace = Palace(restored)
    worker = Worker(settings, palace, None)
    try:
        docs = await worker.corpus()
        pending_before = len(palace.pending(docs))
        async with aiosqlite.connect(settings.db_path) as conn:
            channel, author = (await conn.execute_fetchall('SELECT channel_id, user_id FROM messages WHERE is_bot=0 AND deleted=0 LIMIT 1'))[0]
            deleted = {r[0] for r in await conn.execute_fetchall('SELECT discord_message_id FROM messages WHERE deleted=1')}
            assert not deleted.intersection(mid for d in docs for mid in d.sources)
            # Exercise recovery on the disposable restored copy, not the archive.
            from datetime import datetime, timezone
            mid = 9000000000000000000
            await messages.insert(conn, discord_message_id=mid, channel_id=channel, user_id=author,
                                  content='Gendannelsestest: jeg aflyser klatring.', timestamp_utc=datetime.now(timezone.utc))
            fresh = await worker.corpus()
            assert any(d.handle == f'msg:{mid}' for d in palace.pending(fresh))
        result = dict(archive_roundtrip=True, source_integrity='ok', index_integrity='ok',
                      source_documents=len(docs), indexed_documents=palace.collection.count(),
                      pending_at_snapshot=pending_before, deleted_messages_excluded=len(deleted),
                      post_restore_change_detected=True)
        (directory / 'report.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        await worker.cache.close()
        palace.backend.close()


if __name__ == '__main__':
    asyncio.run(main())
