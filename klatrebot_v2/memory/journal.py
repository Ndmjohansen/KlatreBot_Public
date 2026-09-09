"""Transactional change capture; no provider calls or index writes in ingestion."""
import time


async def install(conn):
    await conn.execute("""CREATE TRIGGER IF NOT EXISTS message_apply_tombstone
        AFTER INSERT ON message_tombstones BEGIN
        UPDATE messages SET deleted=1, content='' WHERE discord_message_id=NEW.discord_message_id AND deleted=0;
        END""")
    await conn.execute("""CREATE TRIGGER IF NOT EXISTS message_preserve_tombstone
        AFTER INSERT ON messages WHEN EXISTS (
            SELECT 1 FROM message_tombstones WHERE discord_message_id=NEW.discord_message_id
        ) BEGIN UPDATE messages SET deleted=1, content='' WHERE discord_message_id=NEW.discord_message_id; END""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS memory_changes (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
        entity_id INTEGER NOT NULL, operation TEXT NOT NULL,
        enqueued_at REAL NOT NULL DEFAULT (unixepoch()))""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS memory_segment_evidence (
        segment_id INTEGER NOT NULL, message_id INTEGER NOT NULL, content TEXT NOT NULL,
        user_id INTEGER NOT NULL, PRIMARY KEY(segment_id, message_id))""")
    # Seed only once. Subsequent starts must never bless changed historical text.
    await conn.execute("CREATE TABLE IF NOT EXISTS memory_journal_config (key TEXT PRIMARY KEY)")
    await conn.execute("CREATE TABLE IF NOT EXISTS memory_invalid_handles (handle TEXT PRIMARY KEY)")
    await conn.execute("""CREATE VIEW IF NOT EXISTS memory_dependency_edges AS
        SELECT 'msg:' || discord_message_id AS child, 'seg:' || segment_id AS parent FROM segment_messages
        UNION SELECT 'msg:' || discord_message_id, 'mem:' || memory_item_id FROM memory_item_sources
        UNION SELECT 'seg:' || segment_id, 'mem:' || id FROM memory_items
        UNION SELECT 'seg:' || segment_id, 'amb:' || ambient_id FROM daily_ambient_sources
        UNION SELECT CASE source_kind WHEN 'segment' THEN 'seg:' WHEN 'memory_item' THEN 'mem:' ELSE 'roll:' END || source_id,
                     'roll:' || rollup_id FROM memory_rollup_sources""")
    if not await conn.execute_fetchall("SELECT 1 FROM memory_journal_config WHERE key='evidence_seeded'"):
        await conn.execute("""INSERT INTO memory_segment_evidence
            SELECT sm.segment_id, m.discord_message_id, m.content, m.user_id
            FROM segment_messages sm JOIN messages m ON m.discord_message_id=sm.discord_message_id""")
        await conn.execute("INSERT INTO memory_journal_config VALUES ('evidence_seeded')")
    # Only semantically relevant changes generate events. Routine last-seen updates
    # and no-op alias upserts therefore don't invalidate the prepared corpus.
    tables = {
        'messages': ('message', 'discord_message_id', ['content', 'channel_id', 'user_id', 'timestamp_utc', 'is_bot', 'deleted']),
        'users': ('structure', 'discord_user_id', ['display_name']),
        'user_aliases': ('structure', 'discord_user_id', ['alias', 'alias_normalized']),
        'conversation_segments': ('structure', 'id', ['summary', 'topic_title', 'status']),
        'memory_items': ('structure', 'id', ['subject', 'text', 'type']),
        'memory_rollups': ('structure', 'id', ['title', 'summary', 'key_items_json', 'status']),
        'daily_ambient_memory': ('structure', 'id', ['title', 'summary', 'key_items_json', 'status']),
        'segment_messages': ('structure', 'segment_id', ['discord_message_id']),
        'memory_item_sources': ('structure', 'memory_item_id', ['discord_message_id']),
        'memory_rollup_sources': ('structure', 'rollup_id', ['source_kind', 'source_id']),
        'daily_ambient_sources': ('structure', 'ambient_id', ['segment_id']),
        'memory_invalid_handles': ('structure', 'handle', ['handle']),
        'memory_segment_evidence': ('structure', 'segment_id', ['content', 'user_id']),
    }
    for table, (kind, key, columns) in tables.items():
        for operation in ['INSERT', 'UPDATE', 'DELETE']:
            ref = 'OLD' if operation == 'DELETE' else 'NEW'
            condition = ' OR '.join(f'OLD.{c} IS NOT NEW.{c}' for c in columns)
            when = f'WHEN {condition}' if operation == 'UPDATE' else ''
            await conn.execute(f"""CREATE TRIGGER IF NOT EXISTS memory_capture_{table}_{operation}
                AFTER {operation} ON {table} {when} BEGIN
                INSERT INTO memory_changes(kind, entity_id, operation)
                VALUES ('{kind}', {ref}.{key}, '{operation}'); END""")
    # Persist evidence invalidation independently of the prunable work journal.
    for operation in ['UPDATE', 'DELETE']:
        when = "WHEN " + ' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in tables['messages'][2]) if operation == 'UPDATE' else ''
        await conn.execute(f"""CREATE TRIGGER IF NOT EXISTS memory_evidence_{operation}
            AFTER {operation} ON messages {when} BEGIN
            INSERT OR IGNORE INTO memory_invalid_handles
            WITH RECURSIVE affected(handle) AS (
                SELECT parent FROM memory_dependency_edges WHERE child='msg:' || OLD.discord_message_id
                UNION SELECT parent FROM memory_dependency_edges JOIN affected ON child=affected.handle
            ) SELECT handle FROM affected;
            END""")
    for table, prefix in [('conversation_segments', 'seg'), ('memory_items', 'mem'), ('memory_rollups', 'roll'), ('daily_ambient_memory', 'amb')]:
        fields = tables[table][2]
        when = ' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in fields)
        await conn.execute(f"""CREATE TRIGGER IF NOT EXISTS memory_change_parent_{prefix}
            BEFORE UPDATE ON {table} WHEN {when} BEGIN
            INSERT OR IGNORE INTO memory_invalid_handles
            WITH RECURSIVE affected(handle) AS (
                SELECT parent FROM memory_dependency_edges WHERE child='{prefix}:' || OLD.id
                UNION SELECT parent FROM memory_dependency_edges JOIN affected ON child=affected.handle
            ) SELECT handle FROM affected;
            END""")
        await conn.execute(f"""CREATE TRIGGER IF NOT EXISTS memory_remove_{prefix} BEFORE DELETE ON {table} BEGIN
            INSERT OR IGNORE INTO memory_invalid_handles
            WITH RECURSIVE affected(handle) AS (
                SELECT parent FROM memory_dependency_edges WHERE child='{prefix}:' || OLD.id
                UNION SELECT parent FROM memory_dependency_edges JOIN affected ON child=affected.handle
            ) SELECT handle FROM affected;
            DELETE FROM memory_invalid_handles WHERE handle='{prefix}:' || OLD.id;
            END""")
    await conn.execute("""CREATE TRIGGER IF NOT EXISTS memory_remove_evidence AFTER DELETE ON conversation_segments
        BEGIN DELETE FROM memory_segment_evidence WHERE segment_id=OLD.id; END""")
    await conn.execute("""CREATE VIEW IF NOT EXISTS memory_invalid_current AS
        WITH RECURSIVE invalid(handle) AS (
            SELECT handle FROM memory_invalid_handles
            UNION SELECT 'seg:' || e.segment_id FROM memory_segment_evidence e
            LEFT JOIN messages m ON m.discord_message_id=e.message_id
            WHERE m.discord_message_id IS NULL OR m.deleted=1 OR m.content IS NOT e.content OR m.user_id IS NOT e.user_id
            UNION SELECT parent FROM memory_dependency_edges JOIN invalid ON child=invalid.handle
        ) SELECT handle FROM invalid""")


async def boundary(conn):
    rows = await conn.execute_fetchall("SELECT seq FROM sqlite_sequence WHERE name='memory_changes'")
    return rows[0][0] if rows else 0


async def pending_status(conn, indexed_seq):
    count, oldest = (await conn.execute_fetchall(
        "SELECT count(*), min(enqueued_at) FROM memory_changes WHERE seq>?", (indexed_seq,)))[0]
    return dict(pending_changes=count, oldest_pending_age_seconds=max(0, time.time() - oldest) if oldest else 0)
