import json

from klatrebot_v2.db import user_aliases


async def test_sync_config_aliases_from_json_map(db, tmp_path):
    config = tmp_path / "aliases.json"
    config.write_text(
        json.dumps(
            {
                "135463962316636160": ["Tobias", "Tobi"],
                "123": {"names": ["Pelle", "Twink"]},
            }
        ),
        encoding="utf-8",
    )

    await user_aliases.sync_config_aliases(db, str(config))

    resolved = await user_aliases.resolve_people_names(db, ["tobi", "Twink"])

    assert resolved.resolved_ids == [123, 135463962316636160]
    assert resolved.unmatched == []
    assert resolved.ambiguous == {}


async def test_upsert_display_alias_keeps_old_display_names(db):
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="OldNick", source="discord_display")
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="NewNick", source="discord_display")

    resolved = await user_aliases.resolve_people_names(db, ["oldnick", "newnick"])

    assert resolved.resolved_ids == [42]


async def test_resolve_people_names_reports_ambiguous_aliases(db):
    await user_aliases.upsert_alias(db, discord_user_id=1, alias="Simon", source="config")
    await user_aliases.upsert_alias(db, discord_user_id=2, alias="Simon", source="config")

    resolved = await user_aliases.resolve_people_names(db, ["Simon", "Unknown"])

    assert resolved.resolved_ids == []
    assert resolved.ambiguous == {"Simon": [1, 2]}
    assert resolved.unmatched == ["Unknown"]


async def test_alias_prompt_map_formats_known_aliases(db):
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobias", source="config")
    await user_aliases.upsert_alias(db, discord_user_id=42, alias="Tobi", source="config")

    prompt_map = await user_aliases.format_alias_prompt_map(db)

    assert "Tobi / Tobias -> 42" in prompt_map
