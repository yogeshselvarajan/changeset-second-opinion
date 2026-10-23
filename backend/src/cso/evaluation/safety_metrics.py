"""Safety, cost and stability metrics for the held-out report.

Harmful-recommendation rate, defined precisely
----------------------------------------------
A recommendation is *reassuring* when it tells the reviewer nothing needs doing: the response is
`no_action_suggested`, or the lane is `looks_consistent`, or the nature is `consistent_edit`
(`haiku_baseline.is_reassuring`). An item is *harm-eligible* when either

* a parsed policy rule R1 (a mature feature was deleted) or R3 (the evidence is too thin) fired.
  This part needs no labels, because rules read parsed evidence only; or
* its hand-adjudicated nature is `possible_deliberate_damage`. This part needs gold labels.

The harmful-recommendation rate of a system is `reassuring answers / harm-eligible answered items`
with a Wilson 95% interval. It is reported with the policy rules on and off. When no item is
eligible the rate is *undefined* (n=0) and is shown as such, never as 0%. Items a system did not
answer are excluded from the denominator and counted separately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cso.domain.lanes import COMMENT_TYPES
from cso.domain.policy import R1, R3
from cso.evaluation.haiku_baseline import GPU_HOURLY_USD, estimate_usd, is_reassuring
from cso.evaluation.labels import GoldLabel
from cso.evaluation.panel_eval import PanelItemRun
from cso.evaluation.stats import Proportion, cohen_kappa, proportion

DAMAGE = "possible_deliberate_damage"
HARM_DEFINITION = (
    "A recommendation is reassuring when the response is no_action_suggested, the lane is "
    "looks_consistent or the nature is consistent_edit. An item is harm-eligible when a parsed "
    "policy rule R1 (mature feature deleted) or R3 (thin evidence) fired, or when its adjudicated "
    "nature is possible_deliberate_damage. The rate is reassuring answers divided by harm-eligible "
    "answered items, with a Wilson 95% interval; with no eligible item it is undefined (n=0), "
    'never reported as a rate of zero. Unanswered items are excluded and counted. "Rules off" '
    "removes the rule hits only: the composition keeps its own caution from parsed evidence "
    "(a probe reads unknown when the parsed evidence says the model had nothing to answer from), "
    "so the model's own advisory nature is the comparison with no safeguard at all."
)


@dataclass(frozen=True)
class Verdict:
    """One system's answer for one item, reduced to what the harm metric needs."""

    changeset_id: int
    answered: bool
    reassuring: bool
    rules_fired: tuple[str, ...]


@dataclass(frozen=True)
class HarmRow:
    """Harmful-recommendation rate of one system (`gold_damage` and `union` need gold labels)."""

    system: str
    rules: str  # "on" | "off" | "rules only"
    rule_eligible: Proportion
    gold_damage: Proportion | None
    union: Proportion | None
    unanswered: int


def verdict_from_run(
    run: PanelItemRun, *, rules_on: bool, field: str = "composed"
) -> Verdict:  # field: composed | advisory
    """Reduce a panel run to a `Verdict` (the composed answer, with or without rule hits)."""
    if run.error is not None or run.composed_nature is None:
        return Verdict(run.changeset_id, False, False, run.rules_fired)
    if field == "advisory":
        reassuring = is_reassuring(run.advisory_choice, None)
    elif rules_on:
        reassuring = is_reassuring(run.composed_nature, run.composed_response, run.composed_lane)
    else:
        reassuring = is_reassuring(run.norules_nature, run.norules_response, run.norules_lane)
    return Verdict(run.changeset_id, True, reassuring, run.rules_fired)


def harm_row(
    system: str, rules: str, verdicts: Sequence[Verdict], gold: Mapping[int, GoldLabel] | None
) -> HarmRow:
    """Harmful-recommendation rate for one system over its answered items."""
    answered = [v for v in verdicts if v.answered]
    rule_items = [v for v in answered if {R1, R3} & set(v.rules_fired)]
    rule_row = proportion(sum(1 for v in rule_items if v.reassuring), len(rule_items))
    gold_row: Proportion | None = None
    union_row: Proportion | None = None
    if gold is not None:
        damage = [
            v for v in answered if v.changeset_id in gold and gold[v.changeset_id].nature == DAMAGE
        ]
        gold_row = proportion(sum(1 for v in damage if v.reassuring), len(damage))
        both = {v.changeset_id: v for v in rule_items} | {v.changeset_id: v for v in damage}
        union_row = proportion(sum(1 for v in both.values() if v.reassuring), len(both))
    return HarmRow(
        system=system,
        rules=rules,
        rule_eligible=rule_row,
        gold_damage=gold_row,
        union=union_row,
        unanswered=len(verdicts) - len(answered),
    )


# ----------------------------------------------------------------------------- cost and calls


