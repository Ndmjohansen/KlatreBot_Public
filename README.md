# KlatreBot V2

V1 archived under `klatrebot_v1/` — kept for reference, not deployed.

## Run locally

```
cp .env.example .env   # fill in keys
poetry install
poetry run python3 -m klatrebot_v2
```

## Test

```
poetry run pytest                  # unit tests
poetry run pytest -m integration   # smoke boot (requires real DISCORD_KEY)
```

## Deploy to Pi (one-shot)

Clone repo to `/home/Admin/KlatreBot/KlatreBot_Public`, install Poetry for the `Admin` user, then:

```
sudo bash install.sh
sudo -e /etc/klatrebot/klatrebot.env   # fill in real values
sudo systemctl start klatrebot
```

`install.sh` is idempotent and safe to re-run after pulling new commits. It installs dependencies, creates `/home/Admin/klatrebot-data`, writes a placeholder env file if missing, installs the systemd unit, and registers backup cron.

`klatrebot.service` is a template in the repo. Do not edit the `@SERVICE_USER@`, `@PROJECT_DIR@`, `@DATA_DIR@`, or `@POETRY_DIR@` placeholders manually; `install.sh` and CI replace them when installing `/etc/systemd/system/klatrebot.service`.

CI auto-deploys on push to `main` only. The deploy job SSHes to the Pi, checks out `main`, runs `poetry install --sync`, rewrites `/etc/klatrebot/klatrebot.env` from GitHub secrets, installs the templated unit, and restarts `klatrebot`.

## Durable memory

Memory is kept in the same SQLite DB as raw message logs. First backfill a named production memory index manually:

```
poetry run python -m klatrebot_v2.memory compile \
  --db /home/Admin/klatrebot-data/klatrebot_v2.db \
  --from 2025-10-01T00:00:00+00:00 \
  --to 2026-05-16T00:00:00+00:00 \
  --name production \
  --concurrency 2
```

For CI-managed production deploys, set these as GitHub repository variables because the deploy workflow rewrites `/etc/klatrebot/klatrebot.env` on every push to `main`:

```
MEMORY_ENABLED=true
MEMORY_ACTIVE_RUN_NAME=production
MEMORY_ROLLING_ENABLED=true
MEMORY_ROLLING_RUN_NAME=production
```

Set `USER_ALIASES_CONFIG_PATH` as a GitHub repository secret. It should point at the host-local JSON alias file, which must stay outside git.

For direct/manual installs, the same values can be edited in `/etc/klatrebot/klatrebot.env`, but a later CI deploy will replace that file from GitHub secrets and variables.

Rolling updates run through `klatrebot-memory.timer`, which starts `klatrebot-memory.service` every 2 hours. The service reads the same `/etc/klatrebot/klatrebot.env`, compiles only an incremental window, leaves the newest 45 minutes untouched so ongoing conversations are picked up next run, and keeps the bot on the last successful memory if compilation fails.

Useful commands:

```
sudo systemctl status klatrebot-memory.timer
sudo systemctl start klatrebot-memory.service
sudo journalctl -u klatrebot-memory.service -f
```

## Backup

Backups use `sqlite3 .backup`, `zip`, and `rclone`. Configure the `gdrive` rclone remote for the service user before relying on cron. Daily cron suggestion (atomic sqlite snapshot, no service stop):

```
0 3 * * * bash /home/Admin/KlatreBot/KlatreBot_Public/backup/backup.sh /home/Admin/klatrebot-data/klatrebot_v2.db gdrive
```
