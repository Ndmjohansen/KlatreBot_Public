# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

KlatreBot — Danish-language Discord bot for a climbing group. Wraps OpenAI with Discord history storage. Deployed as systemd service on a Raspberry Pi; main branch auto-deploys via SSH GitHub Action.

V1 source is archived under `klatrebot_v1/` (kept for reference; not deployed).

## Environment

- Project uses **Poetry**. Poetry manages its own venv (default location); do not create or activate a venv manually. `poetry run python3 -m klatrebot_v2` resolves the right interpreter automatically.
- Install / sync deps: `poetry install --sync`.
- Secrets via `.env` (local) or `/etc/klatrebot/klatrebot.env` (systemd `EnvironmentFile`). Required keys: `DISCORD_KEY`, `OPENAI_KEY`, `DISCORD_MAIN_CHANNEL_ID`, `DISCORD_SANDBOX_CHANNEL_ID`, `ADMIN_USER_ID`. Optional Hermes / API keys: `HERMES_ENABLED`, `HERMES_URL`, `HERMES_TOKEN`, `HERMES_MODEL`, `API_ENABLED`, `API_HOST`, `API_PORT`, `API_TOKEN`. See `.env.example`.

## Common commands

- Run bot locally: `poetry run python3 -m klatrebot_v2` (uses `.env`).
- Run all tests: `poetry run pytest -v`
- Run single test: `poetry run pytest tests/unit/test_chat.py::test_name -v`
- Service control on Pi: `sudo systemctl {start|stop|restart|status} klatrebot`; logs via `sudo journalctl -u klatrebot -f`.

## Dependency management

- `pyproject.toml` uses PEP 621 `[project]` table (Poetry 2.x). Top-level deps under `dependencies`; dev-only under `[tool.poetry.group.dev.dependencies]`. `package-mode = false` — project is an app, not a library.
- After editing deps in `pyproject.toml`, run `poetry lock` and commit `poetry.lock`.
- Before adding a new top-level dep, check current versions: `poetry show --top-level` and `poetry show --outdated`. Prefer the latest stable; pin a lower bound (e.g. `>=X.Y`) only when needed.
- Bumping: `poetry update <package>` (or `poetry update` for all). Then `poetry check`, `poetry run pytest`.

## Deployment

`.github/workflows/main.yml` SSHes into the Pi on push to `main`: `git pull`, `poetry install --sync`, rewrite `/etc/klatrebot/klatrebot.env` from secrets, `systemctl restart klatrebot`. No staging — main = prod.

## Architecture

Single-process async Discord bot. Entry point: `python3 -m klatrebot_v2` → `klatrebot_v2/__main__.py`. Python package: `klatrebot_v2/`.

Core layers:

- `klatrebot_v2/bot.py` — `KlatreBot` class; `discord.py` `commands.Bot`. Loads cogs on startup.
- `klatrebot_v2/cogs/` — Discord command/event handlers split by domain:
  - `chat.py` — `!gpt` command. Routes via `llm/router.py` classifier (gpt-5.4-nano) to either the existing OpenAI chat path OR the Hermes Agent on the LAN. Falls back to chat path on Hermes failure. Supports `--fast`/`--agent` overrides.
  - `api.py` — aiohttp read-only HTTP API exposed to Hermes on the LAN. Endpoints: `/health`, `/api/schema`, `/api/query` (SELECT/WITH/EXPLAIN only, statement timeout, `PRAGMA query_only=1`), `/api/search_messages_semantic`. Bearer auth. Started in `bot.setup_hook`.
  - `hermes_health.py` — 60s probe loop; posts admin-mention alerts to sandbox channel on Hermes up↔down transitions (30 min cooldown on down-alerts).
  - `attendance.py` — Klatretid attendance tracking (`!klatretid`, `!fremmøde`, etc.).
  - `auto_responses.py` — Keyword-triggered auto-responses (`!glar`).
  - `referat.py` — `!referat` meeting-summary command.
  - `trivia.py` — Trivia/quiz commands.
- `klatrebot_v2/llm/` — LLM integration:
  - `client.py` — `AsyncOpenAI` wrapper for OpenAI calls.
  - `chat.py` — Chat completion logic with recent message context (the "fast" branch of `!gpt`).
  - `prompt.py` — System prompt loading from `SOUL.MD`.
  - `ratelimit.py` — Per-user rate limiting.
  - `router.py` — `classify(question)` returns `"chat"` or `"agent"`. Cheap nano model with JSON-schema structured output. Failures default to `"chat"`.
  - `hermes_client.py` — `AsyncOpenAI` pointed at Hermes' OpenAI-compatible `/v1`. `health()`, `is_available()` cache, `ask()`. `HermesUnavailable` raised on disabled / cached-down / live error.
  - `embeddings.py` — Batched OpenAI embeddings (text-embedding-3-small) for the message vector store.
- `klatrebot_v2/db/` — Database layer (aiosqlite):
  - `connection.py` — DB connection + WAL mode + sqlite-vec extension load.
  - `migrations.py` — Schema creation (`CREATE TABLE IF NOT EXISTS`); includes vec0 virtual table for `message_embeddings`.
  - `messages.py`, `users.py`, `attendance.py`, `models.py` — CRUD per domain.
  - `embeddings.py` — vec0 wrappers (`upsert`, `upsert_many`, `existing_ids`, `search`).
- `klatrebot_v2/settings.py` — `pydantic-settings` config; reads env vars.
- `klatrebot_v2/tasks.py` — Scheduled background tasks (klatretid announcements, etc.).
- `klatrebot_v2/pelle.py` — `whereTheFuckIsPelle` feature helper.
- `klatrebot_v2/time_utils.py` — Timezone-aware datetime helpers.
- `klatrebot_v2/logging_config.py` — Logging setup.

## Hermes integration

Complex `!gpt` queries (history lookups, multi-step reasoning, attendance trends) are routed to a Hermes Agent (Nous Research) running on a separate Ubuntu LAN host. Hermes calls back into the bot via the read-only HTTP API in `cogs/api.py`. The `klatrebot-tools` Hermes plugin lives at `infra/hermes/plugins/klatrebot-tools/` and ships with the repo.

Plugin handler convention: tool functions are **synchronous** (`def`, not `async def`) and accept `**_kwargs` to swallow registry extras like `task_id`. They return a JSON string `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}`. Use `httpx.Client` (sync), not `AsyncClient`.

Read-only enforcement layers (Pi side, in `cogs/api.py`):
1. Separate `aiosqlite` connection opened with `mode=ro` URI.
2. `PRAGMA query_only = 1`.
3. SQL guard: only `SELECT|WITH|EXPLAIN|safe-PRAGMA` accepted.
4. Statement timeout via `asyncio.wait_for`.
Pi → API and Ubuntu → Hermes are LAN-only, gated by UFW + bearer tokens.

See `infra/README.md` for the architecture overview and `infra/SETUP_NOTES.md` (gitignored) for live host configuration.

## Conventions

- User-facing strings are Danish; preserve language when editing them.
- DB schema lives in `klatrebot_v2/db/migrations.py`; add `CREATE TABLE IF NOT EXISTS` there for new tables (no migration framework).
- Logging goes to stderr → journalctl on Pi.
- Tests live in `tests/unit/` (fast, no I/O) and `tests/integration/` (boot subprocess; opt-in via `-m integration`).
