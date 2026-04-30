# KlatreBot V2 — Service Setup (Raspberry Pi)

One-time installation. Run on the Pi as a sudo-capable user (e.g. `Admin`).

## Prerequisites

- Repo cloned to `/home/Admin/KlatreBot/KlatreBot_Public`
- Poetry installed for the target user (`command -v poetry` succeeds)
- Python ≥3.11

## 1. Install dependencies

```bash
cd /home/Admin/KlatreBot/KlatreBot_Public/klatrebot_v2
poetry install --sync --no-interaction
```

## 2. Create env file

```bash
sudo install -d -m 755 /etc/klatrebot
sudo install -m 600 -o root -g root /dev/stdin /etc/klatrebot/klatrebot-v2.env <<'EOF'
DISCORD_KEY=<same value as V1 BOT_KEY>
OPENAI_KEY=<same value as V1 OPENAI_API>
DISCORD_MAIN_CHANNEL_ID=<channel id>
DISCORD_SANDBOX_CHANNEL_ID=<channel id>
ADMIN_USER_ID=<your discord user id>
EOF
```

Optional overrides (defaults shown — only add lines you want to change):

```
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

## 3. Patch + install systemd unit

`klatrebot-v2.service` contains a `@POETRY_DIR@` sentinel that needs replacing with the directory of the Poetry binary on PATH (so systemd can find `poetry`).

```bash
cd /home/Admin/KlatreBot/KlatreBot_Public/klatrebot_v2

POETRY_BIN="$(command -v poetry)"
POETRY_DIR="$(dirname "$POETRY_BIN")"

# Patch the sentinel and install
sed "s|@POETRY_DIR@|${POETRY_DIR}|g" klatrebot-v2.service \
  | sudo install -m 644 -o root -g root /dev/stdin /etc/systemd/system/klatrebot-v2.service

sudo systemctl daemon-reload
sudo systemctl enable klatrebot-v2
sudo systemctl start klatrebot-v2
```

## 4. Verify

```bash
sudo systemctl status klatrebot-v2
sudo journalctl -u klatrebot-v2 -f
```

Look for `Bot startup completed` log line. If startup fails, check journal for tracebacks (env file misconfigured, Poetry not found, etc.).

## Updating after `git pull`

If only Python source changed:
```bash
sudo systemctl restart klatrebot-v2
```

If `pyproject.toml` / `poetry.lock` changed:
```bash
cd /home/Admin/KlatreBot/KlatreBot_Public/klatrebot_v2
poetry install --sync --no-interaction
sudo systemctl restart klatrebot-v2
```

If `klatrebot-v2.service` changed: re-run step 3.

## Service management

| Command | Effect |
|---|---|
| `sudo systemctl start klatrebot-v2` | Start |
| `sudo systemctl stop klatrebot-v2` | Stop |
| `sudo systemctl restart klatrebot-v2` | Restart |
| `sudo systemctl status klatrebot-v2` | Show status |
| `sudo journalctl -u klatrebot-v2 -f` | Tail logs |

## Cutover (when swapping V1 → V2)

```bash
sudo systemctl stop klatrebot
sudo systemctl disable klatrebot
sudo systemctl start klatrebot-v2  # if not already running
```

The CI deploy workflow `main.yml` will need its V1 install/restart block replaced with the V2 equivalent at cutover time.
