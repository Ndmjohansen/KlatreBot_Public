import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.llm import chat
from klatrebot_v2.memory import adjudication as ev, answering, routing


def source(mid=1, author=1, text="Jeg tager toget", **changes):
    return dict(discord_message_id=mid, channel_id=4, user_id=author,
                user_display_name=f"Person {author}", timestamp_utc="2026-09-01T12:00:00+00:00",
                content=text, is_bot=False, **changes)


def route(kind="history", **changes):
    result = routing.fallback("Hvad sagde vi om transport?", "(none)")
    result.kind = result.parts[0].kind = kind
    for key, value in changes.items():
        setattr(result.parts[0], key, value)
    return result


def citation(handle="msg:1", quote="Jeg tager toget", role="support"):
    return dict(source_handle=handle, quote=quote, role=role)


def assessment(status="supported", citations=None):
    return dict(status=status, evidence=[citation()] if citations is None else citations)


def draft(text="Person 1 skrev, at vedkommende tager toget.", citations=None):
    return dict(claims=[dict(text=text, citations=[citation()] if citations is None else citations)])


def verified(valid=True):
    return dict(source_reading="Kildens indhold vurderet selvstændigt.", valid=valid, supported_claims=[valid], feedback="" if valid else "Bevar afsenderen og gengiv kun det underbyggede.")


def model_input(raw):
    data = json.loads(raw)
    if "messages" in data:
        rows = {m["source_handle"]: dict(m, **data["authors"][m["author"]]) for m in data["messages"]}
        for role in ("sources", "context"):
            data[role] = [rows[h] for h in data[role]]
    return data


