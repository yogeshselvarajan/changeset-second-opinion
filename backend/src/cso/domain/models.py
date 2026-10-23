"""Typed entities shared by adapters, policy, jobs and the API."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cso.domain.enums import (
    Band,
    ChangeAction,
    CoverageGapReason,
    Disposition,
    DraftStatus,
    EvidenceSource,
    FetchStatus,
    JobKind,
    JobStatus,
    Lane,
    Nature,
    OsmType,
    Response,
    RunStatus,
    Severity,
    TagChange,
)

type Tags = dict[str, str]
type BBox = tuple[float, float, float, float]  # (west, south, east, north)

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegInt = Annotated[int, Field(ge=0)]
NonNegFloat = Annotated[float, Field(ge=0.0)]


class FrozenModel(BaseModel):
    """Base for immutable value objects: frozen, unknown fields rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- evidence inputs


class UserFacts(FrozenModel):
    """Public facts about the changeset author; any field may be unknown."""

    uid: int | None = None
    display_name: str | None = None
    account_age_days: NonNegInt | None = None
    changesets_count: NonNegInt | None = None
    # 'edit_time': the count when the edit was made (changeset tag). 'current': the account's
    # total when fetched, which can only overstate the edit-time count (None on old snapshots:
    # treated as current).
    changesets_count_basis: Literal["edit_time", "current"] | None = None
    blocks_active: NonNegInt | None = None


class ChangesetMeta(FrozenModel):
    """Changeset metadata as returned by the OSM API (plus the attribution envelope)."""

    id: int
    uid: int | None = None
    user_display: str | None = None
    comment: str | None = None
    source: str | None = None
    created_by: str | None = None
    locale: str | None = None
    imagery_used: str | None = None
    review_requested: bool = False
    created_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    open: bool = False
    bbox: BBox | None = None
    bbox_wraps: bool = False
    comments_count: NonNegInt = 0
    changes_count: NonNegInt = 0
    # The author's changeset count when this edit was made, from the changeset's own
    # `changesets_count` tag (published by some editors only).
    changesets_count: NonNegInt | None = None
    attribution: dict[str, str] = Field(default_factory=dict)  # copyright, attribution, license


class GeometryChange(FrozenModel):
    """Coarse geometry delta of a modified element."""

    node_moved_m: float | None = None
    way_node_delta: int | None = None


class ChangedObject(FrozenModel):
    """One element touched by the changeset, with before (v-1) and after (v) tags."""

    osm_type: OsmType
    osm_id: int
    action: ChangeAction
    version_after: int
    version_before: int | None = None
    tags_before: Tags | None = None
    tags_after: Tags | None = None
    created_at_first_version: AwareDatetime | None = None
    created_by_uid: int | None = None  # uid that created the element (version 1); None if unknown
    age_days: NonNegInt | None = None
    geometry_change: GeometryChange | None = None
    source: EvidenceSource = EvidenceSource.OSM_API


class TagDiff(FrozenModel):
    """A single tag key difference between before and after versions of an element."""

    osm_type: OsmType
    osm_id: int
    key: str
    before: str | None = None
    after: str | None = None
    change: TagChange


class DiscussionEntry(FrozenModel):
    """A changeset discussion comment; `text` is raw here and sanitized at render time."""

    id: int
    author_display: str
    date: AwareDatetime
    text: str


class HistoryGap(FrozenModel):
    """An element whose prior version could not be reconstructed, with the reason."""

    osm_type: OsmType
    osm_id: int
    reason: CoverageGapReason


class Coverage(FrozenModel):
    """Honest record of what was and was not fetched; mandatory on every snapshot."""

    elements_in_changeset: NonNegInt
    elements_detailed: NonNegInt
    elements_skipped_budget: NonNegInt = 0
    history_gaps: list[HistoryGap] = Field(default_factory=list)
    user_profile: FetchStatus = FetchStatus.FETCHED
    discussion: FetchStatus = FetchStatus.FETCHED
    snapshot_truncated: bool = False
    score: Probability = 1.0


