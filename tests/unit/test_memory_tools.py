from datetime import datetime, timezone

from pydantic import BaseModel

from klatrebot_v2.db import user_aliases
from klatrebot_v2.memory import tools


class _FakeRecall(BaseModel):
    answerable: bool = True
    results: list = []
    source_handles: list[str] = []


async def test_recall_tool_resolves_people_names(monkeypatch, db):
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobi", source="config")
    called = {}

    async def fake_recall(conn, **kwargs):
        called.update(kwargs)
        return _FakeRecall()

    monkeypatch.setattr(tools, "recall_community_memory", fake_recall)

    output = await tools.execute_memory_tool(
        db,
        run_id=7,
        name="recall_community_memory",
        arguments={"query": "Kjugekull", "people_names": ["Tobi"]},
    )

    assert '"resolved_people"' in output
    assert called["run_id"] == 7
    assert called["people"] == [42]


async def test_recall_tool_reports_ambiguous_people_names(monkeypatch, db):
    await user_aliases.upsert_alias(db, discord_user_id=1, alias="Simon", source="config")
    await user_aliases.upsert_alias(db, discord_user_id=2, alias="Simon", source="config")

    async def fake_recall(conn, **kwargs):
        assert kwargs["people"] is None
        return _FakeRecall()

    monkeypatch.setattr(tools, "recall_community_memory", fake_recall)

    output = await tools.execute_memory_tool(
        db,
        run_id=7,
        name="recall_community_memory",
        arguments={
            "query": "Spanien",
            "people_names": ["Simon"],
            "date_start": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    assert '"ambiguous": {"Simon": [1, 2]}' in output
