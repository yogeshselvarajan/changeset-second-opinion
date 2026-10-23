"""A per-process burst limiter on model drafting (calls and tokens); past it, drafts use templates.

This is NOT the daily ceiling. The authorities that survive a restart are:

* the daily draft-job cap, counted from the `jobs` table (`observability.budget.BudgetGuard`), and
* the daily Bedrock dollar ceiling, kept in a `SpendLedger` that is rebuilt from the draft jobs'
  `result_ref["bedrock_usd"]` before every draft (`jobs.spend.LedgerSpend` with
  `adapters.bedrock.spend.MeteredDrafter`).

`DraftBudget` counts different things (model calls and tokens in this process) as a coarse safety
net against a runaway loop, so no quantity is counted twice towards one limit. It resets at the UTC
day boundary and on restart, so it is never relied on as the daily limit; the dollar ceiling is.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, date, datetime

DEFAULT_DAILY_CALLS = 200
DEFAULT_DAILY_TOKENS = 200_000
CALLS_ENV = "CSO_DRAFT_DAILY_CALLS"
TOKENS_ENV = "CSO_DRAFT_DAILY_TOKENS"


class DraftBudget:
    """Counts model calls and tokens for the current UTC day."""

    def __init__(
        self,
        max_calls: int = DEFAULT_DAILY_CALLS,
        max_tokens: int = DEFAULT_DAILY_TOKENS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self._clock = clock
        self._day: date = clock().date()
        self.calls = 0
        self.tokens = 0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> DraftBudget:
        """Limits from CSO_DRAFT_DAILY_CALLS and CSO_DRAFT_DAILY_TOKENS (200 and 200000)."""
        env = os.environ if environ is None else environ
        return cls(
            max_calls=int(env.get(CALLS_ENV, DEFAULT_DAILY_CALLS)),
            max_tokens=int(env.get(TOKENS_ENV, DEFAULT_DAILY_TOKENS)),
        )

    def _roll(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day, self.calls, self.tokens = today, 0, 0

    def allow(self) -> bool:
        """True while another model call fits inside today's limits."""
        self._roll()
        return self.calls < self.max_calls and self.tokens < self.max_tokens

    def record(self, tokens: int) -> None:
        """Count one model call and its tokens."""
        self._roll()
        self.calls += 1
        self.tokens += max(0, tokens)
