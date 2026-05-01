# klatrebot-tools — Hermes plugin (HTTP variant)

Read-only access to KlatreBot's database via the Pi's HTTP API. Hermes never touches the SQLite file directly — Pi is single source of truth, real-time.

## Install

```
mkdir -p ~/.hermes/plugins
scp -r klatrebot-tools <USER>@<UBUNTU>:~/.hermes/plugins/
ssh <USER>@<UBUNTU> "hermes plugins enable klatrebot-tools"
```

## Required env

Add to Hermes' env file (e.g. `~/.hermes/.env`):

```
KLATREBOT_API_URL=http://192.168.50.172:8765
KLATREBOT_API_TOKEN=<bearer-token-from-pi>
KLATREBOT_API_TIMEOUT=10
```

## Tools

- `klatrebot_query(sql, params?, limit?)` — arbitrary SELECT/WITH/EXPLAIN. Read-only enforced server-side.
- `klatrebot_schema()` — DDL for all tables/views/indexes.
- `klatrebot_search_semantic(query, k?, channel_id?, since?, until?)` — vec0 ANN over message embeddings. Embedding done Pi-side.
- `klatrebot_health()` — connectivity probe + latency.

All return JSON strings: `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}`.

## Pi-side server

Lives in `klatrebot_v2/cogs/api.py`. Started inside the bot process on `setup_hook`. Same event loop as Discord client.

Required Pi env:

```
API_ENABLED=true
API_HOST=0.0.0.0
API_PORT=8765
API_TOKEN=<long-random-secret>
```

UFW: allow 8765 from Ubuntu LAN IP only.
