"""Source-of-truth documents shared by the worker and degraded retrieval."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import re
from functools import cached_property


def utc(value):
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass
class Document:
    id: str
    handle: str
    text: str
    kind: str
    channel: int
    timestamp: str
    sources: list[int]
    authors: list[int]
    subjects: list[int]
    excerpts: list[dict]

    @cached_property
    def digest(self):
        # Same serialized fields as asdict(), without recursively copying provenance.
        values = {field.name: getattr(self, field.name) for field in fields(self)}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    @cached_property
    def terms(self):
        return frozenset(re.findall(r"\w{2,}", self.text.casefold()))

    @cached_property
    def source_start(self):
        return min(utc(e["timestamp_utc"]) for e in self.excerpts)

    @cached_property
    def source_end(self):
        return utc(self.timestamp)


class CorpusState:
    """Reusable documents; state is published only after a successful source read."""
    def __init__(self):
        self.messages = {}
        self.aliases = None
        self.specs = {}
        self.documents = {}
        self.dependencies = {}
        self.subject_patterns = []


async def load_corpus(conn, run_id, state=None):
    """Bulk reads; derived authorship requires unanimous human source authorship.

    Subjects require a mention or an unambiguous name in the document text.
    Original source timestamps also define derived document dates.
    """
    rows = await conn.execute_fetchall(
        "SELECT discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot FROM messages WHERE deleted=0"
    )
    messages = {r[0]: r for r in rows}
    state = state or CorpusState()
    changed_messages = {mid for mid in messages.keys() | state.messages.keys()
                        if messages.get(mid) != state.messages.get(mid)}
    aliases = {}
    alias_rows = await conn.execute_fetchall(
        "SELECT discord_user_id, display_name FROM users UNION SELECT discord_user_id, alias FROM user_aliases"
    )
    aliases_changed = alias_rows != state.aliases
    for uid, name in alias_rows:
        if name.strip():
            aliases.setdefault(name.casefold().strip(), set()).add(uid)
    subject_patterns = [(name, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)"), next(iter(ids)))
                        for name, ids in aliases.items() if len(ids) == 1]

    def subjects_in(text):
        ids = {int(x) for x in re.findall(r"<@!?(\d+)>", text)}
        lower = text.casefold()
        ids.update(uid for name, pattern, uid in subject_patterns if name in lower and pattern.search(lower))
        return sorted(ids)
    sources = {}
    invalid = {f'seg:{r[0]}' for r in await conn.execute_fetchall("""
        SELECT DISTINCT e.segment_id FROM memory_segment_evidence e
        LEFT JOIN messages m ON m.discord_message_id=e.message_id
        WHERE m.discord_message_id IS NULL OR m.deleted=1
           OR m.content IS NOT e.content OR m.user_id IS NOT e.user_id""")}
    invalid.update(r[0] for r in await conn.execute_fetchall('SELECT handle FROM memory_invalid_handles'))
    for mid, sid in await conn.execute_fetchall("SELECT id, segment_id FROM memory_items"):
        if f'seg:{sid}' in invalid:
            invalid.add(f'mem:{mid}')
    for table, column, prefix in [("segment_messages", "segment_id", "seg"),
                                   ("memory_item_sources", "memory_item_id", "mem")]:
        for parent, mid in await conn.execute_fetchall(f"SELECT {column}, discord_message_id FROM {table}"):
            sources.setdefault(f"{prefix}:{parent}", set()).add(mid)
    for aid, sid in await conn.execute_fetchall("SELECT ambient_id, segment_id FROM daily_ambient_sources"):
        sources.setdefault(f"amb:{aid}", set()).update(sources.get(f"seg:{sid}", set()))
        if f'seg:{sid}' in invalid:
            invalid.add(f'amb:{aid}')
    links = await conn.execute_fetchall("SELECT rollup_id, source_kind, source_id FROM memory_rollup_sources")
    # Monotonic fixed point handles nested rollups, including malformed cycles.
    for _ in range(len({r[0] for r in links}) + 1):
        changed = False
        for rid, kind, sid in links:
            source_handle = f"{ {'segment': 'seg', 'memory_item': 'mem', 'rollup': 'roll'}[kind]}:{sid}"
            if source_handle in invalid and f'roll:{rid}' not in invalid:
                invalid.add(f'roll:{rid}')
                changed = True
            target = sources.setdefault(f"roll:{rid}", set())
            before = len(target)
            target.update(sources.get(f"{ {'segment': 'seg', 'memory_item': 'mem', 'rollup': 'roll'}[kind]}:{sid}", set()))
            changed |= len(target) != before
        if not changed:
            break
    docs = []
    specs_by_handle, documents_by_handle = {}, {}
    # Share original source excerpts across summaries instead of copying each source.
    excerpts_by_id = {r[0]: dict(discord_message_id=r[0], user_id=r[2], channel_id=r[1],
                                timestamp_utc=utc(r[4]).isoformat(), content=r[3])
                      for r in rows if not r[5]}

    def add(handle, text, kind, mids):
        if handle in invalid:
            return
        mids = tuple(sorted(mids))
        spec = (text, kind, mids)
        specs_by_handle[handle] = spec
        if (not aliases_changed and state.specs.get(handle) == spec
                and not changed_messages.intersection(mids)):
            reused = state.documents.get(handle, [])
            documents_by_handle[handle] = reused
            docs.extend(reused)
            return
        evidence = [messages[mid] for mid in mids if mid in messages and not messages[mid][5]]
        if not text.strip() or not evidence:
            return
        # Cross-channel derived content cannot satisfy a single channel constraint.
        channels = {r[1] for r in evidence}
        if len(channels) != 1:
            return
        authors = sorted({r[2] for r in evidence})
        excerpts = [excerpts_by_id[r[0]] for r in evidence]
        timestamp = max(e["timestamp_utc"] for e in excerpts)
        source_ids = [r[0] for r in evidence]
        subjects = subjects_in(text)
        chunks = []
        # Even four-byte Unicode characters stay below 6,000 UTF-8 bytes/tokens.
        for offset in range(0, len(text), 1500):
            chunks.append(Document(f"{handle}:{offset // 1500}", handle, text[offset:offset + 1500],
                                   kind, evidence[0][1], timestamp, source_ids, authors, subjects, excerpts))
        documents_by_handle[handle] = chunks
        docs.extend(chunks)

    for mid, channel, author, text, timestamp, bot in rows:
        if not bot:
            add(f"msg:{mid}", text, "raw_message", [mid])
    specs = [
        ("SELECT id, topic_title || char(10) || summary, 'segment_summary', participant_ids_json FROM conversation_segments WHERE compiler_run_id=? AND status='summarized'", "seg"),
        ("SELECT mi.id, mi.subject || char(10) || mi.text, mi.type, mi.speaker_ids_json FROM memory_items mi JOIN conversation_segments cs ON cs.id=mi.segment_id WHERE mi.compiler_run_id=? AND cs.status='summarized'", "mem"),
        ("SELECT id, title || char(10) || summary || char(10) || key_items_json, 'rollup_' || period_type, '[]' FROM memory_rollups WHERE compiler_run_id=? AND status='completed'", "roll"),
        ("SELECT id, title || char(10) || summary || char(10) || key_items_json, 'daily_ambient', '[]' FROM daily_ambient_memory WHERE compiler_run_id=? AND status='completed'", "amb"),
    ]
    for sql, prefix in specs:
        for did, text, kind, subjects in await conn.execute_fetchall(sql, (run_id,)):
            handle = f"{prefix}:{did}"
            add(handle, text, kind, sources.get(handle, []))
    state.messages, state.aliases = messages, alias_rows
    state.specs, state.documents = specs_by_handle, documents_by_handle
    state.subject_patterns = subject_patterns
    state.dependencies = {}
    for handle, mids in sources.items():
        for mid in mids:
            state.dependencies.setdefault(mid, set()).add(handle)
    for mid, sid in await conn.execute_fetchall('SELECT id, segment_id FROM memory_items'):
        for source_id in sources.get(f'seg:{sid}', ()):
            state.dependencies.setdefault(source_id, set()).add(f'mem:{mid}')
    return docs


async def apply_message_changes(conn, state, mids):
    """Update only changed raw documents; invalidate their existing derivatives."""
    for mid in mids:
        rows = await conn.execute_fetchall(
            "SELECT discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot FROM messages WHERE discord_message_id=? AND deleted=0", (mid,))
        row = rows[0] if rows else None
        old = state.messages.get(mid)
        if row == old:
            continue
        handle = f'msg:{mid}'
        if old is not None:
            for derived in state.dependencies.get(mid, ()):
                state.documents.pop(derived, None)
                state.specs.pop(derived, None)
        if row is None:
            state.documents.pop(handle, None)
            state.specs.pop(handle, None)
            state.messages.pop(mid, None)
            continue
        state.messages[mid] = row
        _, channel, author, content, timestamp, bot = row
        if bot or not content.strip():
            state.documents.pop(handle, None)
            state.specs.pop(handle, None)
            continue
        lower = content.casefold()
        subjects = {int(x) for x in re.findall(r'<@!?(\d+)>', content)}
        subjects.update(uid for name, pattern, uid in state.subject_patterns if name in lower and pattern.search(lower))
        timestamp = utc(timestamp).isoformat()
        excerpts = [dict(discord_message_id=mid, user_id=author, channel_id=channel,
                         timestamp_utc=timestamp, content=content)]
        state.documents[handle] = [Document(f'{handle}:{offset // 1500}', handle,
            content[offset:offset + 1500], 'raw_message', channel, timestamp, [mid],
            [author], sorted(subjects), excerpts) for offset in range(0, len(content), 1500)]
        state.specs[handle] = (content, 'raw_message', (mid,))
    return [doc for chunks in state.documents.values() for doc in chunks]
