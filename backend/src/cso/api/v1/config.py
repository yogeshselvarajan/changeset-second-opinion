"""The active community configuration, the packs on offer, and the stored versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, Request

from cso.api.db import SessionFactoryDep
from cso.api.problems import (
    ConflictError,
    NotFoundError,
    get_request_id,
    problem_responses,
)
from cso.api.routing import Admin, Viewer, actor_of, make_router
from cso.api.schemas import (
    BandReliability,
    CalibrateRequest,
    CalibrationResult,
    CommunityConfig,
    ConfigDiff,
    ConfigVersion,
    ConfigVersionsResponse,
    DiffItem,
    PackActivated,
    PackListResponse,
    PackSummary,
    ProbeReliability,
    ReliabilityReport,
)
from cso.calibrate import UnknownPackError, run_calibration
from cso.domain.calibration import MIN_LABELS_PER_PROBE, CalibrationReport
from cso.domain.config import CommunityConfig as DomainConfig
from cso.domain.config import ConfigError
from cso.domain.enums import Band
from cso.domain.pack_diff import diff_configs
from cso.domain.panel import PANEL_LABELS
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, ConfigsRepo

router = make_router(tags=["config"])


def _packs() -> dict[str, tuple[DomainConfig, str]]:
    """Every pack file next to the default configuration, by pack id, with its file text."""
    try:
        return DomainConfig.load_all_with_text()
    except ConfigError as exc:
        raise ConflictError(
            "A community pack file is invalid; the pack list cannot be built."
        ) from exc


def _summary(config: DomainConfig, *, active: bool) -> PackSummary:
    info = config.pack
    return PackSummary(
        id=config.pack_id,
        title=info.title if info else config.id,
        description=info.description if info else "",
        author=info.author if info else "",
        version=info.version if info else "",
        config_version=config.version,
        is_active=active,
    )


async def _active_pack_id(factory: SessionFactoryDep) -> str:
    async with session_scope(factory) as session:
        row = await ConfigsRepo(session).get_active()
    if row is None:
        return DomainConfig.load().pack_id
    if row.pack_id:
        return row.pack_id
    return DomainConfig.from_yaml_text(row.yaml, source=f"stored config {row.version}").pack_id


@router.get(
    "/config",
    response_model=CommunityConfig,
    summary="The active community configuration",
)
async def get_config(factory: SessionFactoryDep, principal: Viewer) -> CommunityConfig:
    """Option sets, bands, rules and tone settings. Nothing in it is secret."""
    async with session_scope(factory) as session:
        row = await ConfigsRepo(session).get_active()
    if row is None:  # nothing stored yet: show the configuration the next analysis will use
        return CommunityConfig.load()
    return CommunityConfig.from_yaml_text(row.yaml, source=f"stored config {row.version}")


@router.get(
    "/config/versions",
    response_model=ConfigVersionsResponse,
    summary="Stored configuration versions",
    responses=problem_responses(401, 403),
)
async def list_config_versions(
    factory: SessionFactoryDep, principal: Admin
) -> ConfigVersionsResponse:
    """Newest first; `sha` is the content hash that names the version."""
    async with session_scope(factory) as session:
        rows = await ConfigsRepo(session).list_versions()
        items = [
            ConfigVersion(
                version=row.version,
                created_at=row.created_at,
                sha=row.version.removeprefix("sha256:"),
            )
            for row in rows
        ]
    return ConfigVersionsResponse(items=items)


@router.get(
    "/config/packs",
    response_model=PackListResponse,
    summary="Community packs the server can offer",
    responses=problem_responses(409),
)
async def list_config_packs(factory: SessionFactoryDep, principal: Viewer) -> PackListResponse:
    """Each pack with who wrote it and a mark on the one in use."""
    packs = _packs()
    active = await _active_pack_id(factory)
    return PackListResponse(
        items=[_summary(config, active=pack_id == active) for pack_id, (config, _) in packs.items()]
    )


@router.post(
    "/config/packs/{pack_id}/activate",
    response_model=PackActivated,
    summary="Make a pack the active configuration",
    responses=problem_responses(401, 403, 404, 409),
)
async def activate_config_pack(
    pack_id: str, request: Request, factory: SessionFactoryDep, principal: Admin
) -> PackActivated:
    """Stores the pack as a new configuration version (if it is new) and activates it.

    Runs already made keep the version they used. Later analyses and drafts use this one, and the
    change is written to the audit trail.
    """
    pair = _packs().get(pack_id)
    if pair is None:
        raise NotFoundError("There is no pack with that id.")
    config, yaml_text = pair
    async with session_scope(factory) as session:
        repo = ConfigsRepo(session)
        before = await repo.get_active()
        await repo.add_if_absent(config, yaml_text, activate=True)
        await AuditRepo(session).append(
            actor=actor_of(principal),
            action="config.pack_activated",
            payload={
                "pack_id": config.pack_id,
                "config_version": config.version,
                "previous_version": None if before is None else before.version,
            },
            session_id=principal.session_id,
            request_id=get_request_id(request),
        )
    return PackActivated(pack=_summary(config, active=True), config_version=config.version)


def _reliability(pack_id: str, report: CalibrationReport, synthetic: int = 0) -> ReliabilityReport:
    return ReliabilityReport(
        pack_id=pack_id,
        n_outcomes=report.n_outcomes,
        n_labelled_outcomes=report.n_labelled_outcomes,
        min_labels=MIN_LABELS_PER_PROBE,
        synthetic_outcomes=synthetic,
        probes=[
            ProbeReliability(
                probe=p.probe,
                label=PANEL_LABELS[p.probe],
                n=p.n,
                status=p.status,
                default_low=p.default_low,
                default_high=p.default_high,
                low=p.low,
                high=p.high,
                correct=p.default_accuracy.correct,
                decided=p.default_accuracy.decided,
                lower=p.default_accuracy.lower,
                upper=p.default_accuracy.upper,
                tuned_correct=p.tuned_accuracy.correct,
                tuned_decided=p.tuned_accuracy.decided,
                tuned_lower=p.tuned_accuracy.lower,
                tuned_upper=p.tuned_accuracy.upper,
                coverage=p.coverage,
            )
            for p in report.probes
        ],
        bands=[
            BandReliability(
                band=Band(b.band),
                n=b.n,
                correct=b.accuracy.correct,
                decided=b.accuracy.decided,
                lower=b.accuracy.lower,
                upper=b.accuracy.upper,
                status=b.status,
            )
            for b in report.bands
        ],
    )


@router.get(
    "/config/reliability",
    response_model=ReliabilityReport,
    summary="What reviewers' decisions say about the fact probes",
    responses=problem_responses(401, 403, 404),
)
async def get_config_reliability(
    factory: SessionFactoryDep,
    principal: Admin,
    pack_id: Annotated[str | None, Query(max_length=40)] = None,
) -> ReliabilityReport:
    """A dry run of the calibration: per probe, how many readings were labelled, how accurate the
    decided ones were, and the cut points a refit would pick. Nothing is stored or applied."""
    del principal
    try:
        run = await run_calibration(factory, pack_id=pack_id, apply=False, actor="system")
    except UnknownPackError as exc:
        raise NotFoundError("There is no pack with that id.") from exc
    return _reliability(run.pack_id, run.report)


@router.post(
    "/config/calibrate",
    response_model=CalibrationResult,
    summary="Refit the cut points from reviewers' decisions",
    responses=problem_responses(401, 403, 404),
)
async def calibrate_config(
    body: CalibrateRequest, request: Request, factory: SessionFactoryDep, principal: Admin
) -> CalibrationResult:
    """Without `apply` this is the same dry run as the reliability report. With `apply` the fitted
    cut points become a new configuration version (the pack's file is not edited) and active; runs
    already made keep the version they used. Nothing here ever runs by itself."""
    try:
        run = await run_calibration(
            factory, pack_id=body.pack_id, apply=body.apply, actor=actor_of(principal)
        )
    except UnknownPackError as exc:
        raise NotFoundError("There is no pack with that id.") from exc
    base = _reliability(run.pack_id, run.report)
    return CalibrationResult(
        **base.model_dump(),
        applied=run.applied,
        calibration_id=run.calibration_id,
        config_version=run.config_version,
        reason=run.reason,
    )


@router.get(
    "/config/diff",
    response_model=ConfigDiff,
    summary="What differs between two packs",
    responses=problem_responses(404, 409),
)
async def get_config_diff(
    principal: Viewer,
    a: Annotated[str, Query(min_length=1, max_length=40, description="Pack id")],
    b: Annotated[str, Query(min_length=1, max_length=40, description="Pack id")],
) -> ConfigDiff:
    """The settings that differ, by area. The banned-word list is reported as a count only."""
    del principal
    packs = _packs()
    first, second = packs.get(a), packs.get(b)
    if first is None or second is None:
        raise NotFoundError("One of the packs does not exist.")
    left, right = first[0], second[0]
    return ConfigDiff(
        a=left.pack_id,
        b=right.pack_id,
        changes=[
            DiffItem(area=row.area, key=row.key, a=row.a, b=row.b)
            for row in diff_configs(left, right)
        ],
    )