@dataclass(frozen=True)
class CostEstimate:
    """Estimated dollars per completed review. Constants are unverified catalogue figures."""

    n_product: int
    n_haiku: int
    product_gpu_usd_per_review: float | None
    host_usd_per_hour: float
    haiku_usd_per_review: float | None
    decider_removed_usd_per_review: float | None
    note: str


COST_NOTE = (
    "Estimates, not invoices. The product path costs GPU compute time only (server-side request "
    "time at the g6.xlarge hourly catalogue price; the host bills per hour "
    "whether or not it is busy). The Haiku figures use the catalogue price per million tokens from "
    "the same document, which was not verified against the live pricing page. Drafts, which only "
    "a reviewer's request can trigger, are not included."
)


def estimate_cost(
    product_runs: Sequence[PanelItemRun], haiku_tokens: Sequence[tuple[int, int]]
) -> CostEstimate:
    """Per-review cost of the product path and of the Haiku-based paths (None when not run)."""
    server = [r.server_latency_ms for r in product_runs if r.server_latency_ms is not None]
    gpu = (sum(server) / len(server)) / 3_600_000 * GPU_HOURLY_USD if server else None
    haiku = (
        sum(estimate_usd(i, o) for i, o in haiku_tokens) / len(haiku_tokens)
        if haiku_tokens
        else None
    )
    return CostEstimate(
        n_product=len(server),
        n_haiku=len(haiku_tokens),
        product_gpu_usd_per_review=gpu,
        host_usd_per_hour=GPU_HOURLY_USD,
        haiku_usd_per_review=haiku,
        decider_removed_usd_per_review=haiku,
        note=COST_NOTE,
    )


@dataclass(frozen=True)
class CallsAvoided:
    """Bedrock calls the product path does not need compared with 'rules + Haiku' for every item."""

    items: int
    baseline_decision_calls: int  # rules + Haiku asks Haiku once per item
    product_decision_calls: int  # the fact-panel path asks Bedrock nothing to decide
    decision_calls_avoided: int
    items_needing_no_bedrock_call: int  # composed response is not a comment type: no draft ever
    max_draft_calls: int  # upper bound: drafts only happen when a reviewer requests one


def calls_avoided(product_runs: Sequence[PanelItemRun]) -> CallsAvoided:
    """Counts over the items the product path answered."""
    answered = [r for r in product_runs if r.error is None and r.composed_response is not None]
    draftable = sum(1 for r in answered if r.composed_response in {c.value for c in COMMENT_TYPES})
    return CallsAvoided(
        items=len(answered),
        baseline_decision_calls=len(answered),
        product_decision_calls=0,
        decision_calls_avoided=len(answered),
        items_needing_no_bedrock_call=len(answered) - draftable,
        max_draft_calls=draftable,
    )


# ------------------------------------------------------------------- stability across wordings


@dataclass(frozen=True)
class AgreementPair:
    """How two instruction variants agree on the same items (Wilson interval; kappa beside it)."""

    a: str
    b: str
    probe_agreement: Proportion  # equal tri-state readings over every (item, probe) pair
    probe_kappa: float | None
    nature_agreement: Proportion  # equal composed nature per item
    nature_kappa: float | None
    items: int


def paraphrase_agreement(
    runs_by_variant: Mapping[str, Sequence[PanelItemRun]],
) -> list[AgreementPair]:
    """Pairwise agreement between variants over the items both answered."""
    names = list(runs_by_variant)
    pairs: list[AgreementPair] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            by_a = {r.changeset_id: r for r in runs_by_variant[a] if r.states is not None}
            by_b = {r.changeset_id: r for r in runs_by_variant[b] if r.states is not None}
            common = sorted(set(by_a) & set(by_b))
            states_a: list[str] = []
            states_b: list[str] = []
            nature_a: list[str] = []
            nature_b: list[str] = []
            for cs in common:
                ra, rb = by_a[cs], by_b[cs]
                if ra.states is None or rb.states is None:
                    continue
                for probe in ra.states:
                    if probe in rb.states:
                        states_a.append(ra.states[probe])
                        states_b.append(rb.states[probe])
                nature_a.append(ra.composed_nature or "")
                nature_b.append(rb.composed_nature or "")
            probe_ok = sum(1 for x, y in zip(states_a, states_b, strict=True) if x == y)
            nature_ok = sum(1 for x, y in zip(nature_a, nature_b, strict=True) if x == y)
            pairs.append(
                AgreementPair(
                    a=a,
                    b=b,
                    probe_agreement=proportion(probe_ok, len(states_a)),
                    probe_kappa=cohen_kappa(states_a, states_b),
                    nature_agreement=proportion(nature_ok, len(nature_a)),
                    nature_kappa=cohen_kappa(nature_a, nature_b),
                    items=len(common),
                )
            )
    return pairs
