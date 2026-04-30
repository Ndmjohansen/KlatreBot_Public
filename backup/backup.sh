#!/usr/bin/env bash
set -euo pipefail

# rclone-based backup for KlatreBot V2 sqlite db.
# Uses `sqlite3 .backup` for an atomic snapshot — safe with WAL, no service stop required.
#
# Usage: backup.sh /path/to/klatrebot_v2.db gdrive
#   args: DB_PATH RCLONE_REMOTE
#
# Example cron (every day at 03:00):
#   0 3 * * * /home/Admin/KlatreBot/KlatreBot_Public/backup/backup.sh \
#     /home/Admin/klatrebot-data/klatrebot_v2.db gdrive

DB_PATH=${1:-/home/Admin/klatrebot-data/klatrebot_v2.db}
RCLONE_REMOTE=${2:-gdrive}

TMPDIR=${TMPDIR:-/tmp}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT="${TMPDIR}/klatrebot_v2_${TIMESTAMP}.db"
ZIPNAME="KlatreBot_v2_Backup_${TIMESTAMP}.zip"
ZIPPATH="${TMPDIR}/${ZIPNAME}"
LOG_FILE="$(dirname "$(readlink -f "$0")")/backup.log"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

cleanup() {
    rm -f "${SNAPSHOT}" "${ZIPPATH}"
}
trap cleanup EXIT

echo "[$(date -Is)] Starting backup of ${DB_PATH}"

if [ ! -f "${DB_PATH}" ]; then
    echo "ERROR: ${DB_PATH} does not exist"
    exit 1
fi

echo "Snapshotting via sqlite3 .backup → ${SNAPSHOT}"
sqlite3 "${DB_PATH}" ".backup '${SNAPSHOT}'"

echo "Compressing snapshot → ${ZIPPATH}"
( cd "${TMPDIR}" && zip -q "${ZIPNAME}" "$(basename "${SNAPSHOT}")" )

echo "Uploading to ${RCLONE_REMOTE}:KlatreBot_v2_Backups/${TIMESTAMP}/"
rclone copy "${ZIPPATH}" "${RCLONE_REMOTE}:KlatreBot_v2_Backups/${TIMESTAMP}/" -P

echo "Cleaning up local snapshots older than 2 days"
find "${TMPDIR}" -maxdepth 1 -type f -name "KlatreBot_v2_Backup_*.zip" -mtime +2 -print -delete

echo "[$(date -Is)] Backup complete"
