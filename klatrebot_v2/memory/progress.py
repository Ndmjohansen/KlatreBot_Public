"""Read a running initial backfill's checkpoints without opening its index.

For resumed or incremental syncs, use the worker's memory_progress journal lines.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--total", required=True, type=int)
    parser.add_argument("--started-at", help="Initial backfill start, ISO timestamp")
    parser.add_argument("--unit", default="klatrebot-backfill")
    args = parser.parse_args()
    if args.total <= 0:
        parser.error("--total must be positive")
    manifest = args.index / "manifest.json"
    state = json.loads(manifest.read_text()) if manifest.exists() else {}
    completed = len(state.get("hashes", {}))
    remaining = max(0, args.total - completed)
    unit = subprocess.run(["systemctl", "show", args.unit, "--property=SubState", "--value"],
                          capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    print(f"Backfill: {completed:,} / {args.total:,} chunks ({100 * completed / args.total:.1f}%)")
    print(f"Remaining: {remaining:,} | Service: {unit}")
    if args.started_at and completed and remaining and unit == "running":
        started = datetime.fromisoformat(args.started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        eta_minutes = max(0, elapsed) / completed * remaining / 60
        print(f"Rough ETA: {eta_minutes:.0f} min (chunk sizes vary)")
    print(f"Index reconciled through: {state.get('watermark') or 'pending completion'}")


if __name__ == "__main__":
    main()
