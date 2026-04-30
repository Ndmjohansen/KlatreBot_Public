# KlatreBot V2 — Design

**Status**: Approved (Phase 1 design)
**Date**: 2026-04-30
**Owner**: Nicklas Johansen

## 1. Goal

Replace the rotted V1 KlatreBot codebase with a clean Phase 1 rewrite, lean on features, with structure positioned for a Phase 2 agentic-framework integration (Hermes / OpenClaw) without invasive rework.

V1 stays untouched at the repo root for reference and is deletable later. V2 ships as an isolated sibling subdir with its own Poetry project.

## 2. Scope

### Features kept (Phase 1)

| Surface | Detail |
|---|---|
| `!gpt <question>` | Single-pass LLM via OpenAI Responses API + native `web_search` tool |
| `!referat` | Summarizes channel messages from last 05:00 local until now |
| `!glar`, `!pelle`, `!uptime`, `!ugenr` | Trivia commands |
| Klatretid attendance | Mon + Thu 17:00 local, ✅ / ❌ reactions, sqlite-persisted event log |
| `!klatring` | Status command for current attendance session |
| `gpt_response_poster` queue | **Dropped** — discord.py async handles concurrency |
| Auto-response triggers | `uge N`, `!downus`/fail, `klatrebot...?`, `!glar` substring, `det kan man ik`, `elmo`/`elon`, `ekstrabladet.dk` |

### Features dropped

`!jpg`, `!beep`, `!logs*`, `!clear`, `!set_display_name`, `!make_admin`, `!user_stats`, `!db_stats`, `!rag_stats`, `!generate_embeddings`, `!rag_search`, `!rag_toggle`, `!find_user`, `!test_user_query`, `!test_mention`, daily JSON log, vector DB / embeddings, RAG entirely, `go_to_bed`, `daily_message_log.json`, ProomptTaskQueue, ChadLogger, `migrate_discord_history.py`, backup script, systemd + GH Actions deploy.

### Phase 2 (later, out of scope here)

Hermes / OpenClaw agent framework integration. Hooks in via new `llm/agent.py` + new `cogs/agent.py` + `llm/tools/*`. Phase 1 is structured so this is purely additive.

## 3. Stack

- **Language**: Python (>=3.11)
- **Discord lib**: `discord.py` (latest)
- **LLM**: OpenAI Responses API via `AsyncOpenAI`
- **Models**: `MODEL` env var, default `gpt-5.4`
- **Validation**: Pydantic 2.13.3 — at edges only (settings, DB rows, LLM I/O contracts), not wrapping discord.py-native types
- **DB**: sqlite via `aiosqlite`, WAL mode, `synchronous=NORMAL`
- **Deps mgmt**: Poetry (separate project from V1, isolated `pyproject.toml` + lock)
- **Config**: `.env` via `pydantic-settings.BaseSettings`
- **System prompt**: `SOUL.MD` file, path via `SOUL_PATH` env var

## 4. Repo layout

```
KlatreBot_Public/
├── (V1 root files untouched)
└── klatrebot_v2/                    # Poetry project root for V2
    ├── pyproject.toml
    ├── poetry.lock
    ├── README.md
    ├── SOUL.MD                      # system prompt
    ├── .env.example
    ├── tests/
    │   ├── conftest.py
    │   ├── unit/
    │   └── integration/
    └── klatrebot_v2/                # importable python package
        ├── __init__.py
        ├── __main__.py              # `poetry run python3 -m klatrebot_v2`
        ├── settings.py              # Pydantic BaseSettings — .env contract
        ├── bot.py                   # discord.py Bot + on_ready, registers cogs
        ├── logging_config.py        # stdlib logging
        ├── tasks.py                 # background scheduler (klatretid)
        ├── db/
        │   ├── __init__.py
        │   ├── models.py            # Pydantic: User, Message, AttendanceSession, AttendanceEvent
        │   ├── connection.py        # shared aiosqlite connection
        │   ├── migrations.py        # CREATE TABLE IF NOT EXISTS
        │   ├── messages.py          # message log queries
        │   ├── users.py             # user upsert/lookup
        │   └── attendance.py        # session + event CRUD, bailer query
        ├── llm/
        │   ├── __init__.py
        │   ├── client.py            # AsyncOpenAI wrapper
        │   ├── prompt.py            # SOUL.MD loader (lru_cache)
        │   ├── chat.py              # build_context + reply (Discord-decoupled)
        │   └── ratelimit.py         # sliding-window per-user
        └── cogs/
            ├── __init__.py
            ├── chat.py              # !gpt
            ├── referat.py           # !referat
            ├── attendance.py        # ✅/❌ reactions + !klatring
            ├── trivia.py            # !ugenr, !uptime, !pelle, !glar
            └── auto_responses.py    # on_message regex matchers
```

