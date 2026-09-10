"""Discord-decoupled LLM call pipeline."""
import json
import re
import asyncio
from typing import Callable

from pydantic import BaseModel

_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _resolve_mentions(text: str, names: dict[int, str]) -> str:
    def sub(m: re.Match) -> str:
        uid = int(m.group(1))
        name = names.get(uid)
        return f"@{name}" if name else m.group(0)
    return _MENTION_RE.sub(sub, text)

from klatrebot_v2.settings import get_settings
from klatrebot_v2.llm.client import get_client
from klatrebot_v2.llm.prompt import load_soul
from klatrebot_v2.db import messages as msg_db, user_aliases, users as users_db
from klatrebot_v2.memory import tools as memory_tools
from klatrebot_v2.memory.store import get_compiler_run_by_name


async def _names_for_ids(conn, ids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for uid in ids:
        u = await users_db.get(conn, uid)
        if u:
            out[uid] = u.display_name
    return out


class ChatReply(BaseModel):
    text: str
    sources: list[str] = []


def _extract_sources(resp) -> list[str]:
    """Return only URLs explicitly cited in the final answer text."""
    sources: list[str] = []
    seen: set[str] = set()
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) != "output_text":
                continue
            for annotation in getattr(content, "annotations", None) or []:
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", None)
                if url and url not in seen:
                    seen.add(url)
                    sources.append(url)
    return sources


def _extract_function_calls(resp) -> list[dict]:
    calls = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) != "function_call":
            continue
        raw_args = getattr(item, "arguments", "{}") or "{}"
        arguments = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
        calls.append(
            {
                "name": getattr(item, "name"),
                "call_id": getattr(item, "call_id"),
                "arguments": arguments,
            }
        )
    return calls


# Bot.setup_hook injects the live aiosqlite.Connection here. Tests monkeypatch.
_get_db_conn: Callable | None = None


def set_db_conn_provider(provider: Callable) -> None:
    global _get_db_conn
    _get_db_conn = provider


async def reply(
    *,
    question: str,
    asking_user_id: int,
    channel_id: int,
    mentions: dict[int, str] | None = None,
    invoking_message_id: int | None = None,
) -> ChatReply:
    s = get_settings()
    if s.memory_enabled and getattr(s, "memory_backend", "legacy") == "mempalace":
        from klatrebot_v2.memory.answering import AnswerSession
        session = AnswerSession()
        try:
            async with asyncio.timeout_at(session.deadline):
                return await _reply(question=question, asking_user_id=asking_user_id,
                    channel_id=channel_id, mentions=mentions, invoking_message_id=invoking_message_id,
                    session=session)
        except TimeoutError:
            from klatrebot_v2.memory.answering import TIMEOUT_LIMIT
            session.timed_out = True
            session.failures.append("DeadlineExceeded")
            for part in session.parts:
                if part.text is None:
                    part.record.coverage = "incomplete"
                    part.text = TIMEOUT_LIMIT
            return ChatReply(text=session.render(), sources=session.urls)
        except Exception as exc:
            session.failures.append(type(exc).__name__)
            if not session.parts:
                from klatrebot_v2.memory.answering import PartResult
                session.parts.append(PartResult("ambiguous"))
            return ChatReply(text=session.render(), sources=session.urls)
        finally:
            session.log()
    return await _reply(question=question, asking_user_id=asking_user_id, channel_id=channel_id,
                        mentions=mentions, invoking_message_id=invoking_message_id)


async def _reply(*, question, asking_user_id, channel_id, mentions=None,
                 invoking_message_id=None, session=None) -> ChatReply:
    if _get_db_conn is None:
        raise RuntimeError("chat.reply called before db conn provider was set")
    conn = _get_db_conn()
    s = get_settings()
    soul = load_soul()

    recent = await msg_db.recent_with_authors(conn, channel_id=channel_id, limit=s.gpt_recent_message_count)

    history_ids: set[int] = set()
    for m in recent:
        history_ids.update(int(x) for x in _MENTION_RE.findall(m.content))
    question_ids = {int(x) for x in _MENTION_RE.findall(question)}
    names: dict[int, str] = dict(mentions or {})
    missing = (history_ids | question_ids) - names.keys()
    if missing:
        names.update(await _names_for_ids(conn, missing))

    context_messages = [m for m in recent if m.discord_message_id != invoking_message_id] if session is not None else recent
    context_block = "\n".join(
        f"[{m.timestamp_utc.isoformat()} msg:{m.discord_message_id} author:{m.user_id} "
        f"{'bot' if m.is_bot else 'human'}] {m.user_display_name}: {_resolve_mentions(m.content, names)}" for m in context_messages
    )
    resolved_question = _resolve_mentions(question, names)
    mention_tokens = (
        "\n".join(f"@{n} -> <@{uid}>" for uid, n in names.items())
        if names
        else "(none)"
    )
    memory_run_id = await _active_memory_run_id(conn, s) if s.memory_enabled else None
    alias_map = await user_aliases.format_alias_prompt_map(conn) if memory_run_id is not None else "(memory disabled)"

    full_input = (
        f"CONTEXT (recent chat):\n{context_block}\n\n"
        f"Asking user Discord ID: {asking_user_id}\n\n"
        f"CHANNEL_ID: {channel_id}\n\n"
        f"MENTION_TOKENS (use exact token to ping a user):\n{mention_tokens}\n\n"
        f"KNOWN_USER_ALIASES:\n{alias_map}\n"
        "Use people_names in memory tool calls for these aliases.\n\n"
        f"QUESTION: {resolved_question}"
    )
    client = get_client()
    if session is not None:
        from klatrebot_v2.memory.answering import answer
        await answer(session, conn=conn, settings=s, client=client, run_id=memory_run_id,
            full_input=full_input, question=question, alias_map=alias_map, channel_id=channel_id,
            recent=recent, invoking_message_id=invoking_message_id, soul=soul)
        return ChatReply(text=session.render(), sources=session.urls)
    tools = [{"type": "web_search"}]
    if memory_run_id is not None:
        tools.extend(memory_tools.MEMORY_TOOL_DEFS)

    resp = await client.responses.create(
        model=s.model,
        instructions=soul,
        input=full_input,
        tools=tools,
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
    )
    for _ in range(8):
        if memory_run_id is None:
            break
        tool_outputs = []
        for call in _extract_function_calls(resp):
            arguments = dict(call["arguments"])
            if call["name"] == "recall_community_memory" and arguments.get("channel_id") is None:
                arguments["channel_id"] = channel_id
            output = await memory_tools.execute_memory_tool(
                conn,
                run_id=memory_run_id,
                name=call["name"],
                arguments=arguments,
                settings=s,
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": output,
                }
            )
        if not tool_outputs:
            break
        resp = await client.responses.create(
            model=s.model,
            instructions=soul,
            input=tool_outputs,
            tools=tools,
            previous_response_id=getattr(resp, "id"),
            reasoning={"effort": "low"},
            text={"verbosity": "medium"},
        )
    return ChatReply(text=resp.output_text or "", sources=_extract_sources(resp))


async def _active_memory_run_id(conn, settings) -> int | None:
    fallback = 0 if getattr(settings, "memory_backend", "legacy") == "mempalace" else None
    if settings.memory_active_run_name:
        found = await get_compiler_run_by_name(conn, settings.memory_active_run_name)
        return int(found["id"]) if found else fallback
    return settings.memory_active_run_id if settings.memory_active_run_id is not None else fallback


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
        reasoning={"effort": "low"},
        text={"verbosity": "medium"},
    )
    return resp.output_text or ""
