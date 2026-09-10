import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.memory.adjudication import classify


async def test_relevance_judgment_does_not_receive_ranking_mechanics():
    response = SimpleNamespace(output_text=json.dumps({"judgments": [
        {"source_handle": "msg:1", "relevance": "relevant", "quote": "Linux"}]}))
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=response)))
    scope = dict(order="latest", cursor="page", limit=10, run_id=2, query="Linux", people=[1], channel_id=4)
    await classify(client, "test", "Hvilket system bruger personen?", scope,
                   [dict(source_handle="msg:1", content="Jeg bruger Linux")], [])
    sent = json.loads(client.responses.create.await_args.kwargs["input"])
    assert sent["filters"] == {"people": [1], "channel_id": 4}


async def test_judgment_input_is_independent_of_candidate_order():
    candidates = [dict(source_handle=f"msg:{i}", content="Kilde") for i in (2, 1)]
    response = SimpleNamespace(output_text=json.dumps({"judgments": [dict(
        source_handle=c["source_handle"], relevance="uncertain", quote="") for c in candidates]}))
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    context = [dict(discord_message_id=i, content="Kontekst") for i in (2, 1)]
    await classify(client, "test", "Hvorfor?", {}, candidates, context)
    await classify(client, "test", "Hvorfor?", {}, candidates[::-1], context[::-1])
    assert create.await_args_list[0].kwargs["input"] == create.await_args_list[1].kwargs["input"]


@pytest.mark.parametrize("order", [None, "relevance"])
@pytest.mark.parametrize("kind", ["raw_message", "fact", "segment_summary", "rollup_week"])
async def test_legacy_keeps_answering_path(monkeypatch, db, order, kind):
    from klatrebot_v2.llm import chat
    settings = SimpleNamespace(memory_enabled=True, memory_backend="legacy",
        memory_active_run_name=None, memory_active_run_id=2, model="test", gpt_recent_message_count=25)
    arguments = dict(query="Hvordan fordelte vi arbejdsopgaverne?", order=order)
    initial = SimpleNamespace(id="initial", output=[SimpleNamespace(type="function_call",
        name="recall_community_memory", call_id="call", arguments=json.dumps(arguments))])
    final = SimpleNamespace(output=[], output_text="Opgaverne stod på tavlen.")
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[initial, final])))
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)
    monkeypatch.setattr(chat, "get_settings", lambda: settings)
    monkeypatch.setattr(chat, "load_soul", lambda: "soul")
    monkeypatch.setattr(chat, "get_client", lambda: client)
    payload = json.dumps(dict(status="ok", answerable=True, results=[dict(kind=kind, text="Tavlen")]))
    execute = AsyncMock(return_value=payload)
    monkeypatch.setattr(chat.memory_tools, "execute_memory_tool", execute)
    selector = AsyncMock(side_effect=AssertionError("Relevance must not invoke latest selection"))
    from klatrebot_v2.memory import answering
    monkeypatch.setattr(answering, "select_latest", selector)
    reply = await chat.reply(question=arguments["query"], asking_user_id=1, channel_id=4)
    assert reply.text == final.output_text
    assert client.responses.create.await_count == 2
    assert client.responses.create.await_args.kwargs["input"][0]["output"] == payload
    selector.assert_not_awaited()


async def test_relevance_ranks_support_above_newer_keyword_overlap(db):
    from datetime import datetime, timezone
    from klatrebot_v2.db import users, messages
    from klatrebot_v2.memory.search import search
    await users.upsert(db, discord_user_id=1, display_name="Person")
    for mid, day, content in [(1, 1, "Serveren bruger port 8081"), (2, 9, "Jeg købte en server")]:
        await messages.insert(db, discord_message_id=mid, channel_id=4, user_id=1,
                              timestamp_utc=datetime(2026, 9, day, tzinfo=timezone.utc), content=content)
    result = await search(db, dict(run_id=0, query="serveren server port 8081", people=[1],
                                  channel_id=4, order="relevance"))
    assert result.results[0].source_handle == "msg:1"
    assert "chronological_page" not in result.coverage


@pytest.mark.parametrize("case", [c for c in json.loads(
    Path("tests/fixtures/evidence_generalization.json").read_text(encoding="utf-8")) if "selected" in c],
    ids=lambda c: c["id"])
async def test_non_excuse_latest_policy_with_real_source_expansion(monkeypatch, db, case):
    from datetime import datetime, timezone
    from klatrebot_v2.db import users, messages
    from klatrebot_v2.memory import latest, tools
    from klatrebot_v2.memory.adjudication import Verdict
    await users.upsert(db, discord_user_id=1, display_name="Person")
    for m in case["messages"]:
        await messages.insert(db, discord_message_id=m["id"], channel_id=4, user_id=1,
            timestamp_utc=datetime(2026, 9, m["day"], tzinfo=timezone.utc), content=m["text"])
    # The opt-in evaluator separately checks these judgments against the real
    # model. Here isolate the policy, using real retrieval and source expansion.
    supplied_context = {}
    async def judge(client, model, question, scope, candidates, context):
        supplied_context.update({f"msg:{m['discord_message_id']}": m for m in context})
        return {c["source_handle"]: Verdict(source_handle=c["source_handle"],
            relevance=case["expected"][str(c["discord_message_id"])],
            quote=c["content"] if case["expected"][str(c["discord_message_id"])] == "relevant" else "")
            for c in candidates}
    monkeypatch.setattr(latest, "classify", judge)
    settings = SimpleNamespace(model="test", memory_backend="mempalace", memory_socket_path="missing")
    args = dict(query=case["question"], people=[1], channel_id=4, order="latest",
                date_end="2026-09-10T00:00:00+00:00")
    initial = await tools.execute_memory_tool(db, run_id=0, settings=settings,
        name="recall_community_memory", arguments=args)
    selection = await latest.select_latest(db, run_id=0, arguments=args, initial=initial,
        settings=settings, client=None, question=case["question"], structured=True)
    assert selection.context == {h: m for h, m in supplied_context.items()
                                 if h != selection.selected["source_handle"]}
    answer = selection.render()
    chosen = next(m for m in case["messages"] if m["id"] == case["selected"])
    assert chosen["text"] in answer
    assert "Det seneste relevante" in answer
