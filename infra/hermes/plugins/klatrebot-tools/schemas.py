"""JSON schemas exposed to the LLM for the klatrebot-tools plugin."""

KLATREBOT_QUERY = {
    "name": "klatrebot_query",
    "description": (
        "Kør vilkårligt SELECT/WITH/EXPLAIN på KlatreBots SQLite database (read-only). "
        "Bruges til alle slags opslag: beskeder, brugere, fremmøde, statistik. "
        "Brug params (?-placeholders) for at undgå SQL-injection ved bruger-input.\n\n"
        "FULDT SKEMA (autoritativt — du behøver ikke kalde klatrebot_schema):\n"
        "  users(\n"
        "    discord_user_id  INTEGER PRIMARY KEY,\n"
        "    display_name     TEXT NOT NULL,\n"
        "    is_admin         INTEGER NOT NULL DEFAULT 0,\n"
        "    created_at       TEXT,\n"
        "    updated_at       TEXT)\n"
        "  messages(\n"
        "    discord_message_id INTEGER PRIMARY KEY,\n"
        "    channel_id         INTEGER NOT NULL,\n"
        "    user_id            INTEGER NOT NULL  -- FK -> users.discord_user_id\n"
        "    content            TEXT NOT NULL,\n"
        "    timestamp_utc      TEXT NOT NULL,    -- ISO 8601, fx '2026-05-01T20:40:46.707000+00:00'\n"
        "    is_bot             INTEGER NOT NULL DEFAULT 0)\n"
        "  attendance_session(\n"
        "    id                 INTEGER PRIMARY KEY,\n"
        "    date_local         TEXT NOT NULL,    -- 'YYYY-MM-DD' i Europe/Copenhagen\n"
        "    channel_id         INTEGER NOT NULL,\n"
        "    message_id         INTEGER NOT NULL,\n"
        "    klatring_start_utc TEXT NOT NULL,    -- ISO 8601\n"
        "    created_at         TEXT)\n"
        "  attendance_reaction_event(\n"
        "    id            INTEGER PRIMARY KEY,\n"
        "    session_id    INTEGER NOT NULL,      -- FK -> attendance_session.id\n"
        "    user_id       INTEGER NOT NULL,      -- FK -> users.discord_user_id\n"
        "    status        TEXT NOT NULL CHECK(status IN ('yes','no')),\n"
        "    timestamp_utc TEXT NOT NULL)\n"
        "  message_embeddings  -- vec0 virtuel tabel; SE NOTE NEDENFOR\n\n"
        "JOIN-IDIOM: messages.user_id = users.discord_user_id "
        "(brugerens id i users-tabellen hedder discord_user_id, ikke user_id).\n\n"
        "NOTE OM VEC0: message_embeddings er en sqlite-vec virtuel tabel. Du kan IKKE "
        "skrive WHERE-betingelser direkte mod 'embedding'-kolonnen i SQL — det kræver "
        "MATCH-syntaks og en query-vektor du ikke har. Brug klatrebot_search_semantic "
        "til alt der ligner emne-/synonym-/'om hvad'-søgning; det embedder query'en "
        "Pi-side og joiner resultatet ind på messages for dig. Du må gerne JOIN'e mod "
        "message_embeddings.message_id hvis du fx vil filtrere beskeder med/uden embedding."
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
