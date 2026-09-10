import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klatrebot_v2.memory.tools import MEMORY_TOOL_DEFS, execute_memory_tool
from klatrebot_v2.memory.search import search


def test_strict_tools_allow_unset_optional_filters():
    for tool in MEMORY_TOOL_DEFS:
        assert tool['strict'] is True
        schema = tool['parameters']
        assert set(schema['required']) == set(schema['properties'])
        for name, prop in schema['properties'].items():
            if name not in {'query', 'source_handles'}:
                assert 'null' in prop['type']
                if 'enum' in prop:
                    assert None in prop['enum']


async def test_null_filters_normalize_and_do_not_broaden_people(db, monkeypatch):
    from klatrebot_v2.db import users
    await users.upsert(db, discord_user_id=1, display_name='Anna')
    rpc = AsyncMock(return_value={'answerable': False, 'results': [], 'source_handles': []})
    monkeypatch.setattr('klatrebot_v2.memory.tools.request', rpc)
    args = dict.fromkeys(MEMORY_TOOL_DEFS[0]['parameters']['properties'])
    args.update(query='afbud', people=[1], channel_id=42)
    await execute_memory_tool(db, run_id=0, name='recall_community_memory', arguments=args,
                              settings=SimpleNamespace(memory_backend='mempalace', memory_socket_path='unused'))
    request = rpc.call_args.args[1]
    assert request['order'] == 'relevance'
    assert request['person_role'] == 'author'
    assert request['people'] == [1]
    assert request['channel_id'] == 42
    assert request['memory_types'] is None
    assert request['limit'] == 10


@pytest.mark.parametrize('extra', [{'memory_types': ['fact', 'plan'], 'people': [1]}, {'people': []}])
async def test_conflicting_latest_filters_are_actionable_before_search(extra):
    result = await search(None, dict(query='afbud', order='latest', run_id=0, **extra), prepared_docs=[])
    assert result.status == 'invalid_arguments'
    assert not result.answerable
    assert 'relevance' in result.coverage['instruction']


async def test_null_context_radius_and_invalid_date(db):
    assert json.loads(await execute_memory_tool(db, run_id=0, name='get_memory_sources',
        arguments={'source_handles': [], 'context_radius': None})) == []
    result = json.loads(await execute_memory_tool(db, run_id=0, name='recall_community_memory',
        arguments={'query': 'afbud', 'date_start': 'sidste tirsdag'}))
    assert result['status'] == 'invalid_arguments'


async def test_null_channel_uses_invoking_channel(monkeypatch, db):
    from klatrebot_v2.llm import chat
    settings = SimpleNamespace(memory_enabled=True, memory_backend='mempalace',
        memory_active_run_name=None, memory_active_run_id=0, gpt_recent_message_count=25, model='test')
    monkeypatch.setattr(chat, 'get_settings', lambda: settings)
    monkeypatch.setattr(chat, 'load_soul', lambda: 'test')
    monkeypatch.setattr(chat, '_get_db_conn', lambda: db)
    first = SimpleNamespace(id='one', output=[SimpleNamespace(type='function_call', name='recall_community_memory',
        call_id='call', arguments=json.dumps({'query': 'afbud', 'channel_id': None}))])
    final = SimpleNamespace(id='two', output=[], output_text='færdig')
    monkeypatch.setattr(chat, 'get_client', lambda: SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[first, final]))))
    execute = AsyncMock(return_value='{}')
    monkeypatch.setattr(chat.memory_tools, 'execute_memory_tool', execute)
    await chat.reply(question='historik', asking_user_id=1, channel_id=42)
    assert execute.call_args.kwargs['arguments']['channel_id'] == 42