**Run**: `cd klatrebot_v2 && poetry install && poetry run python3 -m klatrebot_v2`

## 5. Configuration (`.env` contract)

`klatrebot_v2/settings.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    discord_key: str
    openai_key: str

    discord_main_channel_id: int
    discord_sandbox_channel_id: int
    admin_user_id: int

    model: str = "gpt-5.4"
    soul_path: str = "./SOUL.MD"
    db_path: str = "./klatrebot_v2.db"

    timezone: str = "Europe/Copenhagen"
    klatretid_days: list[int] = [0, 3]          # 0=Mon, 3=Thu
    klatretid_post_hour: int = 17
    klatretid_start_hour: int = 20

    gpt_recent_message_count: int = 25
    rate_limit_per_user_per_hour: int = 30
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

`.env.example` ships with all keys present and placeholder values. Missing required key → `Settings()` raises `ValidationError` → bot exits 1 at startup.

## 6. Database schema (sqlite, WAL + synchronous=NORMAL)

```sql
CREATE TABLE IF NOT EXISTS users (
    discord_user_id  INTEGER PRIMARY KEY,
    display_name     TEXT NOT NULL,
    is_admin         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    discord_message_id  INTEGER PRIMARY KEY,
    channel_id          INTEGER NOT NULL,
    user_id             INTEGER NOT NULL,
    content             TEXT NOT NULL,
    timestamp_utc       TEXT NOT NULL,
    is_bot              INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS attendance_session (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date_local          TEXT NOT NULL,                  -- 'YYYY-MM-DD' of klatring day
    channel_id          INTEGER NOT NULL,
    message_id          INTEGER NOT NULL,
    klatring_start_utc  TEXT NOT NULL,                  -- precomputed 20:00 local → UTC ISO
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date_local, channel_id)
);

CREATE TABLE IF NOT EXISTS attendance_reaction_event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('yes','no')),
    timestamp_utc   TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES attendance_session(id),
    FOREIGN KEY(user_id) REFERENCES users(discord_user_id)
);
CREATE INDEX IF NOT EXISTS idx_reaction_session_user_ts
    ON attendance_reaction_event(session_id, user_id, timestamp_utc);
```

### Pydantic row models (`db/models.py`)

```python
from datetime import datetime
from pydantic import BaseModel
from typing import Literal

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
    date_local: str                  # 'YYYY-MM-DD'
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

### Connection management

Single shared `aiosqlite.Connection` opened in `bot.setup_hook`, closed on shutdown. Each `db/*.py` module imports the connection getter, never opens its own.

### Migrations

`db/migrations.py::async run(conn)` executes the DDL above. No migration framework — schema-only file. Idempotent (`IF NOT EXISTS`).

## 7. LLM layer

### `llm/client.py`

```python
from openai import AsyncOpenAI
from klatrebot_v2.settings import settings

client = AsyncOpenAI(
    api_key=settings.openai_key,
    timeout=60.0,
    max_retries=0,    # we handle retries ourselves
)
```

