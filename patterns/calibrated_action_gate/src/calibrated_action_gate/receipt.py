"""A decision receipt: everything needed to audit or replay one gated decision."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .aggregate import Aggregate
from .questions import RequestPlan
from .validate import ValidatedResponse

RECEIPT_VERSION = "1"


@dataclass(frozen=True)
class Receipt:
    """Immutable record of one decision: questions, every permutation, aggregates, timing."""

    receipt_version: str
    decider: dict[str, Any]
    questions_hash: str
    state_tokens: int
    permutations: list[dict[str, Any]]
    aggregated: dict[str, dict[str, Any]]
    nouls: dict[str, float]
    timing_ms: dict[str, int]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable dict."""
        return asdict(self)

    def to_json(self) -> str:
        """Canonical JSON string (sorted keys, so equal receipts serialise identically)."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


def build_receipt(
    plan: RequestPlan,
    validated: ValidatedResponse,
    aggregates: dict[str, Aggregate],
    *,
    decider: dict[str, Any],
    timing_ms: dict[str, int],
) -> Receipt:
    """Assemble a receipt from a plan, its validated response and the per-question aggregates."""
    perms = [
        {
            "name": name,
            "order": list(order),
            "probabilities": validated.choices[name].probabilities,
            "confidence": validated.choices[name].confidence,
        }
        for name, order in plan.orders.items()
    ]
    return Receipt(
        receipt_version=RECEIPT_VERSION,
        decider=decider,
        questions_hash=plan.questions_hash,
        state_tokens=validated.input_tokens,
        permutations=perms,
        aggregated={name: asdict(agg) for name, agg in aggregates.items()},
        nouls=dict(validated.nouls),
        timing_ms=timing_ms,
    )