def setup(monkeypatch, db, responses, *, rows=None, status="ok", kind="raw_message"):
    settings = SimpleNamespace(memory_enabled=True, memory_backend="mempalace",
        memory_active_run_name=None, memory_active_run_id=2, model="test", gpt_recent_message_count=25)
    converted = [SimpleNamespace(output_text=(r.model_dump_json() if hasattr(r, "model_dump_json")
                else json.dumps(r) if isinstance(r, dict) else r), output=[],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)) for r in responses]
    create = AsyncMock(side_effect=converted)
    monkeypatch.setattr(chat, "_get_db_conn", lambda: db)
    monkeypatch.setattr(chat, "get_settings", lambda: settings)
    monkeypatch.setattr(chat, "load_soul", lambda: "Danish soul")
    monkeypatch.setattr(chat, "get_client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    rows = [source()] if rows is None else rows

    async def execute(conn, *, name, arguments, **kwargs):
        if name == "get_memory_sources":
            return json.dumps(rows)
        return json.dumps(dict(status=status, answerable=True, indexing_watermark="watermark",
            search_scope=dict(arguments, people=[2] if arguments.get("people_names") == ["Anne"] else None),
            results=[dict(kind=kind, source_handle="msg:1" if kind == "raw_message" else "mem:1")] if rows else []))
    tool = AsyncMock(side_effect=execute)
    monkeypatch.setattr(answering.tools, "execute_memory_tool", tool)
    return create, tool


async def reply(question="Hvad sagde vi om transport?", **kwargs):
    return await chat.reply(question=question, asking_user_id=1, channel_id=4, **kwargs)


@pytest.mark.parametrize("kind", ["raw_message", "fact", "segment_summary", "rollup_week"])
async def test_history_always_retrieves_expands_and_verifies(monkeypatch, db, kind):
    create, tool = setup(monkeypatch, db, [route(), assessment(), draft(), verified()], kind=kind)
    result = await reply()
    assert result.text == draft()["claims"][0]["text"]
    assert [c.kwargs["name"] for c in tool.await_args_list] == ["recall_community_memory", "get_memory_sources"]
    assert create.await_count == 4


async def test_general_has_no_memory_or_verifier_calls(monkeypatch, db):
    create, tool = setup(monkeypatch, db, [route("general"), "Almen viden"])
    assert (await reply()).text == "Almen viden"
    tool.assert_not_awaited()
    assert create.await_count == 2
    assert create.await_args.kwargs["tools"] == [{"type": "web_search"}]


async def test_general_answer_keeps_context_used_to_interpret_followup(monkeypatch, db):
    from klatrebot_v2.db.messages import MessageWithAuthor
    create, tool = setup(monkeypatch, db, [route("general", question="Hvad vil du anbefale?"), "Et forslag."])
    prior = "Jeg har højst 300 kroner og vil helst have noget til udendørs brug."
    monkeypatch.setattr(chat.msg_db, "recent_with_authors", AsyncMock(return_value=[
        MessageWithAuthor(**source(2, text=prior))]))
    assert (await reply(question="Hvad vil du anbefale?")).text == "Et forslag."
    data = json.loads(create.await_args.kwargs["input"])
    assert data["question"] == "Hvad vil du anbefale?"
    assert prior in data["conversation"]
    tool.assert_not_awaited()


@pytest.mark.parametrize("r", [route("ambiguous"), "invalid json", {"kind": "general", "too_many_parts": False, "parts": []}])
async def test_ambiguous_and_invalid_route_search_first_then_clarify(monkeypatch, db, r):
    create, tool = setup(monkeypatch, db, [r], rows=[])
    text = (await reply()).text
    assert answering.LIMITATIONS["bounded"] in text
    assert answering.CLARIFY in text
    assert tool.await_count == 2
    assert create.await_count == 1


async def test_absence_never_generates_a_denial(monkeypatch, db):
    create, tool = setup(monkeypatch, db, [route()], rows=[])
    assert (await reply()).text == answering.LIMITATIONS["bounded"]
    assert tool.await_count == 2
    assert create.await_count == 1


@pytest.mark.parametrize("status,expected", [("unavailable", "unavailable"), ("invalid_arguments", "incomplete")])
async def test_retrieval_errors_use_code_wording(monkeypatch, db, status, expected):
    create, _ = setup(monkeypatch, db, [route()], status=status)
    assert (await reply()).text == answering.LIMITATIONS[expected]
    assert create.await_count == 1


async def test_unknown_people_do_not_broaden(monkeypatch, db):
    _, tool = setup(monkeypatch, db, [route(people_names=["Unknown"])], status="clarification_required")
    assert (await reply()).text == answering.PERSON_CLARIFY
    assert tool.await_count == 1
    assert tool.await_args.kwargs["arguments"]["people_names"] == ["Unknown"]


async def test_corrected_person_scope_survives_reformulation(monkeypatch, db):
    _, tool = setup(monkeypatch, db, [route(people_names=["Anne"],
        date_start="2026-07-01T00:00:00Z", date_end="2026-08-01T00:00:00Z",
        reformulation="tog transport")], rows=[])
    await reply()
    first, second = [c.kwargs["arguments"] for c in tool.await_args_list]
    assert first["people_names"] == ["Anne"]
    assert second["people"] == [2] and second["people_names"] is None
    for key in ("channel_id", "date_start", "date_end", "person_role"):
        assert first[key] == second[key]
    assert second["query"] == "tog transport"


async def test_invoking_message_and_bots_excluded_even_when_retrieved(monkeypatch, db):
    bot = source(3)
    bot["is_bot"] = True
    create, _ = setup(monkeypatch, db, [route()], rows=[source(99), bot])
    assert (await reply(invoking_message_id=99)).text == answering.LIMITATIONS["bounded"]
    assert create.await_count == 1


async def test_recent_human_evidence_is_allowed_after_search(monkeypatch, db):
    from klatrebot_v2.memory.retrieval import SourceMessage
    create, tool = setup(monkeypatch, db, [route(), assessment(), draft(), verified()], rows=[])
    monkeypatch.setattr(chat.msg_db, "recent_with_authors", AsyncMock(return_value=[SourceMessage(**source())]))
    assert (await reply()).text == draft()["claims"][0]["text"]
    assert tool.await_count == 1
    sent = model_input(create.await_args_list[1].kwargs["input"])
    assert sent["sources"][0]["source_handle"] == "msg:1"


@pytest.mark.parametrize("bad", [draft(citations=[citation(handle="msg:other")]),
    draft(citations=[citation(quote="fabricated")]), draft(citations=[])])
async def test_bad_handles_and_quotes_never_sent(monkeypatch, db, bad):
    create, _ = setup(monkeypatch, db, [route(), assessment(), bad, bad])
    text = (await reply()).text
    assert text == answering.INTERPRETATION_LIMIT
    assert source()["content"] not in text
    assert bad["claims"][0]["text"] not in text
    assert create.await_count == 4


async def test_semantic_rejection_allows_exactly_one_repair(monkeypatch, db):
    bad = draft("Person 2 tog flyet. Det gjorde de aldrig igen.")
    create, _ = setup(monkeypatch, db, [route(), assessment(), bad, verified(False), draft(), verified()])
    assert (await reply()).text == draft()["claims"][0]["text"]
    assert create.await_count == 6
    repair = json.loads(create.await_args_list[4].kwargs["input"])
    assert repair["verification_feedback"] == verified(False)["feedback"]


async def test_failed_repair_is_never_rendered(monkeypatch, db):
    bad = draft("Det skete aldrig.")
    create, _ = setup(monkeypatch, db, [route(), assessment(), bad, verified(False), bad, verified(False)])
    text = (await reply()).text
    assert "Det skete aldrig" not in text
    assert text == answering.INTERPRETATION_LIMIT
    assert create.await_count == 6


def test_counterevidence_is_required_and_conflicts_are_distinct():
    sources = {"msg:1": source(), "msg:2": source(2, text="Jeg tager ikke toget")}
    with pytest.raises(ValueError):
        ev.validate_assessment(ev.Assessment(**assessment("contradicted")), sources)
    counter = citation("msg:2", "Jeg tager ikke toget", "counterevidence")
    ev.validate_assessment(ev.Assessment(**assessment("contradicted", [counter])), sources)
    ev.validate_assessment(ev.Assessment(**assessment("conflicting", [citation(), counter])), sources)
    with pytest.raises(ValueError):
        ev.validate_assessment(ev.Assessment(**assessment("conflicting", [counter])), sources)


@pytest.mark.parametrize("citations,status,code", [
    ([citation("msg:missing")], "supported", "unknown_handle"),
    ([citation("msg:2", "Naboens ord")], "supported", "ineligible_primary_source"),
    ([citation("msg:2", "Naboens ord", "counterevidence")], "contradicted", "ineligible_primary_source"),
    ([citation(quote="Naboens ord")], "supported", "nonliteral_excerpt"),
    ([citation(quote="Jeg tager [...] toget")], "supported", "nonliteral_excerpt"),
    ([citation(quote="")], "supported", "empty_excerpt"),
    ([citation(quote="x" * 1001)], "supported", "excerpt_too_long"),
    ([citation(role="context")], "supported", "support_required"),
    ([citation()], "not_found", "not_found_has_evidence"),
    ([citation(), citation(role="counterevidence")], "supported", "opposing_roles_require_conflicting"),
    ([citation(), citation(role="counterevidence"), citation("msg:2", "Naboens ord", "context")],
     "conflicting", "distinct_opposing_sources_required"),
])
def test_assessment_validation_reason_codes(citations, status, code):
    with pytest.raises(ev.EvidenceValidationError) as error:
        ev.validate_assessment(ev.Assessment(**assessment(status, citations)),
            {"msg:1": source()}, {"msg:2": source(2, 2, "Naboens ord")})
    assert error.value.code == code


async def test_context_citation_survives_draft_and_verification(monkeypatch, db):
    citations = [citation(), citation("msg:2", "Tager du toget?", "context")]
    create, _ = setup(monkeypatch, db,
        [route(people_names=["Anne"]), assessment(citations=citations),
         draft(citations=citations), verified()],
        rows=[source(author=2), source(2, 1, "Tager du toget?")])
    assert (await reply()).text == draft()["claims"][0]["text"]
    for call in create.await_args_list[1:]:
        data = model_input(call.kwargs["input"])
        assert data["sources"][0]["user_id"] == 2
        assert data["context"][0]["user_id"] == 1


def test_draft_cannot_promote_context_or_change_admitted_roles():
    record = ev.EvidenceRecord(sources={"msg:1": source()}, context={"msg:2": source(2, 2)},
        assessment=ev.Assessment(**assessment(citations=[citation(), citation("msg:2", role="context")])))
    with pytest.raises(ev.EvidenceValidationError, match="ineligible_primary_source"):
        ev.validate_draft(ev.Draft(**draft(citations=[citation("msg:2")])), record)
    with pytest.raises(ev.EvidenceValidationError, match="citation_role_changed"):
        ev.validate_draft(ev.Draft(**draft(citations=[citation(role="counterevidence")])), record)
    with pytest.raises(ev.EvidenceValidationError, match="primary_citation_required"):
        ev.validate_draft(ev.Draft(**draft(citations=[citation("msg:2", role="context")])), record)


def test_compaction_preserves_all_messages_metadata_and_roles():
    rows = {f"msg:{i}": dict(source(i, i % 3, f"Ordret tekst {i}\n  med mellemrum æøå"),
                            source_handle=f"msg:{i}", author_pronouns="brug navnet") for i in range(187)}
    primary = {h: m for h, m in rows.items() if m["user_id"] == 0}
    payload = ev.compact_sources(primary, rows)
    assert len(payload["messages"]) == 187
    assert len(payload["authors"]) == 3
    decoded = model_input(json.dumps(payload))
    restored = {m["source_handle"]: {k: v for k, v in m.items() if k != "author"}
                for m in decoded["sources"] + decoded["context"]}
    assert restored == rows
    assert set(payload["sources"]) == set(primary)
    assert set(payload["context"]) == set(rows) - set(primary)
    assert len(json.dumps(payload)) < len(json.dumps(dict(sources=list(primary.values()), context=list(rows.values()))))


@pytest.mark.parametrize("bad", ["not json", {}, assessment("contradicted")])
async def test_failed_assessment_repair_preserves_coverage_and_logs_reason(monkeypatch, db, caplog, bad):
    import logging
    create, tool = setup(monkeypatch, db, [route(), bad, bad])
    with caplog.at_level(logging.INFO, logger=answering.__name__):
        assert (await reply()).text == answering.ASSESSMENT_LIMIT
    event = json.loads(caplog.records[-1].message.split("memory_answer ", 1)[1])
    assert event["parts"][0]["coverage"] == "bounded"
    assert create.await_count == 3 and tool.await_count == 2
    assert '"phase": "assessment_repair"' in caplog.text
    assert '"primary_count": 1' in caplog.text and '"input_tokens": 10' in caplog.text
    assert '"reason":' in caplog.text
    assert "Jeg tager toget" not in caplog.text and "not json" not in caplog.text


async def test_malformed_assessment_can_be_repaired(monkeypatch, db):
    create, tool = setup(monkeypatch, db, [route(), "not json", assessment(), draft(), verified()])
    assert (await reply()).text == draft()["claims"][0]["text"]
    assert json.loads(create.await_args_list[2].kwargs["input"])["validation_feedback"] == "malformed_assessment"
    assert tool.await_count == 2


async def test_only_insufficient_evidence_reformulates_and_repair_budget_is_shared(monkeypatch, db):
    create, tool = setup(monkeypatch, db, [route(reformulation="tog transport"),
        "not json", assessment("not_found", []), "not json"])
    assert (await reply()).text == answering.ASSESSMENT_LIMIT
    searches = [c.kwargs["arguments"] for c in tool.await_args_list
                if c.kwargs["name"] == "recall_community_memory"]
    assert len(searches) == 2 and searches[1]["query"] == "tog transport"
    assert create.await_count == 4


def test_bot_sources_remain_ineligible_even_as_context():
    bot = dict(source(), is_bot=True)
    with pytest.raises(ev.EvidenceValidationError, match="bot_source"):
        ev.validate_assessment(ev.Assessment(**assessment("uncertain", [citation(role="context")])),
                               {}, {"msg:1": bot})


async def test_assessment_repair_uses_shared_deadline(monkeypatch, db):
    create, _ = setup(monkeypatch, db, [route(), "not json"])
    responses = iter(create.side_effect)
    async def slow(**kwargs):
        response = next(responses, None)
        if response is not None:
            return response
        await asyncio.sleep(10)
    create.side_effect = slow
    monkeypatch.setattr(answering, "DEADLINE_SECONDS", .05)
    assert (await reply()).text == answering.TIMEOUT_LIMIT
    assert create.await_count == 3


@pytest.mark.parametrize("text", ["Nej, kun en plan blev nævnt.", "**Ja**, det gjorde personen.", "No, it was only planned."])
def test_uncertain_evidence_rejects_categorical_polarity(text):
    record = ev.EvidenceRecord(sources={"msg:1": source()},
        assessment=ev.Assessment(**assessment("uncertain", [citation()])))
    with pytest.raises(ValueError, match="categorical"):
        ev.validate_draft(ev.Draft(**draft(text)), record)
    ev.validate_draft(ev.Draft(**draft("Personen nævnte en plan; gennemførelsen er uafklaret.")), record)


async def test_mixed_composition_preserves_boundaries(monkeypatch, db):
    r = route()
    r.kind = "mixed"
    r.parts.append(route("general").parts[0])
    create, _ = setup(monkeypatch, db, [r, assessment(), draft(), verified(), "Tog kører på skinner."])
    text = (await reply()).text
    assert text.startswith("Fra chathistorikken: ")
    assert "Generel information: Tog kører på skinner." in text
    assert create.await_count == 5  # No unrestricted composing call.


async def test_large_request_asks_to_narrow(monkeypatch, db):
    r = routing.Route(kind="mixed", too_many_parts=True, parts=[])
    _, tool = setup(monkeypatch, db, [r])
    assert "højst tre dele" in (await reply()).text
    tool.assert_not_awaited()


async def test_shared_deadline_returns_limitation_without_excerpts(monkeypatch, db):
    create, _ = setup(monkeypatch, db, [route(), assessment(), draft()])
    responses = iter(create.side_effect)

    async def slow(**kwargs):
        try:
            return next(responses)
        except StopIteration:
            await asyncio.sleep(10)
    create.side_effect = slow
    monkeypatch.setattr(answering, "DEADLINE_SECONDS", .05)
    text = (await reply()).text
    assert answering.TIMEOUT_LIMIT in text
    assert "Jeg tager toget" not in text
    assert draft()["claims"][0]["text"] not in text


async def test_stored_pronouns_reach_draft_and_verifier_after_rename(monkeypatch, db):
    from klatrebot_v2.db import users
    for uid, alias in [(1, "member_one"), (2, "member_two")]:
        await users.upsert(db, discord_user_id=uid, display_name=alias)
        await users.upsert(db, discord_user_id=uid, display_name=f"Renamed {uid}")
        await db.execute("UPDATE user_pronouns SET pronouns='hun/hende' WHERE discord_user_id=?", (uid,))
    await users.upsert(db, discord_user_id=3, display_name="Third member")
    rows = [source(1, 1), source(2, 2), source(3, 3)]
    create, _ = setup(monkeypatch, db, [route(), assessment(), draft(), verified()], rows=rows)
    await reply()
    for call_index in (1, 3):
        sent = model_input(create.await_args_list[call_index].kwargs["input"])
        assert {s["user_id"]: s["author_pronouns"] for s in sent["sources"]} == {
            1: "hun/hende", 2: "hun/hende", 3: "han/ham"}
    sent = model_input(create.await_args_list[2].kwargs["input"])
    assert sent["sources"][0]["author_pronouns"] == "hun/hende"
    assert sent["sources"][0]["content"] == source()["content"]


async def test_pronouns_are_not_inferred_from_aliases(db):
    from klatrebot_v2.db import users
    from klatrebot_v2.memory import pronouns
    for uid in (1, 2):
        await users.upsert(db, discord_user_id=uid, display_name="member_one")
    rows = pronouns.enrich([source(1, 1), source(2, 2)], await pronouns.author_pronouns(db))
    assert all(row["author_pronouns"] == "han/ham" for row in rows)


async def test_seeded_id_works_without_username_alias(db):
    from klatrebot_v2.db import migrations
    from klatrebot_v2.memory import pronouns
    await migrations.run(db, pronoun_seeds={101: "hun/hende"})
    row = source(author=101)
    enriched = pronouns.enrich([row], await pronouns.author_pronouns(db))
    assert enriched[0]["author_pronouns"] == "hun/hende"


async def test_latest_failed_repair_never_dumps_selected_quote(monkeypatch, db):
    from klatrebot_v2.memory.latest import LatestSelection
    create, _ = setup(monkeypatch, db, [route(people_names=["member_one"], latest_authored=True),
        draft(), verified(False), draft(), verified(False)])
    selected = dict(source(), source_handle="msg:1", quote="Jeg tager toget")
    monkeypatch.setattr(answering, "select_latest", AsyncMock(return_value=
        LatestSelection(selected=selected, uncertain=False)))
    text = (await reply(question="Hvad skrev member_one senest?")).text
    assert text == answering.INTERPRETATION_LIMIT
    assert "msg:" not in text and selected["quote"] not in text
    assert create.await_count == 5


async def test_latest_context_reaches_draft_and_verifier_once(monkeypatch, db):
    from klatrebot_v2.memory.latest import LatestSelection
    create, _ = setup(monkeypatch, db, [route(people_names=["Anna"], latest_authored=True),
        draft(), verified()])
    neighbor = dict(source(2, 2, "Hvordan kommer du derhen?"), source_handle="msg:2")
    selection = LatestSelection(selected=dict(source(), source_handle="msg:1", quote="Jeg tager toget"),
                                uncertain=False, context={"msg:2": neighbor})
    monkeypatch.setattr(answering, "select_latest", AsyncMock(return_value=selection))
    assert (await reply(question="Hvad skrev Anna senest om transport?")).text == draft()["claims"][0]["text"]
    for call in create.await_args_list[1:]:
        payload = json.loads(call.kwargs["input"])
        assert payload["context"] == ["msg:2"]
        assert "context" not in payload["latest_selection"]
        assert payload["latest_selection"]["selected"] == {"source_handle": "msg:1"}
        assert sum(m["content"] == neighbor["content"] for m in payload["messages"]) == 1


async def test_routing_timeout_still_searches(monkeypatch, db):
    create, tool = setup(monkeypatch, db, [], rows=[])
    async def slow(**kwargs):
        await asyncio.sleep(10)
    create.side_effect = slow
    monkeypatch.setattr(answering, "ROUTING_SECONDS", .01)
    assert answering.CLARIFY in (await reply()).text
    assert tool.await_count == 2


async def test_caller_cancellation_propagates(monkeypatch, db):
    create, _ = setup(monkeypatch, db, [])
    create.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await reply()


async def test_telemetry_has_counts_but_no_content(monkeypatch, db, caplog):
    import logging
    setup(monkeypatch, db, [route(), assessment(), draft(), verified()])
    with caplog.at_level(logging.INFO, logger=answering.__name__):
        await reply()
    text = caplog.text
    assert '"input_tokens": 10' in text and '"route": "history"' in text
    assert "msg:1" in text
    assert "Jeg tager toget" not in text and "Hvad sagde vi" not in text


async def test_neighbor_is_context_not_target_author_evidence(monkeypatch, db):
    target = source(1, author=2)
    neighbor = source(2, author=1, text="Tager du toget?")
    create, _ = setup(monkeypatch, db, [route(people_names=["Anne"]), assessment(), draft(), verified()],
                       rows=[target, neighbor])
    await reply()
    sent = model_input(create.await_args_list[1].kwargs["input"])
    assert [s["user_id"] for s in sent["sources"]] == [2]
    assert [s["user_id"] for s in sent["context"]] == [1]


async def test_mixed_deadline_preserves_completed_general_part(monkeypatch, db):
    r = route("general")
    r.kind = "mixed"
    r.parts.append(route().parts[0])
    _, tool = setup(monkeypatch, db, [r, "Almen forklaring."])
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)
    tool.side_effect = slow
    monkeypatch.setattr(answering, "DEADLINE_SECONDS", .04)
    text = (await reply()).text
    assert "Generel information: Almen forklaring." in text
    assert "Fra chathistorikken: " + answering.TIMEOUT_LIMIT in text


