"""Attach database-owned pronouns to evidence without changing source content."""
from klatrebot_v2.db import user_pronouns


async def author_pronouns(conn) -> dict[int, str]:
    return await user_pronouns.get_all(conn)


def enrich(rows, stored_pronouns):
    """Apply stored pronouns to community authors only.

    This metadata describes the author, never other people mentioned in a source.
    Source content remains untouched for literal evidence validation.
    """
    return [dict(row, author_pronouns=stored_pronouns.get(row["user_id"], "brug navnet"))
            for row in rows]
