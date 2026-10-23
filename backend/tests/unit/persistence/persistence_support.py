"""Builders shared by the persistence tests: real fixture snapshots, configs, runs, drafts."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.enums import Band, DraftStatus, Lane, Nature, Response, RunStatus
from cso.domain.evidence import render
from cso.domain.models import AnalysisResult, Draft, DraftValidation, EvidenceSnapshot
from cso.persistence.repos import (
    CasesRepo,
    ConfigsRepo,
    DraftsRepo,
    RunsRepo,
    SnapshotsRepo,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
CASES = FIXTURES / "cases"
CASE_01 = CASES / "01-legitimate"
CASE_02 = CASES / "02-good-faith-mistake"


def config() -> tuple[CommunityConfig, str]:
    """The default community config and its YAML text."""
    return CommunityConfig.load(), default_config_path().read_text(encoding="utf-8")


async def rendered_snapshot(case_dir: Path) -> EvidenceSnapshot:
    """A real snapshot from replaying a fixture, with rendered text filled in."""
    snapshot = await collect(ReplayClient(case_dir), ReplayClient(case_dir).case.changeset.id)
    rendered = render(snapshot, config()[0])
    return snapshot.model_copy(
        update={"rendered_text": rendered.text, "rendered_tokens": rendered.estimated_tokens}
    )


def make_result(
    config_version: str, *, lane: Lane = Lane.REVIEW_SUGGESTED, snapshot_id: UUID | None = None
) -> AnalysisResult:
    """A minimal successful run result."""
    return AnalysisResult(
        snapshot_id=snapshot_id,
        config_version=config_version,
        decider_model="test-model",
        status=RunStatus.SUCCEEDED,
        lane=lane,
        band=Band.UNSURE,
        nature=Nature.CONSISTENT_EDIT,
        response=Response.NO_ACTION_SUGGESTED,
        nature_probabilities={n: 0.25 for n in Nature},
        response_probabilities={r: 0.2 for r in Response},
        order_sensitivity=0.1,
        latency_ms=12,
    )


def make_draft(run_id: UUID) -> Draft:
    """A minimal validated draft."""
    return Draft(
        run_id=run_id,
        response_type=Response.WELCOME_AND_TIPS,
        status=DraftStatus.VALIDATED,
        model_id="test-model",
        greeting="Hello",
        body="Thanks for mapping.",
        closing="Happy mapping",
        validation=DraftValidation(ok=True),
    )


class Stored:
    """Ids of a case persisted with a snapshot and a run."""

    def __init__(self, case_id: UUID, snapshot_id: UUID, run_id: UUID, changeset_id: int) -> None:
        self.case_id = case_id
        self.snapshot_id = snapshot_id
        self.run_id = run_id
        self.changeset_id = changeset_id


async def store_case(
    session: AsyncSession,
    snapshot: EvidenceSnapshot,
    *,
    lane: Lane = Lane.REVIEW_SUGGESTED,
    with_run: bool = True,
) -> Stored:
    """Persist config, case, snapshot and (optionally) one run through the repositories."""
    cfg, yaml_text = config()
    await ConfigsRepo(session).add_if_absent(cfg, yaml_text, activate=True)
    cases = CasesRepo(session)
    case, _ = await cases.get_or_create(snapshot.changeset.id)
    snapshot_id, created = await SnapshotsRepo(session).add(case.id, snapshot)
    if created:
        await cases.apply_snapshot(case.id, snapshot, snapshot_id)
    run_id = UUID(int=0)
    if with_run:
        result = make_result(cfg.version, lane=lane, snapshot_id=snapshot_id)
        run_id = await RunsRepo(session).add(case.id, snapshot_id, result)
        await cases.record_run(
            case.id,
            run_id,
            lane=lane,
            band=result.band,
            nature=result.nature,
            response=result.response,
        )
    return Stored(case.id, snapshot_id, run_id, snapshot.changeset.id)


async def store_draft(session: AsyncSession, stored: Stored) -> UUID:
    """Persist one draft of the stored run."""
    cfg, _ = config()
    return await DraftsRepo(session).add(
        stored.case_id, make_draft(stored.run_id), config_version=cfg.version, prompt_version="p1"
    )
