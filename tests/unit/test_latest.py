import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.memory import latest
from klatrebot_v2.memory.adjudication import Verdict


def message(mid, day, text="Jeg bliver hjemme", author=1):
    return dict(discord_message_id=mid, user_id=author, user_display_name="Person",
                channel_id=4, timestamp_utc=f"2026-09-{day:02}T12:00:00+00:00",
                content=text, is_bot=False)


def hit(m):
    return dict(source_handle=f"msg:{m['discord_message_id']}", kind="raw_message",
                created_at_source=m["timestamp_utc"])


SCOPE = dict(people=[1], order="latest", channel_id=4, query="afbud",
             date_start=None, date_end=None, person_role="author", limit=10)


def payload(ranked, page, cursor=None):
    return json.dumps(dict(status="ok", search_scope=SCOPE, results=[hit(m) for m in ranked],
                           coverage=dict(chronological_page=[hit(m) for m in page]),
                           continuation_cursor=cursor))


async def run(monkeypatch, initial, sources, decisions, pages=(), **kwargs):
    pending = iter(pages)

    async def tool(conn, *, name, arguments, **kw):
        if name == "get_memory_sources":
            return json.dumps(sources)
        assert arguments["people"] == [1]
        assert arguments["channel_id"] == 4
        assert arguments["query"] == "afbud"
        return next(pending)

    async def judge(client, model, question, scope, candidates, context):
        return {c["source_handle"]: Verdict(source_handle=c["source_handle"],
                  relevance=decisions[c["discord_message_id"]],
                  quote=c["content"] if decisions[c["discord_message_id"]] == "relevant" else "")
                for c in candidates}

    execute = AsyncMock(side_effect=tool)
    monkeypatch.setattr(latest.tools, "execute_memory_tool", execute)
    monkeypatch.setattr(latest, "classify", judge)
    answer = await latest.select_latest(None, run_id=2, arguments=SCOPE,
                                        initial=initial, settings=SimpleNamespace(model="test"),
                                        client=None, question="Seneste afbud?", **kwargs)
    return answer, execute


async def test_newer_indirect_beats_explicit_older_and_neighbor(monkeypatch):
    newer = message(3, 3, "Jeg skal putte, undskyldningsmaxer")
    older = message(2, 1, "Jeg kommer ikke, er syg")
    neighbor = message(4, 4, "Jeg er syg", author=2)
    answer, _ = await run(monkeypatch, payload([older, newer], [newer, older]),
                          [newer, older, neighbor], {3: "relevant", 2: "relevant"})
    assert newer["content"] in answer
    assert older["content"] not in answer
    assert "03-09-2026" in answer


async def test_ranked_hit_cannot_skip_newer_chronological_pages(monkeypatch):
    old, newest, newer = message(1, 1), message(9, 9, "Hej"), message(5, 5, "Må springe over")
    answer, execute = await run(monkeypatch, payload([old], [newest], "cursor"),
        [old, newest, newer], {1: "relevant", 9: "irrelevant", 5: "relevant"},
        pages=[payload([], [newer, old])])
    assert newer["content"] in answer
    assert any(c.kwargs["name"] == "recall_community_memory" for c in execute.await_args_list)


async def test_uncertain_newer_gets_context_and_blocks_latest_claim(monkeypatch):
    old, newer = message(1, 1), message(3, 3, "Måske")
    answer, execute = await run(monkeypatch, payload([old], [newer, old]),
        [old, newer], {1: "relevant", 3: "uncertain"})
    assert "kan ikke kalde det det seneste" in answer
    assert any(c.kwargs["arguments"].get("context_radius") == 5 for c in execute.await_args_list)


async def test_page_budget_does_not_claim_latest_or_fetch_unused_page(monkeypatch):
    old, newest = message(1, 1), message(9, 9, "Hej")
    answer, execute = await run(monkeypatch, payload([old], [newest], "next"),
        [old, newest], {1: "relevant", 9: "irrelevant"}, max_pages=1)
    assert "kan ikke kalde det det seneste" in answer
    assert execute.await_count == 1


async def test_no_evidence_is_not_denial(monkeypatch):
    answer, _ = await run(monkeypatch, payload([], []), [], {})
    assert "Det betyder ikke" in answer


@pytest.mark.parametrize("change", [{"user_id": 2}, {"channel_id": 99}, {"is_bot": True}])
async def test_source_outside_scope_fails_closed(monkeypatch, change):
    wrong = dict(message(1, 1), **change)
    answer, _ = await run(monkeypatch, payload([wrong], [wrong]), [wrong], {1: "relevant"})
    assert "kunne ikke fastslå" in answer


