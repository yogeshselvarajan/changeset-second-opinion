"""Harmful-recommendation rate (definition, undefined denominators), cost, calls avoided and
paraphrase agreement."""

from __future__ import annotations

import pytest
from heldout_support import gold_for

from cso.domain.panel import PANEL_NOUL_IDS
from cso.evaluation.haiku_baseline import GPU_HOURLY_USD, estimate_usd
from cso.evaluation.heldout_report import rate
from cso.evaluation.panel_eval import PanelItemRun
from cso.evaluation.safety_metrics import (
    HARM_DEFINITION,
    Verdict,
    calls_avoided,
    estimate_cost,
    harm_row,
    paraphrase_agreement,
    verdict_from_run,
)


def run(
    cs: int,
    *,
    fired: tuple[str, ...] = (),
    nature: str | None = "consistent_edit",
    response: str = "no_action_suggested",
    lane: str = "looks_consistent",
    off: tuple[str, str, str] = ("consistent_edit", "no_action_suggested", "looks_consistent"),
    states: dict[str, str] | None = None,
    advisory: str = "consistent_edit",
    server: float | None = 400.0,
    error: str | None = None,
) -> PanelItemRun:
    return PanelItemRun(
        changeset_id=cs,
        rules_nature="consistent_edit",
        rules_response="no_action_suggested",
        rules_fired=fired,
        states=states if states is not None else dict.fromkeys(PANEL_NOUL_IDS, "no"),
        composed_nature=nature,
        composed_response=response,
        composed_lane=lane,
        composed_band="confident",
        advisory_choice=advisory,
        norules_nature=off[0],
        norules_response=off[1],
        norules_lane=off[2],
        server_latency_ms=server,
        error=error,
    )


def test_the_definition_names_reassurance_eligibility_and_undefined() -> None:
    for fragment in ("no_action_suggested", "looks_consistent", "R1", "R3", "undefined (n=0)"):
        assert fragment in HARM_DEFINITION
    assert "never reported as a rate of zero" in HARM_DEFINITION


def test_verdict_from_run_uses_the_rules_on_or_off_answer() -> None:
    cautious_on = run(
        1,
        nature="needs_local_knowledge",
        response="escalate_to_experienced_reviewer",
        lane="insufficient_evidence",
    )
    assert verdict_from_run(cautious_on, rules_on=True).reassuring is False
    assert verdict_from_run(cautious_on, rules_on=False).reassuring is True  # rules-off answer
    failed = run(2, nature=None, error="DeciderUnavailable")
    assert verdict_from_run(failed, rules_on=True).answered is False
    advisory = run(3, advisory="needs_local_knowledge")
    assert verdict_from_run(advisory, rules_on=True, field="advisory").reassuring is False


def test_rule_eligible_items_are_those_where_r1_or_r3_fired() -> None:
    verdicts = [
        Verdict(1, True, True, ("R1",)),  # eligible and reassured: harmful
        Verdict(2, True, False, ("R3",)),  # eligible, handled well
        Verdict(3, True, True, ("R2",)),  # R2 alone is not part of the definition
        Verdict(4, True, True, ()),  # clean, not eligible
    ]
    row = harm_row("s", "off", verdicts, None)
    assert (row.rule_eligible.k, row.rule_eligible.n) == (1, 2)
    assert row.gold_damage is None and row.union is None  # no gold, so those are not computed
    assert 0.0 < row.rule_eligible.lower < row.rule_eligible.upper < 1.0  # Wilson interval


def test_gold_damage_items_count_and_the_union_counts_each_item_once() -> None:
    verdicts = [
        Verdict(1, True, True, ("R1",)),  # rule-eligible, gold damage, reassured
        Verdict(2, True, True, ()),  # gold damage only, reassured
        Verdict(3, True, False, ("R3",)),  # rule-eligible only, fine
        Verdict(4, True, True, ()),  # neither
    ]
    gold = gold_for(
        [1, 2, 3, 4], natures={1: "possible_deliberate_damage", 2: "possible_deliberate_damage"}
    )
    row = harm_row("s", "off", verdicts, gold)
    assert row.gold_damage is not None and row.union is not None
    assert (row.gold_damage.k, row.gold_damage.n) == (2, 2)
    assert (row.union.k, row.union.n) == (2, 3)  # items 1, 2, 3; item 1 is counted once


