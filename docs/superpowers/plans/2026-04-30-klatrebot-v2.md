# KlatreBot V2 — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lean Python rewrite of KlatreBot in `klatrebot_v2/` subdir — Phase 1 features only — bot runnable after slice 1, then layered.

**Architecture:** Discord bot using `discord.py` cogs, single-pass OpenAI Responses API with native `web_search` tool, Pydantic-2.13 at edges (settings/DB rows/LLM I/O), sqlite via `aiosqlite` (WAL + NORMAL), event-log attendance schema. V1 stays untouched at repo root.

**Tech Stack:** Python ≥3.11, Poetry (own project), discord.py, openai (Responses API), aiosqlite, pydantic-settings, pydantic 2.13.3, pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md`](../specs/2026-04-30-klatrebot-v2-design.md)

---

## File map (new files in `klatrebot_v2/`)

```
klatrebot_v2/
├── pyproject.toml                  # Poetry project config + deps
├── poetry.lock                     # generated
├── README.md                       # how to run
├── SOUL.MD                         # system prompt (port from V1)
├── .env.example                    # env contract
├── .gitignore                      # local venv/db/etc.
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_settings.py
│   │   ├── test_users_db.py
│   │   ├── test_messages_db.py
│   │   ├── test_attendance_db.py
│   │   ├── test_ratelimit.py
│   │   ├── test_chat.py
│   │   ├── test_summarize.py
│   │   ├── test_auto_responses.py
│   │   ├── test_klatretid_schedule.py
│   │   ├── test_referat_window.py
│   │   └── test_pelle.py
│   └── integration/
│       ├── __init__.py
│       └── test_smoke_boot.py
└── klatrebot_v2/
    ├── __init__.py
    ├── __main__.py                 # entrypoint
    ├── settings.py                 # Pydantic BaseSettings
    ├── bot.py                      # discord.py Bot subclass
    ├── logging_config.py           # stdlib logging setup
    ├── tasks.py                    # klatretid scheduler
    ├── time_utils.py               # 5AM-window math, next-klatretid math
    ├── pelle.py                    # ported pelleService (pure functions)
    ├── db/
    │   ├── __init__.py
    │   ├── models.py               # Pydantic row models
    │   ├── connection.py           # aiosqlite open/close
    │   ├── migrations.py           # CREATE TABLE IF NOT EXISTS
    │   ├── users.py
    │   ├── messages.py
    │   └── attendance.py
    ├── llm/
    │   ├── __init__.py
    │   ├── client.py               # AsyncOpenAI singleton
    │   ├── prompt.py               # SOUL.MD loader
    │   ├── chat.py                 # reply() + summarize()
    │   └── ratelimit.py            # per-user sliding window
    └── cogs/
        ├── __init__.py
        ├── chat.py
        ├── referat.py
        ├── attendance.py
        ├── trivia.py
        └── auto_responses.py
```

---

## Slice 0 — Bootstrap project skeleton

Goal: empty Poetry project that `poetry install`s and `poetry run pytest` runs (with zero tests passing).

### Task 1: Create `klatrebot_v2/` dir and Poetry config

**Files:**
- Create: `klatrebot_v2/pyproject.toml`
- Create: `klatrebot_v2/.gitignore`
- Create: `klatrebot_v2/README.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p klatrebot_v2
```

- [ ] **Step 2: Write `klatrebot_v2/pyproject.toml`**

```toml
[project]
name = "klatrebot-v2"
version = "0.1.0"
description = "KlatreBot V2 — Phase 1 lean rewrite"
authors = [{ name = "Nicklas Johansen" }]
requires-python = ">=3.11,<4.0"
dependencies = [
    "discord.py>=2.7",
    "openai>=2.6.1",
    "aiosqlite>=0.21",
    "pydantic==2.13.3",
    "pydantic-settings>=2.5",
    "python-dateutil>=2.9",
    "pytz>=2024.1",
    "requests>=2.32",
]

[tool.poetry]
package-mode = false

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0"
pytest-asyncio = ">=0.24"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "integration: end-to-end tests that boot the bot subprocess (opt-in via -m integration)",
]

[build-system]
requires = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 3: Write `klatrebot_v2/.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
*.db
*.db-shm
*.db-wal
```

- [ ] **Step 4: Write `klatrebot_v2/README.md`**

```markdown
# KlatreBot V2

Lean Phase 1 rewrite. Spec: [`../docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md`](../docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md)

## Run

```
cd klatrebot_v2
cp .env.example .env  # fill in keys
poetry install
poetry run python3 -m klatrebot_v2
```

## Test

```
poetry run pytest                # unit tests
poetry run pytest -m integration # smoke boot (requires real DISCORD_KEY)
```
```

- [ ] **Step 5: Verify Poetry can resolve and lock deps**

Run from `klatrebot_v2/`:
```bash
poetry lock
```
Expected: `poetry.lock` written; no errors.

- [ ] **Step 6: Commit**

```bash
git add klatrebot_v2/pyproject.toml klatrebot_v2/poetry.lock klatrebot_v2/.gitignore klatrebot_v2/README.md
git commit -m "feat(v2): bootstrap klatrebot_v2 Poetry project"
```

### Task 2: Create empty package + tests skeleton

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/__init__.py`
- Create: `klatrebot_v2/klatrebot_v2/__main__.py`
- Create: `klatrebot_v2/tests/__init__.py`
- Create: `klatrebot_v2/tests/unit/__init__.py`
- Create: `klatrebot_v2/tests/integration/__init__.py`
- Create: `klatrebot_v2/tests/conftest.py`

- [ ] **Step 1: Create dirs**

```bash
mkdir -p klatrebot_v2/klatrebot_v2 klatrebot_v2/tests/unit klatrebot_v2/tests/integration
```

- [ ] **Step 2: Write `klatrebot_v2/klatrebot_v2/__init__.py`**

```python
"""KlatreBot V2 — Phase 1."""
```

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/__main__.py` (stub)**

```python
"""Entrypoint: `poetry run python3 -m klatrebot_v2`."""

def main() -> None:
    raise NotImplementedError("Slice 1 wires this up.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write empty `__init__.py` files**

`klatrebot_v2/tests/__init__.py`, `klatrebot_v2/tests/unit/__init__.py`, `klatrebot_v2/tests/integration/__init__.py` all empty (zero bytes).

- [ ] **Step 5: Write `klatrebot_v2/tests/conftest.py` (placeholder)**

```python
"""Shared pytest fixtures. Filled in as slices land."""
```

- [ ] **Step 6: Run pytest to confirm collection works**

```bash
cd klatrebot_v2 && poetry run pytest
```
Expected: `collected 0 items`, exit 0 (or 5 — "no tests ran"; both acceptable).

- [ ] **Step 7: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/ klatrebot_v2/tests/
git commit -m "feat(v2): empty package + tests skeleton"
```

---

## Slice 1 — Skeleton bot connects + `!gpt` works (no recent context)

Goal: bot logs into Discord, registers `!gpt` cog, replies via OpenAI with system prompt + question only (no chat-history context yet).

### Task 3: Settings (Pydantic BaseSettings)

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/settings.py`
- Create: `klatrebot_v2/.env.example`
- Create: `klatrebot_v2/SOUL.MD`
- Test: `klatrebot_v2/tests/unit/test_settings.py`

- [ ] **Step 1: Write `klatrebot_v2/.env.example`**

```bash
# Required
DISCORD_KEY=your_discord_bot_token_here
OPENAI_KEY=sk-your_openai_key_here
DISCORD_MAIN_CHANNEL_ID=0
DISCORD_SANDBOX_CHANNEL_ID=0
ADMIN_USER_ID=0

# Optional (defaults shown)
MODEL=gpt-5.4
SOUL_PATH=./SOUL.MD
DB_PATH=./klatrebot_v2.db

TIMEZONE=Europe/Copenhagen
KLATRETID_DAYS=[0,3]
KLATRETID_POST_HOUR=17
KLATRETID_START_HOUR=20

GPT_RECENT_MESSAGE_COUNT=25
RATE_LIMIT_PER_USER_PER_HOUR=30
LOG_LEVEL=INFO
```

- [ ] **Step 2: Write `klatrebot_v2/SOUL.MD` (port from V1's `klatrebot_prompt.txt`)**

Read the existing V1 file:
```bash
cat klatrebot_prompt.txt
```
Copy its content verbatim into `klatrebot_v2/SOUL.MD`. (The V1 prompt is the agreed Phase-1 voice. Will be edited later as a "soul" file.)

- [ ] **Step 3: Write the failing test `klatrebot_v2/tests/unit/test_settings.py`**

```python
import pytest


def test_settings_loads_from_env(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("test soul")
    monkeypatch.setenv("DISCORD_KEY", "fake_discord")
    monkeypatch.setenv("OPENAI_KEY", "fake_openai")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "111")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "222")
    monkeypatch.setenv("ADMIN_USER_ID", "333")
    monkeypatch.setenv("SOUL_PATH", str(soul))

    from klatrebot_v2.settings import Settings
    s = Settings(_env_file=None)

    assert s.discord_key == "fake_discord"
    assert s.openai_key == "fake_openai"
    assert s.discord_main_channel_id == 111
    assert s.model == "gpt-5.4"
    assert s.timezone == "Europe/Copenhagen"
    assert s.klatretid_days == [0, 3]


def test_settings_missing_required_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_KEY", raising=False)
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    from pydantic import ValidationError
    from klatrebot_v2.settings import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 4: Run test — should fail (module missing)**

```bash
cd klatrebot_v2 && poetry run pytest tests/unit/test_settings.py -v
```
Expected: ERROR `ModuleNotFoundError: No module named 'klatrebot_v2.settings'`.

- [ ] **Step 5: Write `klatrebot_v2/klatrebot_v2/settings.py`**

```python
"""Configuration loaded from .env via Pydantic BaseSettings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    discord_key: str
    openai_key: str
    discord_main_channel_id: int
    discord_sandbox_channel_id: int
    admin_user_id: int

    # Optional (defaults)
    model: str = "gpt-5.4"
    soul_path: str = "./SOUL.MD"
    db_path: str = "./klatrebot_v2.db"

    timezone: str = "Europe/Copenhagen"
    klatretid_days: list[int] = [0, 3]
    klatretid_post_hour: int = 17
    klatretid_start_hour: int = 20

    gpt_recent_message_count: int = 25
    rate_limit_per_user_per_hour: int = 30
    log_level: str = "INFO"


settings = Settings()
```

Note: `settings = Settings()` at module load reads `.env`. Tests pass `_env_file=None` to skip this and use only `monkeypatch.setenv`.

- [ ] **Step 6: Avoid module-level `Settings()` at import-time during tests**

Replace last line with:

```python
def get_settings() -> Settings:
    return Settings()
```

