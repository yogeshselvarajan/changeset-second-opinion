"""Loads everything a case page needs inside one session (repositories in, schemas out)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cso.api.mappers import case_detail, evidence_ids_of, evidence_out
from cso.api.schemas import CaseDetail, EvidenceSnapshot
from cso.domain.config import CommunityConfig
from cso.domain.models import EvidenceSnapshot as DomainSnapshot
from cso.persistence.repos import (
    ConfigsRepo,
    DraftsRepo,
    OutcomesRepo,
    RunsRepo,
    SnapshotsRepo,
)
from cso.persistence.tables import ReviewCaseRow


async def load_case_detail(session: AsyncSession, row: ReviewCaseRow) -> CaseDetail:
    """The case with its latest snapshot summary, run, draft and outcome."""
    snapshot = (
        None
        if row.latest_snapshot_id is None
        else await SnapshotsRepo(session).get(row.latest_snapshot_id)
    )
    run = None if row.latest_run_id is None else await RunsRepo(session).get_row(row.latest_run_id)
    draft = (
        None if row.latest_draft_id is None else await DraftsRepo(session).get(row.latest_draft_id)
    )
    outcome = await OutcomesRepo(session).latest_for_case(row.id)
    return case_detail(row, snapshot=snapshot, run=run, draft=draft, outcome=outcome)


async def load_evidence(session: AsyncSession, snapshot: DomainSnapshot) -> EvidenceSnapshot:
    """A stored snapshot with each element's `evidence_id`.

    The ids are those of the compact evidence text, built with the community configuration the
    newest analysis of this snapshot ran with (else the active one, else the packaged default),
    so they match what decisions and drafts cite.
    """
    config = await _config_for_snapshot(session, snapshot)
    return evidence_out(snapshot, evidence_ids_of(snapshot, config))


async def _config_for_snapshot(session: AsyncSession, snapshot: DomainSnapshot) -> CommunityConfig:
    configs = ConfigsRepo(session)
    row = None
    if snapshot.id is not None and snapshot.case_id is not None:
        for run in await RunsRepo(session).list_rows_for_case(snapshot.case_id):
            if run.snapshot_id == snapshot.id:
                row = await configs.get(run.config_version)
                break
    if row is None:
        row = await configs.get_active()
    if row is None:
        return CommunityConfig.load()
    return CommunityConfig.from_yaml_text(row.yaml, source=f"stored config {row.version}")
