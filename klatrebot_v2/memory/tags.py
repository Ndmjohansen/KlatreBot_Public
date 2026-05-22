"""Tag normalization for compiled memory."""
import re


_EDGE_PUNCT = " \t\r\n.,;:!?()[]{}<>\"'`´“”‘’|/\\"
_SPACE_RE = re.compile(r"\s+")


def normalize_tags(raw_tags) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        if not isinstance(raw, str):
            continue
        tag = _SPACE_RE.sub(" ", raw.lower().strip(_EDGE_PUNCT)).strip()
        if not tag or len(tag) > 50 or not any(ch.isalnum() for ch in tag):
            continue
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
