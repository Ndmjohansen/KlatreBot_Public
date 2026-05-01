# KlatreBot

## Development

```bash
poetry install --sync
poetry run python3 -m klatrebot_v2
```

## Test

```bash
poetry run pytest -v
poetry run pytest -m integration
```

## Install

Clone the repo to the Pi, then run:

```bash
sudo bash install.sh
sudo -e /etc/klatrebot/klatrebot.env
sudo systemctl start klatrebot
```
