"""Bounded evidence adjudication for latest recall; timestamps are selected in code."""
import asyncio
import json
import logging
from pydantic import BaseModel, Field

from klatrebot_v2.memory import tools
from klatrebot_v2.memory.corpus import utc
from klatrebot_v2.memory.adjudication import classify


class LatestSelection(BaseModel):
    selected: dict | None
    uncertain: bool
    checked_handles: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    watermark: str | None = None

    def render(self):
        return render(self.selected, uncertain=self.uncertain)


def render(selected, *, uncertain=False):
    if selected is None:
        return ("Jeg kunne ikke fastslå det seneste ud fra de kilder, jeg nåede at kontrollere. "
                "Det betyder ikke, at der ikke findes et svar.")
    stamp = utc(selected["timestamp_utc"]).strftime("%d-%m-%Y kl. %H:%M UTC")
    # Quote the selected source rather than asking another model to choose again.
    quote = selected["quote"].replace("@", "@\u200b")
    name = selected["user_display_name"].replace("@", "@\u200b")
    prefix = "Et relevant udsagn jeg fandt" if uncertain else "Det seneste relevante udsagn jeg fandt"
    answer = f"{prefix} var fra {name} den {stamp}:\n> " + quote.replace("\n", "\n> ")
    if uncertain:
        answer += "\nJeg kunne ikke afklare alle nyere kandidater, så jeg kan ikke kalde det det seneste."
    return answer


async def select_latest(conn, *, run_id, arguments, initial, settings, client, question,
                        max_pages=6, timeout=60, structured=False, invoking_message_id=None):
    """Return None for tool errors; otherwise a grounded answer, even on failure.

    Ranked hits provide a head start. Chronological pages establish coverage down
    to that hit, including short/unindexed messages. Never skip unresolved newer
    evidence just because an older message has more explicit wording.
    """
    payload = json.loads(initial)
    if payload.get("status") not in {"ok", "degraded"}:
        return None
    scope = payload.get("search_scope")
    if not scope or scope.get("order") != "latest" or not scope.get("people"):
        return None
    args = dict(arguments)
    # Preserve the resolved scope across every cursor page, including aliases.
    args.update(scope, people_names=None)
    selected = None
    seen = {}
    unresolved = {}
    boundary_reached = False
    failures = []
    try:
        async with asyncio.timeout(timeout):
            for page_number in range(max_pages):
                page = payload.get("coverage", {}).get("chronological_page", [])
                hits = {r["source_handle"]: r for r in payload.get("results", []) + page
                        if r.get("kind") == "raw_message" and r["source_handle"] != f"msg:{invoking_message_id}"}
                fresh = [h for h in hits if h not in seen]
                if fresh:
                    context = json.loads(await tools.execute_memory_tool(
                        conn, run_id=run_id, name="get_memory_sources",
                        arguments={"source_handles": fresh, "context_radius": 2}, settings=settings))
                    context = [m for m in context if not m["is_bot"] and m["discord_message_id"] != invoking_message_id]
                    by_id = {f"msg:{m['discord_message_id']}": m for m in context}
                    candidates = []
                    for handle in fresh:
                        m = by_id.get(handle)
                        if (m is None or m["is_bot"] or m["user_id"] not in scope["people"]
                                or (scope.get("channel_id") is not None and m["channel_id"] != scope["channel_id"])
                                or (scope.get("date_start") and utc(m["timestamp_utc"]) < utc(scope["date_start"]))
                                or (scope.get("date_end") and utc(m["timestamp_utc"]) >= utc(scope["date_end"]))):
                            raise ValueError("Source changed or escaped scope")
                        candidates.append(dict(m, source_handle=handle))
                    verdicts = await classify(client, settings.model, question, scope, candidates, context)
                    uncertain = [c for c in candidates if verdicts[c["source_handle"]].relevance == "uncertain"]
                    if uncertain:
                        expanded = json.loads(await tools.execute_memory_tool(
                            conn, run_id=run_id, name="get_memory_sources",
                            arguments={"source_handles": [c["source_handle"] for c in uncertain], "context_radius": 5},
                            settings=settings))
                        expanded = [m for m in expanded if not m["is_bot"] and m["discord_message_id"] != invoking_message_id]
                        verdicts.update(await classify(client, settings.model, question, scope, uncertain, expanded))
                    for c in candidates:
                        handle = c["source_handle"]
                        v = verdicts[handle]
                        seen[handle] = c
                        if v.relevance == "uncertain":
                            unresolved[handle] = c
                        if v.relevance == "relevant":
                            c["quote"] = v.quote
                            if selected is None or _key(c) > _key(selected):
                                selected = c
                cursor = payload.get("continuation_cursor")
                # The page's oldest timestamp bounds every not-yet-seen message.
                boundary_reached = not cursor or bool(selected and page and
                    min(utc(r["created_at_source"]) for r in page) < utc(selected["timestamp_utc"]))
                if boundary_reached:
                    break
                if page_number + 1 == max_pages:
                    break
                args["cursor"] = cursor
                payload = json.loads(await tools.execute_memory_tool(
                    conn, run_id=run_id, name="recall_community_memory", arguments=args, settings=settings))
                if payload.get("status") not in {"ok", "degraded"}:
                    break
    except Exception as exc:
        # Cancellation by the caller propagates (CancelledError is BaseException).
        logging.getLogger(__name__).warning("latest_evidence_error type=%s", type(exc).__name__)
        boundary_reached = False
        failures.append(type(exc).__name__)
    uncertain = not boundary_reached or any(selected is None or _key(c) >= _key(selected) for c in unresolved.values())
    logging.getLogger(__name__).info("latest_evidence selected=%s checked=%d unresolved=%d bounded=%s",
        selected["source_handle"] if selected else None, len(seen), len(unresolved), uncertain)
    result = LatestSelection(selected=selected, uncertain=uncertain,
        checked_handles=list(seen), failures=failures, watermark=payload.get("indexing_watermark"))
    return result if structured else result.render()


def _key(candidate):
    return utc(candidate["timestamp_utc"]), candidate["discord_message_id"]
