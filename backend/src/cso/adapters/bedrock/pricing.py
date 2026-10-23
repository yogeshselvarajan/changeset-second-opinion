"""Estimated Bedrock prices, used only to meter spend against the daily dollar ceiling.

THESE ARE ESTIMATES; verify against current Bedrock pricing before relying on them. They exist so
the ceiling in `CSO_BEDROCK_DAILY_USD_CAP` means something, not to produce an invoice. The AWS
Budgets alarm in the deployment stays the real backstop.

Rates are USD per million tokens. The table covers the two ids the deployment allows (the
cross-region inference profile and the foundation model). An
unknown model id falls back to a deliberately high rate, so a mistake errs towards stopping early.
`CSO_BEDROCK_INPUT_USD_PER_MTOK` and `CSO_BEDROCK_OUTPUT_USD_PER_MTOK` override either side.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

PRICING_DISCLAIMER = "estimate; verify against current Bedrock pricing"


@dataclass(frozen=True)
class Rates:
    """Estimated price of a model in USD per million tokens."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float


# Claude Haiku 4.5: estimated list price of $1 per million input and $5 per million output tokens.
HAIKU_4_5 = Rates(input_usd_per_mtok=1.00, output_usd_per_mtok=5.00)

RATES_BY_MODEL: Mapping[str, Rates] = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": HAIKU_4_5,
    "anthropic.claude-haiku-4-5-20251001-v1:0": HAIKU_4_5,
}

# For a model id that is not in the table: high on purpose, so unknown models stop the day early.
CONSERVATIVE_DEFAULT = Rates(input_usd_per_mtok=3.00, output_usd_per_mtok=15.00)


def rates_for(
    model_id: str,
    *,
    input_override: float | None = None,
    output_override: float | None = None,
) -> Rates:
    """The rates to use for `model_id`; each overridden side replaces the table value."""
    base = RATES_BY_MODEL.get(model_id, CONSERVATIVE_DEFAULT)
    return Rates(
        input_usd_per_mtok=base.input_usd_per_mtok if input_override is None else input_override,
        output_usd_per_mtok=(
            base.output_usd_per_mtok if output_override is None else output_override
        ),
    )


def estimate_usd(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    *,
    input_override: float | None = None,
    output_override: float | None = None,
) -> float:
    """Estimated dollar cost of one call (never negative; token counts below 0 count as 0)."""
    rates = rates_for(model_id, input_override=input_override, output_override=output_override)
    return (
        max(0, input_tokens) * rates.input_usd_per_mtok
        + max(0, output_tokens) * rates.output_usd_per_mtok
    ) / 1_000_000
