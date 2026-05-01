"""Discord-decoupled LLM call pipeline."""
import re
from typing import Callable

from pydantic import BaseModel

_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _sanitize_mentions(text: str) -> str:
    """Insert zero-width space inside Discord mentions to prevent unintended pings."""
    return _MENTION_RE.sub(lambda m: f"<@​{m.group(1)}>", text)

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.db import messages as msg_db


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


def _extract_sources(resp) -> list[str]:
    """Pull URLs from `web_search_call.action.sources`. Returns [] if not present."""
    out = getattr(resp, "output", None) or []
    for item in out:
        if getattr(item, "type", None) == "web_search_call":
            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None) if action else None
            if not sources:
                return []
            return [getattr(s, "url", "") for s in sources if getattr(s, "url", None)]
    return []


# Bot.setup_hook injects the live aiosqlite.Connection here. Tests monkeypatch.
_get_db_conn: Callable | None = None


def set_db_conn_provider(provider: Callable) -> None:
    global _get_db_conn
    _get_db_conn = provider


async def reply(*, question: str, asking_user_id: int, channel_id: int) -> ChatReply:
    if _get_db_conn is None:
        raise RuntimeError("chat.reply called before db conn provider was set")
    conn = _get_db_conn()
    s = get_settings()
    soul = load_soul()

    recent = await msg_db.recent_with_authors(conn, channel_id=channel_id, limit=s.gpt_recent_message_count)
    context_block = "\n".join(f"{m.user_display_name}: {m.content}" for m in recent)

    full_input = (
        f"{soul}\n\n"
        f"CONTEXT (recent chat):\n{context_block}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"QUESTION: {question}"
    )
    client = get_client()
    resp = await client.responses.create(
        model=s.model,
        input=full_input,
        tools=[{"type": "web_search"}],
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
        include=["web_search_call.action.sources"],
    )
    return ChatReply(text=_sanitize_mentions(resp.output_text or ""), sources=_extract_sources(resp))


_SUMMARY_INSTRUCTIONS = """
**Instructions for the AI (Output must be in Danish):**

1.  **Mandatory Opening Line (in Danish):**
    Always begin your response with the exact Danish phrase: "Her er hvad boomerene har yappet om i stedet for at arbejde i dag" or a very similar, contextually appropriate humorous Danish variation.

2.  **Primary Task:** Summarize the day's chat. Humorous tone, jokes that reference the actual content.

3.  **User Identification:** Each line shows `Name (id): content`. Refer to people by name in the summary; NEVER print numeric IDs in the output.

4.  **Length:** No 60-word cap; can be longer to cover the day. Stay in Danish.
"""


async def summarize(msgs) -> str:
    """Summarize a list of MessageWithAuthor. One Responses API call, no tools."""
    soul = load_soul()
    body = "\n".join(f"{m.user_display_name} ({m.user_id}): {m.content}" for m in msgs)
    full_input = f"{soul}\n\n{_SUMMARY_INSTRUCTIONS}\n\nBESKEDER:\n{body}"
    client = get_client()
    resp = await client.responses.create(
        model=get_settings().model,
        input=full_input,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return _sanitize_mentions(resp.output_text or "")
