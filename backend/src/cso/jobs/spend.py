"""The Bedrock dollar ceiling as the draft job uses it: rebuilt from the database, then enforced.

How the limits fit together (each quantity is counted once, by one authority):

* Draft jobs per UTC day: `observability.budget.BudgetGuard`, counted from the `jobs` table, checked
  by the API before it queues a draft.
* Bedrock dollars per UTC day: a `SpendLedger`. Before every draft, `hydrate` raises the ledger to
  the total rebuilt from the draft jobs' `result_ref["bedrock_usd"]`, so a restart (or a second
  process) cannot reset the ceiling. Within a job, `MeteredDrafter` asks `allow()` before each
  Bedrock call and the ledger records the estimated cost after it. Hydration takes the larger of the
  in-memory and database totals, never the sum, so this process's own spend is not counted twice.
* `adapters.bedrock.budget.DraftBudget` is only a per-process burst limiter and is not part of the
  daily ceiling.

Spend is an estimate (`adapters.bedrock.pricing`); the AWS Budgets alarm stays the real backstop.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from cso.adapters.bedrock.pricing import estimate_usd
from cso.observability.budget import (
    BedrockBudgetExhausted,
    SpendLedger,
    recompute_spend_from_jobs,
    spend_ledger,
)
from cso.settings import Settings


class LedgerSpend:
    """A `SpendGate` backed by a `SpendLedger` and the settings' price overrides."""

    def __init__(
        self,
        ledger: SpendLedger,
        *,
        input_usd_per_mtok: float | None = None,
        output_usd_per_mtok: float | None = None,
    ) -> None:
        self.ledger = ledger
        self._input_override = input_usd_per_mtok
        self._output_override = output_usd_per_mtok

    @classmethod
    def from_settings(cls, settings: Settings, ledger: SpendLedger | None = None) -> LedgerSpend:
        """The process-wide ledger (unless one is given) with the settings' price overrides."""
        return cls(
            ledger if ledger is not None else spend_ledger(),
            input_usd_per_mtok=settings.bedrock_input_usd_per_mtok,
            output_usd_per_mtok=settings.bedrock_output_usd_per_mtok,
        )

    async def hydrate(self, session: AsyncSession, now: datetime) -> float:
        """Raise the ledger to today's total from the draft jobs; returns the database total."""
        total = await recompute_spend_from_jobs(session, now)
        self.ledger.hydrate(total)
        return total

    def allow(self) -> bool:
        """True while a further Bedrock call fits under the ceiling (counts a rejection if not)."""
        try:
            self.ledger.require()
        except BedrockBudgetExhausted:
            return False
        return True

    def record(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate one call's cost, add it to the ledger and return it."""
        usd = estimate_usd(
            model_id,
            input_tokens,
            output_tokens,
            input_override=self._input_override,
            output_override=self._output_override,
        )
        self.ledger.record(usd)
        return usd
