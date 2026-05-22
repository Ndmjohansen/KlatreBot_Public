"""Conversation segmentation for Discord chat memory."""
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RawMemoryMessage:
    discord_message_id: int
    channel_id: int
    user_id: int
    user_display_name: str
    content: str
    timestamp_utc: datetime
    is_bot: bool = False


@dataclass(frozen=True)
class SegmentConfig:
    gap_minutes: int = 30
    min_human_messages: int = 8
    min_total_chars: int = 500
    min_participants: int = 3
    max_messages: int = 100
    max_duration_minutes: int = 120


@dataclass(frozen=True)
class SegmentCandidate:
    channel_id: int
    messages: list[RawMemoryMessage]

    @property
    def start_time_utc(self) -> datetime:
        return self.messages[0].timestamp_utc

    @property
    def end_time_utc(self) -> datetime:
        return self.messages[-1].timestamp_utc

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def human_messages(self) -> list[RawMemoryMessage]:
        return [m for m in self.messages if not m.is_bot]

    @property
    def human_message_count(self) -> int:
        return len(self.human_messages)

    @property
    def total_chars(self) -> int:
        return sum(len(m.content or "") for m in self.human_messages)

    @property
    def participant_ids(self) -> list[int]:
        return sorted({m.user_id for m in self.human_messages})

    @property
    def duration(self) -> timedelta:
        return self.end_time_utc - self.start_time_utc


def build_segments(
    messages: list[RawMemoryMessage],
    config: SegmentConfig | None = None,
) -> list[SegmentCandidate]:
    """Build adaptive segments from timestamp-ordered Discord messages."""
    config = config or SegmentConfig()
    ordered = sorted(messages, key=lambda m: (m.channel_id, m.timestamp_utc, m.discord_message_id))
    initial = _split_by_channel_and_gap(ordered, config)
    merged = _merge_tiny_segments(initial, config)
    out: list[SegmentCandidate] = []
    for segment in merged:
        out.extend(_split_oversized(segment, config))
    return out


def is_meaningful(segment: SegmentCandidate, config: SegmentConfig | None = None) -> bool:
    config = config or SegmentConfig()
    return (
        segment.human_message_count >= config.min_human_messages
        or segment.total_chars >= config.min_total_chars
        or len(segment.participant_ids) >= config.min_participants
    )


def _split_by_channel_and_gap(
    messages: list[RawMemoryMessage],
    config: SegmentConfig,
) -> list[SegmentCandidate]:
    segments: list[SegmentCandidate] = []
    current: list[RawMemoryMessage] = []
    last: RawMemoryMessage | None = None
    max_gap = timedelta(minutes=config.gap_minutes)

    for message in messages:
        starts_new = (
            last is None
            or message.channel_id != last.channel_id
            or message.timestamp_utc - last.timestamp_utc > max_gap
        )
        if starts_new and current:
            segments.append(SegmentCandidate(channel_id=current[0].channel_id, messages=current))
            current = []
        current.append(message)
        last = message

    if current:
        segments.append(SegmentCandidate(channel_id=current[0].channel_id, messages=current))
    return segments


def _merge_tiny_segments(
    segments: list[SegmentCandidate],
    config: SegmentConfig,
) -> list[SegmentCandidate]:
    merged: list[SegmentCandidate] = []
    pending: SegmentCandidate | None = None

    for segment in segments:
        if pending is None:
            pending = segment
        elif pending.channel_id == segment.channel_id and not is_meaningful(pending, config):
            pending = SegmentCandidate(
                channel_id=pending.channel_id,
                messages=[*pending.messages, *segment.messages],
            )
        else:
            merged.append(pending)
            pending = segment

    if pending is not None:
        if merged and pending.channel_id == merged[-1].channel_id and not is_meaningful(pending, config):
            previous = merged.pop()
            merged.append(
                SegmentCandidate(
                    channel_id=previous.channel_id,
                    messages=[*previous.messages, *pending.messages],
                )
            )
        else:
            merged.append(pending)
    return merged


def _split_oversized(
    segment: SegmentCandidate,
    config: SegmentConfig,
) -> list[SegmentCandidate]:
    if (
        segment.message_count <= config.max_messages
        and segment.duration <= timedelta(minutes=config.max_duration_minutes)
    ):
        return [segment]
    if segment.message_count <= 1:
        return [segment]

    split_at = _largest_internal_gap_index(segment.messages)
    if split_at <= 0 or split_at >= len(segment.messages):
        split_at = min(config.max_messages, max(1, len(segment.messages) // 2))

    left = SegmentCandidate(channel_id=segment.channel_id, messages=segment.messages[:split_at])
    right = SegmentCandidate(channel_id=segment.channel_id, messages=segment.messages[split_at:])
    return [*_split_oversized(left, config), *_split_oversized(right, config)]


def _largest_internal_gap_index(messages: list[RawMemoryMessage]) -> int:
    best_index = 1
    best_gap = timedelta(0)
    for idx in range(1, len(messages)):
        gap = messages[idx].timestamp_utc - messages[idx - 1].timestamp_utc
        if gap > best_gap:
            best_gap = gap
            best_index = idx
    return best_index
