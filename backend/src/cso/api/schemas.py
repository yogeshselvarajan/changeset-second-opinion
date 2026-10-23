"""Request and response schemas of the v1 HTTP contract.

Domain models are reused where the contract shape is identical (Coverage, ChangedObject, TagDiff,
DiscussionEntry, RuleHit, OutcomeInput, DecisionReceipt, CommunityConfig). Confidence is always
shown as every option probability plus a backend band; no field carries a single percentage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cso.api.deps import Role
from cso.api.pagination import DEFAULT_LIMIT, MAX_CURSOR_LENGTH, MAX_LIMIT
from cso.api.problems import FieldError, Problem
from cso.domain.config import CommunityConfig, Option
from cso.domain.enums import (
    Band,
    CaseStatus,
    Disposition,
    DraftStatus,
    EvidenceSource,
    JobKind,
    JobStatus,
    Lane,
    Nature,
    Response,
    RunStatus,
)
from cso.domain.lanes import PanelComposition
from cso.domain.models import (
    ChangedObject,
    Coverage,
    DiscussionEntry,
    DraftValidation,
    NonNegInt,
    OutcomeInput,
    Probability,
    RuleHit,
    TagDiff,
)
from cso.domain.panel import (
    ADVISORY_PROBES,
    CROSS_CHECK_ONLY_PROBES,
    PANEL_LABELS,
    YES_MEANS,
    FactPanel,
    Tri,
)
from cso.domain.receipt import DecisionReceipt

__all__ = [
    "AnalysisAccepted",
    "AnalysisCurrent",
    "AnalysisRequest",
    "AnalysisRun",
    "Attribution",
    "AuditEvent",
    "AuditListQuery",
    "BandReliability",
    "CalibrateRequest",
    "CalibrationResult",
    "AuditListResponse",
    "CaseCreated",
    "CaseDetail",
    "CaseListQuery",
    "CaseListResponse",
    "CaseRunsResponse",
    "CaseSummary",
    "ChangedElement",
    "ChangedObject",
    "ChangesetDetail",
    "CommunityConfig",
    "ConfigDiff",
    "ConfigVersion",
    "ConfigVersionsResponse",
    "Coverage",
    "CreateCaseRequest",
    "DecisionListQuery",
    "DecisionListResponse",
    "DecisionReceipt",
    "DecisionRow",
    "DeciderHealth",
    "DiffItem",
    "DiscussionEntry",
    "Draft",
    "DraftAccepted",
    "DraftRequest",
    "ElementCounts",
    "EvidenceSnapshot",
    "EvidenceQuery",
    "FieldError",
    "HealthzResponse",
    "HumanOutcome",
    "ImportAccepted",
    "ImportRequest",
    "Job",
    "JobResultRef",
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "Option",
    "OutcomeInput",
    "PanelCompositionView",
    "PanelCrossCheck",
    "PanelNature",
    "PanelProbe",
    "PanelView",
    "PackActivated",
    "PackListResponse",
    "PackSummary",
    "Problem",
    "ProbeReliability",
    "PublicCoverage",
    "PublicDecider",
    "PublicProbe",
    "PublicReceipt",
    "PublicRule",
    "ReadyzResponse",
    "ReliabilityReport",
    "RuleHit",
    "RunSummary",
    "TagDiff",
    "UserSummary",
]

CHANGESET_ID_MAX = 9_999_999_999_999  # contract: ^\d{1,13}$
ChangesetId = Annotated[int, Field(ge=1, le=CHANGESET_ID_MAX)]
CursorParam = Annotated[str, Field(min_length=1, max_length=MAX_CURSOR_LENGTH)]
PageLimit = Annotated[int, Field(ge=1, le=MAX_LIMIT)]


class ApiModel(BaseModel):
    """Base for API bodies: unknown fields are rejected and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --------------------------------------------------------------------------- health, session


class HealthzResponse(ApiModel):
    """Process liveness."""

    status: Literal["ok"]


class DeciderHealth(ApiModel):
    """State of the model server as last checked (cached for 10 s)."""

    ok: bool
    model: str | None = None
    checkpoint: str | None = None
    device: str | None = None


class ReadyzResponse(ApiModel):
    """Readiness of the database and the model server."""

    db: bool
    decider: DeciderHealth