### `llm/prompt.py`

```python
from pathlib import Path
from functools import lru_cache
from klatrebot_v2.settings import settings

@lru_cache(maxsize=1)
def load_soul() -> str:
    return Path(settings.soul_path).read_text(encoding="utf-8").strip()
```

Loaded once at first call, cached. Bot restart picks up edits.

### `llm/chat.py` — `!gpt` and `!referat` core

```python
from pydantic import BaseModel
from openai.types.responses import Response
from klatrebot_v2.db import messages as msg_db
from klatrebot_v2.llm.client import client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.settings import settings

class ChatReply(BaseModel):
    text: str
    sources: list[str] = []

async def reply(channel_id: int, question: str, asking_user_id: int) -> ChatReply:
    soul = load_soul()
    recent = await msg_db.recent(channel_id, limit=settings.gpt_recent_message_count)
    context_block = "\n".join(f"{m.user_display_name}: {m.content}" for m in recent)
    full_input = (
        f"{soul}\n\n"
        f"CONTEXT (recent chat):\n{context_block}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"QUESTION: {question}"
    )
    resp: Response = await client.responses.create(
        model=settings.model,
        input=full_input,
        tools=[{"type": "web_search"}],
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
        include=["web_search_call.action.sources"],
    )
    return ChatReply(
        text=_sanitize_mentions(resp.output_text),
        sources=_extract_sources(resp),
    )

async def summarize(messages: list[Message]) -> str:
    """Used by !referat. Builds a 'render messages as bullet log' input,
    sends one Responses API call (no tools, web_search not relevant for chat-history summary),
    returns the Danish summary text."""
```

**Single round-trip**: model decides whether to call `web_search`. No separate planner LLM.

The `_sanitize_mentions` helper keeps V1's truncated-mention safety net. Will be measured via logs and removed if it never fires.

`_extract_sources(resp)` reads `web_search_call.action.sources`; returns `[]` if absent.

### `llm/ratelimit.py`

```python
import time
from collections import defaultdict, deque
from klatrebot_v2.settings import settings

_buckets: dict[int, deque[float]] = defaultdict(deque)
_WINDOW = 3600

def check_and_record(user_id: int) -> bool:
    now = time.monotonic()
    q = _buckets[user_id]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= settings.rate_limit_per_user_per_hour:
        return False
    q.append(now)
    return True
```

In-memory only. Resets on restart (acceptable). Per-user, not global.

## 8. Cogs (commands + listeners)

All cogs are `discord.ext.commands.Cog` subclasses. Loaded once in `bot.setup_hook`. No LLM/DB logic in cogs — they delegate to `llm/` or `db/` modules.

### `cogs/chat.py`

```python
class ChatCog(Cog):
    @command()
    async def gpt(self, ctx, *, question: str):
        if not ratelimit.check_and_record(ctx.author.id):
            await ctx.reply("Slap af, du har spurgt for meget.")
            return
        async with ctx.typing():
            result = await chat.reply(ctx.channel.id, question, ctx.author.id)
        text = result.text
        if result.sources:
            text += f"\n\n_Kilder: {', '.join(result.sources[:3])}_"
        await ctx.reply(text)
```

### `cogs/referat.py`

```python
class RefereatCog(Cog):
    @command()
    async def referat(self, ctx):
        async with ctx.typing():
            window_start = since_5am_local(now=datetime.now(tz=tz()))
            msgs = await messages.in_window(ctx.channel.id, window_start, datetime.utcnow())
            if not msgs:
                await ctx.reply("Ingen beskeder siden 05:00.")
                return
            summary = await chat.summarize(msgs)
        await ctx.reply(summary)
```

### `cogs/attendance.py`

