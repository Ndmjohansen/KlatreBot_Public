"""stdlib logging setup. Called once from __main__.py."""
import logging
import sys

from klatrebot_v2.settings import get_settings


def setup() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    for noisy in ("discord", "discord.http", "openai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
