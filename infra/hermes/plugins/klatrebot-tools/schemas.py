"""JSON schemas exposed to the LLM for the klatrebot-tools plugin."""

KLATREBOT_QUERY = {
    "name": "klatrebot_query",
    "description": (
        "Kør vilkårligt SELECT/WITH/EXPLAIN på KlatreBots SQLite database (read-only). "
        "Bruges til alle slags opslag: beskeder, brugere, fremmøde, statistik. "
        "Brug params (?-placeholders) for at undgå SQL-injection ved bruger-input.\n\n"
        "KERNESKEMA (kald klatrebot_schema for fuld DDL hvis nødvendigt):\n"
        "  users(discord_user_id PK, display_name, is_admin, created_at, updated_at)\n"
        "  messages(discord_message_id PK, channel_id, user_id FK->users.discord_user_id,\n"
        "           content, timestamp_utc TEXT ISO8601, is_bot)\n"
        "  attendance_session(id PK, date_local YYYY-MM-DD, channel_id, message_id,\n"
        "                     klatring_start_utc TEXT ISO8601)\n"
        "  attendance_reaction_event(id PK, session_id FK, user_id FK->users.discord_user_id,\n"
        "                            status 'yes'|'no', timestamp_utc)\n"
        "  message_embeddings (vec0 virtuel; brug klatrebot_search_semantic i stedet)\n\n"
        "JOINS: messages.user_id = users.discord_user_id (IKKE u.user_id)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SELECT, WITH, EXPLAIN eller schema-PRAGMA. Andre statements afvises."},
            "params": {"type": "array", "items": {}, "description": "Positional parameters for ?-placeholders"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        "required": ["sql"],
    },
}

KLATREBOT_SCHEMA = {
    "name": "klatrebot_schema",
    "description": "Hent fuld DDL for alle tabeller, views og indexes i KlatreBots database. Kald før klatrebot_query når du er i tvivl om struktur.",
    "parameters": {"type": "object", "properties": {}},
}

KLATREBOT_SEARCH_SEMANTIC = {
    "name": "klatrebot_search_semantic",
    "description": (
        "Semantisk besked-søgning via embeddings. Finder beskeder med lignende betydning, "
        "ikke kun samme ord. Bruges til 'hvornår snakkede vi om X', emnesøgning, synonym-tolerance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "default": 20, "maximum": 100},
            "channel_id": {"type": "integer"},
            "since": {"type": "string", "description": "ISO 8601 UTC, inclusive"},
            "until": {"type": "string", "description": "ISO 8601 UTC, exclusive"},
        },
        "required": ["query"],
    },
}

KLATREBOT_HEALTH = {
    "name": "klatrebot_health",
    "description": "Tjek om KlatreBot API er nået. Returnerer status + latency.",
    "parameters": {"type": "object", "properties": {}},
}
