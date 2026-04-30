"""Entrypoint: `poetry run python3 -m klatrebot_v2`."""
import asyncio
import logging

from klatrebot_v2 import logging_config
from klatrebot_v2.bot import KlatreBot, on_command_error
from klatrebot_v2.settings import get_settings


def main() -> None:
    logging_config.setup()
    logger = logging.getLogger(__name__)

    s = get_settings()
    bot = KlatreBot()
    bot.on_command_error = on_command_error

    @bot.event
    async def on_error(event_method: str, *args, **kwargs):
        logger.exception("Unhandled exception in %s", event_method)

    logger.info("Starting KlatreBot V2...")
    asyncio.run(bot.start(s.discord_key))


if __name__ == "__main__":
    main()
