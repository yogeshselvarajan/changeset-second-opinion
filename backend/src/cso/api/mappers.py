"""Stored rows and domain objects -> the shapes of the v1 API contract.

Free text that came from mapper-written OpenStreetMap fields is sanitized here (control and
bidirectional characters removed, links defanged, length capped), because it is untrusted data.
Tag values inside elements are returned as stored; the client escapes them when rendering.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError

from cso.api.pagination import Cursor
from cso.api.schemas import (
    AnalysisRun,
    Attribution,
    AuditEvent,
    CaseDetail,
    CaseSummary,
    ChangedElement,
    ChangesetDetail,
    DecisionRow,
    DiscussionEntry,
    Draft,
    ElementCounts,
    EvidenceSnapshot,
    HumanOutcome,
    Job,
    JobResultRef,
    PanelCompositionView,
    PanelView,
    PublicCoverage,
    PublicDecider,
    PublicProbe,
    PublicReceipt,
    PublicRule,
    RunSummary,
    UserSummary,
)
from cso.domain.config import CommunityConfig as DomainConfig
from cso.domain.enums import (
    Band,
    CaseStatus,
    Disposition,
    JobKind,
    JobStatus,
    Lane,
    Nature,
    OsmType,
    Response,
    RunStatus,
)
from cso.domain.evidence import render
from cso.domain.lanes import allowed_comment_types
from cso.domain.models import Draft as DomainDraft
from cso.domain.models import EvidenceSnapshot as DomainSnapshot
from cso.domain.models import HumanOutcome as DomainOutcome
from cso.domain.models import RuleHit
from cso.domain.panel import FactPanel
from cso.domain.receipt import DecisionReceipt
from cso.domain.sanitize import sanitize
from cso.persistence.repos._common import KeysetCursor
from cso.persistence.repos.outcomes_repo import DecisionRecord
from cso.persistence.repos.runs_repo import run_to_model
from cso.persistence.tables import AnalysisRunRow, AuditEventRow, JobRow, ReviewCaseRow

log = structlog.get_logger()

JOB_STEPS = frozenset({"fetch_evidence", "snapshot", "decide", "persist", "draft"})


def clean(text: str | None, max_len: int = 200) -> str | None:
    """Sanitized copy of untrusted text; None stays None."""
    if text is None:
        return None
    return sanitize(text, max_len=max_len).text


# --------------------------------------------------------------------------- cursors


def to_keyset(cursor: Cursor) -> KeysetCursor:
    """API cursor -> repository cursor."""
    return KeysetCursor(created_at=cursor.created_at, id=cursor.id, rank=cursor.rank)


def from_keyset(cursor: KeysetCursor) -> Cursor:
    """Repository cursor -> API cursor."""
    return Cursor(created_at=cursor.created_at, id=cursor.id, rank=cursor.rank)


def audit_cursor(row: AuditEventRow) -> Cursor:
    """Cursor after an audit event: the integer id travels in `rank`."""
    return Cursor(created_at=row.created_at, id=UUID(int=row.id), rank=row.id)


# --------------------------------------------------------------------------- cases


def merge_flags(flags: Sequence[Any], rule_codes: Sequence[str]) -> list[str]:
    """Stage-1 reason codes followed by policy rule codes, without duplicates."""
    seen: set[str] = set()
    merged: list[str] = []
    for item in (*flags, *rule_codes):
        text = str(item)
        if text not in seen:
            seen.add(text)
            merged.append(text)
    return merged


def case_summary(row: ReviewCaseRow, rule_codes: Sequence[str] = ()) -> CaseSummary:
    """One queue row."""
    return CaseSummary(
        id=row.id,
        changeset_id=row.changeset_id,
        lane=Lane(row.lane),
        band=Band(row.band) if row.band else None,
        nature=Nature(row.nature) if row.nature else None,
        response=Response(row.response) if row.response else None,
        editor=clean(row.editor),
        place_label=clean(row.place_label),
        comment=clean(row.comment),
        element_counts=ElementCounts(
            create=row.element_create, modify=row.element_modify, delete=row.element_delete
        ),
        flags=merge_flags(row.flags or [], rule_codes),
        coverage_score=row.coverage_score,
        stale=row.stale,
        status=CaseStatus(row.status),
        latest_outcome=Disposition(row.latest_outcome) if row.latest_outcome else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def changeset_detail(snapshot: DomainSnapshot | None) -> ChangesetDetail | None:
    """Changeset facts from the latest snapshot; None before the first snapshot exists."""
    if snapshot is None:
        return None
    meta, user = snapshot.changeset, snapshot.user
    return ChangesetDetail(
        id=meta.id,
        comment=clean(meta.comment, 1000),
        source=clean(meta.source, 300),
        created_by=clean(meta.created_by),
        locale=clean(meta.locale, 40),
        review_requested=meta.review_requested,
        user=None
        if user is None
        else UserSummary(
            display_name=clean(user.display_name),
            account_age_days=user.account_age_days,
            changesets_count=user.changesets_count,
            changesets_count_basis=user.changesets_count_basis,
            blocks_active=user.blocks_active,
        ),
        created_at=meta.created_at,
        closed_at=meta.closed_at,
        open=meta.open,
        bbox=meta.bbox,
        bbox_wraps=meta.bbox_wraps,
    )


def attribution_of(snapshot: DomainSnapshot | None) -> Attribution:
    """OSM attribution passed through from the API envelope."""
    raw = {} if snapshot is None else snapshot.changeset.attribution
    return Attribution(
        copyright=raw.get("copyright"),
        attribution=raw.get("attribution"),
        license=raw.get("license"),
    )


def draftable_responses(row: ReviewCaseRow, run: AnalysisRunRow | None) -> list[Response]:
    """Response types a draft may be requested for: the one rule behind the case page's draft
    action and `POST /cases/{id}/drafts`.

    Empty when there is no analysis, it failed, or the case is stale (the evidence changed after
    the analysis ran, so a draft would describe an old decision). Otherwise it is the comment
    types that `lanes.allowed_comment_types` allows for the stored run.
    """
    if run is None or row.stale:
        return []
    return sorted(allowed_comment_types(run_to_model(run)), key=lambda r: r.value)


def case_detail(
    row: ReviewCaseRow,
    *,
    snapshot: DomainSnapshot | None,
    run: AnalysisRunRow | None,
    draft: DomainDraft | None,
    outcome: DomainOutcome | None,
) -> CaseDetail:
    """Case page: queue facts plus changeset, latest run, draft and outcome."""
    codes = [] if run is None else rule_codes_of(run)
    summary = case_summary(row, codes)
    return CaseDetail.model_validate(
        {
            **summary.model_dump(),
            "changeset": changeset_detail(snapshot),
            "latest_snapshot_id": row.latest_snapshot_id,
            "latest_run": None if run is None else run_summary(run),
            "latest_draft": None if draft is None else draft_out(draft),
            "outcome_version": row.outcome_version,
            "latest_outcome_detail": None if outcome is None else outcome_out(outcome),
            "attribution": attribution_of(snapshot),
            "allowed_responses": draftable_responses(row, run),
        }
    )


# --------------------------------------------------------------------------- evidence


def evidence_ids_of(
    snapshot: DomainSnapshot, config: DomainConfig
) -> dict[tuple[OsmType, int], str]:
    """`E<n>` id of each object shown in the compact evidence text (the text decisions and drafts
    were written from), keyed by object. Objects the text omits have no id.

    Rendering is deterministic, so this is recomputed on every read instead of being stored.
    """
    rendered = render(snapshot, config, profile="compact")
    return {key: eid for eid, key in rendered.element_ids_rendered.items()}


def evidence_out(
    snapshot: DomainSnapshot,
    evidence_ids: Mapping[tuple[OsmType, int], str] | None = None,
) -> EvidenceSnapshot:
    """The stored evidence; discussion text is sanitized as the contract says.

    `evidence_ids` (from `evidence_ids_of`) sets each element's `evidence_id`; without it every
    element's id is null.
    """
    if snapshot.id is None or snapshot.case_id is None:
        raise ValueError("a stored snapshot has an id and a case id")
    return EvidenceSnapshot(
        id=snapshot.id,
        case_id=snapshot.case_id,
        evidence_version=snapshot.evidence_version,
        source=snapshot.source,
        fetched_at=snapshot.fetched_at,
        provisional=snapshot.provisional,
        coverage=snapshot.coverage,
        elements=[
            ChangedElement.model_validate(
                {
                    **element.model_dump(),
                    "evidence_id": (evidence_ids or {}).get((element.osm_type, element.osm_id)),
                }
            )
            for element in snapshot.elements
        ],
        tag_diffs=list(snapshot.tag_diffs),
        discussion=[
            DiscussionEntry(
                id=entry.id,
                author_display=clean(entry.author_display) or "",
                date=entry.date,
                text=clean(entry.text, 2000) or "",
            )
            for entry in snapshot.discussion
        ],
        rendered_text=snapshot.rendered_text,
        rendered_tokens=snapshot.rendered_tokens,
    )


# --------------------------------------------------------------------------- runs


def rule_codes_of(row: AnalysisRunRow) -> list[str]:
    """Policy rule codes fired in a run."""
    return [
        str(hit["code"]) for hit in row.rules_fired or [] if isinstance(hit, dict) and "code" in hit
    ]


def panel_view(receipt: dict[str, Any] | None) -> PanelView | None:
    """The fact panel from a stored receipt; None for runs made before the panel or a bad record."""
    if not receipt or not receipt.get("panel"):
        return None
    try:
        panel = FactPanel.model_validate(receipt["panel"])
        view = PanelView.from_domain(panel, None, receipt.get("panel_cross_checks") or {})
        composition = receipt.get("panel_composition")
        if composition:
            view = view.model_copy(
                update={
                    "composition": PanelCompositionView(
                        response_row=str(composition["response_row"]),
                        nature_row=str(composition["nature_row"]),
                        yes=[str(i) for i in composition.get("yes", [])],
                        unknown=[str(i) for i in composition.get("unknown", [])],
                    )
                }
            )
        return view
    except (ValidationError, KeyError, ValueError) as exc:
        log.warning("api.panel_view_unreadable", error=str(exc)[:200])
        return None


def run_summary(row: AnalysisRunRow) -> RunSummary:
    """One run as reviewers see it."""
    return RunSummary(
        id=row.id,
        snapshot_id=row.snapshot_id,
        config_version=row.config_version,
        decider_model=row.decider_model,
        status=RunStatus(row.status),
        failure_code=row.failure_reason,
        lane=Lane(row.lane),
        band=Band(row.band) if row.band else None,
        nature=Nature(row.nature) if row.nature else None,
        response=Response(row.response) if row.response else None,
        nature_probabilities={Nature(k): v for k, v in (row.nature_probabilities or {}).items()},
        response_probabilities={
            Response(k): v for k, v in (row.response_probabilities or {}).items()
        },
        reconciled=row.reconciled,
        order_sensitivity=row.order_sensitivity,
        rules_fired=[RuleHit.model_validate(hit) for hit in row.rules_fired or []],
        panel=panel_view(row.receipt),
        created_at=row.created_at,
        latency_ms=row.latency_ms,
    )


def analysis_run(row: AnalysisRunRow) -> AnalysisRun | None:
    """A run with its receipt; None when the row has no receipt."""
    if not row.receipt:
        return None
    receipt = DecisionReceipt.model_validate(row.receipt)
    return AnalysisRun.model_validate({**run_summary(row).model_dump(), "receipt": receipt})


# --------------------------------------------------------------------------- public receipt

PUBLIC_ATTRIBUTION = Attribution(
    copyright="OpenStreetMap contributors",
    attribution="https://www.openstreetmap.org/copyright",
    license="Open Database License 1.0",
)


def public_receipt(
    row: AnalysisRunRow,
    changeset_id: int,
    pack_id: str | None = None,
    calibration_version: str | None = None,
) -> PublicReceipt | None:
    """The shareable form of a run: facts about the changeset and the tool's readings, nothing else.

    Built from an allow-list of fields, so a field added to the run later is not public until it
    is listed here. None when the run has no stored receipt.
    """
    if not row.receipt:
        return None
    run = run_summary(row)
    receipt = DecisionReceipt.model_validate(row.receipt)
    coverage = receipt.coverage or {}
    gaps = coverage.get("history_gaps")
    decider = receipt.decider
    return PublicReceipt(
        run_id=run.id,
        changeset_id=changeset_id,
        created_at=run.created_at,
        config_version=run.config_version,
        pack_id=pack_id,
        calibration_version=calibration_version,
        decider=None
        if decider is None
        else PublicDecider(model=decider.model, checkpoint=decider.checkpoint),
        lane=run.lane,
        band=run.band,
        nature=run.nature,
        response=run.response,
        probes=[
            PublicProbe(
                code=probe.id,
                label=probe.label,
                probability=probe.probability,
                reading=probe.reading,
            )
            for probe in (run.panel.probes if run.panel else [])
        ],
        rules_fired=[
            PublicRule(code=hit.code, label=hit.label, severity=hit.severity.value)
            for hit in run.rules_fired
        ],
        coverage=PublicCoverage(
            score=coverage.get("score"),
            elements_in_changeset=int(coverage.get("elements_in_changeset") or 0),
            elements_detailed=int(coverage.get("elements_detailed") or 0),
            history_gaps_count=len(gaps) if isinstance(gaps, list) else 0,
        ),
        attribution=PUBLIC_ATTRIBUTION,
    )


# --------------------------------------------------------------------------- drafts, outcomes


def draft_out(draft: DomainDraft) -> Draft:
    """A stored draft."""
    if draft.id is None or draft.run_id is None or draft.created_at is None:
        raise ValueError("a stored draft has an id, a run id and a timestamp")
    return Draft(
        id=draft.id,
        run_id=draft.run_id,
        response_type=draft.response_type,
        status=draft.status,
        model_id=draft.model_id,
        greeting=draft.greeting,
        body=draft.body,
        closing=draft.closing,
        cited_evidence_ids=list(draft.cited_evidence_ids),
        validation=draft.validation,
        created_at=draft.created_at,
    )


def outcome_out(outcome: DomainOutcome) -> HumanOutcome:
    """A stored reviewer decision."""
    if outcome.id is None or outcome.created_at is None:
        raise ValueError("a stored outcome has an id and a timestamp")
    return HumanOutcome(
        id=outcome.id,
        reviewer_display=outcome.reviewer_display,
        created_at=outcome.created_at,
        disposition=outcome.disposition,
        response_type=outcome.response_type,
        final_text=outcome.final_text,
        reason_code=outcome.reason_code,
        note=outcome.note,
        run_id_seen=outcome.run_id_seen,
    )


# --------------------------------------------------------------------------- jobs, audit, decisions


def job_out(row: JobRow) -> Job:
    """A job as clients poll it."""
    ref = row.result_ref or {}
    result = (
        JobResultRef(run_id=ref.get("run_id"), draft_id=ref.get("draft_id"))
        if ref.get("run_id") or ref.get("draft_id")
        else None
    )
    return Job.model_validate(
        {
            "id": row.id,
            "kind": JobKind(row.kind),
            "status": JobStatus(row.status),
            "step": row.step if row.step in JOB_STEPS else None,
            "attempts": row.attempts,
            "error": row.last_error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "result_ref": result,
        }
    )


def audit_out(row: AuditEventRow) -> AuditEvent:
    """One audit event."""
    return AuditEvent(
        id=row.id,
        actor=row.actor,
        action=row.action,
        payload=dict(row.payload or {}),
        request_id=row.request_id,
        created_at=row.created_at,
    )


def decision_row(record: DecisionRecord) -> DecisionRow:
    """One row of the decision history."""
    outcome = record.outcome
    if outcome.id is None or outcome.created_at is None:
        raise ValueError("a stored outcome has an id and a timestamp")
    return DecisionRow(
        outcome_id=outcome.id,
        case_id=record.case_id,
        changeset_id=record.changeset_id,
        disposition=outcome.disposition,
        response_type=outcome.response_type,
        lane_at_decision=record.lane_at_decision,
        band_at_decision=record.band_at_decision,
        reviewer_display=outcome.reviewer_display,
        created_at=outcome.created_at,
        config_version=record.config_version,
        decider_model=record.decider_model,
    )
