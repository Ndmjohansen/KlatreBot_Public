"""Stdlib-only snapshot client, usable by cron without loading credentials."""
import argparse
import json
import socket

parser = argparse.ArgumentParser()
parser.add_argument("--socket", default="/run/klatrebot-retrieval/worker.sock")
args = parser.parse_args()
with socket.socket(socket.AF_UNIX) as client:
    client.settimeout(60)
    client.connect(args.socket)
    client.sendall(b'{"operation":"snapshot"}\n')
    with client.makefile("rb") as stream:
        result = json.loads(stream.readline(65536))
    if "error" in result:
        raise RuntimeError(result["error"])
    print(result["snapshot_path"])
