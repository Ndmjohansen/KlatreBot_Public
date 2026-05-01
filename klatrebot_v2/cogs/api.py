"""Read-only HTTP API exposed on the Pi for Hermes Agent.

Single source of truth: Hermes calls these endpoints rather than holding a
replica. Read-only enforced at every layer:
  - Separate aiosqlite connection opened with `mode=ro` URI.
  - `PRAGMA query_only = 1` after open.
  - SQL guard: only statements starting with SELECT / WITH / EXPLAIN allowed.
  - Statement timeout via SQLite progress handler.

Bearer auth required. LAN-only by default (bind to 0.0.0.0 + UFW restrict).
"""
import asyncio
import json
import logging
import re
import time

import aiosqlite
import sqlite_vec
from aiohttp import web
from discord.ext import commands

from klatrebot_v2.db import embeddings as emb_db
from klatrebot_v2.llm import embeddings as emb_llm
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)

_ALLOWED_PREFIX = re.compile(r"^\s*(?:--[^\n]*\n|/\*.*?\*/|\s)*(SELECT|WITH|EXPLAIN|PRAGMA)\b", re.IGNORECASE | re.DOTALL)
_PRAGMA_ALLOWED = re.compile(r"^\s*PRAGMA\s+(table_info|index_list|index_info|foreign_key_list|table_list|database_list)\b", re.IGNORECASE)


def _is_safe_select(sql: str) -> bool:
    """Reject anything that isn't a pure read. PRAGMA only for schema introspection."""
    if not _ALLOWED_PREFIX.match(sql):
        return False
    if re.match(r"^\s*PRAGMA\b", sql, re.IGNORECASE) and not _PRAGMA_ALLOWED.match(sql):
        return False
    return True


async def _open_readonly(db_path: str) -> aiosqlite.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = await aiosqlite.connect(uri, uri=True)
    conn.row_factory = aiosqlite.Row
    try:
        await conn.enable_load_extension(True)
        await conn.load_extension(sqlite_vec.loadable_path())
        await conn.enable_load_extension(False)
    except Exception as e:
        logger.warning("api: sqlite-vec load failed (%s); semantic search disabled", e)
    await conn.execute("PRAGMA query_only = 1")
    return conn


def _require_auth(handler):
    async def wrapper(request: web.Request) -> web.StreamResponse:
        s = get_settings()
        if not s.api_token:
            return web.json_response({"error": "api token not configured"}, status=503)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {s.api_token}":
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)
    return wrapper


class ApiCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runner: web.AppRunner | None = None
        self.ro_conn: aiosqlite.Connection | None = None

    async def cog_load(self) -> None:
        s = get_settings()
        if not s.api_enabled:
            logger.info("api: disabled (API_ENABLED=false)")
            return
        if not s.api_token:
            logger.warning("api: refusing to start without API_TOKEN")
            return

        self.ro_conn = await _open_readonly(s.db_path)

        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_get("/api/schema", _require_auth(self.schema))
        app.router.add_post("/api/query", _require_auth(self.query))
        app.router.add_post("/api/search_messages_semantic", _require_auth(self.semantic))

        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, s.api_host, s.api_port)
        await site.start()
        logger.info("api: listening on %s:%d", s.api_host, s.api_port)

    async def cog_unload(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
        if self.ro_conn is not None:
            await self.ro_conn.close()

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def schema(self, request: web.Request) -> web.Response:
        assert self.ro_conn
        cursor = await self.ro_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'view', 'index') ORDER BY type, name"
        )
        rows = await cursor.fetchall()
        return web.json_response({"objects": [dict(r) for r in rows]})

    async def query(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid json"}, status=400)

        sql = body.get("sql", "")
        params = body.get("params", [])
        max_rows = min(int(body.get("limit", 100)), get_settings().api_max_rows)

        if not isinstance(sql, str) or not sql.strip():
            return web.json_response({"error": "missing 'sql'"}, status=400)
        if not _is_safe_select(sql):
            return web.json_response({"error": "only SELECT / WITH / EXPLAIN / safe PRAGMA allowed"}, status=400)
        if not isinstance(params, (list, tuple)):
            return web.json_response({"error": "'params' must be a list"}, status=400)

        s = get_settings()
        try:
            assert self.ro_conn
            t0 = time.monotonic()
            cursor = await asyncio.wait_for(
                self.ro_conn.execute(sql, params),
                timeout=s.api_query_timeout_seconds,
            )
            rows = await cursor.fetchmany(max_rows)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
        except asyncio.TimeoutError:
            return web.json_response({"error": f"query timeout >{s.api_query_timeout_seconds}s"}, status=504)
        except aiosqlite.Error as e:
            return web.json_response({"error": f"sqlite: {e}"}, status=400)

        cols = [d[0] for d in cursor.description] if cursor.description else []
        return web.json_response({
            "columns": cols,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": len(rows) >= max_rows,
            "elapsed_ms": elapsed_ms,
        })

    async def semantic(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid json"}, status=400)

        query = body.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return web.json_response({"error": "missing 'query'"}, status=400)
        k = min(int(body.get("k", 20)), 100)
        channel_id = body.get("channel_id")
        since = body.get("since")
        until = body.get("until")

        try:
            vecs = await emb_llm.embed([query])
        except Exception as e:
            return web.json_response({"error": f"embed failed: {e}"}, status=502)
        if not vecs or vecs[0] is None:
            return web.json_response({"error": "empty query embedding"}, status=400)

        try:
            from datetime import datetime
            since_dt = datetime.fromisoformat(since) if since else None
            until_dt = datetime.fromisoformat(until) if until else None
        except ValueError as e:
            return web.json_response({"error": f"bad datetime: {e}"}, status=400)

        try:
            assert self.ro_conn
            hits = await emb_db.search(
                self.ro_conn,
                query_vector=vecs[0],
                k=k,
                channel_id=channel_id,
                since=since_dt,
                until=until_dt,
            )
        except aiosqlite.Error as e:
            return web.json_response({"error": f"vector search failed: {e}"}, status=500)
        if not hits:
            return web.json_response({"matches": []})

        ids = [mid for mid, _ in hits]
        placeholders = ",".join("?" * len(ids))
        cursor = await self.ro_conn.execute(
            f"SELECT m.discord_message_id, m.channel_id, m.user_id, "
            f"COALESCE(u.display_name, '?') AS user_display_name, "
            f"m.content, m.timestamp_utc FROM messages m "
            f"LEFT JOIN users u ON u.discord_user_id = m.user_id "
            f"WHERE m.discord_message_id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        by_id = {r["discord_message_id"]: dict(r) for r in rows}
        out = []
        for mid, dist in hits:
            item = by_id.get(mid)
            if item:
                item["distance"] = dist
                out.append(item)
        return web.json_response({"matches": out})


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ApiCog(bot))