@pytest.mark.parametrize("judgments", [[], [dict(source_handle="msg:other", relevance="relevant", quote="x")],
    [dict(source_handle="msg:1", relevance="relevant", quote="fabricated")],
    [dict(source_handle="msg:1", relevance="relevant", quote="")]])
async def test_classifier_rejects_incomplete_or_fabricated_evidence(judgments):
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(output_text=json.dumps(dict(judgments=judgments))))))
    with pytest.raises(ValueError):
        await latest.classify(client, "test", "q", SCOPE,
                              [dict(message(1, 1), source_handle="msg:1")], [])


async def test_classifier_failure_returns_uncertainty(monkeypatch):
    m = message(1, 1)
    monkeypatch.setattr(latest.tools, "execute_memory_tool", AsyncMock(return_value=json.dumps([m])))
    monkeypatch.setattr(latest, "classify", AsyncMock(side_effect=TimeoutError))
    answer = await latest.select_latest(None, run_id=2, arguments=SCOPE, initial=payload([m], [m]),
        settings=SimpleNamespace(model="test"), client=None, question="q")
    assert "kunne ikke fastslå" in answer


async def test_cancellation_propagates(monkeypatch):
    m = message(1, 1)
    monkeypatch.setattr(latest.tools, "execute_memory_tool", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await latest.select_latest(None, run_id=2, arguments=SCOPE, initial=payload([m], [m]),
            settings=SimpleNamespace(model="test"), client=None, question="q")


async def test_chat_returns_limitation_when_latest_draft_invalid(monkeypatch, db):
    from klatrebot_v2.llm import chat
    from klatrebot_v2.memory import answering, routing
    settings = SimpleNamespace(memory_enabled=True, memory_backend="mempalace",
        memory_active_run_name=None, memory_active_run_id=2, model="test", gpt_recent_message_count=25)
    route = routing.fallback("Seneste afbud?", "(none)")
    route.kind = route.parts[0].kind = "history"
    route.parts[0].people_names = ["Person"]
    route.parts[0].latest_authored = True
    response = SimpleNamespace(output_text=route.model_dump_json())
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=response)))
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)
    monkeypatch.setattr(chat, "get_settings", lambda: settings)
    monkeypatch.setattr(chat, "load_soul", lambda: "soul")
    monkeypatch.setattr(chat, "get_client", lambda: client)
    execute = AsyncMock(return_value=payload([], []))
    monkeypatch.setattr(chat.memory_tools, "execute_memory_tool", execute)
    selected = dict(message(1, 1), source_handle="msg:1", quote="Jeg bliver hjemme")
    selection = latest.LatestSelection(selected=selected, uncertain=False)
    selector = AsyncMock(return_value=selection)
    monkeypatch.setattr(answering, "select_latest", selector)
    result = await chat.reply(question="Seneste afbud?", asking_user_id=1, channel_id=4)
    assert result.text == answering.INTERPRETATION_LIMIT
    assert selected["quote"] not in result.text
    assert execute.await_args.kwargs["arguments"]["cursor"] is None
    assert client.responses.create.await_count == 3  # route, invalid draft, one repair


async def test_uncertain_can_be_resolved_with_expanded_context(monkeypatch):
    m = message(1, 1)
    monkeypatch.setattr(latest.tools, "execute_memory_tool", AsyncMock(return_value=json.dumps([m])))
    monkeypatch.setattr(latest, "classify", AsyncMock(side_effect=[
        {"msg:1": Verdict(source_handle="msg:1", relevance="uncertain", quote="")},
        {"msg:1": Verdict(source_handle="msg:1", relevance="relevant", quote=m["content"])}]))
    answer = await latest.select_latest(None, run_id=2, arguments=SCOPE, initial=payload([m], [m]),
        settings=SimpleNamespace(model="test"), client=None, question="q")
    assert "Det seneste relevante" in answer
    assert m["content"] in answer


async def test_deadline_returns_uncertainty(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)
    m = message(1, 1)
    monkeypatch.setattr(latest.tools, "execute_memory_tool", slow)
    answer = await latest.select_latest(None, run_id=2, arguments=SCOPE, initial=payload([m], [m]),
        settings=SimpleNamespace(model="test"), client=None, question="q", timeout=0.01)
    assert "kunne ikke fastslå" in answer


async def test_original_timezone_controls_newest(monkeypatch):
    # A lexically later local timestamp is actually an older instant.
    old = dict(message(1, 3, "Ældre afbud"), timestamp_utc="2026-09-03T14:00:00+02:00")
    new = dict(message(2, 3, "Nyere afbud"), timestamp_utc="2026-09-03T12:30:00+00:00")
    answer, _ = await run(monkeypatch, payload([old, new], [old, new]),
                           [old, new], {1: "relevant", 2: "relevant"})
    assert new["content"] in answer
    assert old["content"] not in answer
