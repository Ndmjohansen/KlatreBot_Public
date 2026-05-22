"""Stable Discord user alias config and lookup."""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite


ALIAS_SOURCES = {"config", "discord_display"}
_SPACES_RE = re.compile(r"\s+")
_STRIP_CHARS = string.whitespace + string.punctuation + "“”‘’«»"


@dataclass(frozen=True)
class AliasResolution:
    resolved_ids: list[int] = field(default_factory=list)
    ambiguous: dict[str, list[int]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)


def normalize_alias(alias: str) -> str:
    normalized = _SPACES_RE.sub(" ", alias.strip(_STRIP_CHARS).lower())
    return normalized.strip(_STRIP_CHARS)


async def upsert_alias(
    conn: aiosqlite.Connection,
    *,
    discord_user_id: int,
    alias: str,
    source: str,
) -> None:
    if source not in ALIAS_SOURCES:
        raise ValueError(f"Unsupported alias source: {source}")
    clean = alias.strip()
    normalized = normalize_alias(clean)
    if not normalized or len(normalized) > 80:
        return
    await conn.execute(
        """
        INSERT INTO user_aliases (discord_user_id, alias, alias_normalized, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(discord_user_id, alias_normalized) DO UPDATE SET
            alias = excluded.alias,
            source = CASE
                WHEN user_aliases.source = 'config' THEN user_aliases.source
                ELSE excluded.source
            END,
            updated_at = datetime('now')
        """,
        (discord_user_id, clean, normalized, source),
    )
    await conn.commit()


async def sync_config_aliases(conn: aiosqlite.Connection, path: str | None) -> None:
    if not path:
        return
    alias_map = load_alias_config(path)
    for discord_user_id, aliases in alias_map.items():
        for alias in aliases:
            await upsert_alias(conn, discord_user_id=discord_user_id, alias=alias, source="config")


def load_alias_config(path: str) -> dict[int, list[str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    users = raw.get("users", raw) if isinstance(raw, dict) else {}
    out: dict[int, list[str]] = {}
    for raw_user_id, value in users.items():
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        aliases = _aliases_from_value(value)
        if aliases:
            out[user_id] = aliases
    return out


def _aliases_from_value(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = value.get("names", [])
    else:
        values = []
    aliases: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        normalized = normalize_alias(item)
        if normalized and normalized not in seen:
            aliases.append(item.strip())
            seen.add(normalized)
    return aliases


async def resolve_people_names(conn: aiosqlite.Connection, names: list[str] | None) -> AliasResolution:
    if not names:
        return AliasResolution()
    resolved: set[int] = set()
    ambiguous: dict[str, list[int]] = {}
    unmatched: list[str] = []
    for name in names:
        normalized = normalize_alias(name)
        if not normalized:
            continue
        rows = await conn.execute_fetchall(
            """
            SELECT DISTINCT discord_user_id
            FROM user_aliases
            WHERE alias_normalized = ?
            ORDER BY discord_user_id
            """,
            (normalized,),
        )
        ids = [int(row[0]) for row in rows]
        if len(ids) == 1:
            resolved.add(ids[0])
        elif len(ids) > 1:
            ambiguous[name] = ids
        else:
            unmatched.append(name)
    return AliasResolution(resolved_ids=sorted(resolved), ambiguous=ambiguous, unmatched=unmatched)


async def format_alias_prompt_map(conn: aiosqlite.Connection, *, limit: int = 200) -> str:
    rows = await conn.execute_fetchall(
        """
        SELECT discord_user_id, alias
        FROM user_aliases
        ORDER BY discord_user_id, source, alias_normalized
        LIMIT ?
        """,
        (limit,),
    )
    if not rows:
        return "(none)"
    grouped: dict[int, list[str]] = {}
    for user_id, alias in rows:
        grouped.setdefault(int(user_id), []).append(str(alias))
    return "\n".join(
        f"{' / '.join(_dedupe_preserve_order(aliases))} -> {user_id}"
        for user_id, aliases in grouped.items()
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_alias(value)
        if key and key not in seen:
            out.append(value)
            seen.add(key)
    return out
