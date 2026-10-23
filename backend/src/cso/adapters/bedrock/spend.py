"""Dollar metering around a drafter: ask before each call, record after it.

`MeteredDrafter` wraps one `Drafter` for ONE draft job. Before each model call it asks a
`SpendGate` whether the daily dollar ceiling still has room; when it does not, it raises
`BudgetExceeded`, which `produce_draft` already turns into the offline template with reason
`budget_exceeded` (so a draft is never lost because the ceiling was reached, and no Bedrock call
is made). After each call it records the estimated cost in the gate and adds it to `usd`, which the
draft job writes to its `result_ref` so the day's total can be rebuilt after a restart.

The gate itself (`jobs.spend.LedgerSpend`) lives in the jobs layer; this module only needs its two
methods, so the adapter does not depend on the API or the observability packages.
"""

from __future__ import annotations

from typing import Protocol

from cso.adapters.bedrock.types import Drafter, DraftingError, DraftRequest, RawDraft


class SpendGate(Protocol):
    """The dollar ceiling as the drafter sees it."""

    def allow(self) -> bool:
        """True while one more model call fits under today's ceiling."""
        ...

    def record(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Add one call's estimated cost to today's total; returns that estimated cost."""
        ...


class BudgetExceeded(DraftingError):
    """Today's Bedrock dollar ceiling is reached; the caller falls back to a template."""

    code = "budget_exceeded"


class MeteredDrafter:
    """A `Drafter` that stops at the ceiling and meters what it spends (one per draft job)."""

    def __init__(self, inner: Drafter, gate: SpendGate) -> None:
        self._inner = inner
        self._gate = gate
        self.model_id = inner.model_id
        self.usd = 0.0
        self.calls = 0

    async def draft(self, request: DraftRequest) -> RawDraft:
        """Draft through the wrapped drafter unless the ceiling is reached."""
        if not self._gate.allow():
            raise BudgetExceeded("the daily Bedrock ceiling is reached")
        raw = await self._inner.draft(request)
        self.calls += 1
        self.usd += self._gate.record(raw.model_id, raw.input_tokens, raw.output_tokens)
        return raw
