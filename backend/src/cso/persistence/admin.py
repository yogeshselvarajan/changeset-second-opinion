"""Operator actions: run migrations and seed fixture cases for replay mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.enums import RunStatus
from cso.domain.evidence import render
from cso.domain.fixtures import FixtureError
from cso.domain.models import AnalysisResult, EvidenceSnapshot
from cso.domain.receipt import DecisionReceipt
from cso.persistence.db import session_scope
from cso.persistence.repos import (
    CasesRepo,
    ConfigsRepo,
    RunsRepo,
    SnapshotsRepo,
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str) -> Config:
    """Programmatic alembic config (works without alembic.ini, e.g. inside the Docker image)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Apply migrations up to `revision`. Blocking: call from a thread inside an event loop."""
    command.upgrade(alembic_config(database_url), revision)


@dataclass
class SeedReport:
    """What `seed_fixtures` did."""

    cases_created: int = 0
    cases_existing: int = 0
    snapshots_created: int = 0
    runs_created: int = 0
    runs_skipped: list[str] = field(default_factory=list)


def _case_dirs(fixtures_dir: Path) -> list[Path]:
    root = fixtures_dir / "cases" if (fixtures_dir / "cases").is_dir() else fixtures_dir
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "expected.json").is_file())


def _run_from_receipt(receipt: DecisionReceipt, snapshot_id: UUID) -> AnalysisResult | None:
    """Build a stored run from a precomputed receipt; None if it lacks what a run needs."""
    nature = receipt.aggregated.get("nature")
    response = receipt.aggregated.get("response")
    recon = receipt.reconciliation
    composition = receipt.panel_composition
    if receipt.lane is not None and composition is not None and nature is None:
        # A fact-panel receipt: the reading is the table row that fired, with no probabilities.
        final = recon.to if recon is not None and recon.to else composition["response"]
        return AnalysisResult.model_validate(
            {
                "snapshot_id": snapshot_id,
                "config_version": receipt.config_version,
                "decider_model": None if receipt.decider is None else receipt.decider.model,
                "status": RunStatus.SUCCEEDED,
                "lane": receipt.lane,
                "band": receipt.band,
                "nature": composition["nature"],
                "response": final,
                "reconciled": bool(recon and recon.applied),
                "reconciled_from": None if recon is None else recon.from_,
                "rules_fired": receipt.rules_fired,
                "errors": receipt.errors,
                "latency_ms": sum(receipt.timing_ms.values()),
            }
        )
    if receipt.lane is None or nature is None or response is None:
        return None
    final_response = recon.to if recon is not None and recon.applied and recon.to else None
    return AnalysisResult.model_validate(
        {
            "snapshot_id": snapshot_id,
            "config_version": receipt.config_version,
            "decider_model": None if receipt.decider is None else receipt.decider.model,
            "status": RunStatus.SUCCEEDED,
            "lane": receipt.lane,
            "band": receipt.band,
            "nature": nature.argmax,
            "response": final_response or response.argmax,
            "nature_probabilities": nature.probabilities,
            "response_probabilities": response.probabilities,
            "reconciled": bool(recon and recon.applied),
            "reconciled_from": None if recon is None else recon.from_,
            "order_sensitivity": nature.order_sensitivity,
            "rules_fired": receipt.rules_fired,
            "errors": receipt.errors,
            "latency_ms": sum(receipt.timing_ms.values()),
        }
    )


async def seed_fixtures(
    factory: async_sessionmaker[AsyncSession],
    fixtures_dir: Path,
    *,
    config: CommunityConfig | None = None,
    config_yaml: str | None = None,
) -> SeedReport:
    """Load every fixture case as a case plus its snapshot (idempotent).

    A precomputed run is stored only when the fixture's expected.json carries a receipt made with
    the same config version; otherwise it is skipped and named in the report.
    """
    cfg = config or CommunityConfig.load()
    yaml_text = config_yaml or default_config_path().read_text(encoding="utf-8")
    report = SeedReport()
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(cfg, yaml_text, activate=True)
        cases, snapshots, runs = CasesRepo(session), SnapshotsRepo(session), RunsRepo(session)
        for case_dir in _case_dirs(fixtures_dir):
            client = ReplayClient(case_dir)
            expected = client.case.expected
            snap = await collect(client, client.case.changeset.id)
            rendered = render(snap, cfg)
            snap = snap.model_copy(
                update={
                    "rendered_text": rendered.text,
                    "rendered_tokens": rendered.estimated_tokens,
                }
            )
            case, created = await cases.get_or_create(snap.changeset.id)
            report.cases_created += int(created)
            report.cases_existing += int(not created)
            snapshot_id, snap_created = await snapshots.add(case.id, snap)
            report.snapshots_created += int(snap_created)
            if snap_created:
                await cases.apply_snapshot(case.id, snap, snapshot_id)
            if expected.place_label:
                await cases.set_place_label(case.id, expected.place_label)
            if expected.receipt is not None:
                await _seed_run(
                    runs,
                    cases,
                    case.id,
                    snapshot_id,
                    snap,
                    expected.receipt,
                    cfg,
                    report,
                    case_dir.name,
                )
    return report


async def _seed_run(
    runs: RunsRepo,
    cases: CasesRepo,
    case_id: UUID,
    snapshot_id: UUID,
    snap: EvidenceSnapshot,
    raw_receipt: dict[str, Any],
    cfg: CommunityConfig,
    report: SeedReport,
    name: str,
) -> None:
    try:
        receipt = DecisionReceipt.model_validate(raw_receipt)
    except ValueError as exc:
        raise FixtureError(f"{name}: expected.json receipt is invalid: {exc}") from exc
    if receipt.config_version != cfg.version:
        report.runs_skipped.append(
            f"{name}: receipt config {receipt.config_version} != {cfg.version}"
        )
        return
    if receipt.evidence_version != snap.evidence_version:
        report.runs_skipped.append(f"{name}: receipt evidence_version does not match the snapshot")
        return
    result = _run_from_receipt(receipt, snapshot_id)
    if result is None:
        report.runs_skipped.append(f"{name}: receipt has no lane or aggregated answers")
        return
    run_id = await runs.add(case_id, snapshot_id, result, receipt=receipt)
    await cases.record_run(
        case_id,
        run_id,
        lane=result.lane,
        band=result.band,
        nature=result.nature,
        response=result.response,
        rules_fired=[hit.code for hit in result.rules_fired],
    )
    report.runs_created += 1