class LoginRequest(ApiModel):
    """Invite-code login for a reviewer session."""

    invite_code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class MeResponse(ApiModel):
    """Identity of the caller and the runtime mode."""

    id: str
    display_name: str | None = None
    role: Role
    mode: Literal["replay", "live"]
    # True when the server is set up for "Sign in with OpenStreetMap" (the login screen shows the
    # button only then). `via_osm` says this session came from that sign-in.
    osm_signin: bool = False
    via_osm: bool = False
    # True for an OpenStreetMap sign-in on a workspace nobody has claimed yet: the app offers
    # "claim this workspace" (POST /workspace/claim) and the caller becomes its admin.
    can_claim: bool = False


class LoginResponse(ApiModel):
    """Result of a login; the session itself travels in the `cso_session` cookie."""

    me: MeResponse


# --------------------------------------------------------------------------- shared shapes


class ElementCounts(ApiModel):
    """Elements created, modified and deleted by the changeset."""

    create: NonNegInt = 0
    modify: NonNegInt = 0
    delete: NonNegInt = 0


class UserSummary(ApiModel):
    """Public facts about the changeset author; any value may be unknown."""

    display_name: str | None = None
    account_age_days: NonNegInt | None = None
    changesets_count: NonNegInt | None = None
    changesets_count_basis: Literal["edit_time", "current"] | None = Field(
        default=None,
        description=(
            "edit_time: the author's changeset count when the edit was made; current: the "
            "account's total now, which can only overstate the count at edit time"
        ),
    )
    blocks_active: NonNegInt | None = None


class Attribution(ApiModel):
    """OpenStreetMap attribution passed through from the API envelope."""

    copyright: str | None = None
    attribution: str | None = None
    license: str | None = None


class ChangesetDetail(ApiModel):
    """Changeset facts shown on the case page; free text is sanitized before it is rendered."""

    id: int
    comment: str | None = None
    source: str | None = None
    created_by: str | None = None
    locale: str | None = None
    review_requested: bool = False
    user: UserSummary | None = None
    created_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    open: bool = False
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="west, south, east, north"
    )
    bbox_wraps: bool = False


# --------------------------------------------------------------------------- fact panel (ADR-009)

PanelCrossCheck = Literal["agree", "disagree", "undecided", "n/a"]


class PanelProbe(ApiModel):
    """One yes/no fact the Decider was asked, with its probability and a three-way reading."""

    id: str
    label: str = Field(description="Plain-language statement of the fact that was asked")
    probability: Probability
    reading: Tri = Field(description="no below the low threshold, yes above the high, else unknown")
    yes_means: Literal["concern", "reassurance"] = Field(
        description="Whether a yes raises or lowers the level of review suggested"
    )
    use: Literal["composed", "cross_check_only", "advisory"] = Field(
        description="composed: feeds the suggestion; cross_check_only and advisory are shown only"
    )


class PanelNature(ApiModel):
    """The four-way reading the model also gives; shown for audit and never used for lanes."""

    advisory: Literal[True] = True
    probabilities: dict[Nature, Probability] = Field(
        description="Every option with its probability; no single figure is shown"
    )
    choice: Nature


class PanelCompositionView(ApiModel):
    """Which table rows produced the suggested response and reading."""

    response_row: str
    nature_row: str
    yes: list[str] = Field(default_factory=list, description="Probe ids read as yes")
    unknown: list[str] = Field(default_factory=list, description="Probe ids read as unknown")


class PanelView(ApiModel):
    """The fact panel as reviewers see it: every probe reading, the table rows and cross-checks."""

    low: Probability
    high: Probability
    probes: list[PanelProbe]
    composition: PanelCompositionView | None = None
    cross_checks: dict[str, PanelCrossCheck] = Field(
        default_factory=dict,
        description="Panel reading compared with the value computed from parsed evidence",
    )
    advisory_nature: PanelNature

    @classmethod
    def from_domain(
        cls,
        panel: FactPanel,
        composition: PanelComposition | None = None,
        cross_checks: Mapping[str, str] | None = None,
    ) -> PanelView:
        """Build the view from a domain panel, the composition that fired and the cross-checks."""
        probes = [
            PanelProbe(
                id=i,
                label=PANEL_LABELS[i],
                probability=panel.readings[i].probability,
                reading=panel.readings[i].state,
                yes_means=YES_MEANS[i],
                use=(
                    "advisory"
                    if i in ADVISORY_PROBES
                    else "cross_check_only"
                    if i in CROSS_CHECK_ONLY_PROBES
                    else "composed"
                ),
            )
            for i in panel.ids
        ]
        nature = panel.advisory_nature
        return cls(
            low=panel.low,
            high=panel.high,
            probes=probes,
            composition=(
                None
                if composition is None
                else PanelCompositionView(
                    response_row=composition.response_row,
                    nature_row=composition.nature_row,
                    yes=list(composition.yes),
                    unknown=list(composition.unknown),
                )
            ),
            cross_checks={k: v for k, v in (cross_checks or {}).items()},  # type: ignore[misc]
            advisory_nature=PanelNature(
                probabilities={Nature(k): v for k, v in nature.probabilities.items()},
                choice=Nature(nature.choice),
            ),
        )


