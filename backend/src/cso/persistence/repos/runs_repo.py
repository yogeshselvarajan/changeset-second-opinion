"""Analysis runs: append-only record of one Decider + policy-gate run."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cso.domain.models import AnalysisResult, DecisionOutputs
from cso.domain.receipt import DecisionReceipt
from cso.persistence.repos._common import utcnow
from cso.persistence.tables import AnalysisRunRow


def _outputs_from_receipt(receipt: dict[str, Any] | None) -> DecisionOutputs | None:
    if not receipt or not receipt.get("permutations"):
        return None
    aggregated = receipt.get("aggregated") or {}
    if "nature" not in aggregated or "response" not in aggregated:
        return None
    return DecisionOutputs.model_validate(
        {
            "permutations": receipt["permutations"],
            "nature": aggregated["nature"],
            "response": aggregated["response"],
            "nouls": receipt.get("nouls") or {},
        }
    )


def run_to_model(row: AnalysisRunRow) -> AnalysisResult:
    """Rebuild the domain result from its stored row (outputs come from the receipt)."""
    receipt = row.receipt
    reconciliation = (receipt or {}).get("reconciliation") or {}
    return AnalysisResult.model_validate(
        {
            "id": row.id,
            "snapshot_id": row.snapshot_id,
            "config_version": row.config_version,
            "decider_model": row.decider_model,
            "status": row.status,
            "failure_code": row.failure_reason,
            "lane": row.lane,
            "band": row.band,
            "nature": row.nature,
            "response": row.response,
            "nature_probabilities": row.nature_probabilities,
            "response_probabilities": row.response_probabilities,
            "reconciled": row.reconciled,
            "reconciled_from": reconciliation.get("from"),
            "order_sensitivity": row.order_sensitivity,
            "rules_fired": row.rules_fired,
            "outputs": _outputs_from_receipt(receipt),
            "errors": (receipt or {}).get("errors", []),
            "created_at": row.created_at,
            "latency_ms": row.latency_ms,
        }
    )


class RunsRepo:
    """Insert and read runs; corrections are new rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self,
        case_id: UUID,
        snapshot_id: UUID,
        result: AnalysisResult,
        *,
        receipt: DecisionReceipt | None = None,
        job_id: UUID | None = None,
        decider_checkpoint: str | None = None,
        now: datetime | None = None,
    ) -> UUID:
        """Store one run; the id comes from `result.id` when set (so receipts can cite it)."""
        dump = result.model_dump(mode="json")
        row = AnalysisRunRow(
            id=result.id or uuid4(),
            case_id=case_id,
            snapshot_id=snapshot_id,
            job_id=job_id,
            config_version=result.config_version,
            decider_model=result.decider_model,
            decider_checkpoint=decider_checkpoint,
            status=result.status.value,
            failure_reason=result.failure_code,
            lane=result.lane.value,
            band=None if result.band is None else result.band.value,
            nature=None if result.nature is None else result.nature.value,
            response=None if result.response is None else result.response.value,
            reconciled=result.reconciled,
            nature_probabilities=dump["nature_probabilities"],
            response_probabilities=dump["response_probabilities"],
            order_sensitivity=result.order_sensitivity,
            rules_fired=dump["rules_fired"],
            receipt=None if receipt is None else receipt.to_json_dict(),
            latency_ms=result.latency_ms,
            created_at=now or result.created_at or utcnow(),
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def get(self, run_id: UUID) -> AnalysisResult | None:
        """The run with this id, if any."""
        row = await self._s.get(AnalysisRunRow, run_id)
        return None if row is None else run_to_model(row)

    async def get_row(self, run_id: UUID) -> AnalysisRunRow | None:
        """The stored row (includes the receipt JSON and the case id)."""
        return await self._s.get(AnalysisRunRow, run_id)

    async def list_for_case(self, case_id: UUID) -> list[AnalysisResult]:
        """Runs of a case, newest first."""
        result = await self._s.execute(
            sa.select(AnalysisRunRow)
            .where(AnalysisRunRow.case_id == case_id)
            .order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id)
        )
        return [run_to_model(r) for r in result.scalars()]

    async def latest_for_case(self, case_id: UUID) -> AnalysisResult | None:
        """Newest run of a case."""
        runs = await self.list_for_case(case_id)
        return runs[0] if runs else None

    async def list_rows_for_case(self, case_id: UUID) -> list[AnalysisRunRow]:
        """Stored rows (with receipts) of a case, newest first."""
        result = await self._s.execute(
            sa.select(AnalysisRunRow)
            .where(AnalysisRunRow.case_id == case_id)
            .order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id)
        )
        return list(result.scalars())

    async def rule_codes_by_id(self, run_ids: Sequence[UUID]) -> dict[UUID, list[str]]:
        """Policy rule codes fired in each run, for the queue's `flags` (one query per page)."""
        if not run_ids:
            return {}
        result = await self._s.execute(
            sa.select(AnalysisRunRow.id, AnalysisRunRow.rules_fired).where(
                AnalysisRunRow.id.in_(list(run_ids))
            )
        )
        return {
            run_id: [str(hit["code"]) for hit in hits if isinstance(hit, dict) and "code" in hit]
            for run_id, hits in result.all()
        }