```python
class AttendanceCog(Cog):
    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        session = await attendance_db.active_session(payload.channel_id)
        if not session or payload.user_id == bot.user.id:
            return
        status = "yes" if payload.emoji.name == "✅" else "no" if payload.emoji.name == "❌" else None
        if status is None:
            return
        await attendance_db.record_event(session.id, payload.user_id, status)

    @Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        session = await attendance_db.active_session(payload.channel_id)
        if not session or payload.user_id == bot.user.id:
            return
        # Removing a reaction = retracting that intent → record the opposite
        opposite = "no" if payload.emoji.name == "✅" else "yes" if payload.emoji.name == "❌" else None
        if opposite is None:
            return
        await attendance_db.record_event(session.id, payload.user_id, opposite)

    @command()
    async def klatring(self, ctx):
        session = await attendance_db.active_session(ctx.channel.id)
        if not session:
            await ctx.reply("Ingen klatretid lige nu.")
            return
        await ctx.reply(_render_tally(session))
```

User's **latest event** = current intent. Bailer status is computed via SQL on demand, never stored as a flag.

### `cogs/trivia.py`

```python
class TriviaCog(Cog):
    @command()
    async def ugenr(self, ctx):
        await ctx.reply(f"Vi er i uge {datetime.now().isocalendar()[1]}")

    @command()
    async def uptime(self, ctx):
        delta = datetime.utcnow() - bot.start_time
        await ctx.reply(f"Uppe i {delta}")

    @command()
    async def pelle(self, ctx):
        await ctx.reply(where_the_fuck_is_pelle())

    @command()
    async def glar(self, ctx):
        await ctx.reply("https://imgur.com/CnRFnel")
```

`where_the_fuck_is_pelle()` ports from V1's `pelleService.py` as a pure function (Discord-decoupled). Reviewed during port; dead helpers dropped.

### `cogs/auto_responses.py`

Data-driven trigger table; replaces V1's giant `on_message` if/regex blob.

```python
@dataclass(frozen=True)
class AutoResponse:
    name: str
    pattern: re.Pattern
    response: Callable[[discord.Message], Awaitable[str | None]]

RESPONSES: list[AutoResponse] = [
    AutoResponse("ugenr_match",        re.compile(r"\buge\s?(\d{1,2})\b", re.I), _handle_uge_match),
    AutoResponse("downus",             re.compile(r"!downus|fail", re.I),         lambda m: _static("https://cdn.discordapp.com/.../downus_on_wall.gif")),
    AutoResponse("klatrebot_question", re.compile(r"^klatrebot.*\?$", re.I),      lambda m: _static(_random_svar())),
    AutoResponse("det_kan_man_ik",     re.compile(r"det\skan\sman\s(\w+\s)?ik", re.I), lambda m: _static("https://cdn.discordapp.com/.../pellememetekst.gif")),
    AutoResponse("elmo",               re.compile(r"\b(elmo|elon)\b", re.I),      lambda m: _static("https://imgur.com/LNVCB8g")),
    AutoResponse("ekstrabladet",       re.compile(r"ekstrabladet\.dk|eb\.dk", re.I), lambda m: _static(_eb_roast())),
]

class AutoResponsesCog(Cog):
    @Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        await users.upsert(message.author)
        await messages.insert(message)
        for ar in RESPONSES:
            if ar.pattern.search(message.content):
                logger.info(f"auto_response.fired name={ar.name}")
                reply = await ar.response(message)
                if reply:
                    await message.channel.send(reply)
                break    # first match wins; no double-fires
        await self.bot.process_commands(message)   # don't block command dispatch
```

Adding a trigger = one entry in `RESPONSES`. First match wins (V1 fired all matches; that was a bug-shaped quirk).

## 9. Background tasks

`tasks.py` holds the klatretid scheduler:

```python
async def klatretid_scheduler():
    while True:
        next_post = _next_klatretid_post_time()  # next Mon/Thu 17:00 local → UTC
        await asyncio.sleep((next_post - datetime.utcnow()).total_seconds())
        await _post_klatretid_embed()
```

