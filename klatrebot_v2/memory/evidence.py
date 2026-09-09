"""Check compiler inputs across provider waits before publishing derived claims."""
import hashlib
import json

TABLES = {'msg': 'messages', 'seg': 'conversation_segments', 'mem': 'memory_items',
          'roll': 'memory_rollups', 'amb': 'daily_ambient_memory'}
PREFIXES = {'segment': 'seg', 'skipped_segment': 'seg', 'memory_item': 'mem', 'rollup': 'roll'}


async def signature(conn, sources):
    handles = [f"{PREFIXES[s['kind']]}:{s['id']}" for s in sources]
    invalid = {r[0] for r in await conn.execute_fetchall('SELECT handle FROM memory_invalid_current')}
    if invalid.intersection(handles):
        raise ValueError('Compiler source invalidated')
    values = {}
    todo = list(handles)
    while todo:
        handle = todo.pop()
        if handle in values:
            continue
        prefix, sid = handle.split(':')
        key = 'discord_message_id' if prefix == 'msg' else 'id'
        cursor = await conn.execute(f'SELECT * FROM {TABLES[prefix]} WHERE {key}=?', (int(sid),))
        row = await cursor.fetchone()
        if row is None:
            raise ValueError('Compiler source removed')
        data = dict(zip([c[0] for c in cursor.description], row))
        if data.get('deleted'):
            raise ValueError('Compiler source deleted')
        children = sorted(r[0] for r in await conn.execute_fetchall('SELECT child FROM memory_dependency_edges WHERE parent=?', (handle,)))
        values[handle] = (data, children)
        todo.extend(children)
    for source, handle in zip(sources, handles):
        row = values[handle][0]
        for key in ('summary', 'text'):
            if key in source and source[key] != row.get(key):
                raise ValueError('Compiler source changed before generation')
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


async def verify_publication(conn, handle, sources, expected):
    try:
        valid = await signature(conn, sources) == expected
    except ValueError:
        valid = False
    if not valid:
        await conn.execute('INSERT OR IGNORE INTO memory_invalid_handles VALUES (?)', (handle,))
        await conn.commit()
    return valid
