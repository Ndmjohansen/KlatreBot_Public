"""Read-only SQLite connection to the Litestream replica of klatrebot_v2.db.

Single shared connection per Hermes process. Opened with mode=ro URI so any
write attempt fails fast — defense in depth even though the file is also
filesystem read-only.
"""
import os
import sqlite3
from typing import Optional

import sqlite_vec


REPLICA_PATH = os.environ.get(
    "KLATREBOT_REPLICA_PATH",
    "/var/lib/klatrebot-replica/klatrebot_v2.db",
)

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        uri = f"file:{REPLICA_PATH}?mode=ro&immutable=0"
        _conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        try:
            _conn.enable_load_extension(True)
            sqlite_vec.load(_conn)
            _conn.enable_load_extension(False)
        except sqlite3.OperationalError as e:
            # Vector extension load failure is non-fatal; semantic search will
            # raise its own clear error when invoked.
            import logging
            logging.getLogger(__name__).warning(
                "sqlite-vec load failed: %s; semantic search disabled", e
            )
    return _conn
