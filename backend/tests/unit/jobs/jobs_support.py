"""Fakes and builders for the jobs tests: a scripted Decider, a manual clock, OSM providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.decider.client import PanelResult
from cso.adapters.osm import OsmSource, ReplayClient
from cso.adapters.osm.errors import NotFoundError
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.panel import AdvisoryNature, FactPanel, NoulReading, classify
from cso.domain.receipt import DeciderIdentity
from cso.jobs import Deps, ReplayOsmProvider, enqueue_changeset
from cso.persistence.db import session_scope
from cso.persistence.tables import (
    AnalysisRunRow,
    AuditEventRow,
    EvidenceSnapshotRow,
    JobRow,
    ReviewCaseRow,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
CASES = FIXTURES / "cases"

# Probes whose "yes" is a concern get a low probability, reassurance probes a high one.
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

IDENTITY = DeciderIdentity(
    model="fake-decider", checkpoint="fake/checkpoint", device="cpu", max_length=4096
)


def config() -> tuple[CommunityConfig, str]:
    """The default community config and its YAML text."""
    return CommunityConfig.load(), default_config_path().read_text(encoding="utf-8")


def make_panel(cfg: CommunityConfig, probabilities: dict[str, float] | None = None) -> FactPanel:
    """A valid fact panel with the given probe probabilities (default: reassuring)."""
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


def make_result(cfg: CommunityConfig, panel: FactPanel | None = None) -> PanelResult:
    """A successful Decider result around `panel`."""
    return PanelResult(
        panel=panel or make_panel(cfg),
        identity=IDENTITY,
        questions_hash="qh-test",
        input_tokens=1500,
        output_tokens=12,
        server_latency_ms=42.0,
        latency_ms=50,
    )


class FakePanelDecider:
    """Scripted Decider: records calls and overlap, optionally fails or waits.

    `failures` is consumed one entry per call; None means "succeed this time".
    """

    def __init__(
        self,
        cfg: CommunityConfig,
        *,
        probabilities: dict[str, float] | None = None,
        failures: Sequence[BaseException | None] = (),
        delay: float = 0.0,
        on_call: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._cfg = cfg
        self._probabilities = probabilities
        self._failures = list(failures)
        self._delay = delay
        self._on_call = on_call
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.states: list[str] = []

    async def decide_panel(self, state: str, config: CommunityConfig) -> PanelResult:
        self.calls += 1
        self.states.append(state)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self._delay:
                await anyio.sleep(self._delay)
            if self._on_call is not None:
                await self._on_call()
            failure = self._failures.pop(0) if self._failures else None
            if failure is not None:
                raise failure
            return make_result(self._cfg, make_panel(self._cfg, self._probabilities))
        finally:
            self.active -= 1


class ManualClock:
    """A clock tests advance by hand; starts at the real current time."""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _AliasedSource:
    """Answers a made-up changeset id with a fixture's data; everything else passes through."""

    def __init__(self, inner: ReplayClient) -> None:
        self._inner = inner
        self._real_id = inner.case.changeset.id

    @property
    def calls(self) -> int:
        return self._inner.calls

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        return await self._inner.get_changeset(self._real_id)

    async def get_osc(self, changeset_id: int) -> bytes:
        return await self._inner.get_osc(self._real_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class AliasProvider(ReplayOsmProvider):
    """Replay provider that also serves made-up changeset ids from a chosen fixture."""

    def __init__(self, fixtures_dir: Path, aliases: dict[int, str]) -> None:
        super().__init__(fixtures_dir)
        self._aliases = aliases
        self.requests: list[int] = []

    def source_for(self, changeset_id: int) -> OsmSource:
        self.requests.append(changeset_id)
        if changeset_id in self._aliases:
            return _AliasedSource(ReplayClient(CASES / self._aliases[changeset_id]))  # type: ignore[return-value]
        return super().source_for(changeset_id)


class CrashingProvider(ReplayOsmProvider):
    """Replay provider whose first `crashes` lookups raise an unexpected error."""

    def __init__(self, fixtures_dir: Path, crashes: int) -> None:
        super().__init__(fixtures_dir)
        self.crashes = crashes
        self.lookups = 0

    def source_for(self, changeset_id: int) -> OsmSource:
        self.lookups += 1
        if self.lookups <= self.crashes:
            raise RuntimeError("boom")
        return super().source_for(changeset_id)


class CountingProvider(ReplayOsmProvider):
    """Replay provider that counts how many times evidence was requested."""

    def __init__(self, fixtures_dir: Path) -> None:
        super().__init__(fixtures_dir)
        self.lookups = 0

    def source_for(self, changeset_id: int) -> OsmSource:
        self.lookups += 1
        return super().source_for(changeset_id)


class MissingProvider(ReplayOsmProvider):
    """Provider that has no fixture for anything."""

    def source_for(self, changeset_id: int) -> OsmSource:
        raise NotFoundError(f"no fixture for {changeset_id}")


def make_deps(decider: FakePanelDecider, provider: ReplayOsmProvider | None = None) -> Deps:
    """Dependencies wired to fakes (no network, no real Decider)."""
    cfg, yaml_text = config()
    return Deps(
        osm=provider or ReplayOsmProvider(FIXTURES),
        decider=decider,
        config=cfg,
        config_yaml=yaml_text,
    )


Factory = async_sessionmaker[AsyncSession]


async def enqueue_fixture(factory: Factory, number: int, clock: ManualClock) -> tuple[UUID, UUID]:
    """Create the case of fixture `number` (1..8) and queue its analysis: (case_id, job_id)."""
    async with session_scope(factory) as session:
        queued = await enqueue_changeset(session, 900000000000 + number, now=clock())
    return queued.case.id, queued.job.id


async def get_job(factory: Factory, job_id: UUID) -> JobRow:
    async with factory() as session:
        row = await session.get(JobRow, job_id, populate_existing=True)
    assert row is not None
    return row


async def get_case(factory: Factory, case_id: UUID) -> ReviewCaseRow:
    async with factory() as session:
        row = await session.get(ReviewCaseRow, case_id, populate_existing=True)
    assert row is not None
    return row


async def runs_of(factory: Factory, case_id: UUID) -> list[AnalysisRunRow]:
    async with factory() as session:
        result = await session.execute(
            sa.select(AnalysisRunRow)
            .where(AnalysisRunRow.case_id == case_id)
            .order_by(AnalysisRunRow.created_at)
        )
        return list(result.scalars())


async def snapshot_count(factory: Factory, case_id: UUID) -> int:
    async with factory() as session:
        result = await session.execute(
            sa.select(sa.func.count())
            .select_from(EvidenceSnapshotRow)
            .where(EvidenceSnapshotRow.case_id == case_id)
        )
        return int(result.scalar_one())


async def audit_actions(factory: Factory, case_id: UUID) -> list[str]:
    async with factory() as session:
        result = await session.execute(
            sa.select(AuditEventRow.action)
            .where(AuditEventRow.case_id == case_id)
            .order_by(AuditEventRow.id)
        )
        return list(result.scalars())
