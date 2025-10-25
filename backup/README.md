# KlatreBot rclone backup

Minimal headless backup using rclone. Script: `backup/backup.sh`.

Usage
- Configure `rclone` on the host with a remote (example name: `gdrive`).
- Make `backup/backup.sh` executable: `chmod +x backup/backup.sh`.
- Run manually:
```
backup/backup.sh /path/to/repo gdrive
```

What it does
- Stops `klatrebot.service` (if present)
- Zips `klatrebot.db` and `chroma_db/chroma.sqlite3` into `/tmp` with timestamp
- Uses `rclone copy` to upload to `gdrive:KlatreBot_Backups/<TIMESTAMP>/`
- Restarts `klatrebot.service` (if present)

Notes
- Edit `SHUTDOWN_CMD` and `RESTART_CMD` inside the script if you run KlatreBot differently.
- The script assumes `zip` and `rclone` are installed.
- Use cron or systemd timer to schedule daily runs.


