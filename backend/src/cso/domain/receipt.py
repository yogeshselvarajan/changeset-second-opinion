"""Decision receipt: the audit record of one analysis (stored in `analysis_runs.receipt`)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from cso.domain.enums import Band, Lane
from cso.domain.models import (
    AggregatedChoice,
    DecisionOutputs,
    EvidenceSnapshot,
    FrozenModel,
    NonNegInt,
    PermutationResult,
    Probability,
    RuleHit,
)
from cso.domain.panel import FactPanel

RECEIPT_VERSION = "1"


class DeciderIdentity(FrozenModel):
    """What `GET /health` said about the model that produced the answers."""

    model: str
    checkpoint: str
    device: str
    max_length: NonNegInt
    temperature: float | None = None
    base_model: str | None = None
    prefix_cache: bool | None = None
    server_git_sha: str | None = None


class ReconciliationRecord(FrozenModel):
    """Q2 reconciliation against Q1; serialised with the key `from`."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    applied: bool
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


class DecisionReceipt(FrozenModel):
    """Everything needed to audit or replay one decision. Immutable; corrections are new rows."""

    receipt_version: str = RECEIPT_VERSION
    case_id: str | None = None
    snapshot_id: str | None = None
    evidence_version: str
    coverage: dict[str, Any]
    decider: DeciderIdentity | None
    config_version: str
    questions_hash: str | None
    state_tokens: NonNegInt = 0
    permutations: list[PermutationResult] = Field(default_factory=list)
    aggregated: dict[str, AggregatedChoice] = Field(default_factory=dict)
    nouls: dict[str, Probability] = Field(default_factory=dict)
    panel: FactPanel | None = None  # tri-state fact panel; its nature answer is advisory only
    panel_questions_hash: str | None = None
    # Which composition rows fired and how each probe compared with the value computed from parsed
    # evidence. Additive: receipts written before these fields existed load with None.
    panel_composition: dict[str, Any] | None = None
    panel_cross_checks: dict[str, str] | None = None
    band: Band | None = None
    rules_fired: list[RuleHit] = Field(default_factory=list)
    reconciliation: ReconciliationRecord | None = None
    lane: Lane | None = None
    timing_ms: dict[str, NonNegInt] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    human_outcome_ids: list[str] = Field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-ready dict using the documented key names (`from` in reconciliation)."""
        return self.model_dump(mode="json", by_alias=True)


def build_receipt(
    snapshot: EvidenceSnapshot,
    *,
    config_version: str,
    questions_hash: str | None = None,
    identity: DeciderIdentity | None = None,
    outputs: DecisionOutputs | None = None,
    panel: FactPanel | None = None,
    panel_questions_hash: str | None = None,
    panel_composition: Mapping[str, Any] | None = None,
    panel_cross_checks: Mapping[str, str] | None = None,
    state_tokens: int = 0,
    timing_ms: Mapping[str, int] | None = None,
    band: Band | None = None,
    rules_fired: Sequence[RuleHit] = (),
    reconciliation: ReconciliationRecord | None = None,
    lane: Lane | None = None,
    errors: Sequence[str] = (),
) -> DecisionReceipt:
    """Merge a snapshot, config version, question hash, Decider output and timings.

    Policy-gate fields (`band`, `rules_fired`, `reconciliation`, `lane`) come from the gate and stay
    empty for a run that failed before the gate; `outputs=None` records a failed run.
    """
    return DecisionReceipt(
        case_id=None if snapshot.case_id is None else str(snapshot.case_id),
        snapshot_id=None if snapshot.id is None else str(snapshot.id),
        evidence_version=snapshot.evidence_version,
        coverage=snapshot.coverage.model_dump(mode="json"),
        decider=identity,
        config_version=config_version,
        questions_hash=questions_hash,
        state_tokens=state_tokens,
        permutations=[] if outputs is None else list(outputs.permutations),
        aggregated={}
        if outputs is None
        else {"nature": outputs.nature, "response": outputs.response},
        nouls={} if outputs is None else dict(outputs.nouls),
        panel=panel,
        panel_questions_hash=panel_questions_hash,
        panel_composition=None if panel_composition is None else dict(panel_composition),
        panel_cross_checks=None if panel_cross_checks is None else dict(panel_cross_checks),
        band=band,
        rules_fired=list(rules_fired),
        reconciliation=reconciliation,
        lane=lane,
        timing_ms=dict(timing_ms or {}),
        errors=list(errors),
    )