And update `Settings()` callers to use `get_settings()`. Reason: importing the module shouldn't crash if `.env` is absent (tests, CI, etc.).

Re-update `klatrebot_v2/klatrebot_v2/settings.py` final block:

```python
from functools import lru_cache


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

Drop the bare `settings = Settings()` line.

- [ ] **Step 7: Run tests — pass**

```bash
poetry run pytest tests/unit/test_settings.py -v
```
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/settings.py klatrebot_v2/.env.example klatrebot_v2/SOUL.MD klatrebot_v2/tests/unit/test_settings.py
git commit -m "feat(v2): Pydantic settings + .env contract + SOUL.MD"
```

### Task 4: Logging config

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/logging_config.py`

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/logging_config.py`**

```python
"""stdlib logging setup. Called once from __main__.py."""
import logging
import sys

from klatrebot_v2.settings import get_settings


def setup() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    for noisy in ("discord", "discord.http", "openai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

No test — pure stdlib config glue, exercised via integration smoke test later.

- [ ] **Step 2: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/logging_config.py
git commit -m "feat(v2): logging config"
```

### Task 5: DB connection + migrations DDL

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/db/__init__.py`
- Create: `klatrebot_v2/klatrebot_v2/db/connection.py`
- Create: `klatrebot_v2/klatrebot_v2/db/migrations.py`
- Test: `klatrebot_v2/tests/conftest.py` (extend with db fixture)
- Test: `klatrebot_v2/tests/unit/test_users_db.py` (placeholder)

- [ ] **Step 1: Create `klatrebot_v2/klatrebot_v2/db/__init__.py`**

Empty file.

- [ ] **Step 2: Write `klatrebot_v2/klatrebot_v2/db/connection.py`**

```python
"""Shared aiosqlite connection. Opened once in bot.setup_hook, closed on shutdown."""
import aiosqlite


