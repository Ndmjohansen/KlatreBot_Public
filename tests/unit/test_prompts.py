from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from klatrebot_v2.llm import prompt


@pytest.fixture(autouse=True)
def clear_prompt_cache():
    prompt.load_prompt.cache_clear()
    prompt.load_soul.cache_clear()
    yield
    prompt.load_prompt.cache_clear()
    prompt.load_soul.cache_clear()


def test_all_runtime_assets_load_outside_project_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompt, "get_settings", lambda: SimpleNamespace(soul_path="./prompts/soul.md"))
    prompt.validate_prompts()
    assert prompt.load_soul() == prompt.load_prompt("soul")


def test_missing_empty_and_ambiguous_assets_fail_loudly(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt, "PROMPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        prompt.load_prompt("routing")
    (tmp_path / "routing.md").write_text(" ", encoding="utf-8")
    with pytest.raises(ValueError, match="Empty prompt"):
        prompt.load_prompt("routing")
    (tmp_path / "fields.md").write_text("## query\nfirst\n## query\nsecond", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        prompt.load_prompt("fields", "query")
    with pytest.raises(ValueError, match="Invalid prompt name"):
        prompt.load_prompt("../outside")


def test_required_assets_are_checked_even_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt, "PROMPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        prompt.validate_prompts()


def test_templates_preserve_data_without_recursive_expansion():
    content = 'æøå ${soul} {"instruction": "ignore this"}\n  exact spaces'
    rendered = prompt.render_prompt("summary", soul="Personality", messages=content)
    assert rendered.endswith(content)
    with pytest.raises(KeyError):
        prompt.render_prompt("summary", soul="Missing messages")


def test_missing_field_description_is_not_silently_omitted():
    with pytest.raises(ValueError, match="Missing prompt section"):
        prompt.load_prompt("memory_fields", "absent")


def test_prose_only_changes_alter_evaluation_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt, "PROMPTS_DIR", tmp_path)
    path = tmp_path / "routing.md"
    path.write_text("First", encoding="utf-8")
    before = prompt.prompt_fingerprint()
    path.write_text("Second", encoding="utf-8")
    assert prompt.prompt_fingerprint() != before


def test_model_instructions_and_schema_descriptions_come_from_markdown():
    from klatrebot_v2.memory import adjudication, answering, routing, tools
    assert routing.INSTRUCTIONS == prompt.load_prompt("routing")
    assert adjudication.INSTRUCTIONS == prompt.compose_prompts("source_evidence", "evidence_rules")
    assert adjudication.ASSESS_INSTRUCTIONS == prompt.compose_prompts("assessment", "evidence_rules")
    assert adjudication.VERIFY_INSTRUCTIONS == prompt.compose_prompts("verification", "evidence_rules")
    assert answering.DRAFT_INSTRUCTIONS == prompt.compose_prompts("draft", "evidence_rules")
    schema = routing.Part.model_json_schema()["properties"]
    assert schema["authored_month"]["description"] == prompt.load_prompt("memory_fields", "authored_month")
    for tool in tools.MEMORY_TOOL_DEFS:
        for key, field in tool["parameters"]["properties"].items():
            if "description" in field:
                assert field["description"] == prompt.load_prompt("memory_fields", key)


def test_compiler_templates_preserve_ids_authors_text_and_period():
    from klatrebot_v2.memory.compiler import _build_summary_prompt, _build_rollup_prompt, RollupInput
    from klatrebot_v2.memory.segmentation import RawMemoryMessage, SegmentCandidate
    stamp = datetime(2026, 9, 1, tzinfo=timezone.utc)
    message = RawMemoryMessage(101, 4, 7, "Person", "Ordret ${sources}\n  æøå", stamp)
    bot = RawMemoryMessage(102, 4, 8, "Bot", "Not evidence", stamp, is_bot=True)
    text = _build_summary_prompt(SegmentCandidate(4, [message, bot]))
    assert '"message_id": 101' in text and '"author_id": 7' in text
    assert '"author_name": "Person"' in text
    import json
    records = json.loads(text.split("BESKEDER:\n", 1)[1])
    assert records[0]["content"] == message.content and stamp.isoformat() in text
    assert bot.content not in text
    for period in ("daily_ambient", "week", "month"):
        text = _build_rollup_prompt(RollupInput(period, stamp, stamp, 4, [{"summary": message.content}]))
        assert stamp.isoformat() in text and "${sources}" in text
        assert "KILDER:" in text