async def test_mixed_latest_does_not_exit_before_general_part(monkeypatch, db):
    from klatrebot_v2.memory.latest import LatestSelection
    r = route(people_names=["Anna"], latest_authored=True)
    r.kind = "mixed"
    r.parts.append(route("general").parts[0])
    _, _ = setup(monkeypatch, db, [r, draft(), verified(), "Almen forklaring."])
    selection = LatestSelection(selected=dict(source(), source_handle="msg:1", quote="Jeg tager toget"), uncertain=False)
    monkeypatch.setattr(answering, "select_latest", AsyncMock(return_value=selection))
    text = (await reply(question="Hvad skrev Anna senest, og hvordan virker tog?")).text
    assert draft()["claims"][0]["text"] in text
    assert "Generel information: Almen forklaring." in text


async def test_contradiction_without_counterevidence_fails_closed(monkeypatch, db):
    create, _ = setup(monkeypatch, db, [route(), assessment("contradicted"), assessment("contradicted")])
    assert (await reply()).text == answering.ASSESSMENT_LIMIT
    assert create.await_count == 3


async def test_conflicting_sources_are_passed_to_whole_draft_verifier(monkeypatch, db):
    counter = citation("msg:2", "Jeg tager ikke toget", "counterevidence")
    create, _ = setup(monkeypatch, db, [route(), assessment("conflicting", [citation(), counter]),
        draft("Kilderne modsiger hinanden.", [citation(), counter]), verified()],
        rows=[source(), source(2, text="Jeg tager ikke toget")])
    assert (await reply()).text == "Kilderne modsiger hinanden."
    sent = model_input(create.await_args.kwargs["input"])
    assert sent["assessment"]["status"] == "conflicting"
    assert {s["source_handle"] for s in sent["sources"]} == {"msg:1", "msg:2"}


