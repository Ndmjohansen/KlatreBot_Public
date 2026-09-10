"""Strict filtering, rank fusion and resumable source-time retrieval."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import heapq
import json
import re
import time

from klatrebot_v2.memory.corpus import load_corpus, utc
from klatrebot_v2.memory.palace import embed
from klatrebot_v2.memory.retrieval import MemoryResult, RecallResult


def scope_hash(request):
    scope = {k: v for k, v in request.items() if k not in {"cursor", "limit"}}
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def encode_cursor(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def filtered(docs, request):
    people = set(request.get("people") or [])
    types = request.get("memory_types") or []
    role = request.get("person_role", "author")
    start, end = request.get("date_start"), request.get("date_end")
    start, end = utc(start) if start else None, utc(end) if end else None
    out = []
    for d in docs:
        if request.get("channel_id") is not None and d.channel != request["channel_id"]:
            continue
        if types and d.kind not in types:
            continue
        if people:
            if role == "author" and (len(d.authors) != 1 or not people.intersection(d.authors)):
                continue
            if role == "subject" and not people.intersection(d.subjects):
                continue
        # Every source must satisfy time constraints for a derived claim.
        if start and d.source_start < start:
            continue
        if end and d.source_end >= end:
            continue
        out.append(d)
    return out


def lexical_ids(docs, query):
    terms = set(re.findall(r"\w{2,}", query.casefold()))
    matches = ((len(terms.intersection(d.terms)), d.timestamp, d.id) for d in docs)
    return [did for _, _, did in heapq.nlargest(30, (match for match in matches if match[0]))]


def fuse(*rankings):
    scores = {}
    for ranking in rankings:
        for rank, did in enumerate(ranking, 1):
            scores[did] = scores.get(did, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda did: (-scores[did], did))


def result_for(d):
    return MemoryResult(kind=d.kind, source_handle=d.handle, text=d.text,
                        type=d.kind, participants=d.authors, created_at_source=utc(d.timestamp),
                        source_ids=d.sources, source_excerpts=d.excerpts[:10],
                        match_source="raw" if d.kind == "raw_message" else "derived")


async def search(conn, request, palace=None, client=None, *, prepared_docs=None, index_lock=None):
    local_started = time.perf_counter()
    embedding_seconds = 0
    if request.get("order", "relevance") not in {"relevance", "latest"}:
        raise ValueError("Invalid order")
    if request.get("person_role", "author") not in {"author", "subject"}:
        raise ValueError("Invalid person_role")
    limit = max(1, min(10, int(request.get("limit", 6))))
    if not request["query"].strip():
        return RecallResult(answerable=False)
    if request.get('order') == 'latest' and request.get('memory_types') and 'raw_message' not in request['memory_types']:
        return RecallResult(answerable=False, status='invalid_arguments', coverage={
            'instruction': 'latest søger rå beskeder, men memory_types udelukker dem. Gentag med memory_types=null og bevar person, kanal og datoer. Brug relevance hvis spørgsmålet ikke handler om den seneste forekomst.'})
    docs = filtered(prepared_docs if prepared_docs is not None else await load_corpus(conn, request["run_id"]), request)
    latest = request.get("order") == "latest"
    coverage = {"exhaustive": False, "instruction": "Kontrollér relevans og afsender i kilderne. Sig 'det seneste jeg fandt' ved begrænset søgning."}
    cursor = None
    chronological = []
    if latest:
        if request.get("person_role", "author") != "author" or not request.get("people"):
            return RecallResult(answerable=False, status="invalid_arguments",
                                coverage={"instruction": "latest kræver en bestemt afsender og person_role=author. Brug relevance ved almindelige historiske spørgsmål om fællesskabet. Gæt ikke en person for at udfylde et filter."})
        docs = [d for d in docs if d.kind == "raw_message"]
        end = utc(request["date_end"]) if request.get("date_end") else datetime.now(timezone.utc)
        page_before = None
        if request.get("cursor"):
            try:
                state = json.loads(base64.urlsafe_b64decode(request["cursor"]))
                if state["scope"] != scope_hash(request):
                    raise ValueError("Cursor scope mismatch")
                end = utc(state["end"])
                page_before = tuple(state["before"]) if state.get("before") else None
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("Invalid continuation cursor") from exc
        start = end - timedelta(days=30)
        if request.get("date_start"):
            start = max(start, utc(request["date_start"]))
        older_exists = any(d.source_end < start for d in docs)
        docs = [d for d in docs if start <= d.source_end < end]
        if page_before:
            docs = [d for d in docs if (d.timestamp, d.id) < page_before]
        ordered = sorted(docs, key=lambda d: (d.timestamp, d.id), reverse=True)
        # Chronological results include unindexed messages and short/indirect replies.
        chronological = ordered[:limit]
        if len(ordered) > limit:
            cursor = encode_cursor(dict(scope=scope_hash(request), end=end.isoformat(),
                                        before=[chronological[-1].timestamp, chronological[-1].id]))
        elif older_exists:
            cursor = encode_cursor(dict(scope=scope_hash(request), end=start.isoformat()))
        coverage.update(window_start=start.isoformat(), window_end=end.isoformat(),
                        chronological_page=[result_for(d).model_dump(mode="json") for d in chronological],
                        window_exhausted=len(ordered) <= limit)
    status = "ok" if palace else "degraded"
    semantic, lexical = [], []
    if palace:
        # Indexed documents already have native lexical scores. Only pending
        # documents need the source-side fallback scan; don't rank everything twice.
        pending = [d for d in docs if palace.manifest.get("hashes", {}).get(d.id) != d.digest]
        lexical = lexical_ids(pending, request["query"])
        coverage["unindexed_candidates"] = len(pending)
        vector = None
        embedding_started = time.perf_counter()
        try:
            vectors, _ = await embed(client, [request["query"]])
            vector = vectors[0]
        except Exception:
            status = "degraded"
        finally:
            embedding_seconds = time.perf_counter() - embedding_started
        try:
            if index_lock is None:
                semantic, indexed_lexical = await asyncio.to_thread(palace.candidates, docs, request["query"], vector)
            else:
                async with index_lock:
                    task = asyncio.create_task(asyncio.to_thread(palace.candidates, docs, request["query"], vector))
                    try:
                        semantic, indexed_lexical = await asyncio.shield(task)
                    except asyncio.CancelledError:
                        await task
                        raise
            coverage["index_timings"] = dict(palace.last_timings)
            lexical = fuse(indexed_lexical, lexical)[:30]
        except Exception:
            status = "degraded"
            lexical = lexical_ids(docs, request["query"])
    else:
        lexical = lexical_ids(docs, request["query"])
    by_id = {d.id: d for d in docs}
    ranking = fuse(semantic, lexical)
    if latest:
        ranking = sorted(set(ranking), key=lambda did: (by_id[did].timestamp, did), reverse=True)
    results, seen = [], set()
    for did in ranking:
        d = by_id[did]
        if seen.intersection(d.sources):
            continue
        results.append(result_for(d))
        seen.update(d.sources)
        if len(results) >= limit:
            break
    coverage["local_search_ms"] = (time.perf_counter() - local_started - embedding_seconds) * 1000
    return RecallResult(answerable=bool(results or chronological), results=results,
                        source_handles=list(dict.fromkeys([r.source_handle for r in results] + [d.handle for d in chronological])),
                        status=status, coverage=coverage, continuation_cursor=cursor,
                        indexing_watermark=palace.watermark if palace else None)
