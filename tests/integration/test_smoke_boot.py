"""Credentialed login/setup smoke check without opening a Discord gateway."""
import os
import subprocess
import sys
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
        "MEMORY_ENABLED": "false",
        "MEMORY_BACKEND": "legacy",
        "MEMORY_SYNC_ENABLED": "false",
        "MEMORY_ROLLING_ENABLED": "false",
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", """
import asyncio, logging, os
from klatrebot_v2.bot import KlatreBot
logging.basicConfig(level=logging.INFO)
async def main():
    async with KlatreBot() as bot:
        await bot.login(os.environ['DISCORD_KEY'])
asyncio.run(main())
"""],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).parents[2]),
    )
    try:
        output, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0, output
        assert "Bot startup completed" in output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)