async def test_preparation_outage_fails_closed(monkeypatch, db):
    setup(monkeypatch, db, [])
    monkeypatch.setattr(chat.msg_db, "recent_with_authors", AsyncMock(side_effect=OSError))
    assert (await reply()).text == answering.LIMITATIONS["unavailable"]


def test_latest_only_for_explicit_named_authored_request():
    assert route(latest_authored=False, people_names=["Anna"]).parts[0].arguments(4)["order"] == "relevance"
    assert route(latest_authored=True).parts[0].arguments(4)["order"] == "relevance"
    assert route(latest_authored=True, people_names=["Anna"], person_role="subject").parts[0].arguments(4)["order"] == "relevance"


async def test_router_does_not_treat_invocation_as_prior_conversation(monkeypatch, db):
    from klatrebot_v2.memory.retrieval import SourceMessage
    create, _ = setup(monkeypatch, db, [route("ambiguous")], rows=[])
    monkeypatch.setattr(chat.msg_db, "recent_with_authors", AsyncMock(return_value=[
        SourceMessage(**source(99, text="!gpt Hvad med toget?"))]))
    await reply(invoking_message_id=99)
    sent = model_input(create.await_args.kwargs["input"])
    assert "msg:99" not in sent
    assert "!gpt" not in sent
    assert "QUESTION:" in sent