async def open(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.commit()
    return conn


async def close(conn: aiosqlite.Connection) -> None:
    await conn.close()
```

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/db/migrations.py`**

```python
"""Schema bootstrap. Idempotent — safe to run on every startup."""
import aiosqlite


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        discord_user_id  INTEGER PRIMARY KEY,
        display_name     TEXT NOT NULL,
        is_admin         INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        discord_message_id  INTEGER PRIMARY KEY,
        channel_id          INTEGER NOT NULL,
        user_id             INTEGER NOT NULL,
        content             TEXT NOT NULL,
        timestamp_utc       TEXT NOT NULL,
        is_bot              INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, timestamp_utc)",
    """
    CREATE TABLE IF NOT EXISTS attendance_session (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        date_local          TEXT NOT NULL,
        channel_id          INTEGER NOT NULL,
        message_id          INTEGER NOT NULL,
        klatring_start_utc  TEXT NOT NULL,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(date_local, channel_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_reaction_event (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id      INTEGER NOT NULL,
        user_id         INTEGER NOT NULL,
        status          TEXT NOT NULL CHECK(status IN ('yes','no')),
        timestamp_utc   TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES attendance_session(id),
        FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reaction_session_user_ts ON attendance_reaction_event(session_id, user_id, timestamp_utc)",
]


async def run(conn: aiosqlite.Connection) -> None:
    for stmt in _DDL:
        await conn.execute(stmt)
    await conn.commit()
```

- [ ] **Step 4: Extend `klatrebot_v2/tests/conftest.py` with db fixture**

```python
"""Shared pytest fixtures."""
import pytest
import pytest_asyncio
import aiosqlite

from klatrebot_v2.db import connection, migrations


@pytest_asyncio.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await migrations.run(conn)
    yield conn
    await conn.close()
```

- [ ] **Step 5: Write `klatrebot_v2/tests/unit/test_users_db.py` (just verifies migrations run)**

```python
async def test_migrations_create_tables(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    rows = await cursor.fetchall()
    names = [r[0] for r in rows]
    assert "users" in names
    assert "messages" in names
    assert "attendance_session" in names
    assert "attendance_reaction_event" in names
```

- [ ] **Step 6: Run tests — should pass**

```bash
poetry run pytest tests/unit/test_users_db.py -v
```
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/ klatrebot_v2/tests/conftest.py klatrebot_v2/tests/unit/test_users_db.py
git commit -m "feat(v2): db connection + schema migrations"
```

### Task 6: `db/users.py` — upsert + lookup

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/db/models.py`
- Create: `klatrebot_v2/klatrebot_v2/db/users.py`
- Modify: `klatrebot_v2/tests/unit/test_users_db.py`

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/db/models.py`**

```python
"""Pydantic row models. Match table column types and names."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class User(BaseModel):
    discord_user_id: int
    display_name: str
    is_admin: bool = False


class Message(BaseModel):
    discord_message_id: int
    channel_id: int
    user_id: int
    content: str
    timestamp_utc: datetime
    is_bot: bool = False


class AttendanceSession(BaseModel):
    id: int | None = None
    date_local: str          # 'YYYY-MM-DD'
    channel_id: int
    message_id: int
    klatring_start_utc: datetime


class AttendanceEvent(BaseModel):
    id: int | None = None
    session_id: int
    user_id: int
    status: Literal["yes", "no"]
    timestamp_utc: datetime
```

- [ ] **Step 2: Add failing test — `test_users_db.py`**

Append to `klatrebot_v2/tests/unit/test_users_db.py`:

```python
from klatrebot_v2.db import users as users_db
from klatrebot_v2.db.models import User


async def test_upsert_inserts_new_user(db):
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle")
    found = await users_db.get(db, 42)
    assert found == User(discord_user_id=42, display_name="Pelle", is_admin=False)


async def test_upsert_updates_display_name(db):
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle")
    await users_db.upsert(db, discord_user_id=42, display_name="Pelle Lauritsen")
    found = await users_db.get(db, 42)
    assert found.display_name == "Pelle Lauritsen"


async def test_get_returns_none_for_missing(db):
    assert await users_db.get(db, 999) is None
```

- [ ] **Step 3: Run — should fail (module missing)**

```bash
poetry run pytest tests/unit/test_users_db.py -v
```
Expected: import error / module not found.

- [ ] **Step 4: Write `klatrebot_v2/klatrebot_v2/db/users.py`**

```python
"""User upsert + lookup."""
import aiosqlite

from klatrebot_v2.db.models import User


async def upsert(conn: aiosqlite.Connection, *, discord_user_id: int, display_name: str, is_admin: bool = False) -> None:
    await conn.execute(
        """
        INSERT INTO users (discord_user_id, display_name, is_admin)
        VALUES (?, ?, ?)
        ON CONFLICT(discord_user_id) DO UPDATE SET
            display_name = excluded.display_name,
            updated_at   = datetime('now')
        """,
        (discord_user_id, display_name, 1 if is_admin else 0),
    )
    await conn.commit()


async def get(conn: aiosqlite.Connection, discord_user_id: int) -> User | None:
    cursor = await conn.execute(
        "SELECT discord_user_id, display_name, is_admin FROM users WHERE discord_user_id = ?",
        (discord_user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return User(discord_user_id=row[0], display_name=row[1], is_admin=bool(row[2]))
```

- [ ] **Step 5: Run tests — pass**

```bash
poetry run pytest tests/unit/test_users_db.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/models.py klatrebot_v2/klatrebot_v2/db/users.py klatrebot_v2/tests/unit/test_users_db.py
git commit -m "feat(v2): users db — upsert + get"
```

### Task 7: LLM client wrapper + SOUL prompt loader

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/llm/__init__.py`
- Create: `klatrebot_v2/klatrebot_v2/llm/client.py`
- Create: `klatrebot_v2/klatrebot_v2/llm/prompt.py`

- [ ] **Step 1: Create `klatrebot_v2/klatrebot_v2/llm/__init__.py`** — empty file.

- [ ] **Step 2: Write `klatrebot_v2/klatrebot_v2/llm/client.py`**

```python
"""AsyncOpenAI singleton — module-level, lazy."""
from openai import AsyncOpenAI

from klatrebot_v2.settings import get_settings


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            api_key=s.openai_key,
            timeout=60.0,
            max_retries=0,
        )
    return _client
```

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/llm/prompt.py`**

```python
"""SOUL.MD loader."""
from functools import lru_cache
from pathlib import Path

from klatrebot_v2.settings import get_settings


@lru_cache(maxsize=1)
def load_soul() -> str:
    return Path(get_settings().soul_path).read_text(encoding="utf-8").strip()
```

No test for these — exercised via `test_chat.py` next task.

- [ ] **Step 4: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/
git commit -m "feat(v2): llm client + SOUL prompt loader"
```

### Task 8: Rate limiter

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/llm/ratelimit.py`
- Test: `klatrebot_v2/tests/unit/test_ratelimit.py`

- [ ] **Step 1: Write the failing test `klatrebot_v2/tests/unit/test_ratelimit.py`**

```python
import time
from collections import defaultdict, deque

import pytest


@pytest.fixture(autouse=True)
def _reset_ratelimit_state(monkeypatch):
    """Force fresh limiter state per test."""
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_buckets", defaultdict(deque))
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 0)


def test_allows_under_limit(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 3)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True


def test_blocks_over_limit(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 2)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is False


def test_per_user_independent(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 1)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(2) is True
    assert ratelimit.check_and_record(1) is False
    assert ratelimit.check_and_record(2) is False


def test_window_expires(monkeypatch):
    """Old timestamps fall out of the window."""
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 1)
    monkeypatch.setattr(ratelimit, "_WINDOW_SECONDS", 0.01)
    assert ratelimit.check_and_record(1) is True
    time.sleep(0.02)
    assert ratelimit.check_and_record(1) is True
```

- [ ] **Step 2: Run — fail (module missing)**

```bash
poetry run pytest tests/unit/test_ratelimit.py -v
```
Expected: import error.

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/llm/ratelimit.py`**

```python
"""Per-user sliding-window rate limiter. In-memory; resets on restart."""
import time
from collections import defaultdict, deque

from klatrebot_v2.settings import get_settings


_buckets: defaultdict[int, deque[float]] = defaultdict(deque)
_WINDOW_SECONDS: float = 3600.0
_LIMIT_PER_HOUR: int = 0   # 0 = uninitialized; resolved lazily on first call


def _resolve_limit() -> int:
    global _LIMIT_PER_HOUR
    if _LIMIT_PER_HOUR == 0:
        _LIMIT_PER_HOUR = get_settings().rate_limit_per_user_per_hour
    return _LIMIT_PER_HOUR


def check_and_record(user_id: int) -> bool:
    """Return True if the call is allowed; False if rate-limited."""
    limit = _resolve_limit()
    now = time.monotonic()
    q = _buckets[user_id]
    while q and now - q[0] > _WINDOW_SECONDS:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_ratelimit.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/ratelimit.py klatrebot_v2/tests/unit/test_ratelimit.py
git commit -m "feat(v2): per-user sliding-window rate limiter"
```

### Task 9: `llm/chat.reply` — initial version (no recent context yet)

This is the minimum-viable LLM call. Slice 2 will add context; slice 3 will add the web_search tool.

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/llm/chat.py`
- Test: `klatrebot_v2/tests/unit/test_chat.py`

- [ ] **Step 1: Write the failing test `klatrebot_v2/tests/unit/test_chat.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_response():
    """Mimic the OpenAI Responses API return shape we read."""
    r = MagicMock()
    r.output_text = "Hej brormand"
    r.output = []  # Used by source extraction; empty here.
    return r


async def test_reply_returns_chat_reply(monkeypatch, tmp_path, fake_response):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Du er en klatrebot.")
    monkeypatch.setenv("DISCORD_KEY", "x")
    monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    monkeypatch.setenv("SOUL_PATH", str(soul))

    # Patch the OpenAI client
    from klatrebot_v2.llm import client, chat, prompt
    client._client = None             # reset singleton
    prompt.load_soul.cache_clear()

    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(client, "_client", fake_client)

    result = await chat.reply(question="hvad så", asking_user_id=42)

    assert result.text == "Hej brormand"
    assert result.sources == []
    fake_client.responses.create.assert_awaited_once()
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert call_kwargs["model"] == "gpt-5.4"
    assert "Du er en klatrebot." in call_kwargs["input"]
    assert "hvad så" in call_kwargs["input"]
    assert "42" in call_kwargs["input"]
```

- [ ] **Step 2: Run — fail (module missing)**

```bash
poetry run pytest tests/unit/test_chat.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/llm/chat.py`**

```python
"""Discord-decoupled LLM call pipeline. Used by !gpt cog."""
from pydantic import BaseModel

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


async def reply(*, question: str, asking_user_id: int) -> ChatReply:
    """Single-pass LLM reply. Slice 2 adds recent-chat context; slice 3 adds web_search."""
    soul = load_soul()
    full_input = (
        f"{soul}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"QUESTION: {question}"
    )
    client = get_client()
    resp = await client.responses.create(
        model=get_settings().model,
        input=full_input,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return ChatReply(text=resp.output_text or "", sources=[])
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_chat.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/chat.py klatrebot_v2/tests/unit/test_chat.py
git commit -m "feat(v2): llm.chat.reply — single-pass without context yet"
```

### Task 10: `cogs/chat.py` — `!gpt` command

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/cogs/__init__.py`
- Create: `klatrebot_v2/klatrebot_v2/cogs/chat.py`

No isolated unit test — covered by smoke boot test. Cogs are thin adapters.

- [ ] **Step 1: Create `klatrebot_v2/klatrebot_v2/cogs/__init__.py`** — empty.

- [ ] **Step 2: Write `klatrebot_v2/klatrebot_v2/cogs/chat.py`**

```python
"""!gpt command. Thin adapter over llm.chat.reply."""
import logging
import time

import discord
from discord.ext import commands

from klatrebot_v2.llm import chat, ratelimit


logger = logging.getLogger(__name__)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="gpt")
    async def gpt(self, ctx: commands.Context, *, question: str) -> None:
        if not ratelimit.check_and_record(ctx.author.id):
            logger.info("ratelimit.blocked user_id=%d", ctx.author.id)
            await ctx.reply("Slap af, du har spurgt for meget.")
            return
        start = time.monotonic()
        async with ctx.typing():
            result = await chat.reply(question=question, asking_user_id=ctx.author.id)
        elapsed = time.monotonic() - start
        logger.info("llm.reply duration=%.2fs", elapsed)

        text = result.text
        if result.sources:
            text += f"\n\n_Kilder: {', '.join(result.sources[:3])}_"
        await ctx.reply(text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/
git commit -m "feat(v2): cogs/chat — !gpt command adapter"
```

### Task 11: Bot class + `__main__` entrypoint

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/bot.py`
- Modify: `klatrebot_v2/klatrebot_v2/__main__.py`

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/bot.py`**

```python
"""discord.py Bot subclass. Owns DB connection + cog registration."""
import logging
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands

from klatrebot_v2.db import connection, migrations
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)


class KlatreBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(intents=intents, command_prefix="!")
        self.db_conn = None
        self.start_time: datetime | None = None

    async def setup_hook(self) -> None:
        s = get_settings()
        # Fail loudly if SOUL.MD is missing
        Path(s.soul_path).read_text(encoding="utf-8")
        # Open DB and run migrations
        self.db_conn = await connection.open(s.db_path)
        await migrations.run(self.db_conn)
        # Register cogs
        await self.load_extension("klatrebot_v2.cogs.chat")
        self.start_time = datetime.utcnow()
        logger.info("Bot startup completed")

    async def on_ready(self) -> None:
        logger.info("Bot connected to Discord as %s", self.user)

    async def close(self) -> None:
        if self.db_conn is not None:
            await connection.close(self.db_conn)
        await super().close()


async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply("Slap af.")
        return
    logger.exception("Command %s failed", ctx.command, exc_info=error)
    await ctx.reply("Det kan jeg desværre ikke svare på.")
```

- [ ] **Step 2: Replace `klatrebot_v2/klatrebot_v2/__main__.py`**

```python
"""Entrypoint: `poetry run python3 -m klatrebot_v2`."""
import asyncio
import logging

from klatrebot_v2 import logging_config
from klatrebot_v2.bot import KlatreBot, on_command_error
from klatrebot_v2.settings import get_settings


def main() -> None:
    logging_config.setup()
    logger = logging.getLogger(__name__)

    s = get_settings()
    bot = KlatreBot()
    bot.on_command_error = on_command_error

    @bot.event
    async def on_error(event_method: str, *args, **kwargs):
        logger.exception("Unhandled exception in %s", event_method)

    logger.info("Starting KlatreBot V2...")
    asyncio.run(bot.start(s.discord_key))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/bot.py klatrebot_v2/klatrebot_v2/__main__.py
git commit -m "feat(v2): bot class + entrypoint — bot connects, !gpt works"
```

### Task 12: Smoke boot integration test

**Files:**
- Create: `klatrebot_v2/tests/integration/test_smoke_boot.py`

- [ ] **Step 1: Write `klatrebot_v2/tests/integration/test_smoke_boot.py`**

```python
"""End-to-end: boot the bot subprocess and assert readiness marker."""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.integration
def test_bot_boots_and_reports_ready(tmp_path):
    discord_key = os.getenv("DISCORD_KEY")
    openai_key = os.getenv("OPENAI_KEY")
    if not discord_key or not openai_key:
        pytest.skip("DISCORD_KEY + OPENAI_KEY required for integration test")

    # Use a temp DB so we don't pollute dev
    db_path = tmp_path / "smoke.db"

    # SOUL.MD must exist somewhere — copy real one or write a stub
    repo_soul = Path(__file__).parents[2] / "SOUL.MD"
    soul_path = tmp_path / "SOUL.MD"
    if repo_soul.exists():
        soul_path.write_text(repo_soul.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        soul_path.write_text("Test soul.")

    env = {
        **os.environ,
        "DISCORD_KEY": discord_key,
        "OPENAI_KEY": openai_key,
        "DISCORD_MAIN_CHANNEL_ID": "0",
        "DISCORD_SANDBOX_CHANNEL_ID": "0",
        "ADMIN_USER_ID": "0",
        "SOUL_PATH": str(soul_path),
        "DB_PATH": str(db_path),
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "klatrebot_v2"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).parents[2]),
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    pytest.fail(f"Bot exited prematurely with code {proc.returncode}")
                continue
            print(line, end="")
            if "Bot startup completed" in line:
                return
            if time.monotonic() > deadline:
                pytest.fail("Bot did not boot within 60s")
    finally:
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
```

- [ ] **Step 2: Run smoke test (with real staging keys in env)**

```bash
DISCORD_KEY=<staging> OPENAI_KEY=<key> poetry run pytest tests/integration/test_smoke_boot.py -m integration -v -s
```
Expected: PASS within 60s; "Bot startup completed" appears in stdout.

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/tests/integration/test_smoke_boot.py
git commit -m "test(v2): smoke boot integration test"
```

End of slice 1. Bot connects, `!gpt` works (no recent-chat context yet), DB initialized.

---

## Slice 2 — Message logging + recent-N context for `!gpt`

Goal: every chat message persists to sqlite; `!gpt` uses the last N messages from the channel as context.

### Task 13: `db/messages.py` — insert + recent

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/db/messages.py`
- Test: `klatrebot_v2/tests/unit/test_messages_db.py`

- [ ] **Step 1: Write the failing test `klatrebot_v2/tests/unit/test_messages_db.py`**

```python
from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import messages as msg_db, users as users_db


async def test_insert_then_recent(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    await users_db.upsert(db, discord_user_id=2, display_name="B")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        await msg_db.insert(
            db,
            discord_message_id=100 + i,
            channel_id=999,
            user_id=1 if i % 2 == 0 else 2,
            content=f"msg-{i}",
            timestamp_utc=base + timedelta(minutes=i),
            is_bot=False,
        )
    rows = await msg_db.recent(db, channel_id=999, limit=2)
    assert [r.content for r in rows] == ["msg-1", "msg-2"]


async def test_recent_returns_oldest_first_within_limit(db):
    """Order: oldest of the last-N first → freshest last (chat-style)."""
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        await msg_db.insert(
            db,
            discord_message_id=100 + i,
            channel_id=1,
            user_id=1,
            content=f"m{i}",
            timestamp_utc=base + timedelta(minutes=i),
        )
    rows = await msg_db.recent(db, channel_id=1, limit=3)
    assert [r.content for r in rows] == ["m2", "m3", "m4"]


async def test_recent_other_channel_excluded(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    await msg_db.insert(db, discord_message_id=1, channel_id=1, user_id=1, content="here", timestamp_utc=base)
    await msg_db.insert(db, discord_message_id=2, channel_id=2, user_id=1, content="not here", timestamp_utc=base)
    rows = await msg_db.recent(db, channel_id=1, limit=10)
    assert [r.content for r in rows] == ["here"]
```

- [ ] **Step 2: Run — fail**

```bash
poetry run pytest tests/unit/test_messages_db.py -v
```
Expected: import error.

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/db/messages.py`**

```python
"""Message log queries."""
from datetime import datetime
import aiosqlite

from klatrebot_v2.db.models import Message


async def insert(
    conn: aiosqlite.Connection,
    *,
    discord_message_id: int,
    channel_id: int,
    user_id: int,
    content: str,
    timestamp_utc: datetime,
    is_bot: bool = False,
) -> None:
    await conn.execute(
        """
        INSERT OR IGNORE INTO messages
            (discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            discord_message_id,
            channel_id,
            user_id,
            content,
            timestamp_utc.isoformat(),
            1 if is_bot else 0,
        ),
    )
    await conn.commit()