# --------------------------------------------------------------------------- runs and drafts


class RunSummary(ApiModel):
    """One analysis run: lane, band and every option probability (never a single percentage)."""

    id: UUID
    snapshot_id: UUID
    config_version: str
    decider_model: str | None = None
    status: RunStatus
    failure_code: str | None = Field(
        default=None, description="Reason code when the run failed, for example decider_unavailable"
    )
    lane: Lane
    band: Band | None = None
    nature: Nature | None = None
    response: Response | None = None
    nature_probabilities: dict[Nature, Probability] = Field(default_factory=dict)
    response_probabilities: dict[Response, Probability] = Field(default_factory=dict)
    reconciled: bool = False
    order_sensitivity: float = Field(default=0.0, ge=0.0)
    rules_fired: list[RuleHit] = Field(default_factory=list)
    panel: PanelView | None = Field(
        default=None, description="Fact panel readings; absent for runs made before the panel"
    )
    created_at: AwareDatetime
    latency_ms: NonNegInt = 0


class AnalysisRun(RunSummary):
    """A run together with its decision receipt."""

    receipt: DecisionReceipt


class Draft(ApiModel):
    """A comment candidate with its validation result; a person edits and posts it."""

    id: UUID
    run_id: UUID
    response_type: Response
    status: DraftStatus
    model_id: str | None = None
    greeting: str
    body: str
    closing: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    validation: DraftValidation
    created_at: AwareDatetime


class HumanOutcome(OutcomeInput):
    """A stored reviewer decision (append-only; a correction is a new record)."""

    id: UUID
    reviewer_display: str
    created_at: AwareDatetime


# --------------------------------------------------------------------------- cases


class CaseSummary(ApiModel):
    """One row of the queue."""

    id: UUID
    changeset_id: int
    lane: Lane
    band: Band | None = None
    nature: Nature | None = None
    response: Response | None = None
    editor: str | None = None
    place_label: str | None = None
    comment: str | None = Field(
        default=None, description="The mapper's own changeset comment (untrusted text)"
    )
    element_counts: ElementCounts
    flags: list[str] = Field(
        default_factory=list, description="OSMCha reason codes and policy rule codes"
    )
    coverage_score: Probability
    stale: bool
    status: CaseStatus
    latest_outcome: Disposition | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CaseDetail(CaseSummary):
    """Everything the case page needs; evidence comes from the evidence endpoint."""

    changeset: ChangesetDetail | None = Field(
        default=None, description="Empty until the first evidence snapshot exists"
    )
    latest_snapshot_id: UUID | None = None
    latest_run: RunSummary | None = None
    latest_draft: Draft | None = None
    outcome_version: NonNegInt = Field(
        default=0, description='Send as If-Match: W/"<outcome_version>" when recording an outcome'
    )
    latest_outcome_detail: HumanOutcome | None = None
    attribution: Attribution = Field(default_factory=Attribution)
    allowed_responses: list[Response] = Field(
        default_factory=list,
        description=(
            "Response types a draft may be requested for, from the latest analysis. Empty when "
            "there is no analysis, it failed, or the case changed since it ran (stale)."
        ),
    )


