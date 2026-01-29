#!/usr/bin/env bash
set -euo pipefail

# Minimal rclone-based backup script for headless systems
# Usage: backup.sh /path/to/repo gdrive
#   args: REPO_DIR RCLONE_REMOTE

REPO_DIR=${1:-.}
RCLONE_REMOTE=${2:-gdrive}

# Adjust these as needed
TMPDIR=${TMPDIR:-/tmp}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ZIPNAME="KlatreBot_Backup_${TIMESTAMP}.zip"
ZIPPATH="${TMPDIR}/${ZIPNAME}"
LOG_FILE="${REPO_DIR}/backup/backup.log"

# Optional service commands (comment out if not used)
SHUTDOWN_CMD="sudo systemctl stop klatrebot.service" 
RESTART_CMD="sudo systemctl start klatrebot.service"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

cleanup() {
    exit_code=$?
    echo "Restarting KlatreBot (exit code: ${exit_code})" || true
    eval ${RESTART_CMD} || true
    exit ${exit_code}
}

trap cleanup EXIT

echo "Stopping KlatreBot (if running)" || true
eval ${SHUTDOWN_CMD} || true

echo "Creating archive ${ZIPPATH}"
cd "${REPO_DIR}"
zip -r -q "${ZIPPATH}" klatrebot.db chroma_db/

echo "Uploading ${ZIPPATH} to ${RCLONE_REMOTE}:KlatreBot_Backups/${TIMESTAMP}/"
rclone copy "${ZIPPATH}" "${RCLONE_REMOTE}:KlatreBot_Backups/${TIMESTAMP}/" -P

echo "Cleaning up local backups older than 2 days"
find "${TMPDIR}" -maxdepth 1 -type f -name "KlatreBot_Backup_*.zip" -mtime +2 -print -delete

echo "Restarting KlatreBot" || true
eval ${RESTART_CMD} || true

echo "Done"