async def test_recent_does_not_authorize_latest_even_if_router_says_so(monkeypatch, db):
    from klatrebot_v2.memory.retrieval import SourceMessage
    setup(monkeypatch, db, [route(people_names=["Anna"], latest_authored=True), assessment(), draft(), verified()], rows=[])
    monkeypatch.setattr(chat.msg_db, "recent_with_authors", AsyncMock(return_value=[SourceMessage(**source())]))
    selector = AsyncMock(side_effect=AssertionError("Recent is not latest"))
    monkeypatch.setattr(answering, "select_latest", selector)
    assert "Person 1" in (await reply(question="Hvad sagde Anna lige om toget?")).text
    selector.assert_not_awaited()


@pytest.mark.parametrize("question,expected", [("Hvad skrev Anna senest?", True),
    ("Annas seneste besked?", True), ("Hvad skrev Anna sidste uge?", False),
    ("Hvad skrev Anna lige?", False), ("What was Anna's last message?", True)])
def test_explicit_latest_guard(question, expected):
    assert routing.explicitly_latest(question, [], None) is expected


def test_person_correction_inherits_latest_from_humans_only():
    prior = SimpleNamespace(content="Hvad var Annas seneste afbud?", is_bot=False, discord_message_id=1)
    current = SimpleNamespace(content="Nej, jeg mente Bo.", is_bot=False, discord_message_id=2)
    assert routing.explicitly_latest(current.content, [prior, current], 2)
    prior.is_bot = True
    assert not routing.explicitly_latest(current.content, [prior, current], 2)