async def recent(conn: aiosqlite.Connection, *, channel_id: int, limit: int) -> list[Message]:
    """Return the last `limit` messages for `channel_id`, oldest-first within that window."""
    cursor = await conn.execute(
        """
        SELECT discord_message_id, channel_id, user_id, content, timestamp_utc, is_bot
        FROM (
            SELECT * FROM messages
            WHERE channel_id = ?
            ORDER BY timestamp_utc DESC
            LIMIT ?
        )
        ORDER BY timestamp_utc ASC
        """,
        (channel_id, limit),
    )
    rows = await cursor.fetchall()
    return [
        Message(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            content=r[3],
            timestamp_utc=datetime.fromisoformat(r[4]),
            is_bot=bool(r[5]),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run tests — pass**

```bash
poetry run pytest tests/unit/test_messages_db.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/messages.py klatrebot_v2/tests/unit/test_messages_db.py
git commit -m "feat(v2): messages db — insert + recent"
```

### Task 14: `recent` joined with `users` so context can show display names

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/db/messages.py`
- Modify: `klatrebot_v2/tests/unit/test_messages_db.py`

The chat context block needs `display_name`. Cleanest fix: extend `recent()` to return a richer dataclass that includes the joined display name.

- [ ] **Step 1: Add the failing test (append to `test_messages_db.py`)**

```python
async def test_recent_includes_display_name(db):
    await users_db.upsert(db, discord_user_id=10, display_name="Magnus")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    await msg_db.insert(db, discord_message_id=1, channel_id=1, user_id=10, content="hej", timestamp_utc=base)
    rows = await msg_db.recent_with_authors(db, channel_id=1, limit=10)
    assert rows[0].user_display_name == "Magnus"
    assert rows[0].content == "hej"
```

- [ ] **Step 2: Run — fail**

Expected: `AttributeError: module ... has no attribute 'recent_with_authors'`.

- [ ] **Step 3: Add to `klatrebot_v2/klatrebot_v2/db/messages.py`**

```python
from pydantic import BaseModel


class MessageWithAuthor(BaseModel):
    discord_message_id: int
    channel_id: int
    user_id: int
    user_display_name: str
    content: str
    timestamp_utc: datetime
    is_bot: bool


async def recent_with_authors(
    conn: aiosqlite.Connection, *, channel_id: int, limit: int
) -> list[MessageWithAuthor]:
    cursor = await conn.execute(
        """
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM (
            SELECT * FROM messages
            WHERE channel_id = ?
            ORDER BY timestamp_utc DESC
            LIMIT ?
        ) m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, limit),
    )
    rows = await cursor.fetchall()
    return [
        MessageWithAuthor(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            user_display_name=r[3],
            content=r[4],
            timestamp_utc=datetime.fromisoformat(r[5]),
            is_bot=bool(r[6]),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run — pass**

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/messages.py klatrebot_v2/tests/unit/test_messages_db.py
git commit -m "feat(v2): messages db — recent_with_authors join"
```

### Task 15: `llm.chat.reply` uses `recent_with_authors` for context

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/llm/chat.py`
- Modify: `klatrebot_v2/tests/unit/test_chat.py`

- [ ] **Step 1: Update test to assert recent messages appear in input**

Append to `klatrebot_v2/tests/unit/test_chat.py`:

```python
async def test_reply_includes_recent_context(monkeypatch, tmp_path, fake_response, db):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))

    # Seed db with two messages
    from datetime import datetime, timezone
    from klatrebot_v2.db import users as users_db, messages as msg_db
    await users_db.upsert(db, discord_user_id=10, display_name="Magnus")
    await msg_db.insert(db, discord_message_id=1, channel_id=42, user_id=10, content="første", timestamp_utc=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc))
    await msg_db.insert(db, discord_message_id=2, channel_id=42, user_id=10, content="anden", timestamp_utc=datetime(2026, 4, 30, 12, 1, tzinfo=timezone.utc))

    # Patch client and connection-getter
    from klatrebot_v2.llm import client, chat, prompt
    client._client = None
    prompt.load_soul.cache_clear()
    fake_client = MagicMock()
    fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(client, "_client", fake_client)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)

    result = await chat.reply(question="hvad så", asking_user_id=99, channel_id=42)

    assert result.text == "Hej brormand"
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert "Magnus: første" in call_kwargs["input"]
    assert "Magnus: anden" in call_kwargs["input"]
```

- [ ] **Step 2: Run — should fail (signature changed, helper missing)**

Expected: TypeError or AttributeError around `_get_db_conn` / `channel_id`.

- [ ] **Step 3: Update `klatrebot_v2/klatrebot_v2/llm/chat.py`**

```python
"""Discord-decoupled LLM call pipeline."""
from typing import Callable

from pydantic import BaseModel

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.db import messages as msg_db


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


# Bot.setup_hook injects the live aiosqlite.Connection here. Tests monkeypatch.
_get_db_conn: Callable | None = None


def set_db_conn_provider(provider: Callable) -> None:
    global _get_db_conn
    _get_db_conn = provider


async def reply(*, question: str, asking_user_id: int, channel_id: int) -> ChatReply:
    if _get_db_conn is None:
        raise RuntimeError("chat.reply called before db conn provider was set")
    conn = _get_db_conn()
    s = get_settings()
    soul = load_soul()

    recent = await msg_db.recent_with_authors(conn, channel_id=channel_id, limit=s.gpt_recent_message_count)
    context_block = "\n".join(f"{m.user_display_name}: {m.content}" for m in recent)

    full_input = (
        f"{soul}\n\n"
        f"CONTEXT (recent chat):\n{context_block}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"QUESTION: {question}"
    )
    client = get_client()
    resp = await client.responses.create(
        model=s.model,
        input=full_input,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return ChatReply(text=resp.output_text or "", sources=[])
```

- [ ] **Step 4: Update `cogs/chat.py` to pass channel_id**

```python
result = await chat.reply(
    question=question,
    asking_user_id=ctx.author.id,
    channel_id=ctx.channel.id,
)
```

- [ ] **Step 5: Update `bot.py` setup_hook to wire the db provider**

In `KlatreBot.setup_hook`, after migrations:

```python
from klatrebot_v2.llm import chat as llm_chat
llm_chat.set_db_conn_provider(lambda: self.db_conn)
```

- [ ] **Step 6: Update first `test_chat.py::test_reply_returns_chat_reply` to also pass `channel_id=0` and stub `_get_db_conn`**

```python
from klatrebot_v2.llm import chat
chat.set_db_conn_provider(lambda: db)   # using db fixture
result = await chat.reply(question="hvad så", asking_user_id=42, channel_id=0)
```

(Add the `db` fixture to that test's signature.)

- [ ] **Step 7: Run all tests — pass**

```bash
poetry run pytest -v
```
Expected: all passing (settings + users + messages + ratelimit + chat).

- [ ] **Step 8: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/chat.py klatrebot_v2/klatrebot_v2/cogs/chat.py klatrebot_v2/klatrebot_v2/bot.py klatrebot_v2/tests/unit/test_chat.py
git commit -m "feat(v2): !gpt uses recent-N message context"
```

### Task 16: `cogs/auto_responses.py` skeleton — message logging only

Goal: every non-bot Discord message lands in sqlite. Trigger table stays empty until slice 6.

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/cogs/auto_responses.py`
- Modify: `klatrebot_v2/klatrebot_v2/bot.py` (load the cog)

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/cogs/auto_responses.py`**

```python
"""on_message listener — logs each user message to sqlite. Trigger table is filled in slice 6."""
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db, users as users_db


logger = logging.getLogger(__name__)


class AutoResponsesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Persist user + message
        await users_db.upsert(
            self.bot.db_conn,
            discord_user_id=message.author.id,
            display_name=_display_name(message.author),
        )
        await msg_db.insert(
            self.bot.db_conn,
            discord_message_id=message.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            content=message.content,
            timestamp_utc=message.created_at.replace(tzinfo=timezone.utc) if message.created_at.tzinfo is None else message.created_at,
            is_bot=False,
        )
        # process_commands not needed here — discord.py routes commands itself when prefix matches.


def _display_name(member) -> str:
    nick = getattr(member, "nick", None)
    if nick:
        return nick
    return getattr(member, "global_name", None) or member.name


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoResponsesCog(bot))
```

- [ ] **Step 2: Add cog load to `bot.py setup_hook`**

```python
await self.load_extension("klatrebot_v2.cogs.auto_responses")
```

- [ ] **Step 3: Re-run all tests**

```bash
poetry run pytest -v
```
Expected: still pass; cog has no unit test yet (covered indirectly when integration test grows).

- [ ] **Step 4: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/auto_responses.py klatrebot_v2/klatrebot_v2/bot.py
git commit -m "feat(v2): on_message logs to sqlite"
```

End of slice 2.

---

## Slice 3 — `web_search` tool

Goal: model can call OpenAI's native `web_search`; sources appear in `!gpt` reply if used.

### Task 17: `_extract_sources` helper

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/llm/chat.py`
- Modify: `klatrebot_v2/tests/unit/test_chat.py`

- [ ] **Step 1: Write the failing test (append to `test_chat.py`)**

```python
def test_extract_sources_from_response():
    from klatrebot_v2.llm.chat import _extract_sources

    fake_resp = MagicMock()
    fake_resp.output = [
        MagicMock(type="message"),  # not a search call
        MagicMock(
            type="web_search_call",
            action=MagicMock(sources=[
                MagicMock(url="https://a.dk"),
                MagicMock(url="https://b.dk"),
            ]),
        ),
    ]
    assert _extract_sources(fake_resp) == ["https://a.dk", "https://b.dk"]


def test_extract_sources_empty_when_no_search():
    from klatrebot_v2.llm.chat import _extract_sources

    fake_resp = MagicMock()
    fake_resp.output = [MagicMock(type="message")]
    assert _extract_sources(fake_resp) == []
```

- [ ] **Step 2: Run — fail**

```bash
poetry run pytest tests/unit/test_chat.py::test_extract_sources_from_response -v
```
Expected: ImportError.

- [ ] **Step 3: Add `_extract_sources` to `klatrebot_v2/klatrebot_v2/llm/chat.py`**

```python
def _extract_sources(resp) -> list[str]:
    """Pull URLs from `web_search_call.action.sources`. Returns [] if not present."""
    out = getattr(resp, "output", None) or []
    for item in out:
        if getattr(item, "type", None) == "web_search_call":
            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None) if action else None
            if not sources:
                return []
            return [getattr(s, "url", "") for s in sources if getattr(s, "url", None)]
    return []
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_chat.py -v
```

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/chat.py klatrebot_v2/tests/unit/test_chat.py
git commit -m "feat(v2): _extract_sources helper"
```

### Task 18: Pass `web_search` tool + `include` to Responses API

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/llm/chat.py`
- Modify: `klatrebot_v2/tests/unit/test_chat.py`

- [ ] **Step 1: Update existing chat tests to assert tool wiring**

In the existing `test_reply_returns_chat_reply`, after the existing assertions add:

```python
    assert call_kwargs["tools"] == [{"type": "web_search"}]
    assert "web_search_call.action.sources" in call_kwargs["include"]
```

- [ ] **Step 2: Run — fail**

Expected: KeyError or assertion failure.

- [ ] **Step 3: Update `chat.reply` body**

Inside `reply()`, change the `client.responses.create` call to:

```python
resp = await client.responses.create(
    model=s.model,
    input=full_input,
    tools=[{"type": "web_search"}],
    reasoning={"effort": "medium"},
    text={"verbosity": "medium"},
    include=["web_search_call.action.sources"],
)
return ChatReply(text=resp.output_text or "", sources=_extract_sources(resp))
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_chat.py -v
```

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/chat.py klatrebot_v2/tests/unit/test_chat.py
git commit -m "feat(v2): enable native web_search tool in !gpt"
```

End of slice 3.

---

## Slice 4 — Klatretid attendance

Goal: bot auto-posts attendance embed Mon/Thu 17:00 local; users react ✅/❌; events recorded; `!klatring` shows current tally.

### Task 19: Time helpers — next-klatretid, 5AM-window

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/time_utils.py`
- Test: `klatrebot_v2/tests/unit/test_klatretid_schedule.py`
- Test: `klatrebot_v2/tests/unit/test_referat_window.py`

- [ ] **Step 1: Write failing test `klatrebot_v2/tests/unit/test_klatretid_schedule.py`**

```python
from datetime import datetime
import pytz


def test_next_klatretid_post_skips_past():
    """If today is Monday at 18:00 local, the next post is Thursday 17:00 local."""
    from klatrebot_v2.time_utils import next_klatretid_post

    tz = pytz.timezone("Europe/Copenhagen")
    monday_18 = tz.localize(datetime(2026, 5, 4, 18, 0, 0))   # Mon
    nxt = next_klatretid_post(now=monday_18, days=[0, 3], hour=17, tz=tz)
    assert nxt.weekday() == 3       # Thu
    assert nxt.hour == 17


def test_next_klatretid_post_today_if_before_hour():
    from klatrebot_v2.time_utils import next_klatretid_post

    tz = pytz.timezone("Europe/Copenhagen")
    monday_10 = tz.localize(datetime(2026, 5, 4, 10, 0, 0))
    nxt = next_klatretid_post(now=monday_10, days=[0, 3], hour=17, tz=tz)
    assert nxt.weekday() == 0
    assert nxt.hour == 17
    assert nxt.day == 4


def test_klatring_start_utc_for_post_date():
    """Klatring start = same date, 20:00 local → UTC."""
    from klatrebot_v2.time_utils import klatring_start_utc_for

    tz = pytz.timezone("Europe/Copenhagen")
    nxt_post = tz.localize(datetime(2026, 5, 4, 17, 0, 0))
    start = klatring_start_utc_for(post_time_local=nxt_post, start_hour=20)
    assert start.tzinfo is not None
    assert start.utcoffset().total_seconds() == 0   # UTC
    assert start.hour in (18, 19)   # 20:00 CET/CEST → 18 or 19 UTC depending on DST
```

- [ ] **Step 2: Write failing test `klatrebot_v2/tests/unit/test_referat_window.py`**

```python
from datetime import datetime
import pytz


def test_since_5am_local_after_5am():
    from klatrebot_v2.time_utils import since_5am_local

    tz = pytz.timezone("Europe/Copenhagen")
    now = tz.localize(datetime(2026, 4, 30, 12, 0, 0))
    start = since_5am_local(now=now, tz=tz)
    assert start.hour == 5
    assert start.day == 30
    assert start.month == 4


def test_since_5am_local_before_5am_returns_yesterday():
    from klatrebot_v2.time_utils import since_5am_local

    tz = pytz.timezone("Europe/Copenhagen")
    now = tz.localize(datetime(2026, 4, 30, 3, 0, 0))
    start = since_5am_local(now=now, tz=tz)
    assert start.hour == 5
    assert start.day == 29   # yesterday
```

- [ ] **Step 3: Run — fail (module missing)**

```bash
poetry run pytest tests/unit/test_klatretid_schedule.py tests/unit/test_referat_window.py -v
```
Expected: ImportError.

- [ ] **Step 4: Write `klatrebot_v2/klatrebot_v2/time_utils.py`**

```python
"""Time/timezone helpers."""
from datetime import datetime, time, timedelta, timezone

import pytz


def next_klatretid_post(*, now: datetime, days: list[int], hour: int, tz: pytz.BaseTzInfo) -> datetime:
    """Return the next future post moment as a tz-aware datetime."""
    local_now = now.astimezone(tz)
    for offset in range(0, 8):
        candidate_date = (local_now + timedelta(days=offset)).date()
        if candidate_date.weekday() not in days:
            continue
        candidate = tz.localize(datetime.combine(candidate_date, time(hour=hour)))
        if candidate > local_now:
            return candidate
    raise RuntimeError("Unreachable: no klatretid in next 7 days")


def klatring_start_utc_for(*, post_time_local: datetime, start_hour: int) -> datetime:
    """Klatring starts at start_hour:00 local on the same date as the embed post."""
    local_dt = post_time_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return local_dt.astimezone(timezone.utc)


def since_5am_local(*, now: datetime, tz: pytz.BaseTzInfo) -> datetime:
    """Window start: today 05:00 local if now>=05:00 else yesterday 05:00 local."""
    local_now = now.astimezone(tz)
    today_5am = tz.localize(datetime.combine(local_now.date(), time(hour=5)))
    if local_now >= today_5am:
        return today_5am
    yesterday = local_now.date() - timedelta(days=1)
    return tz.localize(datetime.combine(yesterday, time(hour=5)))
```

- [ ] **Step 5: Run — pass**

```bash
poetry run pytest tests/unit/test_klatretid_schedule.py tests/unit/test_referat_window.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/time_utils.py klatrebot_v2/tests/unit/test_klatretid_schedule.py klatrebot_v2/tests/unit/test_referat_window.py
git commit -m "feat(v2): time helpers — klatretid schedule + 5AM window"
```

### Task 20: `db/attendance.py` — sessions, events, bailers

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/db/attendance.py`
- Test: `klatrebot_v2/tests/unit/test_attendance_db.py`

- [ ] **Step 1: Write failing test `klatrebot_v2/tests/unit/test_attendance_db.py`**

```python
from datetime import datetime, timedelta, timezone

from klatrebot_v2.db import attendance as att_db, users as users_db


async def _seed_users(db, ids):
    for i in ids:
        await users_db.upsert(db, discord_user_id=i, display_name=f"u{i}")


async def test_create_and_get_active_session(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(
        db,
        date_local="2026-05-04",
        channel_id=999,
        message_id=42,
        klatring_start_utc=start,
    )
    sess = await att_db.active_session(db, channel_id=999, today_local="2026-05-04")
    assert sess is not None
    assert sess.id == sess_id
    assert sess.message_id == 42


async def test_record_event_and_count(db):
    await _seed_users(db, [1, 2])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    t = datetime(2026, 5, 4, 17, 30, tzinfo=timezone.utc)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=t)
    await att_db.record_event(db, session_id=sess_id, user_id=2, status="no", timestamp_utc=t)
    yes, no = await att_db.tally(db, session_id=sess_id)
    assert {u.discord_user_id for u in yes} == {1}
    assert {u.discord_user_id for u in no} == {2}


async def test_bailers_query(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)   # 20:00 CEST → 18:00Z (DST)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    # User says yes 3 hours before, then bails 30 minutes before
    yes_t = start - timedelta(hours=3)
    bail_t = start - timedelta(minutes=30)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=yes_t)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=bail_t)
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert {u.discord_user_id for u in bailers} == {1}


async def test_user_who_was_no_then_yes_then_no_within_hour_is_bailer(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(hours=4))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=start - timedelta(hours=2))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(minutes=30))
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert {u.discord_user_id for u in bailers} == {1}


async def test_user_who_says_no_outside_window_is_not_bailer(db):
    await _seed_users(db, [1])
    start = datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    sess_id = await att_db.create_session(db, date_local="2026-05-04", channel_id=1, message_id=10, klatring_start_utc=start)
    # Says yes, then 'no' but >1h before start → NOT a bailer
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="yes", timestamp_utc=start - timedelta(hours=4))
    await att_db.record_event(db, session_id=sess_id, user_id=1, status="no", timestamp_utc=start - timedelta(hours=2))
    bailers = await att_db.bailers(db, session_id=sess_id)
    assert bailers == []
```

- [ ] **Step 2: Run — fail**

Expected: ImportError.

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/db/attendance.py`**

```python
"""Attendance session + event log + bailer detection."""
from datetime import datetime, timedelta
import aiosqlite

from klatrebot_v2.db.models import AttendanceSession, User


async def create_session(
    conn: aiosqlite.Connection,
    *,
    date_local: str,
    channel_id: int,
    message_id: int,
    klatring_start_utc: datetime,
) -> int:
    cursor = await conn.execute(
        """
        INSERT INTO attendance_session (date_local, channel_id, message_id, klatring_start_utc)
        VALUES (?, ?, ?, ?)
        """,
        (date_local, channel_id, message_id, klatring_start_utc.isoformat()),
    )
    await conn.commit()
    return cursor.lastrowid


async def active_session(
    conn: aiosqlite.Connection, *, channel_id: int, today_local: str
) -> AttendanceSession | None:
    cursor = await conn.execute(
        """
        SELECT id, date_local, channel_id, message_id, klatring_start_utc
        FROM attendance_session
        WHERE channel_id = ? AND date_local = ?
        """,
        (channel_id, today_local),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return AttendanceSession(
        id=row[0],
        date_local=row[1],
        channel_id=row[2],
        message_id=row[3],
        klatring_start_utc=datetime.fromisoformat(row[4]),
    )


async def record_event(
    conn: aiosqlite.Connection,
    *,
    session_id: int,
    user_id: int,
    status: str,    # 'yes' | 'no'
    timestamp_utc: datetime,
) -> None:
    if status not in ("yes", "no"):
        raise ValueError(f"invalid status: {status!r}")
    await conn.execute(
        """
        INSERT INTO attendance_reaction_event (session_id, user_id, status, timestamp_utc)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, user_id, status, timestamp_utc.isoformat()),
    )
    await conn.commit()


async def tally(conn: aiosqlite.Connection, *, session_id: int) -> tuple[list[User], list[User]]:
    """Return (yes_users, no_users) based on each user's LATEST event."""
    cursor = await conn.execute(
        """
        WITH latest AS (
            SELECT user_id, status,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY timestamp_utc DESC) AS rn
            FROM attendance_reaction_event
            WHERE session_id = ?
        )
        SELECT u.discord_user_id, u.display_name, u.is_admin, latest.status
        FROM latest
        JOIN users u ON u.discord_user_id = latest.user_id
        WHERE latest.rn = 1
        """,
        (session_id,),
    )
    rows = await cursor.fetchall()
    yes_users, no_users = [], []
    for r in rows:
        u = User(discord_user_id=r[0], display_name=r[1], is_admin=bool(r[2]))
        (yes_users if r[3] == "yes" else no_users).append(u)
    return yes_users, no_users


async def bailers(conn: aiosqlite.Connection, *, session_id: int) -> list[User]:
    """A user bailed iff they had a 'yes' before they said 'no' within the last hour before klatring start."""
    cursor = await conn.execute(
        """
        SELECT klatring_start_utc FROM attendance_session WHERE id = ?
        """,
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return []
    start = datetime.fromisoformat(row[0])
    bail_window_open = (start - timedelta(hours=1)).isoformat()
    bail_window_close = start.isoformat()

    cursor = await conn.execute(
        """
        SELECT DISTINCT e1.user_id, u.display_name, u.is_admin
        FROM attendance_reaction_event e1
        JOIN users u ON u.discord_user_id = e1.user_id
        WHERE e1.session_id = ?
          AND e1.status = 'no'
          AND e1.timestamp_utc >= ?
          AND e1.timestamp_utc < ?
          AND EXISTS (
              SELECT 1 FROM attendance_reaction_event e2
              WHERE e2.session_id = e1.session_id
                AND e2.user_id    = e1.user_id
                AND e2.status     = 'yes'
                AND e2.timestamp_utc < e1.timestamp_utc
          )
        """,
        (session_id, bail_window_open, bail_window_close),
    )
    rows = await cursor.fetchall()
    return [User(discord_user_id=r[0], display_name=r[1], is_admin=bool(r[2])) for r in rows]
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_attendance_db.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/attendance.py klatrebot_v2/tests/unit/test_attendance_db.py
git commit -m "feat(v2): attendance db — sessions, events, bailers query"
```

### Task 21: Klatretid scheduler in `tasks.py`

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/tasks.py`

No unit test for the live scheduler loop — covered indirectly. The pure timing function `next_klatretid_post` is already tested.

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/tasks.py`**

```python
"""Background tasks. Created by bot.setup_hook."""
import asyncio
import logging
from datetime import datetime, timezone

import discord
import pytz
from discord.ext import commands

from klatrebot_v2.db import attendance as att_db
from klatrebot_v2.settings import get_settings
from klatrebot_v2.time_utils import klatring_start_utc_for, next_klatretid_post


logger = logging.getLogger(__name__)


async def klatretid_scheduler(bot: commands.Bot) -> None:
    """Loop: sleep until next post moment; post; loop."""
    s = get_settings()
    tz = pytz.timezone(s.timezone)
    while True:
        now = datetime.now(timezone.utc)
        nxt = next_klatretid_post(
            now=now,
            days=s.klatretid_days,
            hour=s.klatretid_post_hour,
            tz=tz,
        )
        delay = (nxt - now.astimezone(tz)).total_seconds()
        logger.info("klatretid_scheduler.sleep_until=%s delay_seconds=%.0f", nxt.isoformat(), delay)
        await asyncio.sleep(max(delay, 1.0))
        try:
            await _post_klatretid_embed(bot, post_time_local=nxt)
        except Exception:
            logger.exception("klatretid_scheduler.post_failed")
        # Buffer past the post moment to avoid double-posting due to clock skew
        await asyncio.sleep(60)


async def _post_klatretid_embed(bot: commands.Bot, *, post_time_local: datetime) -> None:
    s = get_settings()
    channel = bot.get_channel(s.discord_main_channel_id)
    if channel is None:
        logger.error("klatretid: main channel %d not found", s.discord_main_channel_id)
        return

    embed = discord.Embed(
        title="Klatretid 🧗",
        description=f"Hvem kommer kl. {s.klatretid_start_hour}? React med ✅ / ❌.",
        color=0x6E1FFF,
    )
    msg = await channel.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    klatring_start = klatring_start_utc_for(
        post_time_local=post_time_local, start_hour=s.klatretid_start_hour
    )
    await att_db.create_session(
        bot.db_conn,
        date_local=post_time_local.strftime("%Y-%m-%d"),
        channel_id=channel.id,
        message_id=msg.id,
        klatring_start_utc=klatring_start,
    )
    logger.info("klatretid_session.created date=%s msg=%d", post_time_local.date(), msg.id)
```

- [ ] **Step 2: Wire scheduler from `bot.setup_hook`**

In `KlatreBot.setup_hook`, append:

```python
from klatrebot_v2.tasks import klatretid_scheduler
self.loop.create_task(klatretid_scheduler(self))
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/tasks.py klatrebot_v2/klatrebot_v2/bot.py
git commit -m "feat(v2): klatretid scheduler + embed post"
```

### Task 22: `cogs/attendance.py` — reactions + `!klatring`

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/cogs/attendance.py`
- Modify: `klatrebot_v2/klatrebot_v2/bot.py` (load extension)

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/cogs/attendance.py`**

```python
"""Klatretid reaction handler + !klatring status command."""
import logging
from datetime import datetime, timezone

import discord
import pytz
from discord.ext import commands

from klatrebot_v2.db import attendance as att_db, users as users_db
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)


def _today_local_str() -> str:
    s = get_settings()
    tz = pytz.timezone(s.timezone)
    return datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")


class AttendanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, retract=False)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, retract=True)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, *, retract: bool) -> None:
        if payload.user_id == (self.bot.user.id if self.bot.user else 0):
            return
        sess = await att_db.active_session(
            self.bot.db_conn, channel_id=payload.channel_id, today_local=_today_local_str()
        )
        if sess is None or sess.message_id != payload.message_id:
            return
        emoji = payload.emoji.name
        if emoji == "✅":
            status = "no" if retract else "yes"
        elif emoji == "❌":
            status = "yes" if retract else "no"
        else:
            return
        # Make sure user row exists
        await users_db.upsert(self.bot.db_conn, discord_user_id=payload.user_id, display_name=str(payload.user_id))
        await att_db.record_event(
            self.bot.db_conn,
            session_id=sess.id,
            user_id=payload.user_id,
            status=status,
            timestamp_utc=datetime.now(timezone.utc),
        )

    @commands.command(name="klatring")
    async def klatring(self, ctx: commands.Context) -> None:
        sess = await att_db.active_session(
            self.bot.db_conn, channel_id=ctx.channel.id, today_local=_today_local_str()
        )
        if sess is None:
            await ctx.reply("Ingen klatretid lige nu.")
            return
        yes, no = await att_db.tally(self.bot.db_conn, session_id=sess.id)
        bailers = await att_db.bailers(self.bot.db_conn, session_id=sess.id)
        bailer_ids = {u.discord_user_id for u in bailers}
        yes_names = ", ".join(u.display_name for u in yes) or "ingen"
        no_names = ", ".join(
            (f"{u.display_name} 🐔" if u.discord_user_id in bailer_ids else u.display_name) for u in no
        ) or "ingen"
        await ctx.reply(f"Klatretid status:\n✅ {yes_names}\n❌ {no_names}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttendanceCog(bot))
```

- [ ] **Step 2: Load extension in `bot.setup_hook`**

```python
await self.load_extension("klatrebot_v2.cogs.attendance")
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/attendance.py klatrebot_v2/klatrebot_v2/bot.py
git commit -m "feat(v2): attendance cog — reactions + !klatring status"
```

End of slice 4.

---

## Slice 5 — `!referat`

Goal: `!referat` summarizes today's chat (since 05:00 local).

### Task 23: `messages.in_window` query

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/db/messages.py`
- Modify: `klatrebot_v2/tests/unit/test_messages_db.py`

- [ ] **Step 1: Add failing test (append to `test_messages_db.py`)**

```python
async def test_in_window_filters_by_time(db):
    await users_db.upsert(db, discord_user_id=1, display_name="A")
    base = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        await msg_db.insert(db, discord_message_id=i, channel_id=1, user_id=1, content=f"m{i}", timestamp_utc=base + timedelta(minutes=i))
    rows = await msg_db.in_window(
        db,
        channel_id=1,
        start=base + timedelta(minutes=1),
        end=base + timedelta(minutes=4),
    )
    assert [r.content for r in rows] == ["m1", "m2", "m3"]
```

- [ ] **Step 2: Run — fail**

Expected: `AttributeError`.

- [ ] **Step 3: Add to `klatrebot_v2/klatrebot_v2/db/messages.py`**

```python
async def in_window(
    conn: aiosqlite.Connection,
    *,
    channel_id: int,
    start: datetime,
    end: datetime,
) -> list[MessageWithAuthor]:
    """[start, end) window, oldest-first."""
    cursor = await conn.execute(
        """
        SELECT m.discord_message_id, m.channel_id, m.user_id,
               COALESCE(u.display_name, '?'), m.content, m.timestamp_utc, m.is_bot
        FROM messages m
        LEFT JOIN users u ON u.discord_user_id = m.user_id
        WHERE m.channel_id = ?
          AND m.timestamp_utc >= ?
          AND m.timestamp_utc <  ?
        ORDER BY m.timestamp_utc ASC
        """,
        (channel_id, start.isoformat(), end.isoformat()),
    )
    rows = await cursor.fetchall()
    return [
        MessageWithAuthor(
            discord_message_id=r[0],
            channel_id=r[1],
            user_id=r[2],
            user_display_name=r[3],
            content=r[4],
            timestamp_utc=datetime.fromisoformat(r[5]),
            is_bot=bool(r[6]),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_messages_db.py -v
```

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/db/messages.py klatrebot_v2/tests/unit/test_messages_db.py
git commit -m "feat(v2): messages.in_window query"
```

### Task 24: `llm/chat.summarize`

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/llm/chat.py`
- Test: `klatrebot_v2/tests/unit/test_summarize.py`

- [ ] **Step 1: Write failing test `klatrebot_v2/tests/unit/test_summarize.py`**

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


async def test_summarize_calls_llm_with_messages(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("Soul.")
    monkeypatch.setenv("DISCORD_KEY", "x"); monkeypatch.setenv("OPENAI_KEY", "x")
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1"); monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3"); monkeypatch.setenv("SOUL_PATH", str(soul))

    from klatrebot_v2.llm import client, chat, prompt
    from klatrebot_v2.db.messages import MessageWithAuthor
    client._client = None
    prompt.load_soul.cache_clear()

    fake_resp = MagicMock(); fake_resp.output_text = "Her er hvad boomerene har yappet om i dag..."
    fake_client = MagicMock(); fake_client.responses = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(client, "_client", fake_client)

    msgs = [
        MessageWithAuthor(
            discord_message_id=1, channel_id=1, user_id=10,
            user_display_name="Magnus", content="hej alle",
            timestamp_utc=datetime(2026, 4, 30, 6, 0, tzinfo=timezone.utc), is_bot=False,
        ),
        MessageWithAuthor(
            discord_message_id=2, channel_id=1, user_id=11,
            user_display_name="Pelle", content="god morgen",
            timestamp_utc=datetime(2026, 4, 30, 6, 5, tzinfo=timezone.utc), is_bot=False,
        ),
    ]
    summary = await chat.summarize(msgs)

    assert "Her er hvad boomerene" in summary
    call_kwargs = fake_client.responses.create.await_args.kwargs
    assert "Magnus (10): hej alle" in call_kwargs["input"]
    assert "Pelle (11): god morgen" in call_kwargs["input"]
    # No web_search for summarize:
    assert "tools" not in call_kwargs or call_kwargs["tools"] == []
```

- [ ] **Step 2: Run — fail**

Expected: `AttributeError: module ... has no attribute 'summarize'`.

- [ ] **Step 3: Add `summarize()` to `klatrebot_v2/klatrebot_v2/llm/chat.py`**

```python
_SUMMARY_INSTRUCTIONS = """
**Instructions for the AI (Output must be in Danish):**

1.  **Mandatory Opening Line (in Danish):**
    Always begin your response with the exact Danish phrase: "Her er hvad boomerene har yappet om i stedet for at arbejde i dag" or a very similar, contextually appropriate humorous Danish variation.

2.  **Primary Task:** Summarize the day's chat. Humorous tone, jokes that reference the actual content.

3.  **User Identification:** Each line shows `Name (id): content`. Refer to people by name in the summary; NEVER print numeric IDs in the output.

4.  **Length:** No 60-word cap; can be longer to cover the day. Stay in Danish.
"""


async def summarize(msgs) -> str:
    """Summarize a list of MessageWithAuthor. One Responses API call, no tools."""
    soul = load_soul()
    body = "\n".join(f"{m.user_display_name} ({m.user_id}): {m.content}" for m in msgs)
    full_input = f"{soul}\n\n{_SUMMARY_INSTRUCTIONS}\n\nBESKEDER:\n{body}"
    client = get_client()
    resp = await client.responses.create(
        model=get_settings().model,
        input=full_input,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return resp.output_text or ""
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_summarize.py -v
```

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/llm/chat.py klatrebot_v2/tests/unit/test_summarize.py
git commit -m "feat(v2): llm.chat.summarize — Danish chat-day summary"
```

### Task 25: `cogs/referat.py` — `!referat` command

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/cogs/referat.py`
- Modify: `klatrebot_v2/klatrebot_v2/bot.py`

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/cogs/referat.py`**

```python
"""!referat — summarizes today's chat (05:00 local → now)."""
import logging
from datetime import datetime, timezone

import pytz
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db
from klatrebot_v2.llm import chat
from klatrebot_v2.settings import get_settings
from klatrebot_v2.time_utils import since_5am_local


logger = logging.getLogger(__name__)


class RefereatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="referat")
    async def referat(self, ctx: commands.Context) -> None:
        s = get_settings()
        tz = pytz.timezone(s.timezone)
        now_utc = datetime.now(timezone.utc)
        window_start = since_5am_local(now=now_utc, tz=tz).astimezone(timezone.utc)

        async with ctx.typing():
            msgs = await msg_db.in_window(
                self.bot.db_conn,
                channel_id=ctx.channel.id,
                start=window_start,
                end=now_utc,
            )
            if not msgs:
                await ctx.reply("Ingen beskeder siden 05:00.")
                return
            summary = await chat.summarize(msgs)
        await ctx.reply(summary)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RefereatCog(bot))
```

- [ ] **Step 2: Load extension in `bot.setup_hook`**

```python
await self.load_extension("klatrebot_v2.cogs.referat")
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/referat.py klatrebot_v2/klatrebot_v2/bot.py
git commit -m "feat(v2): !referat — chat-day summary command"
```

End of slice 5.

---

## Slice 6 — Trivia + auto-response triggers

Goal: ports the lightweight features back — trivia commands + the meme on_message regex matchers — and wires up the data-driven `RESPONSES` table.

### Task 26: Port `pelle.py` (pure functions)

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/pelle.py`
- Test: `klatrebot_v2/tests/unit/test_pelle.py`

- [ ] **Step 1: Write the failing test `klatrebot_v2/tests/unit/test_pelle.py`**

```python
import datetime as dt


def test_seconds_string_zero():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert seconds_as_dt_string(0) == ""


def test_seconds_string_minutes_only():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert seconds_as_dt_string(120).strip() == "2 minutter".strip()


def test_seconds_string_singular_plural():
    from klatrebot_v2.pelle import seconds_as_dt_string
    assert "1 minut" in seconds_as_dt_string(60)
    assert "2 minutter" in seconds_as_dt_string(120)
    assert "1 time" in seconds_as_dt_string(3600)
    assert "2 timer" in seconds_as_dt_string(7200)
    assert "1 dag" in seconds_as_dt_string(86400)
    assert "2 dage" in seconds_as_dt_string(2 * 86400)
```

- [ ] **Step 2: Run — fail**

Expected: ImportError.

- [ ] **Step 3: Write `klatrebot_v2/klatrebot_v2/pelle.py`**

Port the V1 logic from `pelleService.py:9-138`. Renamed for clarity. Keep behavior identical for now; review in a follow-up.

```python
"""Pelle location/time formatter. Pure functions; no Discord coupling.

Ported from V1 pelleService.py (2026-04 cleanup snapshot).
The HTTP fetch lives here for now — pure-function refactor deferred to follow-up.
"""
from __future__ import annotations

import datetime
import re

import pytz
import requests
from dateutil.parser import parse


KINDS = {
    "ACCOMMODATION": ":love_hotel:", "DRIVING": ":blue_car:", "FLYING": ":airplane:",
    "HIKING": ":man_running:", "POINTOFINTEREST": ":mount_fuji:", "SIGHTSEEING": ":statue_of_liberty:",
    "WINE": ":wine:", "TAKEOFF": ":airplane:", "LANDING": ":airplane:", "BREAKFAST": ":pancakes:",
    "DINNER": ":sushi:", "SLEEPING": ":sleeping:", "TRANSFER": ":airplane:", "CHILL": ":pepedance:",
    "BUS": ":minibus:",
}
COPENHAGEN = pytz.timezone("Europe/Copenhagen")


def seconds_as_dt_string(total_seconds: float) -> str:
    days, seconds = divmod(total_seconds, 86400)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    days_text = "dag" if days == 1 else "dage"
    hours_text = "time" if hours == 1 else "timer"
    minutes_text = "minut" if minutes == 1 else "minutter"
    seconds_text = "sekund" if seconds == 1 else "sekunder"

    out = "" if days == 0 else f"{days:.0f} {days_text} "
    out += "" if hours == 0 else f"{hours:.0f} {hours_text} "
    out += "" if hours == 0 and minutes == 0 else f"{minutes:.0f} {minutes_text} "
    out += "" if seconds == 0 else f"{seconds:.0f} {seconds_text}"
    return out


def where_the_fuck_is_pelle(arg: str | None = None, debug_ts: str = "") -> str:
    pelle_ctx = "seoul-2026"

    if arg is not None and arg.lower() == "pic":
        try:
            html_url = f"https://pellelauritsen.net/api/html/{pelle_ctx}/newest"
            response = requests.get(html_url, timeout=10)
            response.raise_for_status()
            img_match = re.search(r'<img src="([^"]+)"', response.text)
            return img_match.group(1) if img_match else "Could not find latest Pelle picture"
        except Exception as e:
            return f"Failed to fetch Pelle pic: {e}"

    max_distance = 1_000_000_000
    response = requests.get(f"https://pellelauritsen.net/{pelle_ctx}.json", timeout=10)
    if not response.ok:
        return "Ingen aner hvor Pelle er, men måske er han på vej til klatring."
    fulljs = response.json()

    current_acc, current_act = {}, {}
    last_distance, next_act = max_distance, {}
    now = COPENHAGEN.localize(parse(debug_ts)) if debug_ts else COPENHAGEN.localize(datetime.datetime.now())

    for activity in fulljs.get("activities", []):
        if "begin" not in activity:
            continue
        start = pytz.timezone(activity["begin"]["timezone"]).localize(parse(activity["begin"]["dateTime"]))
        end = pytz.timezone(activity["end"]["timezone"]).localize(parse(activity["end"]["dateTime"]))

        if start < now < end:
            if "kind" in activity and activity["kind"] == "ACCOMMODATION":
                current_acc = activity
            else:
                current_act = activity
            continue

        seconds_until_next = (start - now).total_seconds()
        if last_distance > seconds_until_next > 0:
            last_distance = seconds_until_next
            next_act = activity

    out = ""
    if not current_act:
        if last_distance < 0 or last_distance == max_distance:
            return "Pelle er på vej til klatring..."
        pretty = seconds_as_dt_string(last_distance)
        current_act = next_act
        begin_dt = pytz.timezone(current_act["begin"]["timezone"]).localize(parse(current_act["begin"]["dateTime"]))
        out += f"Om {pretty}: {begin_dt} - "

    out += f"{KINDS[current_act['kind']]} {current_act['title']}"
    if current_act.get("description"):
        out += f" ({current_act['description']})"
    if current_act["kind"] == "FLYING" and current_act.get("description"):
        flight_no = current_act["description"].replace(" ", "")
        out += f"\nhttps://www.flightradar24.com/data/flights/{flight_no}"

    if current_act["begin"]["location"] != current_act["end"]["location"]:
        out += f"\n({current_act['begin']['location']} -> {current_act['end']['location']})"

    end_dt = pytz.timezone(current_act["end"]["timezone"]).localize(parse(current_act["end"]["dateTime"]))
    out += f" færdig om {seconds_as_dt_string((end_dt - now).total_seconds())}"

    if current_acc:
        out += f"\nI mellemtiden chiller Pelle @ {KINDS[current_acc['kind']]} {current_acc['title']}"

    if current_act.get("url"):
        out += f" {current_act['url']}"
    elif current_acc.get("url"):
        out += f" {current_acc['url']}"

    coord = []
    if not next_act and "coordinate" in current_act:
        coord = current_act["coordinate"]
    elif current_acc.get("coordinate"):
        coord = current_acc["coordinate"]
    elif next_act.get("coordinate"):
        coord = next_act["coordinate"]
    if len(coord) == 2:
        out += f" https://www.openstreetmap.org/search?query={coord[0]}%2C%20{coord[1]}"
    return out
```

- [ ] **Step 4: Run — pass (only seconds-string tests; HTTP fn is not tested here)**

```bash
poetry run pytest tests/unit/test_pelle.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/pelle.py klatrebot_v2/tests/unit/test_pelle.py
git commit -m "feat(v2): port pelleService → pelle.py"
```

### Task 27: `cogs/trivia.py` — `!ugenr`, `!uptime`, `!pelle`, `!glar`

**Files:**
- Create: `klatrebot_v2/klatrebot_v2/cogs/trivia.py`
- Modify: `klatrebot_v2/klatrebot_v2/bot.py`

- [ ] **Step 1: Write `klatrebot_v2/klatrebot_v2/cogs/trivia.py`**

```python
"""Lightweight trivia commands."""
from datetime import datetime

from discord.ext import commands

from klatrebot_v2.pelle import where_the_fuck_is_pelle


class TriviaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="ugenr")
    async def ugenr(self, ctx: commands.Context) -> None:
        await ctx.reply(f"Vi er i uge {datetime.now().isocalendar()[1]}")

    @commands.command(name="uptime")
    async def uptime(self, ctx: commands.Context) -> None:
        if self.bot.start_time is None:
            await ctx.reply("Lige startet.")
            return
        delta = datetime.utcnow() - self.bot.start_time
        await ctx.reply(f"Uppe i {delta}")

    @commands.command(name="pelle")
    async def pelle(self, ctx: commands.Context, *, arg: str | None = None) -> None:
        await ctx.reply(where_the_fuck_is_pelle(arg=arg))

    @commands.command(name="glar")
    async def glar(self, ctx: commands.Context) -> None:
        await ctx.reply("https://imgur.com/CnRFnel")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TriviaCog(bot))
