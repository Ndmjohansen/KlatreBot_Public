"""Tool handlers — call the Pi's read-only HTTP API. Always return a JSON string.

Hermes registry calls handlers synchronously, so we use httpx.Client (sync), not
AsyncClient. Handlers receive (args: dict) plus arbitrary **kwargs from the
registry (task_id, etc.) — accept them with **_kwargs.
"""
import json
import logging
import os
import time

import httpx


logger = logging.getLogger(__name__)

API_URL = os.environ.get("KLATREBOT_API_URL", "http://192.168.50.172:8765").rstrip("/")
API_TOKEN = os.environ.get("KLATREBOT_API_TOKEN", "")
TIMEOUT = float(os.environ.get("KLATREBOT_API_TIMEOUT", "10"))


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def _request(method: str, path: str, *, json_body: dict | None = None, timeout: float = TIMEOUT) -> str:
    """Single shared HTTP path. Returns a tool-response JSON string ready to return."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    url = f"{API_URL}{path}"
    try:
        with httpx.Client(timeout=timeout) as http:
            resp = http.request(method, url, json=json_body, headers=headers)
        if resp.status_code != 200:
            return _err(f"http {resp.status_code}: {resp.text[:200]}")
        return _ok(resp.json())
    except Exception as e:
        return _err(f"request failed: {e}")


def klatrebot_query(args: dict, **_kwargs) -> str:
    sql = args.get("sql", "")
    if not sql.strip():
        return _err("missing 'sql'")
    return _request("POST", "/api/query", json_body={
        "sql": sql,
        "params": args.get("params", []),
        "limit": args.get("limit", 100),
    })


def klatrebot_schema(args: dict, **_kwargs) -> str:
    return _request("GET", "/api/schema")


def klatrebot_search_semantic(args: dict, **_kwargs) -> str:
    query = args.get("query", "")
    if not query.strip():
        return _err("missing 'query'")
    payload = {"query": query, "k": args.get("k", 20)}
    for k in ("channel_id", "since", "until"):
        if k in args and args[k] is not None:
            payload[k] = args[k]
    return _request("POST", "/api/search_messages_semantic", json_body=payload)


def klatrebot_health(args: dict, **_kwargs) -> str:
    """Plain ping; ignores auth (the /health endpoint is unauthenticated by design)."""
    try:
        t0 = time.monotonic()
        with httpx.Client(timeout=3.0) as http:
            resp = http.get(f"{API_URL}/health")
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return _ok({"status": resp.json().get("status"), "elapsed_ms": elapsed_ms, "code": resp.status_code})
    except Exception as e:
        return _err(f"unreachable: {e}")