async def test_invalid_assessment_repairs_same_evidence(monkeypatch, db):
    bad = assessment(citations=[citation("msg:neighbor")])
    create, tool = setup(monkeypatch, db, [route(reformulation="tog transport"), bad,
        assessment(), draft(), verified()])
    assert (await reply()).text == draft()["claims"][0]["text"]
    calls = [c.kwargs["arguments"] for c in tool.await_args_list if c.kwargs["name"] == "recall_community_memory"]
    assert len(calls) == 1
    first = json.loads(create.await_args_list[1].kwargs["input"])
    repair = json.loads(create.await_args_list[2].kwargs["input"])
    assert repair.pop("validation_feedback") == "unknown_handle"
    first.pop("validation_feedback")
    assert first == repair


@pytest.mark.parametrize("question,end", [
    ("Hvad var det seneste før den 24. juli 2026?", "2026-07-24T00:00:00+02:00"),
    ("Hvad var det seneste før 2. januar 2026?", "2026-01-02T00:00:00+01:00"),
    ("What happened before 2026-07-24?", "2026-07-24T00:00:00+02:00")])
def test_calendar_cutoff_uses_requested_day_exclusively(question, end):
    part = route(question=question, date_end="2026-07-23").parts[0]
    corrected = routing.preserve_cutoff(part, question, "Europe/Copenhagen")
    assert corrected.date_end == end
    assert part.date_end == "2026-07-23"  # The proposal remains reviewable.


