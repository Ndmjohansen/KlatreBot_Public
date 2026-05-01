"""Normalize timestamp columns to ISO 8601 with explicit UTC offset.

Problem: v1 wrote `YYYY-MM-DD HH:MM:SS` (space, no tz). v2 writes
`datetime.isoformat()` -> `YYYY-MM-DDTHH:MM:SS+00:00`. Both stored as TEXT.
Lex order disagrees across the boundary (space 0x20 < 'T' 0x54), so
`WHERE timestamp_utc >= ? AND timestamp_utc < ?` range scans break when
the bounds straddle formats.

Fix: rewrite every row to canonical ISO with `+00:00`. Naive (no tz)
strings are assumed UTC — column is named *_utc and v1 stored UTC.

Targeted columns:
    messages.timestamp_utc
    attendance_session.klatring_start_utc
    attendance_reaction_event.timestamp_utc

NOT touched:
    users.created_at / updated_at — v2 default is `datetime('now')` which
    is itself space-separated. Normalizing would diverge from native v2
    inserts. These columns aren't used for range queries.

Idempotent: rows already in canonical form are skipped (no-op UPDATE).

Usage:
    poetry run python scripts/normalize_timestamps.py --db ./klatrebot_v2.db [--dry-run] [-v]
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("normalize")

TARGETS: list[tuple[str, str, str]] = [
    # (table, pk_column, ts_column)
    ("messages", "discord_message_id", "timestamp_utc"),
    ("attendance_session", "id", "klatring_start_utc"),
    ("attendance_reaction_event", "id", "timestamp_utc"),
]


def _canonical(raw: str) -> str | None:
    """Return canonical form, or None if already canonical / unparseable."""
    if not raw:
        return None
    # Already canonical: has 'T' separator AND a tz suffix.
    has_t = "T" in raw
    has_tz = raw.endswith("Z") or "+" in raw[10:] or "-" in raw[10:]
    s = raw.replace(" ", "T", 1) if " " in raw else raw
    s = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        log.warning("unparseable timestamp: %r", raw)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    canon = dt.isoformat()
    if has_t and has_tz and canon == raw:
        return None
    return canon


def _normalize_table(
    conn: sqlite3.Connection, table: str, pk: str, col: str, dry_run: bool
) -> tuple[int, int]:
    if not _table_exists(conn, table):
        log.info("%s: table missing, skipped", table)
        return 0, 0
    rows = conn.execute(f"SELECT {pk}, {col} FROM {table}").fetchall()
    updates: list[tuple[str, int]] = []
    skipped = 0
    for pk_val, ts in rows:
        canon = _canonical(ts)
        if canon is None:
            skipped += 1
            continue
        updates.append((canon, pk_val))
    if updates and not dry_run:
        conn.executemany(f"UPDATE {table} SET {col} = ? WHERE {pk} = ?", updates)
        conn.commit()
    log.info(
        "%s.%s: %d to update, %d unchanged%s",
        table, col, len(updates), skipped, " (dry-run)" if dry_run else "",
    )
    return len(updates), skipped


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return r is not None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True, help="Path to klatrebot v2 sqlite db")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    p = Path(args.db)
    if not p.exists():
        log.error("db not found: %s", p)
        return 2

    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    total_updated = 0
    for table, pk, col in TARGETS:
        n, _ = _normalize_table(conn, table, pk, col, args.dry_run)
        total_updated += n

    log.info("done. %d rows %s", total_updated, "would update" if args.dry_run else "updated")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