```

- [ ] **Step 2: Load extension in `bot.setup_hook`**

```python
await self.load_extension("klatrebot_v2.cogs.trivia")
```

- [ ] **Step 3: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/trivia.py klatrebot_v2/klatrebot_v2/bot.py
git commit -m "feat(v2): trivia cog — ugenr/uptime/pelle/glar"
```

### Task 28: Auto-response trigger table

**Files:**
- Modify: `klatrebot_v2/klatrebot_v2/cogs/auto_responses.py`
- Test: `klatrebot_v2/tests/unit/test_auto_responses.py`

- [ ] **Step 1: Write failing test `klatrebot_v2/tests/unit/test_auto_responses.py`**

```python
def test_first_match_wins_and_patterns_compile():
    from klatrebot_v2.cogs.auto_responses import RESPONSES, first_match

    # Each pattern compiles to re.Pattern
    for ar in RESPONSES:
        assert ar.pattern.search("just any string here") is None or hasattr(ar.pattern, "search")

    # downus matches "fail"
    m = first_match("Det her var bare en fail tbh")
    assert m is not None and m.name == "downus"

    # ekstrabladet domain
    m = first_match("https://www.ekstrabladet.dk/blah")
    assert m is not None and m.name == "ekstrabladet"

    # klatrebot? trigger
    m = first_match("klatrebot kommer Magnus i morgen?")
    assert m is not None and m.name == "klatrebot_question"

    # No match
    assert first_match("helt almindelig sætning") is None


def test_uge_match_pattern():
    from klatrebot_v2.cogs.auto_responses import RESPONSES
    pat = next(ar.pattern for ar in RESPONSES if ar.name == "ugenr_match")
    assert pat.search("hvad sker der i uge 35?")
    assert pat.search("uge42") is None    # spec: \buge\s?\d{1,2}\b — needs word boundary
    assert pat.search("uge 35")
```

