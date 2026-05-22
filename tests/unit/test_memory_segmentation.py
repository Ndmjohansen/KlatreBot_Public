from datetime import datetime, timedelta, timezone

from klatrebot_v2.memory.segmentation import RawMemoryMessage, SegmentConfig, build_segments


def msg(mid: int, *, minutes: int, content: str = "hej", channel: int = 1, user: int = 10, is_bot: bool = False):
    return RawMemoryMessage(
        discord_message_id=mid,
        channel_id=channel,
        user_id=user,
        user_display_name=f"user-{user}",
        content=content,
        timestamp_utc=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        is_bot=is_bot,
    )


def test_build_segments_splits_on_gap_between_human_messages():
    messages = [
        msg(1, minutes=0, content="første besked"),
        msg(2, minutes=5, content="anden besked"),
        msg(3, minutes=50, content="ny snak"),
    ]

    segments = build_segments(
        messages,
        SegmentConfig(gap_minutes=30, min_human_messages=1, min_total_chars=1, min_participants=1),
    )

    assert [[m.discord_message_id for m in s.messages] for s in segments] == [[1, 2], [3]]


def test_build_segments_merges_tiny_adjacent_segments_until_threshold():
    messages = [
        msg(1, minutes=0, content="kort"),
        msg(2, minutes=40, content="stadig kort"),
        msg(3, minutes=80, content="nok personer", user=20),
        msg(4, minutes=120, content="tredje person", user=30),
    ]

    segments = build_segments(
        messages,
        SegmentConfig(gap_minutes=30, min_human_messages=8, min_total_chars=500, min_participants=3),
    )

    assert len(segments) == 1
    assert [m.discord_message_id for m in segments[0].messages] == [1, 2, 3, 4]
    assert segments[0].human_message_count == 4
    assert segments[0].participant_ids == [10, 20, 30]


def test_build_segments_splits_oversized_segments_on_internal_gap():
    messages = [
        msg(1, minutes=0, content="a" * 200),
        msg(2, minutes=10, content="b" * 200),
        msg(3, minutes=70, content="c" * 200),
        msg(4, minutes=80, content="d" * 200),
    ]

    segments = build_segments(
        messages,
        SegmentConfig(
            gap_minutes=120,
            min_human_messages=1,
            min_total_chars=1,
            min_participants=1,
            max_messages=3,
            max_duration_minutes=45,
        ),
    )

    assert [[m.discord_message_id for m in s.messages] for s in segments] == [[1, 2], [3, 4]]


def test_build_segments_keeps_bot_messages_as_context_but_not_human_counts():
    messages = [
        msg(1, minutes=0, content="!gpt hvad sagde vi?", is_bot=False),
        msg(2, minutes=1, content="bot svar", user=999, is_bot=True),
        msg(3, minutes=2, content="menneske svar", user=20),
    ]

    segments = build_segments(
        messages,
        SegmentConfig(gap_minutes=30, min_human_messages=1, min_total_chars=1, min_participants=1),
    )

    assert len(segments) == 1
    assert segments[0].message_count == 3
    assert segments[0].human_message_count == 2
    assert segments[0].participant_ids == [10, 20]
