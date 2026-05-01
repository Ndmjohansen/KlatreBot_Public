"""klatrebot-tools — registers read-only KlatreBot DB tools with Hermes."""
from . import schemas, tools


def register(ctx):
    ctx.register_tool(
        name="get_recent_messages",
        toolset="klatrebot",
        schema=schemas.GET_RECENT_MESSAGES,
        handler=tools.get_recent_messages,
    )
    ctx.register_tool(
        name="search_messages",
        toolset="klatrebot",
        schema=schemas.SEARCH_MESSAGES,
        handler=tools.search_messages,
    )
    ctx.register_tool(
        name="search_messages_semantic",
        toolset="klatrebot",
        schema=schemas.SEARCH_MESSAGES_SEMANTIC,
        handler=tools.search_messages_semantic,
    )
    ctx.register_tool(
        name="messages_in_window",
        toolset="klatrebot",
        schema=schemas.MESSAGES_IN_WINDOW,
        handler=tools.messages_in_window,
    )
    ctx.register_tool(
        name="get_attendance",
        toolset="klatrebot",
        schema=schemas.GET_ATTENDANCE,
        handler=tools.get_attendance,
    )
    ctx.register_tool(
        name="get_user",
        toolset="klatrebot",
        schema=schemas.GET_USER,
        handler=tools.get_user,
    )