V1 polled every 60s. V2 sleeps until exact target. Single coroutine, no busy-loop.

`_post_klatretid_embed`:
1. Computes klatring start (today 20:00 local → UTC)
2. Posts embed in main channel; adds ✅ and ❌ reactions
3. Inserts `attendance_session` row (precomputed `klatring_start_utc`)

Reaction events from cog handlers attach to this session by channel + active-day match.

## 10. Error handling, logging, observability

### `logging_config.py`

```python
def setup():
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    for noisy in ("discord", "discord.http", "openai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

Called from `__main__.py` first-thing.

### Boundary error policy

| Boundary | Failure | Behavior |
|---|---|---|
| Missing required env key | `Settings()` raises ValidationError | Hard-fail at startup, exit 1 |
| Missing SOUL.MD | `FileNotFoundError` | Hard-fail at startup, exit 1 |
| sqlite locked / disk full | `aiosqlite` raises | Log error; surface generic failure to user; bot stays alive |
| OpenAI timeout / 5xx | `openai.APIError` / `asyncio.TimeoutError` | Log; reply "Det kan jeg desværre ikke svare på." No retry — bounded latency |
| Discord disconnect | discord.py auto-reconnects | Log; `on_ready` may fire again — DB init is idempotent |
| Command exception | Bubbles to `on_command_error` | Single global handler; generic Danish reply; full traceback in logs |
| `on_message` listener exception | Bubbles to `bot.on_error` | Logs + swallows; never blocks message processing |

### Global handlers in `bot.py`

```python
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply("Slap af.")
        return
    logger.exception(f"Command {ctx.command} failed", exc_info=error)
    await ctx.reply("Det kan jeg desværre ikke svare på.")

@bot.event
async def on_error(event_method: str, *args, **kwargs):
    logger.exception(f"Unhandled exception in {event_method}")
```

### Startup checks (`bot.setup_hook`)

```python
async def setup_hook(self):
    Path(settings.soul_path).read_text(encoding="utf-8")  # raises if missing
    self.db_conn = await connection.open(settings.db_path)
    await migrations.run(self.db_conn)
    await self.add_cog(ChatCog(self))
    await self.add_cog(RefereatCog(self))
    await self.add_cog(AttendanceCog(self))
    await self.add_cog(TriviaCog(self))
    await self.add_cog(AutoResponsesCog(self))
    self.start_time = datetime.utcnow()
    self.loop.create_task(klatretid_scheduler())
```

Hard-fails on missing config before bot announces ready.

### Observability surface

- stderr logs (timestamps + levels + module)
- **Readiness marker**: `bot.py` logs `"Bot startup completed"` at the very end of `setup_hook` (after cogs added, scheduler started, DB initialized). Smoke test greps for this exact string — keep stable.
- `auto_response.fired name=<X>` per match (audit dead triggers)
- `llm.reply duration=%.2fs` per `!gpt` / `!referat` (regression detection)
- `ratelimit.blocked user_id=%d` per blocked attempt

No metrics/tracing in Phase 1. OpenTelemetry deferred.

## 11. Testing

### Layout

```
klatrebot_v2/tests/
├── conftest.py                  # fixtures: in-memory db, fake settings, mock AsyncOpenAI
├── unit/
│   ├── test_settings.py
│   ├── test_messages_db.py
│   ├── test_attendance_db.py
│   ├── test_ratelimit.py
│   ├── test_chat.py
│   ├── test_referat.py
│   ├── test_auto_responses.py
│   └── test_klatretid_schedule.py
└── integration/
    └── test_smoke_boot.py       # subprocess boot, assert "ready" line in stdout (opt-in: pytest -m integration)
```

### Fixtures

```python
@pytest.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    await migrations.run(conn)
    yield conn
    await conn.close()

