# KlatreBot V2

Lean rewrite. Spec: [`docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md`](docs/superpowers/specs/2026-04-30-klatrebot-v2-design.md)

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

Clone repo to `/home/Admin/KlatreBot/KlatreBot_Public`, then:

```
sudo bash install.sh
sudo -e /etc/klatrebot/klatrebot.env   # fill in real values
sudo systemctl start klatrebot
```

`install.sh` is idempotent — safe to re-run after pulling new commits. CI auto-deploys on push to `main`.

## Backup

Daily cron suggestion (atomic sqlite snapshot, no service stop):

```
0 3 * * * /home/Admin/KlatreBot/KlatreBot_Public/backup/backup.sh /home/Admin/klatrebot-data/klatrebot_v2.db gdrive
```
