# KlatreBot V2

Danish-language Discord bot for a climbing group. Core: discord.py + OpenAI for chat / summaries / attendance helpers. `!gpt` routes via a small classifier to either the fast OpenAI path or a Hermes Agent on the LAN for history-aware queries — see `infra/` for the agent integration. V1 archived under `klatrebot_v1/`.

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

## Backup

Backups use `sqlite3 .backup`, `zip`, and `rclone`. Configure the `gdrive` rclone remote for the service user before relying on cron. Daily cron suggestion (atomic sqlite snapshot, no service stop):

```
0 3 * * * bash /home/Admin/KlatreBot/KlatreBot_Public/backup/backup.sh /home/Admin/klatrebot-data/klatrebot_v2.db gdrive
```
