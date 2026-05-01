# infra/

Cross-host infrastructure for the Hermes Agent integration.

## Architecture

```
Discord !gpt
  └─ Pi: chat cog
      ├─ rate-limit
      ├─ router.classify (gpt-5.4-nano, JSON schema) → "chat" | "agent"
      ├─ "chat":  llm.chat.reply (existing OpenAI Responses path)
      └─ "agent": hermes_client.ask
            └─ AsyncOpenAI to Hermes /v1/chat/completions on the Ubuntu host
                  └─ Hermes runs an agent loop, calls plugin tools as needed
                        └─ klatrebot-tools plugin — sync httpx
                              └─ HTTP back to Pi cogs/api.py on :8765
                                    Read-only SQL with PRAGMA query_only,
                                    statement guard, vector search via
                                    sqlite-vec on the message embedding table.

Pi: KlatreBot bot process is the single source of truth — writer of
    klatrebot_v2.db AND server of the read-only API. No replication.

Ubuntu: Hermes Agent gateway + own memory/skills DB (separate from KlatreBot).
```

Real-time reads (no Litestream / replica). Vector search runs on the Pi against
the live `message_embeddings` (sqlite-vec) table; query embedding happens
Pi-side too.

## Layout

- `hermes/plugins/klatrebot-tools/` — Hermes plugin source. Copy this directory
  into `~/.hermes/plugins/` on the Hermes host, then `hermes plugins enable
  klatrebot-tools`. Plugin needs env vars `KLATREBOT_API_URL`,
  `KLATREBOT_API_TOKEN`, `KLATREBOT_API_TIMEOUT` (set in `~/.hermes/.env`).
- `view-hermes-trace.sh` — convenience script for the Hermes host. Pretty-prints
  the most recent agent session(s) (USER prompt, TOOL_CALLs, TOOL_RESULTs, final
  reply) from `~/.hermes/sessions/`. Usage: `./view-hermes-trace.sh [N] [-v]`.
- `SETUP_NOTES.md` — **gitignored** running notebook of the actual host
  configuration (IPs, paths, env layout). Local-only.

## Plugin tools exposed to the LLM

| Tool | Purpose |
|------|---------|
| `klatrebot_query(sql, params?, limit?)` | Arbitrary SELECT/WITH/EXPLAIN. Read-only enforced server-side. |
| `klatrebot_schema()` | DDL of all tables/views/indexes. |
| `klatrebot_search_semantic(query, k?, channel_id?, since?, until?)` | vec0 ANN over message embeddings. Embedding done on Pi. |
| `klatrebot_health()` | Connectivity probe + latency. |

All return JSON strings `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}`.

## Pi-side env vars

Set in the bot's `.env` (or `/etc/klatrebot/klatrebot.env` for systemd):

```
# Read-only HTTP API exposed to Hermes
API_ENABLED=true
API_HOST=0.0.0.0       # bind LAN-wide; UFW restricts to Ubuntu IP
API_PORT=8765
API_TOKEN=<long-random-secret>

# Wire-up to Hermes
HERMES_ENABLED=true
HERMES_URL=http://<UBUNTU_LAN_IP>:8642
HERMES_TOKEN=<Hermes API_SERVER_KEY>
HERMES_MODEL=hermes-agent
```

## Ubuntu-side env vars

In `~/.hermes/.env`:

```
OPENAI_API_KEY=...
API_SERVER_ENABLED=true
API_SERVER_HOST=<UBUNTU_LAN_IP>
API_SERVER_PORT=8642
API_SERVER_KEY=<long-random-secret>      # same value as HERMES_TOKEN above

KLATREBOT_API_URL=http://<PI_LAN_IP>:8765
KLATREBOT_API_TOKEN=<same as Pi API_TOKEN>
KLATREBOT_API_TIMEOUT=10
```

Network gating: UFW on the Pi allows port 8765 from the Ubuntu LAN IP only;
UFW on Ubuntu allows port 8642 from the Pi LAN IP only.
