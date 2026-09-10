from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.cogs import admin
from klatrebot_v2.db import migrations, user_aliases, user_pronouns, users


@pytest.fixture
def command_context(db, monkeypatch):
    monkeypatch.setattr(admin, "get_settings", lambda: SimpleNamespace(admin_user_id=1))
    return admin.AdminCog(SimpleNamespace(db_conn=db)), SimpleNamespace(
        author=SimpleNamespace(id=1), reply=AsyncMock())


async def test_admin_can_configure_new_user_and_edit_pronouns(db, command_context):
    cog, ctx = command_context
    await cog.set_pronouns.callback(cog, ctx, 123, pronouns="hun/hende")
    await cog.set_display_name.callback(cog, ctx, 123, display_name="Test member")
    assert (await users.get(db, 123)).display_name == "Test member"
    assert (await user_aliases.resolve_people_names(db, ["Test member"])).resolved_ids == [123]
    assert (await user_pronouns.get_all(db))[123] == "hun/hende"
    await cog.set_pronouns.callback(cog, ctx, 123, pronouns="de/dem")
    await users.upsert(db, discord_user_id=123, display_name="Discord rename")
    await migrations.run(db, pronoun_seeds={123: "hun/hende"})
    assert (await user_pronouns.get_all(db))[123] == "de/dem"
    assert (await user_aliases.resolve_people_names(db, ["Test member"])).resolved_ids == [123]


async def test_database_admin_is_allowed(db, command_context):
    cog, ctx = command_context
    await users.upsert(db, discord_user_id=2, display_name="Admin", is_admin=True)
    ctx.author.id = 2
    await cog.set_pronouns.callback(cog, ctx, 123, pronouns="han/ham")
    assert (await user_pronouns.get_all(db))[123] == "han/ham"


async def test_nonadmin_cannot_change_identity(db, command_context):
    cog, ctx = command_context
    ctx.author.id = 2
    await cog.set_display_name.callback(cog, ctx, 123, display_name="Test member")
    await cog.set_pronouns.callback(cog, ctx, 123, pronouns="hun/hende")
    assert await users.get(db, 123) is None
    assert 123 not in await user_pronouns.get_all(db)
    assert ctx.reply.await_count == 2
    assert "ikke adgang" in ctx.reply.await_args.args[0]


@pytest.mark.parametrize("uid,value", [(0, "hun/hende"), (123, ""), (123, "invented")])
async def test_invalid_pronouns_do_not_write(db, command_context, uid, value):
    cog, ctx = command_context
    await cog.set_pronouns.callback(cog, ctx, uid, pronouns=value)
    assert uid not in await user_pronouns.get_all(db)


async def test_new_user_defaults_and_name_edit_preserves_admin(db, command_context):
    cog, ctx = command_context
    await users.upsert(db, discord_user_id=123, display_name="Old", is_admin=True)
    await cog.set_display_name.callback(cog, ctx, 123, display_name="New")
    assert (await users.get(db, 123)).is_admin
    assert (await user_pronouns.get_all(db))[123] == "han/ham"
