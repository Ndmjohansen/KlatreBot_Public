"""Discord-decoupled LLM call pipeline."""
from typing import Callable

from pydantic import BaseModel

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.db import messages as msg_db


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


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
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return ChatReply(text=resp.output_text or "", sources=[])