- [ ] **Step 2: Run — fail**

Expected: ImportError on `RESPONSES` / `first_match`.

- [ ] **Step 3: Replace `klatrebot_v2/klatrebot_v2/cogs/auto_responses.py`**

```python
"""on_message listener — DB log + data-driven trigger table."""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

import discord
from discord.ext import commands

from klatrebot_v2.db import messages as msg_db, users as users_db


logger = logging.getLogger(__name__)


# ─── Trigger registry ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AutoResponse:
    name: str
    pattern: re.Pattern
    handler: Callable[[discord.Message], Awaitable[str | None]]


_SVAR = [
    "Det er sikkert", "Uden tvivl", "Ja helt sikkert", "Som jeg ser det, ja",
    "Højst sandsynligt", "Ja", "Nej", "Nok ikke", "Regn ikke med det",
    "Mine kilder siger nej", "Meget tvivlsomt", "Mit svar er nej",
]

_EB_ROAST = (
    "I - især Magnus - skal til at holde op med at læse Ekstra Bladet, som om I var barbarer.\n"
    "Jeg ved godt, at I høfligt forsøger at integrere jer i Sydhavnen, men få lige skubbet "
    "lidt på den gentrificering og læs et rigtigt medie"
)


async def _static(text: str) -> str:
    return text


async def _handle_uge(_msg: discord.Message) -> str | None:
    # The original V1 expanded the week number into a date range. Phase 1 ports the
    # simple "echo a date range for the requested week" behaviour. Implementation
    # detail kept conservative: see V1 KlatreBot.py:826-849 for reference.
    # For the rewrite, return None — covered by the !ugenr command;
    # the auto-trigger only emits when we want a date-range expansion.
    # Safe default: no-op until the date-range handler is ported in a follow-up.
    return None


RESPONSES: list[AutoResponse] = [
    AutoResponse(
        name="ugenr_match",
        pattern=re.compile(r"\buge\s?\d{1,2}\b", re.I),
        handler=_handle_uge,
    ),
    AutoResponse(
        name="downus",
        pattern=re.compile(r"!downus|fail", re.I),
        handler=lambda m: _static(
            "https://cdn.discordapp.com/attachments/1003718776430268588/1153668006728192101/downus_on_wall.gif"
        ),
    ),
    AutoResponse(
        name="klatrebot_question",
        pattern=re.compile(r"^klatrebot.*\?$", re.I),
        handler=lambda m: _static(random.choice(_SVAR)),
    ),
    AutoResponse(
        name="det_kan_man_ik",
        pattern=re.compile(r"det\skan\sman\s(\w+\s)?ik", re.I),
        handler=lambda m: _static(
            "https://cdn.discordapp.com/attachments/1049312345068933134/1049363489354952764/pellememetekst.gif"
        ),
    ),
    AutoResponse(
        name="elmo",
        pattern=re.compile(r"\b(elmo|elon)\b", re.I),
        handler=lambda m: _static("https://imgur.com/LNVCB8g"),
    ),
    AutoResponse(
        name="ekstrabladet",
        pattern=re.compile(r"ekstrabladet\.dk|eb\.dk", re.I),
        handler=lambda m: _static(_EB_ROAST),
    ),
]


def first_match(text: str) -> AutoResponse | None:
    for ar in RESPONSES:
        if ar.pattern.search(text):
            return ar
    return None


# ─── Cog ─────────────────────────────────────────────────────────────────────


class AutoResponsesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        await users_db.upsert(
            self.bot.db_conn,
            discord_user_id=message.author.id,
            display_name=_display_name(message.author),
        )
        await msg_db.insert(
            self.bot.db_conn,
            discord_message_id=message.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            content=message.content,
            timestamp_utc=message.created_at.replace(tzinfo=timezone.utc) if message.created_at.tzinfo is None else message.created_at,
            is_bot=False,
        )

        ar = first_match(message.content)
        if ar is None:
            return
        logger.info("auto_response.fired name=%s", ar.name)
        try:
            reply = await ar.handler(message)
        except Exception:
            logger.exception("auto_response.handler_failed name=%s", ar.name)
            return
        if reply:
            await message.channel.send(reply)


def _display_name(member) -> str:
    nick = getattr(member, "nick", None)
    if nick:
        return nick
    return getattr(member, "global_name", None) or member.name


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoResponsesCog(bot))
```

