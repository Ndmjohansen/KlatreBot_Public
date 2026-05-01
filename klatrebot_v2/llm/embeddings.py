"""OpenAI embedding wrapper. Batched, multilingual (text-embedding-3-small)."""
import logging

from klatrebot_v2.llm.client import get_client
from klatrebot_v2.settings import get_settings


logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 30000  # ~8k tokens, well under 8191 cap; chars are cheaper to count


async def embed(texts: list[str]) -> list[list[float] | None]:
    """Embed a batch of texts. Returns same-length list; None for skipped (empty) inputs."""
    s = get_settings()
    keep_idx: list[int] = []
    payload: list[str] = []
    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            continue
        keep_idx.append(i)
        payload.append(t[:_MAX_INPUT_CHARS])

    out: list[list[float] | None] = [None] * len(texts)
    if not payload:
        return out

    client = get_client()
    resp = await client.embeddings.create(model=s.embedding_model, input=payload)
    for i, datum in zip(keep_idx, resp.data):
        out[i] = list(datum.embedding)
    return out
