import asyncio
import io
import json
from pathlib import Path
import runpy
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from klatrebot_v2.memory.worker import SnapshotDatabaseMismatch, Worker
from klatrebot_v2.memory import worker as worker_module


@pytest.fixture
def snapshot_worker(tmp_path):
    source = tmp_path / "source.db"
    index = tmp_path / "index"
    index.mkdir()
    for path in (source, index / "sqlite_exact.sqlite3", tmp_path / "other.db"):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE marker(value TEXT)")
            conn.execute("INSERT INTO marker VALUES (?)", (path.name,))
    for name in ("index.json", "manifest.json"):
        (index / name).write_text("{}")
    worker = Worker.__new__(Worker)
    worker.settings = SimpleNamespace(db_path=str(source))
    worker.palace = SimpleNamespace(path=index)
    worker.lock = asyncio.Lock()
    return worker


def test_different_database_rejected_before_snapshot_creation(snapshot_worker, tmp_path):
    with pytest.raises(SnapshotDatabaseMismatch):
        snapshot_worker.snapshot(str(tmp_path / "other.db"))
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("requested", [None, "source.db", ""])
def test_snapshot_requires_explicit_absolute_identity(snapshot_worker, tmp_path, requested):
    with pytest.raises(SnapshotDatabaseMismatch):
        snapshot_worker.snapshot(requested)
    assert not (tmp_path / "snapshots").exists()


def test_matching_database_and_hardlink_alias_back_up_expected_contents(snapshot_worker, tmp_path):
    alias = tmp_path / "alias.db"
    alias.hardlink_to(tmp_path / "source.db")
    for requested in (tmp_path / "source.db", alias):
        result = snapshot_worker.snapshot(str(requested))
        assert Path(result["source_db_path"]).samefile(requested)
        with sqlite3.connect(Path(result["snapshot_path"]) / "source.db") as conn:
            assert conn.execute("SELECT value FROM marker").fetchall() == [("source.db",)]


async def test_protocol_mismatch_returns_error_not_snapshot(snapshot_worker, tmp_path):
    reader = AsyncMock()
    reader.readline.return_value = json.dumps({"operation": "snapshot", "db_path": str(tmp_path / "other.db")}).encode()
    writer = MagicMock(drain=AsyncMock(), wait_closed=AsyncMock())
    await snapshot_worker.handle(reader, writer)
    assert json.loads(writer.write.call_args.args[0]) == {"error": "SnapshotDatabaseMismatch"}
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("response_kind", ["matching", "different", "unconfirmed", "error"])
def test_cron_client_transmits_and_checks_identity(tmp_path, monkeypatch, capsys, response_kind):
    source = tmp_path / "requested.db"
    source.touch()
    other = tmp_path / "other.db"
    other.touch()
    response = {"snapshot_path": "snapshot-result"}
    if response_kind in {"matching", "different"}:
        response["source_db_path"] = str(source if response_kind == "matching" else other)
    elif response_kind == "error":
        response = {"error": "SnapshotDatabaseMismatch"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.makefile.return_value = io.BytesIO(json.dumps(response).encode() + b"\n")
    monkeypatch.setattr("socket.socket", lambda *_args: client)
    monkeypatch.setattr("socket.AF_UNIX", 1, raising=False)
    monkeypatch.setattr("sys.argv", ["snapshot.py", "--db", str(source)])
    script = Path(__file__).resolve().parents[2] / "backup" / "snapshot.py"
    if response_kind == "matching":
        runpy.run_path(str(script), run_name="__main__")
        assert capsys.readouterr().out.strip() == "snapshot-result"
    else:
        with pytest.raises(RuntimeError):
            runpy.run_path(str(script), run_name="__main__")
        assert capsys.readouterr().out == ""
    assert json.loads(client.sendall.call_args.args[0])["db_path"] == str(source.resolve())


async def test_worker_cli_rejects_unconfirmed_snapshot(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.db"
    source.touch()
    monkeypatch.setattr("sys.argv", ["worker", "snapshot"])
    monkeypatch.setattr(worker_module, "get_settings", lambda: SimpleNamespace(
        db_path=str(source), memory_socket_path="socket"))
    monkeypatch.setattr(worker_module, "request", AsyncMock(return_value={"snapshot_path": "wrong"}))
    with pytest.raises(SnapshotDatabaseMismatch):
        await worker_module.main()
    assert capsys.readouterr().out == ""
