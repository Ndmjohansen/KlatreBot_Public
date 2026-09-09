"""Stdlib-only snapshot client, usable by cron without loading credentials."""
import argparse
import json
import socket
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--socket", default="/run/klatrebot-retrieval/worker.sock")
parser.add_argument("--db", required=True)
args = parser.parse_args()
requested_db = Path(args.db).resolve(strict=True)
with socket.socket(socket.AF_UNIX) as client:
    client.settimeout(60)
    client.connect(args.socket)
    client.sendall((json.dumps({"operation": "snapshot", "db_path": str(requested_db)}) + "\n").encode())
    with client.makefile("rb") as stream:
        result = json.loads(stream.readline(65536))
    if "error" in result:
        raise RuntimeError(result["error"])
    if not result.get("source_db_path") or not requested_db.samefile(result["source_db_path"]):
        raise RuntimeError("Worker did not confirm the requested database; refusing backup")
    print(result["snapshot_path"])