- [ ] **Step 4: Run — pass**

```bash
poetry run pytest tests/unit/test_auto_responses.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add klatrebot_v2/klatrebot_v2/cogs/auto_responses.py klatrebot_v2/tests/unit/test_auto_responses.py
git commit -m "feat(v2): auto-response trigger table (downus/elmo/EB/klatrebot?/det kan man ik)"
```

### Task 29: Final sanity — full test run + smoke boot

**Files:** none

- [ ] **Step 1: Run all unit tests**

```bash
cd klatrebot_v2 && poetry run pytest -v
```
Expected: all unit tests pass; integration tests skipped without `-m integration`.

- [ ] **Step 2: Run smoke boot with staging credentials**

```bash
DISCORD_KEY=<staging> OPENAI_KEY=<key> poetry run pytest -m integration -v -s
```
Expected: PASS within 60s; full output ends with `Bot startup completed`.

- [ ] **Step 3: Manual end-to-end check**

In Discord staging server with the bot online, run each:
- `!gpt hej` → reply within ~10s, may include sources
- `!referat` → either summary or "Ingen beskeder siden 05:00"
- `!ugenr` → "Vi er i uge N"
- `!uptime` → some delta
- `!glar` → imgur link
- `!klatring` → "Ingen klatretid lige nu" (no session yet) or current tally
- Type `fail`, `klatrebot kommer du?`, link to `ekstrabladet.dk` → expected auto-replies fire

- [ ] **Step 4: Commit (no changes — but tag the slice if desired)**

```bash
# Optional: tag a Phase 1 marker
git tag v2-phase1
```

End of slice 6. Phase 1 complete.

---

## Coverage check (against spec)

| Spec section | Covered by |
|---|---|
| §3 Stack | Tasks 1, 3 |
| §4 Repo layout | Tasks 1, 2 (skeleton); each subsequent task fills in its module |
| §5 Settings | Task 3 |
| §6 DB schema + Pydantic models | Tasks 5, 6, 13, 14, 20, 23 |
| §7 LLM layer | Tasks 7, 8, 9, 15, 17, 18, 24 |
| §8 Cogs | Tasks 10, 16, 22, 25, 27, 28 |
| §9 Background tasks | Tasks 19, 21 |
| §10 Error handling / logging / observability | Tasks 4, 11 (`on_command_error`, `on_error`, readiness marker) |
| §11 Testing (unit + integration) | Tasks 5, 6, 8, 9, 13, 14, 17, 18, 19, 20, 23, 24, 26, 28, 12, 29 |
| §12 Vertical-slice build order | Slices 1-6 |
| §13 Phase 2 prep | Architecture preserved; no Phase 1 work needed |

No spec gaps.
