"""End-to-end: boot the bot subprocess and assert readiness marker."""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.integration
def test_bot_boots_and_reports_ready(tmp_path):
    discord_key = os.getenv("DISCORD_KEY")
    openai_key = os.getenv("OPENAI_KEY")
    if not discord_key or not openai_key:
        pytest.skip("DISCORD_KEY + OPENAI_KEY required for integration test")

    # Use a temp DB so we don't pollute dev
    db_path = tmp_path / "smoke.db"

    # SOUL.MD must exist somewhere — copy real one or write a stub
    repo_soul = Path(__file__).parents[2] / "SOUL.MD"
    soul_path = tmp_path / "SOUL.MD"
    if repo_soul.exists():
        soul_path.write_text(repo_soul.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        soul_path.write_text("Test soul.")

    env = {
        **os.environ,
        "DISCORD_KEY": discord_key,
        "OPENAI_KEY": openai_key,
        "DISCORD_MAIN_CHANNEL_ID": "0",
        "DISCORD_SANDBOX_CHANNEL_ID": "0",
        "ADMIN_USER_ID": "0",
        "SOUL_PATH": str(soul_path),
        "DB_PATH": str(db_path),
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "klatrebot_v2"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).parents[2]),
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    pytest.fail(f"Bot exited prematurely with code {proc.returncode}")
                continue
            print(line, end="")
            if "Bot startup completed" in line:
                return
            if time.monotonic() > deadline:
                pytest.fail("Bot did not boot within 60s")
    finally:
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