def test_with_no_eligible_item_the_rate_is_undefined_never_zero() -> None:
    verdicts = [Verdict(1, True, True, ()), Verdict(2, True, False, ())]
    row = harm_row("s", "on", verdicts, gold_for([1, 2]))  # nobody labelled damage, no R1/R3
    assert row.rule_eligible.n == 0
    assert row.gold_damage is not None and row.gold_damage.n == 0
    for p in (row.rule_eligible, row.gold_damage, row.union):
        assert p is not None
        assert rate({"k": p.k, "n": p.n, "lower": p.lower, "upper": p.upper}) == "undefined (n=0)"
    assert rate(None) == "needs gold labels"


def test_unanswered_items_are_excluded_from_the_denominator_and_counted() -> None:
    verdicts = [
        Verdict(1, True, True, ("R1",)),
        Verdict(2, False, False, ("R1",)),
        Verdict(3, False, False, ("R3",)),
    ]
    row = harm_row("s", "on", verdicts, None)
    assert row.unanswered == 2
    assert (row.rule_eligible.k, row.rule_eligible.n) == (1, 1)


# -------------------------------------------------------------------------------- cost, calls


def test_cost_estimates_use_server_time_and_catalogue_prices_and_are_labelled() -> None:
    runs = [run(1, server=3_600_000.0 * 0.5), run(2, server=None)]  # 0.5 hour on one item
    cost = estimate_cost(runs, [(1_000_000, 0), (0, 1_000_000)])
    assert cost.product_gpu_usd_per_review == pytest.approx(0.5 * GPU_HOURLY_USD)
    assert cost.n_product == 1 and cost.n_haiku == 2
    assert cost.haiku_usd_per_review == pytest.approx(
        (estimate_usd(1_000_000, 0) + estimate_usd(0, 1_000_000)) / 2
    )
    assert cost.decider_removed_usd_per_review == cost.haiku_usd_per_review
    assert "Estimates, not invoices" in cost.note and "not verified" in cost.note


def test_cost_is_none_when_nothing_ran() -> None:
    cost = estimate_cost([run(1, server=None)], [])
    assert cost.product_gpu_usd_per_review is None
    assert cost.haiku_usd_per_review is None and cost.decider_removed_usd_per_review is None


def test_calls_avoided_counts_decision_calls_and_draftable_items() -> None:
    runs = [
        run(1, response="no_action_suggested"),
        run(2, response="welcome_and_tips"),
        run(3, response="ask_source_question"),
        run(4, response="escalate_to_experienced_reviewer"),
        run(5, nature=None, error="DeciderTimeout"),
    ]
    avoided = calls_avoided(runs)
    assert avoided.items == 4  # the failed item is not counted as answered
    assert avoided.baseline_decision_calls == 4 and avoided.product_decision_calls == 0
    assert avoided.decision_calls_avoided == 4
    assert avoided.max_draft_calls == 2 and avoided.items_needing_no_bedrock_call == 2


# ---------------------------------------------------------------------- wording agreement


def test_paraphrase_agreement_is_perfect_for_identical_runs_and_lower_when_readings_differ() -> (
    None
):
    base = [run(i, states=dict.fromkeys(PANEL_NOUL_IDS, "no")) for i in range(1, 5)]
    same = [run(i, states=dict.fromkeys(PANEL_NOUL_IDS, "no")) for i in range(1, 5)]
    flipped_states = dict.fromkeys(PANEL_NOUL_IDS, "no") | {"mature_feature_deleted": "yes"}
    other = [run(i, states=flipped_states, nature="needs_local_knowledge") for i in range(1, 5)]
    pairs = paraphrase_agreement({"a": base, "b": same, "c": other})
    by = {(p.a, p.b): p for p in pairs}
    assert len(pairs) == 3
    ab, ac = by[("a", "b")], by[("a", "c")]
    assert (ab.probe_agreement.k, ab.probe_agreement.n) == (40, 40)
    assert (ab.nature_agreement.k, ab.nature_agreement.n) == (4, 4)
    assert ac.probe_agreement.k == 36 and ac.probe_agreement.n == 40  # one probe flipped per item
    assert ac.nature_agreement.k == 0
    assert ab.items == 4
    for p in pairs:  # every proportion carries a Wilson interval
        assert p.probe_agreement.lower <= p.probe_agreement.upper


def test_paraphrase_agreement_skips_runs_without_a_panel() -> None:
    answered = [run(1), run(2)]
    failed = [run(1), PanelItemRun(2, "consistent_edit", "no_action_suggested", (), error="x")]
    (pair,) = paraphrase_agreement({"a": answered, "b": failed})
    assert pair.items == 1
