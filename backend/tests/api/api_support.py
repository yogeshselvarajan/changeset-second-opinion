"""Builders for the router tests: callers, seeded cases and runs from real replay fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.osm import ReplayClient, collect
from cso.api.deps import ANONYMOUS_VIEWER, Principal, Role
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.enums import Lane, RunStatus
from cso.domain.evidence import render
from cso.domain.lanes import evaluate_panel_run
from cso.domain.models import AnalysisResult, EvidenceSnapshot
from cso.domain.panel import AdvisoryNature, FactPanel, NoulReading, classify
from cso.domain.receipt import DeciderIdentity, build_receipt
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, ConfigsRepo, RunsRepo, SnapshotsRepo

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
BASE_TIME = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

REASSURING: dict[str, float] = {
    "mature_feature_deleted": 0.05,
    "nonsense_or_offensive_values": 0.05,
    "comment_matches_changes": 0.95,
    "conventions_followed": 0.95,
    "new_account_first_edits": 0.05,
    "deleted_own_recent_additions": 0.05,
    "real_world_change_claimed": 0.05,
    "discussion_cites_source": 0.5,
    "mass_retag_single_key": 0.05,
    "evidence_sufficient": 0.95,
}

# Shared principals have no session row; tests that need attribution to a real session open one.
REVIEWER = Principal(id="reviewer-rae", display_name="Rae Reviewer", role=Role.REVIEWER)
ADMIN = Principal(id="admin-ada", display_name="Ada Admin", role=Role.ADMIN)
SIGNED_IN_VIEWER = Principal(id="viewer-vic", display_name="Vic Viewer", role=Role.VIEWER)
ANONYMOUS = ANONYMOUS_VIEWER


class Caller:
    """The principal the app sees; tests change `.principal` to act as someone else."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal


def config() -> tuple[CommunityConfig, str]:
    """The default community config and its YAML text."""
    return CommunityConfig.load(), default_config_path().read_text(encoding="utf-8")


def case_dir(number: int) -> Path:
    """Fixture directory `NN-*`."""
    return next(FIXTURES.glob(f"{number:02d}-*"))


async def fixture_snapshot(number: int) -> EvidenceSnapshot:
    """A real snapshot from replaying a fixture, with rendered text filled in."""
    replay = ReplayClient(case_dir(number))
    snapshot = await collect(replay, replay.case.changeset.id)
    rendered = render(snapshot, config()[0])
    return snapshot.model_copy(
        update={"rendered_text": rendered.text, "rendered_tokens": rendered.estimated_tokens}
    )


def make_panel(cfg: CommunityConfig, probabilities: dict[str, float] | None = None) -> FactPanel:
    """A valid fact panel (default: reassuring readings)."""
    probs = {**REASSURING, **(probabilities or {})}
    low, high = cfg.panel.thresholds.low, cfg.panel.thresholds.high
    readings = {
        i: NoulReading(id=i, probability=probs[i], state=classify(probs[i], low=low, high=high))
        for i in cfg.panel.noul_ids
    }
    codes = [o.code for o in cfg.option_sets.nature]
    advisory = AdvisoryNature(
        order=codes,
        probabilities={c: 1 / len(codes) for c in codes},
        choice=codes[0],
        confidence=1 / len(codes),
    )
    return FactPanel(
        low=low,
        high=high,
        readings=readings,
        advisory_nature=advisory,
        ids=list(cfg.panel.noul_ids),
    )


@dataclass(frozen=True)
class Seeded:
    """Ids of a stored case."""

    case_id: UUID
    snapshot_id: UUID
    run_id: UUID | None
    changeset_id: int


async def seed_case(
    factory: async_sessionmaker[AsyncSession],
    number: int = 1,
    *,
    with_run: bool = True,
    panel_probabilities: dict[str, float] | None = None,
    now: datetime | None = None,
) -> Seeded:
    """Store config, case, snapshot and (optionally) a panel run the way the worker would."""
    cfg, yaml_text = config()
    snapshot = await fixture_snapshot(number)
    stamp = now or BASE_TIME
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(cfg, yaml_text, activate=True)
        cases = CasesRepo(session)
        case, _ = await cases.get_or_create(snapshot.changeset.id, now=stamp)
        snapshot_id, created = await SnapshotsRepo(session).add(case.id, snapshot, now=stamp)
        if created:
            await cases.apply_snapshot(case.id, snapshot, snapshot_id, now=stamp)
        run_id: UUID | None = None
        if with_run:
            run_id = await _store_panel_run(
                session, case.id, snapshot_id, snapshot, cfg, panel_probabilities, stamp
            )
    return Seeded(case.id, snapshot_id, run_id, snapshot.changeset.id)


async def _store_panel_run(
    session: AsyncSession,
    case_id: UUID,
    snapshot_id: UUID,
    snapshot: EvidenceSnapshot,
    cfg: CommunityConfig,
    probabilities: dict[str, float] | None,
    stamp: datetime,
) -> UUID:
    panel = make_panel(cfg, probabilities)
    outcome = evaluate_panel_run(snapshot, panel, cfg)
    composition = outcome.composition
    analysis = AnalysisResult(
        id=uuid4(),
        snapshot_id=snapshot_id,
        config_version=cfg.version,
        decider_model="fake-decider",
        status=RunStatus.SUCCEEDED,
        created_at=stamp,
        latency_ms=1200,
        **outcome.result_fields(),
    )
    receipt = build_receipt(
        snapshot.model_copy(update={"id": snapshot_id, "case_id": case_id}),
        config_version=cfg.version,
        identity=DeciderIdentity(
            model="fake-decider", checkpoint="fake/checkpoint", device="cpu", max_length=4096
        ),
        panel=panel,
        panel_questions_hash="qh-test",
        panel_composition=None
        if composition is None
        else {
            "nature": composition.nature.value,
            "response": composition.response.value,
            "band": composition.band.value,
            "nature_row": composition.nature_row,
            "response_row": composition.response_row,
            "yes": list(composition.yes),
            "unknown": list(composition.unknown),
        },
        panel_cross_checks=dict(outcome.cross_checks) or None,
        state_tokens=1500,
        timing_ms={"total": 1200},
        band=outcome.band,
        rules_fired=outcome.rule_hits,
        reconciliation=outcome.reconciliation_record(),
        lane=outcome.lane,
    )
    run_id = await RunsRepo(session).add(case_id, snapshot_id, analysis, receipt=receipt, now=stamp)
    await CasesRepo(session).record_run(
        case_id,
        run_id,
        lane=analysis.lane,
        band=analysis.band,
        nature=analysis.nature,
        response=analysis.response,
        now=stamp,
    )
    return run_id


async def seed_bare_cases(
    factory: async_sessionmaker[AsyncSession],
    count: int,
    *,
    first_changeset_id: int = 900000100000,
    lane: Lane = Lane.REVIEW_SUGGESTED,
    start: datetime = BASE_TIME,
) -> list[UUID]:
    """Cases with no snapshot, one second apart, all in `lane` (for paging tests)."""
    ids: list[UUID] = []
    async with session_scope(factory) as session:
        cases = CasesRepo(session)
        for i in range(count):
            stamp = start + timedelta(seconds=i)
            row, _ = await cases.get_or_create(first_changeset_id + i, now=stamp)
            await cases.record_run(
                row.id, uuid4(), lane=lane, band=None, nature=None, response=None, now=stamp
            )
            ids.append(row.id)
    return ids
