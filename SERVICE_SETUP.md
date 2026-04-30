# KlatreBot — Service Setup (Raspberry Pi)

One-time installation. Run on the Pi as a sudo-capable user (e.g. `Admin`).

## Prerequisites

- Repo cloned to `/home/Admin/KlatreBot/KlatreBot_Public`
- Poetry installed for the target user (`command -v poetry` succeeds)
- Python ≥3.11

## 1. Install dependencies

```bash
cd /home/Admin/KlatreBot/KlatreBot_Public
poetry install --sync --no-interaction
```

## 2. Create data dir

DB lives outside the repo so `git pull` / branch ops never touch it.

```bash
sudo install -d -o Admin -g Admin -m 755 /home/Admin/klatrebot-data
```

## 3. Create env file

```bash
sudo install -d -m 755 /etc/klatrebot
sudo install -m 600 -o root -g root /dev/stdin /etc/klatrebot/klatrebot.env <<'EOF'
DISCORD_KEY=<discord bot token>
OPENAI_KEY=<openai api key>
DISCORD_MAIN_CHANNEL_ID=<channel id>
DISCORD_SANDBOX_CHANNEL_ID=<channel id>
ADMIN_USER_ID=<your discord user id>
DB_PATH=/home/Admin/klatrebot-data/klatrebot_v2.db
EOF
```

Optional overrides (defaults shown — only add lines you want to change):

```
MODEL=gpt-5.4
SOUL_PATH=./SOUL.MD
TIMEZONE=Europe/Copenhagen
KLATRETID_DAYS=[0,3]
KLATRETID_POST_HOUR=17
KLATRETID_START_HOUR=20
GPT_RECENT_MESSAGE_COUNT=25
RATE_LIMIT_PER_USER_PER_HOUR=30
LOG_LEVEL=INFO
```

## 4. Patch + install systemd unit

`klatrebot.service` contains a `@POETRY_DIR@` sentinel that needs replacing with the directory of the Poetry binary on PATH (so systemd can find `poetry`).

```bash
cd /home/Admin/KlatreBot/KlatreBot_Public

POETRY_BIN="$(command -v poetry)"
POETRY_DIR="$(dirname "$POETRY_BIN")"

# Patch the sentinel and install
sed "s|@POETRY_DIR@|${POETRY_DIR}|g" klatrebot.service \
  | sudo install -m 644 -o root -g root /dev/stdin /etc/systemd/system/klatrebot.service

sudo systemctl daemon-reload
sudo systemctl enable klatrebot
sudo systemctl start klatrebot
```

## 5. Verify

```bash
sudo systemctl status klatrebot
sudo journalctl -u klatrebot -f
```

Look for `Bot startup completed` log line. If startup fails, check journal for tracebacks (env file misconfigured, Poetry not found, etc.).

## Updating after `git pull`

If only Python source changed:
```bash
sudo systemctl restart klatrebot
```

If `pyproject.toml` / `poetry.lock` changed:
```bash
cd /home/Admin/KlatreBot/KlatreBot_Public
poetry install --sync --no-interaction
sudo systemctl restart klatrebot
```

If `klatrebot.service` changed: re-run step 4.

## Service management

| Command | Effect |
|---|---|
| `sudo systemctl start klatrebot` | Start |
| `sudo systemctl stop klatrebot` | Stop |
| `sudo systemctl restart klatrebot` | Restart |
| `sudo systemctl status klatrebot` | Show status |
| `sudo journalctl -u klatrebot -f` | Tail logs |
