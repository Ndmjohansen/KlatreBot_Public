"""Topic-independent judgments of source evidence, separate from ranking policy."""
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from klatrebot_v2.llm.prompt import compose_prompts


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_handle: str
    relevance: Literal["relevant", "irrelevant", "uncertain"]
    quote: str


class Judgments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judgments: list[Verdict]


INSTRUCTIONS = compose_prompts("source_evidence", "evidence_rules")


async def classify(client, model, question, scope, candidates, context):
    expected = {c["source_handle"]: c for c in candidates}
    if len(expected) != len(candidates):
        raise ValueError("Duplicate evidence candidates")
    # Ranking/page mechanics must not influence whether a source supports a claim.
    filters = {k: v for k, v in scope.items()
               if k in {"people", "channel_id", "date_start", "date_end", "person_role"}}
    response = await client.responses.create(
        model=model, instructions=INSTRUCTIONS,
        input=json.dumps(dict(question=question, filters=filters,
                             **compact_sources(expected, {
                                 c.get("source_handle", f"msg:{c.get('discord_message_id', 0)}"): c
                                 for c in context})), ensure_ascii=False, separators=(",", ":")),
        reasoning={"effort": "medium"},
        text={"format": {"type": "json_schema", "name": "source_evidence",
                         "strict": True, "schema": Judgments.model_json_schema()}},
    )
    parsed = Judgments.model_validate_json(response.output_text)
    verdicts = {v.source_handle: v for v in parsed.judgments}
    if len(verdicts) != len(parsed.judgments) or verdicts.keys() != expected.keys():
        raise ValueError("Incomplete or unknown evidence judgments")
    for handle, v in verdicts.items():
        if v.relevance == "relevant" and (not v.quote.strip() or len(v.quote) > 1000 or v.quote not in expected[handle]["content"]):
            raise ValueError("Unsupported evidence quote")
    return verdicts


EvidenceStatus = Literal["supported", "contradicted", "conflicting", "uncertain", "not_found"]
Coverage = Literal["bounded", "incomplete", "unavailable"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_handle: str
    quote: str
    role: Literal["support", "counterevidence", "context"]


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: EvidenceStatus
    evidence: list[Citation]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    citations: list[Citation]


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim]


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_reading: str
    valid: bool
    supported_claims: list[bool]
    feedback: str


@dataclass
class EvidenceRecord:
    sources: dict[str, dict] = field(default_factory=dict)
    context: dict[str, dict] = field(default_factory=dict)
    search_coverage: list[dict] = field(default_factory=list)
    retrieval_handles: list[str] = field(default_factory=list)
    assessment: Assessment = field(default_factory=lambda: Assessment(status="not_found", evidence=[]))
    coverage: Coverage = "unavailable"
    watermark: str | None = None
    failures: list[str] = field(default_factory=list)
    verification_feedback: str = ""


ASSESS_INSTRUCTIONS = compose_prompts("assessment", "evidence_rules")

VERIFY_INSTRUCTIONS = compose_prompts("verification", "evidence_rules")


