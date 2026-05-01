"""Tool handlers — receive dict args, return JSON string. ALWAYS return JSON, even on error."""
import json
import logging
import os

import openai

from .db import get_conn


logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def get_recent_messages(args: dict) -> str:
    try:
        channel_id = int(args["channel_id"])
        limit = min(int(args.get("limit", 50)), 500)
    except (KeyError, ValueError, TypeError) as e:
        return _err(f"bad args: {e}")

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT m.discord_message_id, m.user_id,
               COALESCE(u.display_name, '?') AS user_display_name,
               m.content, m.timestamp_utc, m.is_bot
        FROM (
            SELECT * FROM messages WHERE channel_id = ?
            ORDER BY timestamp_utc DESC LIMIT ?
        ) m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, limit),
    ).fetchall()
    return _ok([dict(r) for r in rows])


def search_messages(args: dict) -> str:
    try:
        query = str(args["query"])
    except KeyError:
        return _err("missing 'query'")
    if not query.strip():
        return _err("empty query")
    limit = min(int(args.get("limit", 50)), 500)

    where = ["m.content LIKE ?"]
    params: list = [f"%{query}%"]
    for arg, col in (("channel_id", "m.channel_id"),):
        if arg in args and args[arg] is not None:
            where.append(f"{col} = ?")
            params.append(args[arg])
    if "since" in args and args["since"]:
        where.append("m.timestamp_utc >= ?")
        params.append(args["since"])
    if "until" in args and args["until"]:
        where.append("m.timestamp_utc < ?")
        params.append(args["until"])
    params.append(limit)

    sql = (
        "SELECT m.discord_message_id, m.channel_id, m.user_id, "
        "COALESCE(u.display_name, '?') AS user_display_name, m.content, m.timestamp_utc "
        "FROM messages m LEFT JOIN users u ON u.discord_user_id = m.user_id "
        f"WHERE {' AND '.join(where)} ORDER BY m.timestamp_utc DESC LIMIT ?"
    )
    rows = get_conn().execute(sql, params).fetchall()
    return _ok([dict(r) for r in rows])


async def search_messages_semantic(args: dict) -> str:
    try:
        query = str(args["query"])
    except KeyError:
        return _err("missing 'query'")
    if not query.strip():
        return _err("empty query")
    k = min(int(args.get("k", 20)), 100)

    try:
        client = openai.AsyncOpenAI()
        emb_resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
        qvec = list(emb_resp.data[0].embedding)
    except Exception as e:
        return _err(f"embed failed: {e}")

    where = ["e.embedding MATCH ?", "k = ?"]
    params: list = [json.dumps(qvec), k]
    join = ""
    if "channel_id" in args and args["channel_id"] is not None:
        join = "JOIN messages m ON m.discord_message_id = e.message_id"
        where.append("m.channel_id = ?")
        params.append(int(args["channel_id"]))
    if "since" in args and args["since"]:
        if not join:
            join = "JOIN messages m ON m.discord_message_id = e.message_id"
        where.append("m.timestamp_utc >= ?")
        params.append(args["since"])
    if "until" in args and args["until"]:
        if not join:
            join = "JOIN messages m ON m.discord_message_id = e.message_id"
        where.append("m.timestamp_utc < ?")
        params.append(args["until"])

    sql = (
        f"SELECT e.message_id, e.distance FROM message_embeddings e {join} "
        f"WHERE {' AND '.join(where)} ORDER BY e.distance"
    )
    try:
        hits = get_conn().execute(sql, params).fetchall()
    except Exception as e:
        return _err(f"vector search failed: {e}")
    if not hits:
        return _ok([])

    ids = [int(r[0]) for r in hits]
    placeholders = ",".join("?" * len(ids))
    rows = get_conn().execute(
        f"SELECT m.discord_message_id, m.channel_id, m.user_id, "
        f"COALESCE(u.display_name, '?') AS user_display_name, "
        f"m.content, m.timestamp_utc FROM messages m "
        f"LEFT JOIN users u ON u.discord_user_id = m.user_id "
        f"WHERE m.discord_message_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {r["discord_message_id"]: dict(r) for r in rows}
    out = []
    for mid, dist in hits:
        item = by_id.get(int(mid))
        if item:
            item["distance"] = float(dist)
            out.append(item)
    return _ok(out)


def messages_in_window(args: dict) -> str:
    try:
        channel_id = int(args["channel_id"])
        start = str(args["start"])
        end = str(args["end"])
    except (KeyError, ValueError, TypeError) as e:
        return _err(f"bad args: {e}")
    rows = get_conn().execute(
        """
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?') AS user_display_name,
               m.content, m.timestamp_utc
        FROM messages m LEFT JOIN users u ON u.discord_user_id = m.user_id
        WHERE m.channel_id = ? AND m.timestamp_utc >= ? AND m.timestamp_utc < ?
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, start, end),
    ).fetchall()
    return _ok([dict(r) for r in rows])


def get_attendance(args: dict) -> str:
    try:
        date_local = str(args["date_local"])
        channel_id = int(args["channel_id"])
    except (KeyError, ValueError, TypeError) as e:
        return _err(f"bad args: {e}")
    conn = get_conn()
    sess = conn.execute(
        "SELECT id FROM attendance_session WHERE date_local = ? AND channel_id = ?",
        (date_local, channel_id),
    ).fetchone()
    if not sess:
        return _ok({"yes": [], "no": [], "session_found": False})

    sql = """
        SELECT user_id, status FROM (
            SELECT user_id, status,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp_utc DESC) AS rn
            FROM attendance_reaction_event
            WHERE session_id = ?
        ) WHERE rn = 1
    """
    rows = conn.execute(sql, (sess["id"],)).fetchall()
    yes_ids = [r["user_id"] for r in rows if r["status"] == "yes"]
    no_ids = [r["user_id"] for r in rows if r["status"] == "no"]

    def _names(ids):
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        urows = conn.execute(
            f"SELECT discord_user_id, display_name FROM users WHERE discord_user_id IN ({ph})",
            ids,
        ).fetchall()
        return [{"user_id": r["discord_user_id"], "display_name": r["display_name"]} for r in urows]

    return _ok({"yes": _names(yes_ids), "no": _names(no_ids), "session_found": True})


def get_user(args: dict) -> str:
    try:
        user_id = int(args["user_id"])
    except (KeyError, ValueError, TypeError) as e:
        return _err(f"bad args: {e}")
    row = get_conn().execute(
        "SELECT discord_user_id, display_name, is_admin FROM users WHERE discord_user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return _ok(None)
    return _ok(dict(row))
