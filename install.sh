#!/usr/bin/env bash
# KlatreBot V2 — one-shot Pi install script.
# Run as root or with sudo. Idempotent: safe to re-run.

set -euo pipefail

SERVICE_NAME="klatrebot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/klatrebot"
ENV_FILE="${ENV_DIR}/klatrebot.env"

if [ "$EUID" -ne 0 ]; then
    echo "Run as root or with sudo" >&2
    exit 1
fi

if [ -n "${SUDO_USER:-}" ]; then
    TARGET_USER="$SUDO_USER"
else
    TARGET_USER="$(whoami)"
fi

PROJECT_DIR="/home/${TARGET_USER}/KlatreBot/KlatreBot_Public"
DATA_DIR="/home/${TARGET_USER}/klatrebot-data"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "Project dir $PROJECT_DIR missing — clone the repo there first" >&2
    exit 1
fi

POETRY_BIN="$(sudo -u "$TARGET_USER" bash -lc 'command -v poetry' || true)"
if [ -z "$POETRY_BIN" ]; then
    echo "poetry not found on PATH for $TARGET_USER — install: curl -sSL https://install.python-poetry.org | python3 -" >&2
    exit 1
fi
POETRY_DIR="$(dirname "$POETRY_BIN")"
echo "Using poetry at: $POETRY_BIN"

echo "[1/5] Installing dependencies"
sudo -u "$TARGET_USER" bash -lc \
    "cd '$PROJECT_DIR' && '$POETRY_BIN' install --sync --no-interaction"

echo "[2/5] Creating data dir $DATA_DIR"
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DATA_DIR"

echo "[3/5] Ensuring env file $ENV_FILE"
install -d -m 755 "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    install -m 600 -o root -g root /dev/stdin "$ENV_FILE" <<EOF
DISCORD_KEY=replace_me
OPENAI_KEY=replace_me
DISCORD_MAIN_CHANNEL_ID=0
DISCORD_SANDBOX_CHANNEL_ID=0
ADMIN_USER_ID=0
DB_PATH=${DATA_DIR}/klatrebot_v2.db
EOF
    echo "  Wrote placeholder $ENV_FILE — edit with real values, then re-run: systemctl restart $SERVICE_NAME"
else
    echo "  $ENV_FILE already exists — leaving untouched"
fi

echo "[4/5] Installing systemd unit"
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT
sed "s|@POETRY_DIR@|${POETRY_DIR}|g" "$PROJECT_DIR/klatrebot.service" > "$TMP_UNIT"
install -m 644 -o root -g root "$TMP_UNIT" "$SERVICE_FILE"

echo "[5/5] Reloading + enabling systemd unit"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "Install complete."
echo ""
echo "Next:"
echo "  1. Edit secrets:    sudo -e $ENV_FILE"
echo "  2. Start:           sudo systemctl start $SERVICE_NAME"
echo "  3. Tail logs:       sudo journalctl -u $SERVICE_NAME -f"
