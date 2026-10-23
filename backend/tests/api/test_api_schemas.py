"""Schemas of the v1 API contract: enum sets, strictness, fixture round trips, wording rules."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from cso.adapters.osm import ReplayClient, collect
from cso.api import schemas
from cso.api.deps import Role
from cso.api.schemas import (
    AnalysisRun,
    CaseDetail,
    CaseListQuery,
    ChangesetDetail,
    CreateCaseRequest,
    DecisionListQuery,
    Draft,
    ElementCounts,
    EvidenceSnapshot,
    HumanOutcome,
    ImportRequest,
    Job,
    RunSummary,
    UserSummary,
)
from cso.domain.enums import (
    Band,
    CaseStatus,
    Disposition,
    DraftStatus,
    JobStatus,
    Lane,
    Nature,
    Response,
)
from cso.domain.models import DraftValidation
from cso.domain.receipt import DecisionReceipt

CASES = sorted((Path(__file__).parents[2] / "fixtures" / "cases").iterdir())
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

# Literal sets of the v1 API contract (the enums of the exported OpenAPI file).
CONTRACT_ENUMS: dict[type, set[str]] = {
    Lane: {
        "looks_consistent",
        "review_suggested",
        "needs_local_knowledge",
        "insufficient_evidence",
        "rules_only",
    },
    Band: {"confident", "unsure", "cannot_tell"},
    Nature: {
        "consistent_edit",
        "likely_good_faith_mistake",
        "possible_deliberate_damage",
        "needs_local_knowledge",
    },
    Response: {
        "no_action_suggested",
        "welcome_and_tips",
        "ask_source_question",
        "request_local_check",
        "escalate_to_experienced_reviewer",
    },
    Disposition: {
        "agree",
        "different_response",
        "needs_survey",
        "disagree_with_model",
        "no_action",
    },
    CaseStatus: {"new", "analyzing", "analyzed", "decided"},
    JobStatus: {"queued", "running", "succeeded", "failed", "cancelled"},
}


@pytest.mark.parametrize("enum_type", list(CONTRACT_ENUMS), ids=lambda e: e.__name__)
def test_enum_values_match_contract_exactly(enum_type: type) -> None:
    assert {member.value for member in enum_type} == CONTRACT_ENUMS[enum_type]  # type: ignore[attr-defined]


def test_draft_status_contains_contract_values() -> None:
    # The contract lists three values; the domain also has `generated` (see the report).
    contract = {"validated", "rejected_by_validator", "template_fallback"}
    assert contract <= {member.value for member in DraftStatus}


def test_role_values() -> None:
    assert {r.value for r in Role} == {"viewer", "reviewer", "admin"}


# --------------------------------------------------------------------------- strictness


def test_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreateCaseRequest.model_validate({"changeset_id": 5, "source": "manual", "extra": 1})


@pytest.mark.parametrize(
    ("value", "ok"), [(1, True), (900_000_000_001, True), (9_999_999_999_999, True), (0, False)]
)
def test_changeset_id_bounds(value: int, ok: bool) -> None:
    if ok:
        assert CreateCaseRequest(changeset_id=value).changeset_id == value
    else:
        with pytest.raises(ValidationError):
            CreateCaseRequest(changeset_id=value)


def test_changeset_id_accepts_twelve_digit_fixture_ids_and_rejects_fourteen() -> None:
    # Contract: ^\d{1,13}$, so synthetic fixture ids (12 digits) can be created in replay mode.
    assert CreateCaseRequest(changeset_id=900_000_000_001).changeset_id == 900_000_000_001
    with pytest.raises(ValidationError):
        CreateCaseRequest(changeset_id=10_000_000_000_000)


def test_create_case_source_values() -> None:
    assert CreateCaseRequest(changeset_id=5).source == "manual"
    with pytest.raises(ValidationError):
        CreateCaseRequest.model_validate({"changeset_id": 5, "source": "email"})


def test_import_request_rules() -> None:
    assert ImportRequest(source="maproulette", challenge_id=55814).limit == 100
    assert ImportRequest(source="osmcha", ids=[1, 2]).ids == [1, 2]
    with pytest.raises(ValidationError):
        ImportRequest(source="maproulette")  # neither ids nor challenge_id
    with pytest.raises(ValidationError):
        ImportRequest(source="maproulette", challenge_id=1, limit=101)
    with pytest.raises(ValidationError):
        ImportRequest(source="osmcha", ids=list(range(1, 102)))
    with pytest.raises(ValidationError):
        ImportRequest.model_validate({"source": "manual", "ids": [1]})


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_page_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValidationError):
        CaseListQuery(limit=limit)


def test_query_defaults_and_alias() -> None:
    assert CaseListQuery().limit == 50
    query = DecisionListQuery.model_validate({"from": "2026-01-01T00:00:00Z", "limit": 10})
    assert query.from_ == datetime(2026, 1, 1, tzinfo=UTC)
    assert query.limit == 10
    with pytest.raises(ValidationError):
        DecisionListQuery.model_validate({"reviewer": "x", "unknown": 1})


# --------------------------------------------------------------------------- fixture round trips


def _case_detail(snapshot: Any) -> CaseDetail:
    meta = snapshot.changeset
    user = snapshot.user
    run = _run_summary(snapshot)
    return CaseDetail(
        id=uuid4(),
        changeset_id=meta.id,
        lane=Lane.REVIEW_SUGGESTED,
        band=Band.UNSURE,
        nature=Nature.CONSISTENT_EDIT,
        response=Response.NO_ACTION_SUGGESTED,
        editor=meta.created_by,
        place_label=None,
        element_counts=ElementCounts(
            **{action.value: count for action, count in snapshot.element_counts.items()}
        ),
        flags=list(snapshot.flags),
        coverage_score=snapshot.coverage.score,
        stale=False,
        status=CaseStatus.ANALYZED,
        latest_outcome=None,
        created_at=NOW,
        updated_at=NOW,
        changeset=ChangesetDetail(
            id=meta.id,
            comment=meta.comment,
            source=meta.source,
            created_by=meta.created_by,
            locale=meta.locale,
            review_requested=meta.review_requested,
            user=None
            if user is None
            else UserSummary(
                display_name=user.display_name,
                account_age_days=user.account_age_days,
                changesets_count=user.changesets_count,
                blocks_active=user.blocks_active,
            ),
            created_at=meta.created_at,
            closed_at=meta.closed_at,
            open=meta.open,
            bbox=meta.bbox,
            bbox_wraps=meta.bbox_wraps,
        ),
        latest_snapshot_id=uuid4(),
        latest_run=run,
        outcome_version=0,
    )


def _run_summary(snapshot: Any) -> RunSummary:
    return RunSummary(
        id=uuid4(),
        snapshot_id=uuid4(),
        config_version="sha256:abc",
        decider_model="strands-decider-2B",
        status="succeeded",  # type: ignore[arg-type]
        lane=Lane.REVIEW_SUGGESTED,
        band=Band.UNSURE,
        nature=Nature.CONSISTENT_EDIT,
        response=Response.NO_ACTION_SUGGESTED,
        nature_probabilities={n: 0.25 for n in Nature},
        response_probabilities={r: 0.2 for r in Response},
        order_sensitivity=0.12,
        created_at=NOW,
        latency_ms=450,
    )


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_fixture_snapshots_round_trip_through_api_schemas(case_dir: Path) -> None:
    client = ReplayClient(case_dir)
    snapshot = await collect(client, client.case.changeset.id)

    evidence = EvidenceSnapshot(
        id=uuid4(),
        case_id=uuid4(),
        evidence_version=snapshot.evidence_version,
        source=snapshot.source,
        fetched_at=snapshot.fetched_at,
        provisional=snapshot.provisional,
        coverage=snapshot.coverage,
        elements=snapshot.elements,
        tag_diffs=snapshot.tag_diffs,
        discussion=snapshot.discussion,
        rendered_text="coverage first",
        rendered_tokens=3,
    )
    assert EvidenceSnapshot.model_validate_json(evidence.model_dump_json()) == evidence

    detail = _case_detail(snapshot)
    assert CaseDetail.model_validate_json(detail.model_dump_json()) == detail
    assert detail.coverage_score == snapshot.coverage.score


def test_run_job_draft_outcome_round_trips() -> None:
    run = _run_summary(None)
    receipt = DecisionReceipt(
        evidence_version="v1",
        coverage={},
        decider=None,
        config_version="sha256:abc",
        questions_hash=None,
    )
    analysis = AnalysisRun(**run.model_dump(), receipt=receipt)
    assert AnalysisRun.model_validate_json(analysis.model_dump_json()) == analysis

    job = Job(
        id=uuid4(),
        kind="analyze",  # type: ignore[arg-type]
        status=JobStatus.RUNNING,
        step="decide",
        attempts=1,
        created_at=NOW,
        updated_at=NOW,
    )
    assert Job.model_validate_json(job.model_dump_json()) == job
    with pytest.raises(ValidationError):
        Job.model_validate({**job.model_dump(), "step": "unknown_step"})

    draft = Draft(
        id=uuid4(),
        run_id=run.id,
        response_type=Response.WELCOME_AND_TIPS,
        status=DraftStatus.VALIDATED,
        greeting="Hello",
        body="Thanks for mapping.",
        closing="Happy mapping",
        validation=DraftValidation(ok=True),
        created_at=NOW,
    )
    assert Draft.model_validate_json(draft.model_dump_json()) == draft

    outcome = HumanOutcome(
        id=uuid4(),
        disposition=Disposition.AGREE,
        run_id_seen=run.id,
        reviewer_display="mapper_a",
        created_at=NOW,
    )
    assert HumanOutcome.model_validate_json(outcome.model_dump_json()) == outcome


# --------------------------------------------------------------------------- wording rules

BANNED = re.compile(r"\b(vandal|vandalism|spam|illegal|stop|must)\b", re.IGNORECASE)


def _models() -> list[type[BaseModel]]:
    found = []
    for name in schemas.__all__:
        obj = getattr(schemas, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            found.append(obj)
    return found


def _strings(node: Any, key: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_strings(v, k))
    elif isinstance(node, list):
        for item in node:
            out.extend(_strings(item, key))
    elif isinstance(node, str) and key in {"description", "title", "examples", "example"}:
        out.append(node)
    return out


@pytest.mark.parametrize("model", _models(), ids=lambda m: m.__name__)
def test_schema_text_avoids_banned_words(model: type[BaseModel]) -> None:
    texts = _strings(model.model_json_schema())
    offending = [t for t in texts if BANNED.search(t)]
    assert not offending, offending


def test_field_names_avoid_banned_words_and_single_percentages() -> None:
    bad = re.compile(r"vandal|spam|illegal|percent|pct", re.IGNORECASE)
    for model in _models():
        assert not [f for f in model.model_fields if bad.search(f)], model.__name__


def test_confidence_is_all_probabilities_plus_band() -> None:
    fields = RunSummary.model_fields
    assert {"nature_probabilities", "response_probabilities", "band"} <= set(fields)
    scalar_floats = [
        name
        for name, info in fields.items()
        if info.annotation in (float, "float") and name != "order_sensitivity"
    ]
    assert scalar_floats == []