def test_cutoff_does_not_invent_year_or_accept_rewritten_date():
    part = route(question="Hvad skete før den 24. juli?", date_end=None).parts[0]
    assert routing.preserve_cutoff(part, part.question, "Europe/Copenhagen").date_end is None
    with pytest.raises(ValueError):
        routing.preserve_cutoff(route(question="Hvad skete før 2026-07-23?").parts[0],
                                "Hvad skete før 2026-07-24?", "Europe/Copenhagen")


@pytest.mark.parametrize("clock", ["kl. 14", "klokken 14", "14:30"])
def test_calendar_guard_does_not_overwrite_an_explicit_clock(clock):
    question = f"Hvad skete før den 24. juli 2026 {clock}?"
    part = route(question=question, date_end="2026-07-24T14:00:00+02:00").parts[0]
    assert routing.preserve_cutoff(part, question, "Europe/Copenhagen").date_end == part.date_end


def test_late_in_month_is_not_explicit_latest_occurrence():
    assert not routing.explicitly_latest("Hvornår meldte Anna fra sidst i juli?", [], None)
    assert routing.explicitly_latest("Hvad var Annas seneste afbud sidst i juli?", [], None)


@pytest.mark.parametrize("phrase,year,month", [("juli", 2026, 7), ("sidst i juli", 2026, 7), ("december", 2025, 12), ("maj 2024", 2024, 5)])
def test_authored_month_retains_calendar_scope(phrase, year, month):
    from datetime import datetime
    part = route(authored_month=phrase).parts[0]
    result = routing.preserve_authored_month(part, f"Hvad skrev hun i {phrase}?", "Europe/Copenhagen", datetime(2026, 9, 9))
    start = datetime.fromisoformat(result.date_start)
    end = datetime.fromisoformat(result.date_end)
    assert (start.year, start.month, start.day) == (year, month, 1)
    assert end.month == month % 12 + 1 and end.day == 1
    assert start.utcoffset() is not None


