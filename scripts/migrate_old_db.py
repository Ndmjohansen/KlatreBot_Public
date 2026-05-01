"""Migrate v1 klatrebot.db -> v2 schema.

Old schema (v1):
    users(discord_user_id, display_name, message_count, is_admin, created_at, updated_at)
    messages(discord_message_id, discord_channel_id, discord_user_id, content,
             message_type, timestamp, created_at, has_embedding)
    message_embeddings(discord_message_id, embedding BLOB[pickled list[float]],
                       embedding_model, created_at)

New schema (v2): see klatrebot_v2/db/migrations.py.
    users: drop message_count.
    messages: discord_channel_id->channel_id, discord_user_id->user_id,
              timestamp->timestamp_utc, message_type->is_bot (bot_response=1 else 0).
    message_embeddings: vec0 virtual table, FLOAT[1536]. Convert pickled list -> float32 bytes.

Attendance tables in v2 have no v1 source -> left empty.

Usage:
    poetry run python tools/migrate_old_db.py \
        --src C:/Users/Admin/Downloads/oldbot/klatrebot.db \
        --dst ./klatrebot_v2.db [--skip-embeddings] [--batch 1000]

Idempotent for users/messages (INSERT OR IGNORE on PK). Embeddings are
re-inserted only for message_ids not already present in vec0 table.
"""
from __future__ import annotations

import argparse
import logging
import pickle
import sqlite3
import struct
import sys
from pathlib import Path

try:
    import sqlite_vec
except ImportError:
    sqlite_vec = None

log = logging.getLogger("migrate")


def _open_dst(path: str, load_vec: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if load_vec:
        if sqlite_vec is None:
            log.warning("sqlite_vec not installed; embeddings will be skipped")
            return conn
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            log.info("sqlite-vec loaded")
        except (AttributeError, sqlite3.OperationalError) as e:
            log.warning("sqlite-vec load failed (%s); embeddings will be skipped", e)
    return conn


def _bootstrap_schema(dst: sqlite3.Connection, vec_available: bool) -> bool:
    """Apply v2 schema. Returns True iff vec0 virtual table was created."""
    from klatrebot_v2.db.migrations import DDL, VEC_DDL
    for stmt in DDL:
        dst.execute(stmt)
    has_vec = False
    if vec_available:
        try:
            dst.execute(VEC_DDL)
            has_vec = True
        except sqlite3.OperationalError as e:
            log.warning("vec0 virtual table creation failed (%s)", e)
    dst.commit()
    return has_vec


def _migrate_users(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    rows = src.execute(
        "SELECT discord_user_id, display_name, is_admin, created_at, updated_at FROM users"
    ).fetchall()
    before = dst.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    dst.executemany(
        """INSERT OR IGNORE INTO users
           (discord_user_id, display_name, is_admin, created_at, updated_at)
           VALUES (?, COALESCE(?, ''), COALESCE(?, 0),
                   COALESCE(?, datetime('now')), COALESCE(?, datetime('now')))""",
        rows,
    )
    dst.commit()
    after = dst.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return after - before


def _migrate_messages(
    src: sqlite3.Connection, dst: sqlite3.Connection, batch: int
) -> int:
    cur_src = src.execute(
        """SELECT discord_message_id, discord_channel_id, discord_user_id,
                  content, message_type, timestamp
           FROM messages"""
    )
    before = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    buf: list[tuple] = []
    sql = (
        "INSERT OR IGNORE INTO messages "
        "(discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    for mid, ch, uid, content, mtype, ts in cur_src:
        if ch is None or uid is None or ts is None:
            continue
        is_bot = 1 if mtype == "bot_response" else 0
        buf.append((mid, ch, uid, content or "", ts, is_bot))
        if len(buf) >= batch:
            dst.executemany(sql, buf)
            buf.clear()
    if buf:
        dst.executemany(sql, buf)
    dst.commit()
    after = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return after - before


_F32_DIM = 1536


def _pickle_to_f32_bytes(blob: bytes) -> bytes | None:
    try:
        vec = pickle.loads(blob)
    except Exception as e:
        log.debug("unpickle failed: %s", e)
        return None
    if not hasattr(vec, "__len__") or len(vec) != _F32_DIM:
        log.debug("unexpected embedding shape: len=%s", getattr(vec, "__len__", lambda: "?")())
        return None
    try:
        return struct.pack(f"<{_F32_DIM}f", *vec)
    except (struct.error, TypeError) as e:
        log.debug("pack failed: %s", e)
        return None


def _migrate_embeddings(
    src: sqlite3.Connection, dst: sqlite3.Connection, batch: int
) -> tuple[int, int]:
    existing = {
        r[0] for r in dst.execute("SELECT message_id FROM message_embeddings")
    }
    valid_msg_ids = {r[0] for r in dst.execute("SELECT discord_message_id FROM messages")}
    cur_src = src.execute("SELECT discord_message_id, embedding FROM message_embeddings")
    ok = skipped = 0
    buf: list[tuple] = []
    for mid, blob in cur_src:
        if mid in existing or mid not in valid_msg_ids or blob is None:
            skipped += 1
            continue
        packed = _pickle_to_f32_bytes(blob)
        if packed is None:
            skipped += 1
            continue
        buf.append((mid, packed))
        if len(buf) >= batch:
            dst.executemany(
                "INSERT INTO message_embeddings(message_id, embedding) VALUES (?, ?)", buf
            )
            ok += len(buf)
            buf.clear()
    if buf:
        dst.executemany(
            "INSERT INTO message_embeddings(message_id, embedding) VALUES (?, ?)", buf
        )
        ok += len(buf)
    dst.commit()
    return ok, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="Path to v1 klatrebot.db")
    ap.add_argument("--dst", required=True, help="Path to v2 sqlite db (created if missing)")
    ap.add_argument("--skip-embeddings", action="store_true", help="Do not migrate vec embeddings")
    ap.add_argument("--batch", type=int, default=1000)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    src_path = Path(args.src)
    if not src_path.exists():
        log.error("source not found: %s", src_path)
        return 2

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = _open_dst(args.dst, load_vec=not args.skip_embeddings)
    has_vec = _bootstrap_schema(dst, vec_available=not args.skip_embeddings)

    n_users = _migrate_users(src, dst)
    log.info("users: inserted %d", n_users)

    n_msgs = _migrate_messages(src, dst, args.batch)
    log.info("messages: inserted %d", n_msgs)

    if args.skip_embeddings:
        log.info("embeddings: skipped (--skip-embeddings)")
    elif not has_vec:
        log.warning("embeddings: skipped (vec0 unavailable)")
    else:
        ok, skipped = _migrate_embeddings(src, dst, args.batch)
        log.info("embeddings: inserted %d, skipped %d", ok, skipped)

    src.close()
    dst.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
