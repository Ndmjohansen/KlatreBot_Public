"""Tool handlers — call the Pi's read-only HTTP API. Always return a JSON string."""
import json
import logging
import os
import time

import httpx


logger = logging.getLogger(__name__)

API_URL = os.environ.get("KLATREBOT_API_URL", "http://192.168.50.172:8765").rstrip("/")
API_TOKEN = os.environ.get("KLATREBOT_API_TOKEN", "")
TIMEOUT = float(os.environ.get("KLATREBOT_API_TIMEOUT", "10"))


def _headers() -> dict:
    if not API_TOKEN:
        return {}
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


async def klatrebot_query(args: dict) -> str:
    sql = args.get("sql", "")
    if not sql.strip():
        return _err("missing 'sql'")
    payload = {"sql": sql, "params": args.get("params", []), "limit": args.get("limit", 100)}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.post(f"{API_URL}/api/query", json=payload, headers=_headers())
        if resp.status_code != 200:
            return _err(f"http {resp.status_code}: {resp.text[:200]}")
        return _ok(resp.json())
    except Exception as e:
        return _err(f"request failed: {e}")


async def klatrebot_schema(args: dict) -> str:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.get(f"{API_URL}/api/schema", headers=_headers())
        if resp.status_code != 200:
            return _err(f"http {resp.status_code}: {resp.text[:200]}")
        return _ok(resp.json())
    except Exception as e:
        return _err(f"request failed: {e}")


async def klatrebot_search_semantic(args: dict) -> str:
    query = args.get("query", "")
    if not query.strip():
        return _err("missing 'query'")
    payload = {
        "query": query,
        "k": args.get("k", 20),
    }
    for k in ("channel_id", "since", "until"):
        if k in args and args[k] is not None:
            payload[k] = args[k]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.post(f"{API_URL}/api/search_messages_semantic", json=payload, headers=_headers())
        if resp.status_code != 200:
            return _err(f"http {resp.status_code}: {resp.text[:200]}")
        return _ok(resp.json())
    except Exception as e:
        return _err(f"request failed: {e}")


async def klatrebot_health(args: dict) -> str:
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3.0) as http:
            resp = await http.get(f"{API_URL}/health")
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return _ok({"status": resp.json().get("status"), "elapsed_ms": elapsed_ms, "code": resp.status_code})
    except Exception as e:
        return _err(f"unreachable: {e}")
