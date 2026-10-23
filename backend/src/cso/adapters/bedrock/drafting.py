"""Produce one validated draft: model draft, validate, one regeneration, then the template.

Every failure of the model path ends in the offline template, so a draft request never fails
because Bedrock did. The draft is always a candidate for a person to edit; nothing here posts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cso.adapters.bedrock.budget import DraftBudget
from cso.adapters.bedrock.types import Drafter, DraftingError, DraftRequest
from cso.domain.config import Tone
from cso.domain.draft_validation import (
    DraftFields,
    evidence_ids,
    validate_draft,
    violation_note,
)
from cso.domain.enums import DraftStatus, Response
from cso.domain.evidence import RenderedEvidence
from cso.domain.models import DraftValidation
from cso.domain.templates import TEMPLATE_VERSION, template_fields


@dataclass(frozen=True)
class DraftOutcome:
    """A draft with how it was made; `usage` is stored with the draft row."""

    fields: DraftFields
    status: DraftStatus
    validation: DraftValidation
    model_id: str | None
    usage: dict[str, Any] = field(default_factory=dict)


def _fields_of(raw_greeting: str, body: str, closing: str, cited: tuple[str, ...]) -> DraftFields:
    return DraftFields(greeting=raw_greeting, body=body, closing=closing, cited_evidence_ids=cited)


def template_outcome(
    response_type: Response, tone: Tone, *, reason: str, usage: dict[str, Any]
) -> DraftOutcome:
    """The offline template as an outcome; REJECTED_BY_VALIDATOR only if it fails its own checks."""
    fields = template_fields(response_type, tone)
    validation = validate_draft(
        fields,
        tone=tone,
        evidence_ids_available=frozenset(),
        require_citation=False,
    )
    status = DraftStatus.TEMPLATE_FALLBACK if validation.ok else DraftStatus.REJECTED_BY_VALIDATOR
    return DraftOutcome(
        fields=fields,
        status=status,
        validation=validation,
        model_id=None,
        usage={**usage, "fallback_reason": reason, "template_version": TEMPLATE_VERSION},
    )


async def produce_draft(
    *,
    response_type: Response,
    evidence: RenderedEvidence,
    tone: Tone,
    language: str,
    drafter: Drafter | None,
    budget: DraftBudget | None = None,
) -> DraftOutcome:
    """Draft a comment of `response_type` from the rendered evidence, never raising for Bedrock."""
    usage: dict[str, Any] = {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
    if drafter is None:
        return template_outcome(response_type, tone, reason="model_disabled", usage=usage)

    available = evidence_ids(evidence)
    violations: tuple[str, ...] = ()
    first_violations: list[str] = []
    for attempt in range(2):
        if budget is not None and not budget.allow():
            return template_outcome(response_type, tone, reason="budget_exceeded", usage=usage)
        request = DraftRequest(
            evidence_text=evidence.text,
            response_type=response_type,
            tone=tone,
            language=language,
            violations=violations,
        )
        try:
            raw = await drafter.draft(request)
        except DraftingError as exc:
            return template_outcome(response_type, tone, reason=exc.code, usage=usage)
        usage["model_calls"] += 1
        usage["input_tokens"] += raw.input_tokens
        usage["output_tokens"] += raw.output_tokens
        if budget is not None:
            budget.record(raw.input_tokens + raw.output_tokens)

        fields = _fields_of(raw.greeting, raw.body, raw.closing, raw.cited_evidence_ids)
        validation = validate_draft(
            fields,
            tone=tone,
            evidence_ids_available=available,
            evidence_text=evidence.text,
            language=language,
        )
        if validation.ok:
            usage["regenerated"] = attempt == 1
            return DraftOutcome(
                fields=fields,
                status=DraftStatus.VALIDATED,
                validation=validation,
                model_id=raw.model_id,
                usage=usage,
            )
        if attempt == 0:
            first_violations = list(validation.violations)
            violations = (violation_note(validation.violations),)
    usage["first_violations"] = first_violations
    usage["final_violations"] = list(validation.violations)
    return template_outcome(response_type, tone, reason="validator_rejected", usage=usage)