class ChangedElement(ChangedObject):
    """A changed object as the API returns it: the stored facts plus its evidence id."""

    evidence_id: str | None = Field(
        default=None,
        pattern=r"^E[1-9][0-9]*$",
        description=(
            "Id of this object in the evidence text the decision and drafts were written from "
            "(E1, E2, ...), following the order of that text. Null when the object is not shown "
            "there. Drafts cite these ids."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_domain_object(cls, value: object) -> object:
        """A stored `ChangedObject` becomes an element with no id (the mapper sets ids)."""
        if isinstance(value, ChangedObject) and not isinstance(value, ChangedElement):
            return value.model_dump()
        return value


class EvidenceSnapshot(ApiModel):
    """Everything fetched about the changeset at one time, with the coverage record."""

    id: UUID
    case_id: UUID
    evidence_version: str
    source: EvidenceSource
    fetched_at: AwareDatetime
    provisional: bool = False
    coverage: Coverage
    elements: list[ChangedElement] = Field(default_factory=list)
    tag_diffs: list[TagDiff] = Field(default_factory=list)
    discussion: list[DiscussionEntry] = Field(default_factory=list)
    rendered_text: str = ""
    rendered_tokens: NonNegInt = 0


class CreateCaseRequest(ApiModel):
    """Create a case for a changeset id and queue its analysis."""

    changeset_id: ChangesetId
    source: Literal["manual", "maproulette", "osmcha"] = "manual"


class CaseCreated(ApiModel):
    """Result of creating a case: 201 when new, 200 when it already existed."""

    case: CaseDetail
    job_id: UUID | None = Field(
        default=None, description="Analysis job; empty when the case already had a current run"
    )


class ImportRequest(ApiModel):
    """Bulk create from MapRoulette or OSMCha, by explicit ids or by challenge."""

    source: Literal["maproulette", "osmcha"]
    ids: list[ChangesetId] | None = Field(default=None, max_length=MAX_LIMIT)
    challenge_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=MAX_LIMIT, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def _needs_a_selector(self) -> ImportRequest:
        if not self.ids and self.challenge_id is None:
            raise ValueError("send ids or challenge_id")
        return self


class ImportAccepted(ApiModel):
    """Counts of cases created and already present, and the analysis jobs queued."""

    created: NonNegInt
    existing: NonNegInt
    job_ids: list[UUID] = Field(default_factory=list)


class AnalysisRequest(ApiModel):
    """Request a fresh analysis; `force` re-runs even when the evidence is unchanged."""

    force: bool = False


class AnalysisAccepted(ApiModel):
    """202: the analysis job was queued."""

    job_id: UUID


class AnalysisCurrent(ApiModel):
    """200: the latest run is current and `force` was not set."""

    run_id: UUID


class DraftRequest(ApiModel):
    """Request a draft comment for a response type the latest run allows."""

    response_type: Response
    regenerate: bool = False


class DraftAccepted(ApiModel):
    """202: the draft job was queued."""

    job_id: UUID


class CaseRunsResponse(ApiModel):
    """All runs of a case, newest first."""

    items: list[RunSummary]


# --------------------------------------------------------------------------- jobs


class JobResultRef(ApiModel):
    """What a succeeded job produced."""

    run_id: UUID | None = None
    draft_id: UUID | None = None


class Job(ApiModel):
    """Status of a durable background job; poll about every 2 seconds."""

    id: UUID
    kind: JobKind
    status: JobStatus
    step: Literal["fetch_evidence", "snapshot", "decide", "persist", "draft"] | None = None
    attempts: NonNegInt = 0
    error: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    result_ref: JobResultRef | None = None


# --------------------------------------------------------------------------- audit, decisions


class AuditEvent(ApiModel):
    """One audit record; events are never edited."""

    id: int = Field(ge=1, description="Monotonic integer; also the position of the audit cursor")
    actor: str
    action: str
    payload: dict[str, object] = Field(default_factory=dict)
    request_id: str | None = None
    created_at: AwareDatetime


class AuditListResponse(ApiModel):
    """Audit events of a case."""

    items: list[AuditEvent]
    next_cursor: str | None = None


class DecisionRow(ApiModel):
    """A recorded outcome with the lane and band the reviewer saw."""

    outcome_id: UUID
    case_id: UUID
    changeset_id: int
    disposition: Disposition
    response_type: Response | None = None
    lane_at_decision: Lane
    band_at_decision: Band | None = None
    reviewer_display: str
    created_at: AwareDatetime
    config_version: str
    decider_model: str | None = None


class DecisionListResponse(ApiModel):
    """Outcome history across cases."""

    items: list[DecisionRow]
    next_cursor: str | None = None


class CaseListResponse(ApiModel):
    """A page of the queue plus the size of every lane under the current filters."""

    items: list[CaseSummary]
    next_cursor: str | None = None
    counts_by_lane: dict[Lane, NonNegInt] = Field(default_factory=dict)


# --------------------------------------------------------------------------- config


class ConfigVersion(ApiModel):
    """One stored community configuration version."""

    version: str
    created_at: AwareDatetime
    sha: str


class ConfigVersionsResponse(ApiModel):
    """Known configuration versions."""

    items: list[ConfigVersion]


# --------------------------------------------------------------------------- query parameters


class _PageQuery(ApiModel):
    cursor: CursorParam | None = None
    limit: PageLimit = DEFAULT_LIMIT


class CaseListQuery(_PageQuery):
    """Filters of `GET /cases`; the order is fixed by `(lane_rank, created_at desc)`."""

    lane: Lane | None = None
    status: CaseStatus | None = None
    editor: str | None = Field(default=None, max_length=200)
    q: str | None = Field(default=None, max_length=200)
    stale: bool | None = None


class EvidenceQuery(ApiModel):
    """Optional snapshot selector of `GET /cases/{id}/evidence`."""

    snapshot_id: UUID | None = None


class AuditListQuery(ApiModel):
    """Cursor of `GET /cases/{id}/audit`."""

    cursor: CursorParam | None = None
    limit: PageLimit = DEFAULT_LIMIT


class DecisionListQuery(_PageQuery):
    """Filters of `GET /decisions` and `GET /decisions/export.csv` (`from` and `to` are dates)."""

    reviewer: str | None = Field(default=None, max_length=80)
    disposition: Disposition | None = None
    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None


# --------------------------------------------------------------------------- community packs


class PackSummary(ApiModel):
    """One community pack in the list."""

    id: str
    title: str
    description: str
    author: str
    version: str = Field(description="The pack's own version label, for people")
    config_version: str = Field(description="Content hash of the pack file, as the runs name it")
    is_active: bool


class PackListResponse(ApiModel):
    """Every pack the server can offer, with the active one marked."""

    items: list[PackSummary]


class PackActivated(ApiModel):
    """The pack that is active after an activation, and the configuration version it created."""

    pack: PackSummary
    config_version: str


DiffArea = Literal["rules", "thresholds", "bands", "composition", "tone", "options"]


class DiffItem(ApiModel):
    """One setting that differs between two packs. Values are shown as text."""

    area: DiffArea
    key: str = Field(description="For example R1.min_age_days or panel.thresholds.low")
    a: str | None = Field(default=None, description="Value in pack a; absent when a has none")
    b: str | None = Field(default=None, description="Value in pack b; absent when b has none")


class ConfigDiff(ApiModel):
    """What differs between two packs. Swapping a and b swaps the values and nothing else."""

    a: str
    b: str
    changes: list[DiffItem]


# --------------------------------------------------------------------------- calibration


class ProbeReliability(ApiModel):
    """How one fact probe fared against the reviewers' outcomes, and the cut points it would get."""

    probe: str
    label: str
    n: NonNegInt = Field(description="Labelled readings for this probe")
    status: Literal["fitted", "kept_default", "insufficient_data"]
    default_low: Probability
    default_high: Probability
    low: Probability
    high: Probability
    correct: NonNegInt = Field(description="Decided readings that were right at the default cuts")
    decided: NonNegInt
    lower: float
    upper: float
    tuned_correct: NonNegInt
    tuned_decided: NonNegInt
    tuned_lower: float
    tuned_upper: float
    coverage: float | None = None


class BandReliability(ApiModel):
    """How often the readings behind runs of one band were right (a report; cut-offs never move)."""

    band: Band
    n: NonNegInt
    correct: NonNegInt
    decided: NonNegInt
    lower: float
    upper: float
    status: Literal["reported", "insufficient_data"]


class ReliabilityReport(ApiModel):
    """What the recorded outcomes say about a pack's cut points. Reading it changes nothing."""

    pack_id: str
    n_outcomes: NonNegInt = Field(description="Cases whose newest decision was counted")
    n_labelled_outcomes: NonNegInt
    min_labels: NonNegInt = Field(description="Labelled readings a probe needs before it is tuned")
    probes: list[ProbeReliability]
    bands: list[BandReliability]
    synthetic_outcomes: NonNegInt = Field(
        default=0, description="Counted decisions that are synthetic demo data"
    )


class CalibrateRequest(ApiModel):
    """Body of `POST /config/calibrate`: which pack, and whether to apply the result."""

    pack_id: str | None = Field(default=None, max_length=40)
    apply: bool = False


class CalibrationResult(ReliabilityReport):
    """The report, and what applying did (nothing when `applied` is false)."""

    applied: bool
    calibration_id: str | None = None
    config_version: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- public receipt


class PublicProbe(ApiModel):
    """One fact the Decider was asked, with its probability and reading (public receipt)."""

    code: str
    label: str
    probability: Probability
    reading: Tri


class PublicRule(ApiModel):
    """A rule that fired. Only the code, label and severity: never what triggered it."""

    code: str
    label: str
    severity: Literal["info", "warn", "block"]


class PublicCoverage(ApiModel):
    """How much of the changeset the evidence covered."""

    score: float | None = None
    elements_in_changeset: NonNegInt = 0
    elements_detailed: NonNegInt = 0
    history_gaps_count: NonNegInt = 0


class PublicDecider(ApiModel):
    """Which model answered."""

    model: str | None = None
    checkpoint: str | None = None


class PublicReceipt(ApiModel):
    """A decision receipt anyone may read: public OpenStreetMap facts and the tool's own readings.

    It never carries a reviewer name, a session, an outcome, a draft or the evidence text, so a
    link to it can be shared without sharing anything about the person who made it.
    """

    run_id: UUID
    changeset_id: ChangesetId
    created_at: AwareDatetime
    config_version: str
    pack_id: str | None = Field(default=None, description="Community pack the run used, if known")
    calibration_version: str | None = Field(
        default=None, description="Calibration applied to the thresholds, if any"
    )
    decider: PublicDecider | None = None
    lane: Lane
    band: Band | None = None
    nature: Nature | None = None
    response: Response | None = None
    probes: list[PublicProbe] = Field(default_factory=list)
    rules_fired: list[PublicRule] = Field(default_factory=list)
    coverage: PublicCoverage
    attribution: Attribution


# --------------------------------------------------------------------------- workspace, invites


class WorkspaceSettings(ApiModel):
    """The workspace as an admin sees it. `version` goes back as `If-Match` when saving."""

    name: str
    tagline: str
    accent_hex: str = Field(description="Accent on the light canvas (4.5:1 or better)")
    accent_dark_hex: str = Field(description="The same accent lightened for the dark canvas")
    logo_svg: str | None = None
    community_paragraph: str
    active_pack: str | None = Field(
        default=None, description="The pack in force; changed on Config"
    )
    calibration_version: str | None = None
    osm_signin_enabled: bool
    osm_signin_configured: bool = Field(
        description="True when the server holds the OpenStreetMap application settings"
    )
    version: int
    updated_at: AwareDatetime
    accent_contrast_light: float
    accent_contrast_dark: float


class WorkspaceUpdate(ApiModel):
    """The editable settings. Every field is sent; `logo_svg: null` removes the logo."""

    name: str
    tagline: str
    accent_hex: str
    community_paragraph: str
    logo_svg: str | None = None
    osm_signin_enabled: bool = True


class PublicBranding(ApiModel):
    """What a visitor may see: no account needed, cached for five minutes."""

    name: str
    tagline: str
    accent_hex: str
    accent_dark_hex: str
    has_logo: bool
    community_paragraph: str
    osm_signin_enabled: bool


InviteStatus = Literal["active", "expired", "revoked", "spent"]


class InviteOut(ApiModel):
    """An invite code as listed. The code itself is shown once, when it is made."""

    id: UUID
    label: str
    role: Role
    created_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None
    status: InviteStatus
    use_count: int
    max_uses: int | None = None
    created_by: str | None = None


class InviteCreate(ApiModel):
    """A new invite code."""

    role: Role = Role.REVIEWER
    label: str = Field(default="", max_length=80)
    ttl_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    max_uses: int | None = Field(default=None, ge=1, le=10_000)


class InviteCreated(ApiModel):
    """The new invite and its code, which is not stored and cannot be shown again."""

    code: str
    invite: InviteOut


class InviteList(ApiModel):
    """All invites, newest first."""

    items: list[InviteOut]
