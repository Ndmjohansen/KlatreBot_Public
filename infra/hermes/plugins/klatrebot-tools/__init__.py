"""klatrebot-tools — HTTP read-only client for the Pi's API."""
from . import schemas, tools


def register(ctx):
    ctx.register_tool(
        name="klatrebot_query",
        toolset="klatrebot",
        schema=schemas.KLATREBOT_QUERY,
        handler=tools.klatrebot_query,
    )
    ctx.register_tool(
        name="klatrebot_schema",
        toolset="klatrebot",
        schema=schemas.KLATREBOT_SCHEMA,
        handler=tools.klatrebot_schema,
    )
    ctx.register_tool(
        name="klatrebot_search_semantic",
        toolset="klatrebot",
        schema=schemas.KLATREBOT_SEARCH_SEMANTIC,
        handler=tools.klatrebot_search_semantic,
    )
    ctx.register_tool(
        name="klatrebot_health",
        toolset="klatrebot",
        schema=schemas.KLATREBOT_HEALTH,
        handler=tools.klatrebot_health,
    )
