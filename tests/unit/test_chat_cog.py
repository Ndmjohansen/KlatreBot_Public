from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from klatrebot_v2.cogs import chat as chat_cog
from klatrebot_v2.llm.chat import ChatReply


async def test_gpt_reply_suppresses_link_embeds(monkeypatch):
    monkeypatch.setattr(chat_cog.users_db, 'upsert', AsyncMock())
    monkeypatch.setattr(chat_cog.msg_db, 'insert', AsyncMock())
    monkeypatch.setattr(chat_cog.ratelimit, "check_and_record", lambda _user_id: True)
    monkeypatch.setattr(
        chat_cog.chat,
        "reply",
        AsyncMock(
            return_value=ChatReply(
                text="Et svar med en kilde.",
                sources=["https://example.com/source"],
            )
        ),
    )

    @asynccontextmanager
    async def typing():
        yield

    ctx = SimpleNamespace(
        author=SimpleNamespace(id=42, display_name='Anna', bot=False),
        channel=SimpleNamespace(id=7),
        message=SimpleNamespace(mentions=[], id=100, content='!gpt Hvad sker der?', created_at=__import__('datetime').datetime.now()),
        typing=typing,
        reply=AsyncMock(),
    )
    cog = chat_cog.ChatCog(MagicMock())

    await chat_cog.ChatCog.gpt.callback(cog, ctx, question="Hvad sker der?")

    ctx.reply.assert_awaited_once()
    assert chat_cog.chat.reply.await_args.kwargs["invoking_message_id"] == 100
    assert ctx.reply.await_args.kwargs["suppress_embeds"] is True
    assert "https://example.com/source" in ctx.reply.await_args.args[0]
