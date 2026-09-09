import hashlib

import pytest

from klatrebot_v2.memory.evaluate import evaluate, seed


def case():
    return {'id': 'gold', 'request': {'query': 'Hvorfor kom personen ikke?'},
            'expected_source_ids': [100],
            'evidence_sha256': hashlib.sha256('Jeg skal passe katten'.encode()).hexdigest(),
            'messages': [{'discord_message_id': 100, 'channel_id': 42, 'user_id': 1,
                          'content': 'Jeg skal passe katten', 'timestamp_utc': '2026-09-01T12:00:00+00:00'}]}


async def test_evaluator_checks_ranked_sources_and_omits_context(tmp_path, monkeypatch):
    path = tmp_path / 'source.db'
    gold = case()
    await seed(path, [gold])

    async def response(*args, **kwargs):
        return {'results': [{'source_handle': 'msg:100', 'source_ids': [100]}],
                'source_handles': ['msg:100', 'msg:999'], 'status': 'ok',
                'coverage': {'local_search_ms': 1, 'worker_peak_rss_mb': 100,
                             'chronological_page': [{'text': 'private neighbor'}],
                             'instruction': 'private instruction'}}

    monkeypatch.setattr('klatrebot_v2.memory.evaluate.request', response)
    result = await evaluate(path, '/unused', [gold], 0)
    row = result['cases'][0]
    assert row['candidate_ids'] == ['msg:100']
    assert row['first_expected_rank'] == 1
    assert row['source_expansion_correct']
    assert result['recall_at_10'] == 1
    assert result['legacy_recall_at_10'] == 0
    assert not result['quality_passed']  # One case cannot pass the 30-case gate.
    assert 'private' not in str(result)


async def test_evaluator_rejects_changed_gold_before_search(tmp_path, monkeypatch):
    path = tmp_path / 'source.db'
    gold = case()
    await seed(path, [gold])
    gold['evidence_sha256'] = 'outdated'

    async def forbidden(*args, **kwargs):
        raise AssertionError('Must validate evidence before querying')

    monkeypatch.setattr('klatrebot_v2.memory.evaluate.request', forbidden)
    with pytest.raises(ValueError, match='Changed expected evidence'):
        await evaluate(path, '/unused', [gold], 0)


async def test_evaluator_rejects_duplicate_cases():
    with pytest.raises(ValueError, match='unique'):
        await evaluate('/unused', '/unused', [case(), case()], 0)
