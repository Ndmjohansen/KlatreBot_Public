import time
from collections import defaultdict, deque

import pytest


@pytest.fixture(autouse=True)
def _reset_ratelimit_state(monkeypatch):
    """Force fresh limiter state per test."""
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_buckets", defaultdict(deque))
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 0)


def test_allows_under_limit(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 3)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True


def test_blocks_over_limit(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 2)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(1) is False


def test_per_user_independent(monkeypatch):
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 1)
    assert ratelimit.check_and_record(1) is True
    assert ratelimit.check_and_record(2) is True
    assert ratelimit.check_and_record(1) is False
    assert ratelimit.check_and_record(2) is False


def test_window_expires(monkeypatch):
    """Old timestamps fall out of the window."""
    from klatrebot_v2.llm import ratelimit
    monkeypatch.setattr(ratelimit, "_LIMIT_PER_HOUR", 1)
    monkeypatch.setattr(ratelimit, "_WINDOW_SECONDS", 0.01)
    assert ratelimit.check_and_record(1) is True
    time.sleep(0.02)
    assert ratelimit.check_and_record(1) is True