class EvidenceSnapshot(FrozenModel):
    """Immutable capture of everything fetched about a changeset at one time.

    `id` and `case_id` are None until persisted; rendering fields are filled by the evidence
    renderer via `model_copy(update=...)`.
    """

    id: UUID | None = None
    case_id: UUID | None = None
    evidence_version: str
    source: EvidenceSource
    fetched_at: AwareDatetime
    provisional: bool = False
    changeset: ChangesetMeta
    user: UserFacts | None = None
    coverage: Coverage
    elements: list[ChangedObject] = Field(default_factory=list)
    tag_diffs: list[TagDiff] = Field(default_factory=list)
    discussion: list[DiscussionEntry] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)  # stage-1 reason codes (adapters/osm/flags.py)
    element_counts: dict[ChangeAction, NonNegInt] = Field(default_factory=dict)
    rendered_text: str = ""
    rendered_tokens: NonNegInt = 0


# --------------------------------------------------------------------------- decision outputs


class PermutationResult(FrozenModel):
    """One Decider choice answer for one option order (e.g. `nature_p0`)."""

    name: str
    order: list[str]
    probabilities: dict[str, Probability]
    confidence: Probability


class AggregatedChoice(FrozenModel):
    """Mean over permutations of one question: probabilities, argmax and sharpness statistics."""

    probabilities: dict[str, Probability]
    argmax: str
    confidence_agg: Probability
    order_sensitivity: NonNegFloat


class DecisionOutputs(FrozenModel):
    """Raw per-permutation and aggregated Decider outputs for Q1 (nature) and Q2 (response)."""

    permutations: list[PermutationResult]
    nature: AggregatedChoice
    response: AggregatedChoice
    nouls: dict[str, Probability] = Field(default_factory=dict)  # evaluation probes, not rules


class RuleHit(FrozenModel):
    """A deterministic policy rule that fired, with the parsed evidence that triggered it."""

    code: str
    label: str
    severity: Severity
    triggered_by: dict[str, object] = Field(default_factory=dict)


class AnalysisResult(FrozenModel):
    """One immutable analysis run (Decider + policy gate) on one snapshot."""

    id: UUID | None = None
    snapshot_id: UUID | None = None
    config_version: str
    decider_model: str | None = None
    status: RunStatus
    failure_code: str | None = None  # e.g. decider_unavailable, state_too_long, schema
    lane: Lane
    band: Band | None = None
    nature: Nature | None = None
    response: Response | None = None
    nature_probabilities: dict[Nature, Probability] = Field(default_factory=dict)
    response_probabilities: dict[Response, Probability] = Field(default_factory=dict)
    reconciled: bool = False
    reconciled_from: Response | None = None
    order_sensitivity: NonNegFloat = 0.0
    rules_fired: list[RuleHit] = Field(default_factory=list)
    outputs: DecisionOutputs | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: AwareDatetime | None = None
    latency_ms: NonNegInt = 0


# --------------------------------------------------------------------------- human-facing records


class DraftValidation(FrozenModel):
    """Result of validating a draft against tone rules."""

    ok: bool
    violations: list[str] = Field(default_factory=list)


class Draft(FrozenModel):
    """An immutable comment candidate; a human always edits and posts it."""

    id: UUID | None = None
    run_id: UUID | None = None
    response_type: Response
    status: DraftStatus
    model_id: str | None = None
    greeting: str
    body: str
    closing: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    validation: DraftValidation
    config_version: str | None = None
    created_at: AwareDatetime | None = None


class OutcomeInput(FrozenModel):
    """What a reviewer submits when recording a decision."""

    disposition: Disposition
    response_type: Response | None = None
    final_text: str | None = None
    reason_code: str | None = None
    note: str | None = None
    run_id_seen: UUID
    # On a disagreement, the facts the reviewer found wrong, each with the answer they judge right.
    # Used only to refit probe thresholds (never changes a rule or a past run).
    probe_corrections: dict[str, Literal["yes", "no"]] | None = None


class HumanOutcome(OutcomeInput):
    """Append-only record of a reviewer decision; corrections are new rows."""

    id: UUID | None = None
    reviewer_display: str
    created_at: AwareDatetime | None = None


class Job(BaseModel):
    """A durable unit of background work; mutable because it walks a state machine."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    case_id: UUID
    kind: JobKind
    evidence_version: str | None = None
    status: JobStatus = JobStatus.QUEUED
    attempts: NonNegInt = 0
    max_attempts: NonNegInt = 3
    lease_expires_at: AwareDatetime | None = None
    error: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