class EvidenceValidationError(ValueError):
    """A stable, content-free validation reason suitable for logs and repair."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def compact_sources(sources, context=None):
    """Serialize each message once; share identical author metadata losslessly."""
    authors, messages = [], []
    context = context or {}
    for handle, row in sorted((context | sources).items()):
        author = {k: v for k, v in row.items()
                  if k in {"user_id", "user_display_name", "author_pronouns", "is_bot"}}
        if author not in authors:
            authors.append(author)
        message = {k: v for k, v in row.items() if k not in author}
        message.update(source_handle=handle, author=authors.index(author))
        messages.append(message)
    return dict(authors=authors, messages=messages, sources=sorted(sources),
                context=sorted(set(context) - set(sources)))


def selection_metadata(selection):
    if selection is None:
        return None
    data = selection.model_dump(exclude={"context"})
    if selection.selected:
        data["selected"] = {"source_handle": selection.selected["source_handle"]}
    return data


def validate_citations(citations, sources, context=None):
    context = context or {}
    for citation in citations:
        handle = citation.source_handle
        source = sources.get(handle) or context.get(handle)
        if source is None:
            raise EvidenceValidationError("unknown_handle")
        if citation.role != "context" and handle not in sources:
            raise EvidenceValidationError("ineligible_primary_source")
        if source.get("is_bot"):
            raise EvidenceValidationError("bot_source")
        if not citation.quote.strip():
            raise EvidenceValidationError("empty_excerpt")
        if len(citation.quote) > 1000:
            raise EvidenceValidationError("excerpt_too_long")
        if citation.quote not in source["content"]:
            raise EvidenceValidationError("nonliteral_excerpt")


def validate_assessment(assessment, sources, context=None):
    validate_citations(assessment.evidence, sources, context)
    roles = {e.role for e in assessment.evidence}
    primary = [e for e in assessment.evidence if e.role != "context"]
    if assessment.status in {"supported", "contradicted"} and {"support", "counterevidence"} <= roles:
        raise EvidenceValidationError("opposing_roles_require_conflicting")
    if assessment.status == "supported" and "support" not in roles:
        raise EvidenceValidationError("support_required")
    if assessment.status in {"contradicted", "conflicting"} and "counterevidence" not in roles:
        raise EvidenceValidationError("counterevidence_required")
    if assessment.status == "conflicting" and (
            "support" not in roles or len({e.source_handle for e in primary}) < 2):
        raise EvidenceValidationError("distinct_opposing_sources_required")
    if assessment.status == "not_found" and assessment.evidence:
        raise EvidenceValidationError("not_found_has_evidence")


async def assess(client, model, question, sources, context=None, feedback=None):
    response = await client.responses.create(
        model=model, instructions=ASSESS_INSTRUCTIONS,
        input=json.dumps(dict(question=question, **compact_sources(sources, context),
                              validation_feedback=feedback), ensure_ascii=False, separators=(",", ":")),
        reasoning={"effort": "low"}, text={"format": {"type": "json_schema",
            "name": "claim_assessment", "strict": True, "schema": Assessment.model_json_schema()}})
    try:
        result = Assessment.model_validate_json(response.output_text)
    except (ValidationError, TypeError) as exc:
        raise EvidenceValidationError("malformed_assessment") from exc
    validate_assessment(result, sources, context)
    return result


def validate_draft(draft, record, selected_handle=None):
    admitted = {c.source_handle for c in record.assessment.evidence}
    if not draft.claims:
        raise ValueError("Empty historical draft")
    for claim in draft.claims:
        if not claim.text.strip() or not claim.citations:
            raise ValueError("Uncited historical assertion")
        if record.assessment.status == "uncertain" and re.match(
                r"^[\s\W]*(?:ja|nej|yes|no)\b", claim.text, re.I):
            raise ValueError("Uncertain evidence cannot establish a categorical answer")
        validate_citations(claim.citations, record.sources, record.context)
        if not any(c.role != "context" for c in claim.citations):
            raise EvidenceValidationError("primary_citation_required")
        admitted_roles = {(c.source_handle, c.role) for c in record.assessment.evidence}
        if any((c.source_handle, c.role) not in admitted_roles for c in claim.citations):
            raise EvidenceValidationError("citation_role_changed")
        handles = {c.source_handle for c in claim.citations}
        if not handles <= admitted or (selected_handle and selected_handle not in handles):
            raise ValueError("Draft escaped admitted evidence")


async def verify(client, model, question, draft, record, latest_selection=None):
    validate_draft(draft, record, latest_selection.selected["source_handle"]
                   if latest_selection and latest_selection.selected else None)
    response = await client.responses.create(
        model=model, instructions=VERIFY_INSTRUCTIONS,
        input=json.dumps(dict(question=question, draft=draft.model_dump(),
            assessment=record.assessment.model_dump(), **compact_sources(record.sources, record.context),
            latest_selection=selection_metadata(latest_selection)), ensure_ascii=False, separators=(",", ":")),
        reasoning={"effort": "high"}, text={"format": {"type": "json_schema",
            "name": "draft_verification", "strict": True, "schema": Verification.model_json_schema()}})
    result = Verification.model_validate_json(response.output_text)
    record.verification_feedback = result.feedback
    return result.valid and len(result.supported_claims) == len(draft.claims) and all(result.supported_claims)
