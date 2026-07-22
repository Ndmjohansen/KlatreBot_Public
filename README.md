# KlatreBot V2

Discord bot for a climbing group. V1 archived under `klatrebot_v1/` — kept for reference, not deployed.

## Run locally

```
cp .env.example .env   # fill in keys
poetry install
poetry run python3 -m klatrebot_v2
```

## Test

```
poetry run pytest                  # unit
poetry run pytest -m integration   # smoke boot (needs real DISCORD_KEY)
```

## Deploy

Clone the repo to `/home/${TARGET_USER}/KlatreBot/KlatreBot_Public` (the `PROJECT_DIR` in `install.sh`), install Poetry for the service user, then:

```
sudo bash install.sh
sudo -e /etc/klatrebot/klatrebot.env   # fill in real values
sudo systemctl start klatrebot
```

`install.sh` is idempotent. It installs deps, creates the data dir, writes a placeholder env file if missing, installs the bot and memory systemd units, enables the memory timer, and registers the backup cron.

`klatrebot.service` and `klatrebot-memory.service` are templates — the `@SERVICE_USER@`, `@PROJECT_DIR@`, `@DATA_DIR@`, `@POETRY_DIR@` placeholders are substituted by `install.sh` and CI, so don't edit them by hand.

CI auto-deploys on push to `main`: SSH to the host, pull, `poetry install --sync`, rewrite `/etc/klatrebot/klatrebot.env` from GitHub secrets, reinstall the templated units, restart `klatrebot`, and enable the memory timer.

## Durable memory

Memory lives in the same SQLite DB as raw message logs. Backfill a named production run once, manually:

```
poetry run python -m klatrebot_v2.memory compile \
  --db /home/${TARGET_USER}/klatrebot-data/klatrebot_v2.db \
  --from 2025-10-01T00:00:00+00:00 \
  --to 2026-05-16T00:00:00+00:00 \
  --name production \
  --concurrency 2
```

Then enable rolling memory by setting these as GitHub repository variables (CI rewrites `/etc/klatrebot/klatrebot.env` on every deploy, so editing the env file directly only sticks until the next push):

```
MEMORY_ENABLED=true
MEMORY_ACTIVE_RUN_NAME=production
MEMORY_ROLLING_ENABLED=true
MEMORY_ROLLING_RUN_NAME=production
MEMORY_COMPILER_MODEL=gpt-5.6-luna
MEMORY_SEGMENT_GAP_MINUTES=30
MEMORY_SEGMENT_MIN_HUMAN_MESSAGES=8
MEMORY_SEGMENT_MIN_TOTAL_CHARS=300
MEMORY_SEGMENT_MIN_PARTICIPANTS=2
MEMORY_SEGMENT_MAX_MESSAGES=100
MEMORY_SEGMENT_MAX_DURATION_MINUTES=120
```

Set `USER_ALIASES_CONFIG_PATH` as a GitHub repository secret pointing at a host-local JSON alias file (kept outside git).

`klatrebot-memory.timer` fires `klatrebot-memory.service` every 2 hours. The service compiles only an incremental window, leaves the newest 45 minutes untouched so ongoing conversations get picked up next run, and keeps the bot on the last successful memory if compilation fails.

```
sudo systemctl status klatrebot-memory.timer
sudo systemctl start klatrebot-memory.service
sudo journalctl -u klatrebot-memory.service -f
```

## Backup

Backups use `sqlite3 .backup`, `zip`, and `rclone`. Configure the `gdrive` rclone remote for the service user before relying on cron. `install.sh` registers a daily cron entry equivalent to:

```
0 3 * * * bash /home/${TARGET_USER}/KlatreBot/KlatreBot_Public/backup/backup.sh /home/${TARGET_USER}/klatrebot-data/klatrebot_v2.db gdrive
```
