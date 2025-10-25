#!/usr/bin/env bash
set -euo pipefail

# Usage: register_cron.sh install|remove [user] [hour minute]
# Example: register_cron.sh install pi 3 15   # installs cron at 03:15 daily for user pi

ACTION=${1:-install}
USER=${2:-$(whoami)}
HOUR=${3:-3}
MIN=${4:-15}

CRON_CMD="/usr/bin/env bash $(pwd)/backup/backup.sh $(pwd) gdrive >/dev/null 2>&1"
CRON_SPEC="${MIN} ${HOUR} * * * ${CRON_CMD}"

tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

if [ "${ACTION}" = "install" ]; then
  echo "Installing cron job for user ${USER}: ${CRON_SPEC}"
  crontab -l -u "${USER}" 2>/dev/null | grep -v -F "${CRON_CMD}" > "$tmpfile" || true
  echo "${CRON_SPEC}" >> "$tmpfile"
  crontab -u "${USER}" "$tmpfile"
  echo "Installed."
  exit 0
fi

if [ "${ACTION}" = "remove" ]; then
  echo "Removing cron job for user ${USER}"
  crontab -l -u "${USER}" 2>/dev/null | grep -v -F "${CRON_CMD}" > "$tmpfile" || true
  crontab -u "${USER}" "$tmpfile"
  echo "Removed."
  exit 0
fi

echo "Usage: $0 install|remove [user] [hour] [minute]"
exit 2


