"""JSON schemas for klatrebot-tools plugin. Hermes shows these to the LLM."""

GET_RECENT_MESSAGES = {
    "name": "get_recent_messages",
    "description": (
        "Hent de seneste beskeder fra en kanal i KlatreBots historik. "
        "Returnerer liste sorteret ældst-først inden for vinduet."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "integer", "description": "Discord channel ID"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
        },
        "required": ["channel_id"],
    },
}

SEARCH_MESSAGES = {
    "name": "search_messages",
    "description": (
        "Keyword-søgning (SQL LIKE) i beskeder. Brug ved konkrete ord. "
        "Til semantisk/synonym-søgning, brug search_messages_semantic i stedet."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "channel_id": {"type": "integer"},
            "since": {"type": "string", "description": "ISO 8601 UTC, inclusive"},
            "until": {"type": "string", "description": "ISO 8601 UTC, exclusive"},
            "limit": {"type": "integer", "default": 50, "maximum": 500},
        },
        "required": ["query"],
    },
}

SEARCH_MESSAGES_SEMANTIC = {
    "name": "search_messages_semantic",
    "description": (
        "Semantisk søgning via embeddings — finder beskeder med lignende betydning, "
        "ikke kun samme ord. Bruges til 'hvornår snakkede vi om X' eller emnesøgning."
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

MESSAGES_IN_WINDOW = {
    "name": "messages_in_window",
    "description": "Hent alle beskeder i et tidsvindue [start, end) for en kanal.",
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "integer"},
            "start": {"type": "string", "description": "ISO 8601 UTC, inclusive"},
            "end": {"type": "string", "description": "ISO 8601 UTC, exclusive"},
        },
        "required": ["channel_id", "start", "end"],
    },
}

GET_ATTENDANCE = {
    "name": "get_attendance",
    "description": (
        "Optælling af klatretid-fremmøde for en specifik lokal dato. "
        "Returnerer ja-stemmer og nej-stemmer pr. bruger."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_local": {"type": "string", "description": "YYYY-MM-DD i Europe/Copenhagen"},
            "channel_id": {"type": "integer"},
        },
        "required": ["date_local", "channel_id"],
    },
}

GET_USER = {
    "name": "get_user",
    "description": "Slå brugeroplysninger op via Discord user ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer"},
        },
        "required": ["user_id"],
    },
}
