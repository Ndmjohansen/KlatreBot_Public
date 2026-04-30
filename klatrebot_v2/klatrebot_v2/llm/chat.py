"""Discord-decoupled LLM call pipeline. Used by !gpt cog."""
from pydantic import BaseModel

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


async def reply(*, question: str, asking_user_id: int) -> ChatReply:
    """Single-pass LLM reply. Slice 2 adds recent-chat context; slice 3 adds web_search."""
    soul = load_soul()
    full_input = (
        f"{soul}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"QUESTION: {question}"
    )
    client = get_client()
    resp = await client.responses.create(
        model=get_settings().model,
        input=full_input,
        reasoning={"effort": "medium"},
        text={"verbosity": "medium"},
    )
    return ChatReply(text=resp.output_text or "", sources=[])
