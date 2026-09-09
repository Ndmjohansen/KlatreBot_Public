#!/usr/bin/env bash
set -euo pipefail

# rclone-based backup for KlatreBot V2 sqlite db.
# Uses `sqlite3 .backup` for an atomic snapshot — safe with WAL, no service stop required.
#
# Usage: backup.sh /path/to/klatrebot_v2.db gdrive
#   args: DB_PATH RCLONE_REMOTE
#
# Example cron (every day at 03:00):
#   0 3 * * * bash /home/Admin/KlatreBot/KlatreBot_Public/backup/backup.sh \
#     /home/Admin/klatrebot-data/klatrebot_v2.db gdrive

DB_PATH=${1:-/home/Admin/klatrebot-data/klatrebot_v2.db}
RCLONE_REMOTE=${2:-gdrive}

TMPDIR=${TMPDIR:-/tmp}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT="${TMPDIR}/klatrebot_v2_${TIMESTAMP}.db"
WORKER_SNAPSHOT=""
ZIPNAME="KlatreBot_v2_Backup_${TIMESTAMP}.zip"
ZIPPATH="${TMPDIR}/${ZIPNAME}"
LOG_FILE="$(dirname "$(readlink -f "$0")")/backup.log"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

cleanup() {
    rm -f "${SNAPSHOT}" "${ZIPPATH}"
    if [ -n "$WORKER_SNAPSHOT" ]; then
        # Only delete the four known files created by the worker, never recursively.
        rm -f "$WORKER_SNAPSHOT/source.db" "$WORKER_SNAPSHOT/sqlite_exact.sqlite3" \
            "$WORKER_SNAPSHOT/index.json" "$WORKER_SNAPSHOT/manifest.json"
        rmdir "$WORKER_SNAPSHOT"
    fi
}
trap cleanup EXIT

echo "[$(date -Is)] Starting backup of ${DB_PATH}"

SOCKET_PATH=${MEMORY_SOCKET_PATH:-/run/klatrebot-retrieval/worker.sock}
INDEX_PATH=${MEMORY_INDEX_PATH:-$(dirname "$DB_PATH")/mempalace}
if [ -S "$SOCKET_PATH" ]; then
    WORKER_SNAPSHOT=$(python3 "$(dirname "$(readlink -f "$0")")/snapshot.py" --socket "$SOCKET_PATH")
    ( cd "$WORKER_SNAPSHOT" && zip -q "$ZIPPATH" source.db sqlite_exact.sqlite3 index.json manifest.json )
elif [ -d "$INDEX_PATH" ]; then
    echo "Memory index exists but worker is unavailable; refusing an incomplete backup" >&2
    exit 1
else
    sqlite3 "${DB_PATH}" ".backup '${SNAPSHOT}'"
    ( cd "${TMPDIR}" && zip -q "${ZIPNAME}" "$(basename "${SNAPSHOT}")" )
fi

echo "Uploading to ${RCLONE_REMOTE}:KlatreBot_v2_Backups/${TIMESTAMP}/"
rclone copy "${ZIPPATH}" "${RCLONE_REMOTE}:KlatreBot_v2_Backups/${TIMESTAMP}/" -P

echo "Cleaning up local snapshots older than 2 days"
find "${TMPDIR}" -maxdepth 1 -type f -name "KlatreBot_v2_Backup_*.zip" -mtime +2 -print -delete

echo "[$(date -Is)] Backup complete"
