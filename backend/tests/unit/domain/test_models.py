from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cso.domain.enums import (
    Band,
    CaseStatus,
    ChangeAction,
    CoverageGapReason,
    Disposition,
    DraftStatus,
    EvidenceSource,
    JobKind,
    JobStatus,
    Lane,
    Nature,
    OsmType,
    Response,
)
from cso.domain.fixtures import load_case
from cso.domain.models import (
    AnalysisResult,
    ChangedObject,
    Coverage,
    EvidenceSnapshot,
    HumanOutcome,
    Job,
    UserFacts,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "backend" / "fixtures" / "cases"

# Expected literal sets of the public API contract; changing an enum value is a breaking change.
CONTRACT_ENUMS: dict[type[StrEnum], set[str]] = {
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
    CoverageGapReason: {"redacted", "not_found", "timeout", "budget"},
    ChangeAction: {"create", "modify", "delete"},
    DraftStatus: {"generated", "validated", "rejected_by_validator", "template_fallback"},
    JobKind: {"analyze", "draft"},
    OsmType: {"node", "way", "relation"},
}


@pytest.mark.parametrize("enum_cls", list(CONTRACT_ENUMS), ids=lambda e: e.__name__)
def test_enum_literal_sets(enum_cls: type[StrEnum]) -> None:
    assert {m.value for m in enum_cls} == CONTRACT_ENUMS[enum_cls]


def test_evidence_source_contains_contract_values() -> None:
    # `derived` marks facts computed by code rather than fetched.
    assert {m.value for m in EvidenceSource} == {"osm_api", "replay", "derived"}


def test_enum_values_are_unique_and_lowercase() -> None:
    for enum_cls in CONTRACT_ENUMS:
        values = [m.value for m in enum_cls]
        assert len(values) == len(set(values))
        assert all(v == v.lower() for v in values)


def test_snapshot_built_from_fixture_roundtrips() -> None:
    case = load_case(CASES / "02-good-faith-mistake")
    snapshot = EvidenceSnapshot(
        evidence_version="sha256:test",
        source=EvidenceSource.REPLAY,
        fetched_at=datetime(2026, 3, 2, 15, tzinfo=UTC),
        changeset=case.changeset,
        user=case.user,
        coverage=case.expected.coverage,
        discussion=case.discussion,
        flags=case.expected.flags,
    )
    assert EvidenceSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_models_are_frozen_and_reject_unknown_fields() -> None:
    coverage = Coverage(elements_in_changeset=3, elements_detailed=3)
    with pytest.raises(ValidationError):
        coverage.score = 0.1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Coverage(elements_in_changeset=1, elements_detailed=1, surprise=True)  # type: ignore[call-arg]


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_coverage_score_bounds(score: float) -> None:
    with pytest.raises(ValidationError):
        Coverage(elements_in_changeset=1, elements_detailed=1, score=score)


def test_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Coverage(elements_in_changeset=-1, elements_detailed=0)
    with pytest.raises(ValidationError):
        UserFacts(account_age_days=-1)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        ChangedObject(
            osm_type=OsmType.WAY,
            osm_id=1,
            action=ChangeAction.MODIFY,
            version_after=2,
            created_at_first_version=datetime(2020, 1, 1),  # naive
        )


def test_analysis_result_defaults_describe_a_rules_only_run() -> None:
    result = AnalysisResult(
        config_version="sha256:x",
        status="failed",  # type: ignore[arg-type]  # str coerced to RunStatus
        lane=Lane.RULES_ONLY,
    )
    assert result.nature is None and result.response is None and result.band is None
    assert result.rules_fired == [] and result.errors == []


def test_probabilities_are_bounded() -> None:
    with pytest.raises(ValidationError):
        AnalysisResult(
            config_version="v",
            status="succeeded",  # type: ignore[arg-type]
            lane=Lane.REVIEW_SUGGESTED,
            nature_probabilities={Nature.CONSISTENT_EDIT: 1.2},
        )


def test_outcome_requires_run_seen() -> None:
    with pytest.raises(ValidationError):
        HumanOutcome(disposition=Disposition.AGREE, reviewer_display="reviewer_1")  # type: ignore[call-arg]
    outcome = HumanOutcome(
        disposition=Disposition.AGREE, reviewer_display="reviewer_1", run_id_seen=uuid4()
    )
    with pytest.raises(ValidationError):
        outcome.note = "edited"  # type: ignore[misc]  # outcomes are append-only


def test_job_is_mutable_state_machine_record() -> None:
    job = Job(case_id=uuid4(), kind=JobKind.ANALYZE)
    assert job.status is JobStatus.QUEUED and job.attempts == 0
    job.status = JobStatus.RUNNING
    job.attempts += 1
    assert job.status is JobStatus.RUNNING