def test_mentioned_event_month_does_not_filter_authored_time():
    part = route(authored_month=None).parts[0]
    assert routing.preserve_authored_month(part, "Hvilken dato i april nævnte hun?", "Europe/Copenhagen") == part


def test_invented_month_constraint_is_rejected():
    with pytest.raises(ValueError):
        routing.preserve_authored_month(route(authored_month="juli 2025").parts[0], "Hvad skete i juli?", "Europe/Copenhagen")


async def test_latest_corrected_person_uses_user_cutoff_not_router_day(monkeypatch, db):
    from klatrebot_v2.memory.latest import LatestSelection
    question = "Nej, jeg mente Anne. Hvad var hendes seneste afbud før den 24. juli 2026?"
    _, tool = setup(monkeypatch, db, [route(question=question, people_names=["Anne"],
        latest_authored=True, date_end="2026-07-23"), draft(), verified()])
    selection = LatestSelection(selected=dict(source(), source_handle="msg:1", quote="Jeg tager toget"), uncertain=False)
    selector = AsyncMock(return_value=selection)
    monkeypatch.setattr(answering, "select_latest", selector)
    await reply(question=question)
    assert tool.await_args_list[0].kwargs["arguments"]["date_end"] == "2026-07-24T00:00:00+02:00"
    assert selector.await_args.kwargs["arguments"]["people_names"] == ["Anne"]
