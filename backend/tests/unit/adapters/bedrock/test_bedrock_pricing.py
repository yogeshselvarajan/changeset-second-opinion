from __future__ import annotations

import pytest
from pydantic import ValidationError

from cso.adapters.bedrock import PRICING_DISCLAIMER, estimate_usd, rates_for
from cso.adapters.bedrock import pricing as pricing_module
from cso.adapters.bedrock.pricing import CONSERVATIVE_DEFAULT, HAIKU_4_5, RATES_BY_MODEL
from cso.settings import Settings

PROFILE_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
FOUNDATION_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"


def test_the_disclaimer_is_the_agreed_wording_and_is_in_the_module_docs() -> None:
    assert PRICING_DISCLAIMER == "estimate; verify against current Bedrock pricing"
    assert "verify against current Bedrock pricing" in (pricing_module.__doc__ or "")


def test_both_deployed_model_ids_use_the_haiku_rates() -> None:
    assert set(RATES_BY_MODEL) == {PROFILE_ID, FOUNDATION_ID}
    for model_id in (PROFILE_ID, FOUNDATION_ID):
        assert rates_for(model_id) == HAIKU_4_5
    assert (HAIKU_4_5.input_usd_per_mtok, HAIKU_4_5.output_usd_per_mtok) == (1.0, 5.0)


def test_the_default_model_in_settings_has_a_table_entry() -> None:
    assert Settings().bedrock_model_id in RATES_BY_MODEL


def test_an_unknown_model_uses_a_deliberately_higher_rate() -> None:
    rates = rates_for("some.other-model")
    assert rates == CONSERVATIVE_DEFAULT
    assert rates.input_usd_per_mtok > HAIKU_4_5.input_usd_per_mtok
    assert rates.output_usd_per_mtok > HAIKU_4_5.output_usd_per_mtok


def test_each_side_can_be_overridden_on_its_own() -> None:
    assert rates_for(PROFILE_ID, input_override=2.0).input_usd_per_mtok == 2.0
    assert rates_for(PROFILE_ID, input_override=2.0).output_usd_per_mtok == 5.0
    assert rates_for(PROFILE_ID, output_override=9.0).input_usd_per_mtok == 1.0
    assert rates_for(PROFILE_ID, output_override=9.0).output_usd_per_mtok == 9.0
    zero = rates_for(PROFILE_ID, input_override=0.0, output_override=0.0)
    assert (zero.input_usd_per_mtok, zero.output_usd_per_mtok) == (0.0, 0.0)


def test_the_estimate_is_tokens_times_rate_per_million() -> None:
    assert estimate_usd(PROFILE_ID, 900, 120) == pytest.approx(0.0015)
    assert estimate_usd(PROFILE_ID, 1_000_000, 1_000_000) == pytest.approx(6.0)
    assert estimate_usd(PROFILE_ID, 1_000_000, 0, input_override=2.5) == pytest.approx(2.5)
    assert estimate_usd("some.other-model", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_zero_or_negative_token_counts_never_give_a_negative_cost() -> None:
    assert estimate_usd(PROFILE_ID, 0, 0) == 0.0
    assert estimate_usd(PROFILE_ID, -50, -50) == 0.0


def test_the_price_settings_default_to_the_table_and_reject_negative_values() -> None:
    settings = Settings()
    assert settings.bedrock_input_usd_per_mtok is None
    assert settings.bedrock_output_usd_per_mtok is None
    assert Settings(bedrock_input_usd_per_mtok=2.0).bedrock_input_usd_per_mtok == 2.0
    with pytest.raises(ValidationError):
        Settings(bedrock_output_usd_per_mtok=-1.0)
