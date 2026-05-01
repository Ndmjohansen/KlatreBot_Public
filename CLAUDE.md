# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

KlatreBot — Danish-language Discord bot for a climbing group. Wraps OpenAI with Discord history storage. Deployed as systemd service on a Raspberry Pi; main branch auto-deploys via SSH GitHub Action.

V1 source is archived under `klatrebot_v1/` (kept for reference; not deployed).

## Environment

- Project uses **Poetry**. Poetry manages its own venv (default location); do not create or activate a venv manually. `poetry run python3 -m klatrebot_v2` resolves the right interpreter automatically.
- Install / sync deps: `poetry install --sync`.
- Secrets via `.env` (local) or `/etc/klatrebot/klatrebot.env` (systemd `EnvironmentFile`). Keys: `DISCORD_KEY`, `OPENAI_KEY`, `DISCORD_MAIN_CHANNEL_ID`, `DISCORD_SANDBOX_CHANNEL_ID`, `ADMIN_USER_ID`. See `.env.example`.

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
  - `chat.py` — `!gpt` command, on_message LLM handler, rate limiting.
  - `attendance.py` — Klatretid attendance tracking (`!klatretid`, `!fremmøde`, etc.).
  - `auto_responses.py` — Keyword-triggered auto-responses (`!glar`).
  - `referat.py` — `!referat` meeting-summary command.
  - `trivia.py` — Trivia/quiz commands.
- `klatrebot_v2/llm/` — LLM integration:
  - `client.py` — `AsyncOpenAI` wrapper.
  - `chat.py` — Chat completion logic with recent message context.
  - `prompt.py` — System prompt loading from `SOUL.MD`.
  - `ratelimit.py` — Per-user rate limiting.
- `klatrebot_v2/db/` — Database layer (aiosqlite):
  - `connection.py` — DB connection + WAL mode setup.
  - `migrations.py` — Schema creation (`CREATE TABLE IF NOT EXISTS`).
  - `messages.py`, `users.py`, `attendance.py`, `models.py` — CRUD per domain.
- `klatrebot_v2/settings.py` — `pydantic-settings` config; reads env vars.
- `klatrebot_v2/tasks.py` — Scheduled background tasks (klatretid announcements, etc.).
- `klatrebot_v2/pelle.py` — `whereTheFuckIsPelle` feature helper.
- `klatrebot_v2/time_utils.py` — Timezone-aware datetime helpers.
- `klatrebot_v2/logging_config.py` — Logging setup.

## Conventions

- User-facing strings are Danish; preserve language when editing them.
- DB schema lives in `klatrebot_v2/db/migrations.py`; add `CREATE TABLE IF NOT EXISTS` there for new tables (no migration framework).
- Logging goes to stderr → journalctl on Pi.
- Tests live in `tests/unit/` (fast, no I/O) and `tests/integration/` (boot subprocess; opt-in via `-m integration`).
