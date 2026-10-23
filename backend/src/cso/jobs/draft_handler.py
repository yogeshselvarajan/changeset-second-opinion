"""The DRAFT job: one gated, validated comment candidate for a person to edit.

Steps: load the run the job was queued for and its snapshot, render the same compact evidence the
decision saw, run the Strands agent (its hook enforces the stored decision), then store the draft,
the case pointer, an audit event and the job's terminal state in ONE transaction.

Nothing here posts a comment anywhere. A draft is an immutable row that a reviewer edits and posts
under their own OpenStreetMap identity. A Bedrock failure never fails the job: the draft falls back
to an offline template, and so does reaching the daily Bedrock dollar ceiling (reason
`budget_exceeded`, no call made). Each model call's estimated cost is recorded in the ledger and,
with the tokens, in the job's `result_ref` (`bedrock_usd`), so the day's spend is rebuilt from the
jobs table after a restart. A job that fails (or is retried) after a model call keeps that spend in
its `result_ref` too, and a retry adds to it, so failed attempts still count against the ceiling.
Permanent failures carry a short code:

- `draft_run_missing`   the job has no run, or the run or its snapshot is gone
- `draft_response_invalid`  the job's response type is not a response
- `draft_run_stale`     a newer run exists (checked on load and again just before storing)
- `draft_run_mismatch`  the run belongs to another case
- `draft_not_allowed`   the gate blocked it (the stored decision does not allow this type)
- `draft_not_produced`  the agent ended without calling the tool
- `draft_invalid`       even the template failed validation (a bug; nothing is stored)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from strands.models import Model

from cso.adapters.bedrock import PROMPT_VERSION, Drafter, MeteredDrafter
from cso.agent import (
    DraftContext,
    DraftNotAllowed,
    DraftNotProduced,
    ScriptedToolModel,
    run_draft,
)
from cso.domain.enums import DraftStatus, JobStatus, Response
from cso.domain.evidence import render
from cso.domain.models import EvidenceSnapshot
from cso.jobs.deps import DraftingDeps
from cso.jobs.errors import PermanentJobError
from cso.jobs.handlers import JobContext
from cso.observability.budget import BEDROCK_USD_KEY
from cso.observability.metrics import BEDROCK_CALLS, BEDROCK_TOKENS, METRICS, TEMPLATE_FALLBACKS
from cso.persistence.db import session_scope
from cso.persistence.repos import AuditRepo, CasesRepo, DraftsRepo, RunsRepo, SnapshotsRepo

STEP_LOAD = "load"
STEP_DRAFT = "draft"
STEP_PERSIST = "persist"

# Fallback reasons that mean a Bedrock call was attempted and failed (see adapters.bedrock.types).
BEDROCK_ERROR_REASONS = frozenset(
    {"bedrock_unavailable", "bedrock_timeout", "bedrock_refused", "bedrock_output"}
)


def language_of(snapshot: EvidenceSnapshot) -> str:
    """The mapper's language from the changeset locale (`fr-CA` gives `fr`), else English."""
    locale = snapshot.changeset.locale
    if locale:
        primary = locale.replace("_", "-").split("-")[0].strip().lower()
        if 2 <= len(primary) <= 3 and primary.isalpha():
            return primary
    return "en"


def _offline_model(response_type: Response) -> Model:
    return ScriptedToolModel(response_type.value)


def count_usage(usage: dict[str, Any]) -> None:
    """Bump the Bedrock and template-fallback counters from one draft's usage record."""
    calls = int(usage.get("model_calls", 0))
    if calls:
        METRICS.inc(BEDROCK_CALLS, calls, outcome="ok")
        METRICS.inc(BEDROCK_TOKENS, int(usage.get("input_tokens", 0)), direction="input")
        METRICS.inc(BEDROCK_TOKENS, int(usage.get("output_tokens", 0)), direction="output")
    reason = usage.get("fallback_reason")
    if reason in BEDROCK_ERROR_REASONS:
        METRICS.inc(BEDROCK_CALLS, outcome="error")
    if reason:
        METRICS.inc(TEMPLATE_FALLBACKS, reason=str(reason))


def _prior_usd(progress: dict[str, Any] | None) -> float:
    """Dollars an earlier failed attempt of this job already spent (kept in its result_ref)."""
    value = (progress or {}).get(BEDROCK_USD_KEY)
    return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0


def result_ref_of(
    draft_id: UUID,
    status: DraftStatus,
    usage: dict[str, Any],
    meter: MeteredDrafter | None,
    prior_usd: float = 0.0,
) -> dict[str, Any]:
    """The job's result: the draft, plus calls, tokens and estimated dollars when a model ran."""
    ref: dict[str, Any] = {"draft_id": str(draft_id), "status": status.value}
    if int(usage.get("model_calls", 0)):
        ref["model_calls"] = int(usage["model_calls"])
        ref["input_tokens"] = int(usage.get("input_tokens", 0))
        ref["output_tokens"] = int(usage.get("output_tokens", 0))
        if meter is not None:
            ref[BEDROCK_USD_KEY] = round(prior_usd + meter.usd, 6)
    elif prior_usd > 0:
        ref[BEDROCK_USD_KEY] = round(prior_usd, 6)
    return ref


