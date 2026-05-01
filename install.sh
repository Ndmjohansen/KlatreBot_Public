#!/usr/bin/env bash
# KlatreBot V2 — one-shot Pi install script.
# Run as root or with sudo. Idempotent: safe to re-run.

set -euo pipefail

SERVICE_NAME="klatrebot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/klatrebot"
ENV_FILE="${ENV_DIR}/klatrebot.env"
CRON_FILE="/etc/cron.d/klatrebot-backup"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"

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

POETRY_BIN="$(sudo -H -u "$TARGET_USER" bash -lc 'export PATH="$HOME/.local/bin:$PATH"; command -v poetry' || true)"
if [ -z "$POETRY_BIN" ]; then
    echo "Poetry not found on PATH for $TARGET_USER; installing with the official installer"
    sudo -H -u "$TARGET_USER" bash -lc \
        'set -e; command -v curl >/dev/null 2>&1 || { echo "curl is required to install Poetry" >&2; exit 1; }; curl -sSL https://install.python-poetry.org | python3 -'
    POETRY_BIN="$(sudo -H -u "$TARGET_USER" bash -lc 'export PATH="$HOME/.local/bin:$PATH"; command -v poetry' || true)"
fi
if [ -z "$POETRY_BIN" ]; then
    echo "Poetry install completed, but poetry is still not on PATH for $TARGET_USER" >&2
    exit 1
fi
POETRY_DIR="$(dirname "$POETRY_BIN")"
echo "Using poetry at: $POETRY_BIN"

echo "[1/6] Installing dependencies"
sudo -H -u "$TARGET_USER" bash -lc \
    "cd '$PROJECT_DIR' && '$POETRY_BIN' install --sync --no-interaction"

echo "[2/6] Creating data dir $DATA_DIR"
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DATA_DIR"

echo "[3/6] Ensuring env file $ENV_FILE"
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

echo "[4/6] Installing systemd unit"
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT
sed \
    -e "s|@SERVICE_USER@|${TARGET_USER}|g" \
    -e "s|@PROJECT_DIR@|${PROJECT_DIR}|g" \
    -e "s|@DATA_DIR@|${DATA_DIR}|g" \
    -e "s|@POETRY_DIR@|${POETRY_DIR}|g" \
    "$PROJECT_DIR/klatrebot.service" > "$TMP_UNIT"
install -m 644 -o root -g root "$TMP_UNIT" "$SERVICE_FILE"

echo "[5/6] Reloading + enabling systemd unit"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "[6/6] Installing backup cron"
for cmd in sqlite3 zip rclone; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "  WARNING: $cmd not installed — backups will fail until it is installed"
    fi
done
echo "  Ensure rclone remote '${RCLONE_REMOTE}' is configured for $TARGET_USER"
install -m 644 -o root -g root /dev/stdin "$CRON_FILE" <<EOF
# KlatreBot V2 daily DB backup — managed by install.sh
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 3 * * * $TARGET_USER bash ${PROJECT_DIR}/backup/backup.sh ${DATA_DIR}/klatrebot_v2.db ${RCLONE_REMOTE}
EOF

echo ""
echo "Install complete."
echo ""
echo "Next:"
echo "  1. Edit secrets:    sudo -e $ENV_FILE"
echo "  2. Start:           sudo systemctl start $SERVICE_NAME"
echo "  3. Tail logs:       sudo journalctl -u $SERVICE_NAME -f"
echo "  4. Test backup:     ${PROJECT_DIR}/backup/backup.sh"
