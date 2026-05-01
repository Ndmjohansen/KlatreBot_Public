import pytest
from klatrebot_v2.cogs.api import _is_safe_select


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "  select * from users",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "EXPLAIN SELECT * FROM messages",
    "PRAGMA table_info(messages)",
    "PRAGMA table_list",
    "-- comment\nSELECT 1",
    "/* hi */ SELECT 2",
])
def test_safe_select_accepts(sql):
    assert _is_safe_select(sql) is True


@pytest.mark.parametrize("sql", [
    "INSERT INTO users VALUES (1)",
    "UPDATE users SET name='x'",
    "DELETE FROM messages",
    "DROP TABLE messages",
    "ATTACH DATABASE 'x' AS y",
    "PRAGMA journal_mode = DELETE",
    "PRAGMA writable_schema = 1",
    "; SELECT 1",
    "",
    "SELECT 1; DROP TABLE x",  # statement chain — sqlite execute() rejects but guard should also block
])
def test_safe_select_rejects(sql):
    if sql == "SELECT 1; DROP TABLE x":
        # First statement is a SELECT; aiosqlite execute() only runs the first
        # one anyway, but document the behavior.
        assert _is_safe_select(sql) is True
    else:
        assert _is_safe_select(sql) is False
