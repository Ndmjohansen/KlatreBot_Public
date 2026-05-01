# klatrebot-tools — Hermes plugin

Read-only access to KlatreBot's SQLite replica for the Hermes agent.

## Install

Copy the whole `klatrebot-tools/` directory to `~/.hermes/plugins/` on the Hermes host:

```
~/.hermes/plugins/klatrebot-tools/
  __init__.py
  plugin.yaml
  schemas.py
  tools.py
  db.py
```

Install Python deps in Hermes' venv:

```
~/.hermes/venv/bin/pip install sqlite-vec openai
```

## Required env

Set in the env file Hermes loads (e.g. `/etc/klatrebot-hermes.env` or `~/.hermes/.env`):

```
KLATREBOT_REPLICA_PATH=/var/lib/klatrebot-replica/klatrebot_v2.db
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

`OPENAI_API_KEY` is used by `search_messages_semantic` to embed the query (the
vectors themselves are pre-computed on the Pi/dev box and replicated via Litestream).

## Tools registered

- `get_recent_messages(channel_id, limit)`
- `search_messages(query, channel_id?, since?, until?, limit?)` — keyword LIKE
- `search_messages_semantic(query, k?, channel_id?, since?, until?)` — vec0 ANN
- `messages_in_window(channel_id, start, end)`
- `get_attendance(date_local, channel_id)`
- `get_user(user_id)`

All return `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}` JSON strings.

## Verify

After Hermes restart:

```
hermes -z "list your klatrebot tools"
```

Or invoke directly:

```
hermes -z "kald search_messages_semantic med query='klatring' og k=3"
```