@pytest.fixture
def fake_settings(monkeypatch, tmp_path):
    soul = tmp_path / "SOUL.MD"
    soul.write_text("test soul")
    monkeypatch.setenv("DISCORD_KEY", "fake")
    monkeypatch.setenv("OPENAI_KEY", "fake")
    monkeypatch.setenv("SOUL_PATH", str(soul))
    monkeypatch.setenv("DISCORD_MAIN_CHANNEL_ID", "1")
    monkeypatch.setenv("DISCORD_SANDBOX_CHANNEL_ID", "2")
    monkeypatch.setenv("ADMIN_USER_ID", "3")
    return Settings()

@pytest.fixture
def mock_openai(monkeypatch):
    """Patch klatrebot_v2.llm.client.client with an AsyncMock whose
    .responses.create returns a canned Response object exposing .output_text."""
```

### Smoke boot (opt-in)

```python
@pytest.mark.integration
async def test_bot_boots_and_reports_ready():
    proc = subprocess.Popen(
        ["poetry", "run", "python3", "-m", "klatrebot_v2"],
        env={**os.environ, "DISCORD_KEY": REAL_STAGING_KEY, ...},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    try:
        deadline = time.monotonic() + 60
        for line in proc.stdout:
            if "Bot startup completed" in line:
                return
            if time.monotonic() > deadline:
                pytest.fail("Bot did not boot within 60s")
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
```

Caught the V1 init-order bug instantly; kept as a guardrail.

### Coverage policy

No threshold gate Phase 1. Aim for unit happy-path + at least one error path per module.

## 12. Implementation strategy — vertical slice

Build order. Bot is runnable after slice 1.

| Slice | Deliverable |
|---|---|
| 1 | Skeleton: `__main__`, `bot.py`, `settings.py`, `logging_config.py`, `db/connection.py + migrations.py + users.py + messages.py`, `cogs/chat.py` calling `llm/chat.py` with no recent-context. |
| 2 | `on_message` insert (`AutoResponsesCog` minus triggers — just logs to DB); enable recent-N context in `!gpt`. |
| 3 | Add `web_search` tool to `llm/chat.py`; surface sources in `cogs/chat.py`. |
| 4 | Klatretid scheduler in `tasks.py`; `cogs/attendance.py` with reaction handlers; `db/attendance.py` schema + queries; `!klatring` status. |
| 5 | `cogs/referat.py` + `llm/chat.summarize`; 5AM-5AM window math. |
| 6 | `cogs/trivia.py`; auto-response trigger table populated. |

Each slice = own PR. Order avoids dead branches.

## 13. Phase 2 prep — agent layer

Hooks in additively. No Phase 1 file changes required:

```
klatrebot_v2/
├── llm/
│   ├── chat.py          # Phase 1 — UNCHANGED
│   ├── agent.py         # NEW: multi-step planner, tool catalog
│   └── tools/           # NEW: Pydantic-typed tool defs
│       ├── web_search.py
│       ├── recent_chat.py
│       ├── attendance_history.py
│       └── ...
└── cogs/
    ├── chat.py          # !gpt — UNCHANGED
    └── agent.py         # NEW: !ask → llm.agent.run
```

Tool args = Pydantic models → JSON schema export for free. Hermes / OpenClaw consume that format directly. DB layer already provides the data backing tools need.

## 14. Out of scope (Phase 1)

- E2E test against real staging Discord (deferred; needs second bot account)
- CI workflow
- systemd unit + GH Actions deploy
- Backup script
- Feature: streaming `!gpt` replies (incompatible with Discord rate limits / UX)
- Feature: YAML-configured auto-responses
- Feature: `!klatring stats` historical bailer dashboard
- Phase 2 agent integration (separate spec when started)

## 15. Open questions / future decisions

- `_sanitize_mentions` truncated-ID safety net: keep with telemetry; drop once V2 logs show it never fires.
- When V1 is deleted: clean up repo root, move V2 contents up one level if subdir-as-project pattern feels redundant by then.
- Phase 2 is a separate brainstorm + spec when ready.