async def _keep_spend(ctx: JobContext, meter: MeteredDrafter | None, prior_usd: float) -> None:
    """Store the spend of a failing attempt in the job's result_ref so the ceiling still sees it."""
    if meter is None or meter.usd <= 0:
        return
    try:
        async with session_scope(ctx.factory) as session:
            await ctx.save_progress(
                session,
                {
                    "model_calls": meter.calls,
                    BEDROCK_USD_KEY: round(prior_usd + meter.usd, 6),
                },
            )
    except Exception:  # never mask the failure that is being reported
        ctx.log.warning("draft.spend_not_kept")


async def run_draft_job(ctx: JobContext) -> None:
    """Run one draft attempt; finishes the job itself in its final transaction."""
    if ctx.run_id is None:
        raise PermanentJobError("draft_run_missing", "a draft job needs the run it is for")
    try:
        response_type = Response(ctx.response_type or "")
    except ValueError as exc:
        raise PermanentJobError("draft_response_invalid", "unknown response type") from exc

    await ctx.checkpoint(STEP_LOAD)
    async with session_scope(ctx.factory) as session:
        run = await RunsRepo(session).get(ctx.run_id)
        run_row = await RunsRepo(session).get_row(ctx.run_id)
        latest = await RunsRepo(session).latest_for_case(ctx.case_id)
        snapshot = (
            await SnapshotsRepo(session).get(run.snapshot_id)
            if run is not None and run.snapshot_id is not None
            else None
        )
    if run is None or snapshot is None:
        raise PermanentJobError("draft_run_missing", "the run or its snapshot no longer exists")
    if run_row is None or run_row.case_id != ctx.case_id:
        raise PermanentJobError("draft_run_mismatch", "the run belongs to another case")
    if latest is not None and latest.id != run.id:
        raise PermanentJobError("draft_run_stale", "a newer analysis exists; request a new draft")

    config = ctx.active_config
    drafting = ctx.deps.drafting or DraftingDeps()
    drafter: Drafter | None = drafting.drafter
    meter: MeteredDrafter | None = None
    if drafter is not None and drafting.spend is not None:
        # Rebuild today's spend from the draft jobs first, so a restart cannot reset the ceiling.
        async with session_scope(ctx.factory) as session:
            await drafting.spend.hydrate(session, ctx.clock())
        meter = MeteredDrafter(drafter, drafting.spend)
        drafter = meter
    dctx = DraftContext(
        run=run,
        evidence=render(snapshot, config, profile="compact"),
        tone=config.tone,
        language=language_of(snapshot),
        drafter=drafter,
        budget=drafting.budget,
    )
    model = (drafting.model_for or _offline_model)(response_type)

    prior_usd = _prior_usd(ctx.progress)
    try:
        await ctx.checkpoint(STEP_DRAFT)
        try:
            draft = await run_draft(dctx, model, response_type)
        except DraftNotAllowed as exc:
            raise PermanentJobError("draft_not_allowed", str(exc)) from exc
        except DraftNotProduced as exc:
            raise PermanentJobError("draft_not_produced", str(exc)) from exc
        outcome = dctx.outcome
        if outcome is None or draft.status is DraftStatus.REJECTED_BY_VALIDATOR:
            raise PermanentJobError("draft_invalid", "no draft passed validation")
        count_usage(outcome.usage)

        await ctx.checkpoint(STEP_PERSIST)
        async with session_scope(ctx.factory) as session:
            newest = await RunsRepo(session).latest_for_case(ctx.case_id)
            if newest is not None and newest.id != run.id:  # re-checked in the storing transaction
                raise PermanentJobError(
                    "draft_run_stale", "a newer analysis exists; request a new draft"
                )
            draft_id = await DraftsRepo(session).add(
                ctx.case_id,
                draft,
                config_version=config.version,
                prompt_version=PROMPT_VERSION,
                usage=outcome.usage,
                now=ctx.clock(),
            )
            await CasesRepo(session).set_latest_draft(ctx.case_id, draft_id)
            await AuditRepo(session).append(
                actor="system",
                action="draft_created",
                payload={
                    "draft_id": str(draft_id),
                    "run_id": str(run.id),
                    "response_type": response_type.value,
                    "status": draft.status.value,
                },
                case_id=ctx.case_id,
                now=ctx.clock(),
            )
            await ctx.finish(
                session,
                JobStatus.SUCCEEDED,
                result_ref=result_ref_of(draft_id, draft.status, outcome.usage, meter, prior_usd),
            )
    except Exception:
        await _keep_spend(ctx, meter, prior_usd)
        raise
