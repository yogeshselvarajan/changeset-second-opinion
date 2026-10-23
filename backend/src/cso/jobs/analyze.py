"""The analyze pipeline: fetch_evidence -> snapshot -> decide -> persist.

- fetch_evidence: collect evidence through the `OsmSource` seam (GET only, budgeted).
- snapshot: render, insert idempotently by (case, evidence_version), copy queue facts to the case,
  and save the snapshot id as job progress, so a retry after a crash resumes at `decide`.
- decide: one fact-panel request (ADR-009) through the Decider seam, one call at a time, then the
  policy gate (parsed-evidence rules first; the panel can only make a lane more cautious).
- persist: run, case pointer, audit event and the job's terminal state commit in ONE transaction.

A Decider failure never loses the evidence: transient ones retry with backoff, and once retries are
used up (or at once for schema / state-too-long bugs) a failed run with the `rules_only` lane and
its rule hits is stored and the job ends `failed`.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

from cso.adapters.decider.client import PanelResult
from cso.adapters.decider.errors import DeciderError
from cso.adapters.osm import collect
from cso.domain.enums import CaseStatus, JobStatus, RunStatus
from cso.domain.evidence import render
from cso.domain.lanes import PolicyOutcome, evaluate_panel_run
from cso.domain.models import AnalysisResult, EvidenceSnapshot
from cso.domain.receipt import DecisionReceipt, build_receipt
from cso.jobs.errors import (
    PermanentJobError,
    TransientJobError,
    is_permanent_decider_error,
)
from cso.jobs.handlers import JobContext
from cso.jobs.states import STEP_DECIDE, STEP_FETCH, STEP_PERSIST, STEP_SNAPSHOT
from cso.observability.metrics import (
    ANALYSES,
    DECIDER_CALLS,
    DECIDER_LATENCY,
    JOB_FAILURES,
    METRICS,
)
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, CasesRepo, RunsRepo, SnapshotsRepo


def _ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


async def run_analyze(ctx: JobContext) -> None:
    """Run one analyze attempt; finishes the job itself (see module docstring)."""
    timing: dict[str, int] = {}
    snapshot = await _resume(ctx)
    if snapshot is None:
        snapshot = await _fetch_and_store(ctx, timing)
    cfg = ctx.active_config

    await ctx.checkpoint(STEP_DECIDE)
    compact = render(snapshot, cfg, profile="compact")
    started = time.perf_counter()
    try:
        async with ctx.deps.decider_lock:  # single flight, even for deciders without a gate
            result = await ctx.deps.decider.decide_panel(compact.text, cfg)
    except DeciderError as exc:
        timing["decide"] = _ms(started)
        METRICS.inc(DECIDER_CALLS, outcome=exc.failure_code)
        if not is_permanent_decider_error(exc) and not ctx.last_attempt:
            raise TransientJobError(exc.failure_code, str(exc)[:300]) from exc
        ctx.log.warning("analysis.decider_failed", code=exc.failure_code, error=str(exc)[:300])
        await _persist_failed_run(ctx, snapshot, exc.failure_code, timing)
        return
    timing["decide"] = _ms(started)
    METRICS.inc(DECIDER_CALLS, outcome="ok")
    METRICS.observe(DECIDER_LATENCY, result.latency_ms)
    if result.server_latency_ms is not None:
        timing["decide_server"] = max(0, round(result.server_latency_ms))

    outcome = evaluate_panel_run(snapshot, result.panel, cfg)
    await ctx.checkpoint(STEP_PERSIST)
    await _persist_run(ctx, snapshot, outcome, result, compact.estimated_tokens, timing)


async def _resume(ctx: JobContext) -> EvidenceSnapshot | None:
    """The snapshot an earlier attempt already stored, if this job has progress."""
    raw = (ctx.progress or {}).get("snapshot_id")
    if raw is None:
        return None
    async with session_scope(ctx.factory) as session:
        snapshot = await SnapshotsRepo(session).get(UUID(str(raw)))
    if snapshot is not None:
        ctx.log.info("analysis.resumed", snapshot_id=str(raw))
    return snapshot


async def _fetch_and_store(ctx: JobContext, timing: dict[str, int]) -> EvidenceSnapshot:
    deps, cfg = ctx.deps, ctx.active_config
    async with session_scope(ctx.factory) as session:
        case = await CasesRepo(session).get(ctx.case_id)
        if case is None:
            raise PermanentJobError("case_not_found", str(ctx.case_id))
        changeset_id = case.changeset_id

    await ctx.checkpoint(STEP_FETCH)
    started = time.perf_counter()
    snapshot = await collect(
        deps.osm.source_for(changeset_id),
        changeset_id,
        deps.budget,
        cache=deps.cache,
        clock=deps.clock,
    )
    timing["fetch"] = _ms(started)

    await ctx.checkpoint(STEP_SNAPSHOT)
    started = time.perf_counter()
    rendered = render(snapshot, cfg)
    snapshot = snapshot.model_copy(
        update={"rendered_text": rendered.text, "rendered_tokens": rendered.estimated_tokens}
    )
    async with session_scope(ctx.factory) as session:
        cases = CasesRepo(session)
        snapshot_id, created = await SnapshotsRepo(session).add(
            ctx.case_id, snapshot, now=ctx.clock()
        )
        stored_case = await cases.get(ctx.case_id)
        if created or stored_case is None or stored_case.latest_snapshot_id != snapshot_id:
            await cases.apply_snapshot(ctx.case_id, snapshot, snapshot_id, now=ctx.clock())
        await ctx.save_progress(session, {"snapshot_id": str(snapshot_id)})
    timing["snapshot"] = _ms(started)
    return snapshot.model_copy(update={"id": snapshot_id, "case_id": ctx.case_id})


def _stored_id(snapshot: EvidenceSnapshot) -> UUID:
    """The id of a stored snapshot; a missing one is a pipeline bug, not something to retry."""
    if snapshot.id is None:
        raise PermanentJobError("snapshot_not_stored", "decide ran on an unstored snapshot")
    return snapshot.id


def _timing_total(timing: dict[str, int]) -> int:
    return sum(v for k, v in timing.items() if k in {"fetch", "snapshot", "decide"})


async def _persist_run(
    ctx: JobContext,
    snapshot: EvidenceSnapshot,
    outcome: PolicyOutcome,
    result: PanelResult,
    state_tokens: int,
    timing: dict[str, int],
) -> None:
    cfg = ctx.active_config
    snapshot_id = _stored_id(snapshot)
    total = _timing_total(timing)
    timing = {**timing, "total": total}
    analysis = AnalysisResult(
        id=uuid4(),
        snapshot_id=snapshot_id,
        config_version=cfg.version,
        decider_model=result.identity.model,
        status=RunStatus.SUCCEEDED,
        created_at=ctx.clock(),
        latency_ms=total,
        **outcome.result_fields(),
    )
    composition = outcome.composition
    receipt = build_receipt(
        snapshot,
        config_version=cfg.version,
        identity=result.identity,
        panel=result.panel,
        panel_questions_hash=result.questions_hash,
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
        state_tokens=state_tokens,
        timing_ms=timing,
        band=outcome.band,
        rules_fired=outcome.rule_hits,
        reconciliation=outcome.reconciliation_record(),
        lane=outcome.lane,
    )
    await _commit_run(
        ctx,
        snapshot,
        analysis,
        receipt,
        checkpoint=result.identity.checkpoint,
        status=JobStatus.SUCCEEDED,
        error=None,
    )


async def _persist_failed_run(
    ctx: JobContext, snapshot: EvidenceSnapshot, code: str, timing: dict[str, int]
) -> None:
    cfg = ctx.active_config
    snapshot_id = _stored_id(snapshot)
    outcome = evaluate_panel_run(snapshot, None, cfg, failure_code=code)
    total = _timing_total(timing)
    analysis = AnalysisResult(
        id=uuid4(),
        snapshot_id=snapshot_id,
        config_version=cfg.version,
        status=RunStatus.FAILED,
        failure_code=code,
        created_at=ctx.clock(),
        latency_ms=total,
        errors=[code],
        **outcome.result_fields(),
    )
    receipt = build_receipt(
        snapshot,
        config_version=cfg.version,
        timing_ms={**timing, "total": total},
        band=outcome.band,
        rules_fired=outcome.rule_hits,
        lane=outcome.lane,
        errors=[code],
    )
    await _commit_run(
        ctx, snapshot, analysis, receipt, checkpoint=None, status=JobStatus.FAILED, error=code
    )


async def _commit_run(
    ctx: JobContext,
    snapshot: EvidenceSnapshot,
    analysis: AnalysisResult,
    receipt: DecisionReceipt,
    *,
    checkpoint: str | None,
    status: JobStatus,
    error: str | None,
) -> None:
    """Run row, case pointer, audit event and job state in one transaction (all or nothing)."""
    snapshot_id = _stored_id(snapshot)
    async with session_scope(ctx.factory) as session:
        run_id = await RunsRepo(session).add(
            ctx.case_id,
            snapshot_id,
            analysis,
            receipt=receipt,
            job_id=ctx.job_id,
            decider_checkpoint=checkpoint,
            now=ctx.clock(),
        )
        await CasesRepo(session).record_run(
            ctx.case_id,
            run_id,
            lane=analysis.lane,
            band=analysis.band,
            nature=analysis.nature,
            response=analysis.response,
            rules_fired=[hit.code for hit in analysis.rules_fired],
            now=ctx.clock(),
        )
        payload: dict[str, Any] = {
            "job_id": str(ctx.job_id),
            "run_id": str(run_id),
            "lane": analysis.lane.value,
            "status": analysis.status.value,
        }
        if error:
            payload["failure_code"] = error
        await AuditRepo(session).append(
            actor=f"system:worker:{ctx.worker_id}",
            action="analysis.completed" if error is None else "analysis.failed",
            case_id=ctx.case_id,
            payload=payload,
            now=ctx.clock(),
        )
        await ctx.finish(
            session,
            status,
            result_ref={"run_id": str(run_id), "snapshot_id": str(snapshot_id)},
            error=error,
        )
    METRICS.inc(ANALYSES, lane=analysis.lane.value, status=analysis.status.value)
    if status is JobStatus.FAILED:
        METRICS.inc(JOB_FAILURES, kind="analyze", code=error or "unknown")
    ctx.log.info("analysis.persisted", run_id=str(run_id), lane=analysis.lane.value)


def revert_case_if_unanalyzed(status: str, latest_run_id: UUID | None) -> CaseStatus | None:
    """Status a case returns to after a terminal failure that produced no run (else unchanged)."""
    if latest_run_id is None and status == CaseStatus.ANALYZING.value:
        return CaseStatus.NEW
    return None
