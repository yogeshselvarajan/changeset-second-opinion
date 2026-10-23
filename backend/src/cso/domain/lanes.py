"""Sharpness bands, Q1/Q2 reconciliation and lane assignment.

Lanes only order the queue; nothing is hidden. Rules are the floor: a model output can move a lane
toward more review but never past a rule (see `lane_floor`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from cso.domain.config import Bands, CommunityConfig
from cso.domain.enums import Band, Lane, Nature, Response, RunStatus
from cso.domain.models import AnalysisResult, DecisionOutputs, EvidenceSnapshot, RuleHit
from cso.domain.panel import ADVISORY_PROBES, CROSS_CHECK_ONLY_PROBES, FactPanel, Tri
from cso.domain.policy import (
    EVIDENCE_RULES,
    R1,
    R2,
    R3,
    R4,
    ParsedFacts,
    escalation_downgrade_hit,
    escalation_downgrade_target,
    escalation_threshold,
    evaluate_rules,
    has_rule,
    no_model_hit,
    parsed_facts,
)
from cso.domain.receipt import ReconciliationRecord

# Q1 argmax -> allowed Q2 options, in table order (ties resolve to the earlier option).
ALLOWED_RESPONSES: Mapping[Nature, tuple[Response, ...]] = MappingProxyType(
    {
        Nature.CONSISTENT_EDIT: (Response.NO_ACTION_SUGGESTED, Response.WELCOME_AND_TIPS),
        Nature.LIKELY_GOOD_FAITH_MISTAKE: (
            Response.WELCOME_AND_TIPS,
            Response.ASK_SOURCE_QUESTION,
            Response.REQUEST_LOCAL_CHECK,
        ),
        Nature.POSSIBLE_DELIBERATE_DAMAGE: (
            Response.ESCALATE_TO_EXPERIENCED_REVIEWER,
            Response.REQUEST_LOCAL_CHECK,
        ),
        Nature.NEEDS_LOCAL_KNOWLEDGE: (Response.REQUEST_LOCAL_CHECK, Response.ASK_SOURCE_QUESTION),
    }
)

# Responses a reviewer can send to a mapper or community as a drafted comment.
COMMENT_TYPES: frozenset[Response] = frozenset(
    {Response.WELCOME_AND_TIPS, Response.ASK_SOURCE_QUESTION, Response.REQUEST_LOCAL_CHECK}
)

# How much review a lane asks for: 0 none suggested, 1 review, 2 evidence too thin to judge.
LANE_REVIEW_LEVEL: Mapping[Lane, int] = MappingProxyType(
    {
        Lane.LOOKS_CONSISTENT: 0,
        Lane.REVIEW_SUGGESTED: 1,
        Lane.NEEDS_LOCAL_KNOWLEDGE: 1,
        Lane.RULES_ONLY: 1,
        Lane.INSUFFICIENT_EVIDENCE: 2,
    }
)


def lane_floor(rule_hits: Sequence[RuleHit]) -> int:
    """Minimum review level the rules demand: R3 -> 2; R1, R2, R4 -> 1; otherwise 0."""
    if has_rule(rule_hits, R3):
        return 2
    if any(has_rule(rule_hits, code) for code in (R1, R2, R4)):
        return 1
    return 0


def assign_band(p_agg: float, order_sensitivity: float, bands: Bands) -> Band:
    """Band from max(p_agg) of Q1; large order sensitivity forces `cannot_tell`."""
    if order_sensitivity > bands.order_sensitivity_max:
        return Band.CANNOT_TELL
    if p_agg >= bands.confident_min:
        return Band.CONFIDENT
    if p_agg >= bands.unsure_min:
        return Band.UNSURE
    return Band.CANNOT_TELL


def _typed[E: StrEnum](probabilities: Mapping[str, float], enum: type[E]) -> dict[E, float]:
    """Probabilities keyed by enum member; missing or unknown options raise, never defaulted."""
    expected = {member.value for member in enum}
    if set(probabilities) != expected:
        raise ValueError(
            f"probabilities for {enum.__name__} must cover exactly {sorted(expected)}, "
            f"got {sorted(probabilities)}"
        )
    return {member: float(probabilities[member.value]) for member in enum}


def _best[E: StrEnum](options: Sequence[E], probabilities: Mapping[E, float]) -> E:
    """Highest-probability option; ties go to the earlier option."""
    best = options[0]
    for option in options[1:]:
        if probabilities[option] > probabilities[best]:
            best = option
    return best


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Final Q2 response after the nature table, R1 and R5."""

    response: Response
    reconciled: bool
    original: Response
    rule_hits: tuple[RuleHit, ...] = ()


def reconcile(
    nature: Nature,
    response_probs: Mapping[str, float],
    rule_hits: Sequence[RuleHit],
    *,
    nature_probs: Mapping[str, float],
    config: CommunityConfig,
) -> Reconciliation:
    """Keep the model's Q2 answer if the nature table allows it, else the best allowed option.

    R1 removes `no_action_suggested`. R5 downgrades an escalation unless the damage probability
    reaches its threshold or R1 fired. `reconciled` is true whenever the answer changed.
    """
    probs = _typed(response_probs, Response)
    damage = _typed(nature_probs, Nature)[Nature.POSSIBLE_DELIBERATE_DAMAGE]
    original = _best(list(Response), probs)

    permitted = ALLOWED_RESPONSES[nature]
    r1_fired = has_rule(rule_hits, R1)
    if r1_fired:
        permitted = tuple(r for r in permitted if r is not Response.NO_ACTION_SUGGESTED)
    chosen = original if original in permitted else _best(permitted, probs)

    extra: list[RuleHit] = []
    if (
        chosen is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
        and not r1_fired
        and damage < escalation_threshold(config)
    ):
        target = escalation_downgrade_target(config)
        extra.append(
            escalation_downgrade_hit(
                config, damage_probability=damage, original=chosen, downgraded_to=target
            )
        )
        chosen = target

    return Reconciliation(
        response=chosen,
        reconciled=chosen is not original,
        original=original,
        rule_hits=tuple(extra),
    )


def assign_lane(
    band: Band | None,
    nature: Nature | None,
    response: Response | None,
    rule_hits: Sequence[RuleHit],
) -> Lane:
    """Lane from band, nature and rules.

    R3 decides `insufficient_evidence` from coverage alone. Without model output the lane is
    `rules_only`. `looks_consistent` needs a confident `consistent_edit` and no evidence rule.
    """
    if has_rule(rule_hits, R3):
        return Lane.INSUFFICIENT_EVIDENCE
    if band is None or nature is None:
        return Lane.RULES_ONLY
    if (
        band is Band.CONFIDENT
        and nature is Nature.CONSISTENT_EDIT
        and not any(has_rule(rule_hits, code) for code in EVIDENCE_RULES)
    ):
        return Lane.LOOKS_CONSISTENT
    if nature is Nature.NEEDS_LOCAL_KNOWLEDGE or response is Response.REQUEST_LOCAL_CHECK:
        return Lane.NEEDS_LOCAL_KNOWLEDGE
    return Lane.REVIEW_SUGGESTED


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Everything the gate decides for one run; maps onto `AnalysisResult` fields."""

    lane: Lane
    band: Band | None
    nature: Nature | None
    response: Response | None
    reconciled: bool
    reconciled_from: Response | None
    order_sensitivity: float
    rule_hits: tuple[RuleHit, ...]
    nature_probabilities: Mapping[Nature, float]
    response_probabilities: Mapping[Response, float]
    # Fact-panel runs only: the panel, the table rows that fired and parsed cross-checks.
    panel: FactPanel | None = None
    composition: PanelComposition | None = None
    cross_checks: Mapping[str, str] = field(default_factory=dict)

    def reconciliation_record(self) -> ReconciliationRecord | None:
        """Receipt form of the Q2 reconciliation; None when there was no model output."""
        if self.response is None:
            return None
        return ReconciliationRecord.model_validate(
            {
                "applied": self.reconciled,
                "from": None if self.reconciled_from is None else self.reconciled_from.value,
                "to": self.response.value,
            }
        )

    def result_fields(self) -> dict[str, Any]:
        """Keyword arguments for `AnalysisResult` (without status, ids or config version)."""
        return {
            "lane": self.lane,
            "band": self.band,
            "nature": self.nature,
            "response": self.response,
            "nature_probabilities": dict(self.nature_probabilities),
            "response_probabilities": dict(self.response_probabilities),
            "reconciled": self.reconciled,
            "reconciled_from": self.reconciled_from,
            "order_sensitivity": self.order_sensitivity,
            "rules_fired": list(self.rule_hits),
        }


def evaluate_run(
    snapshot: EvidenceSnapshot,
    outputs: DecisionOutputs | None,
    config: CommunityConfig,
    *,
    failure_code: str | None = None,
) -> PolicyOutcome:
    """Run the whole gate: rules, band, reconciliation and lane. `outputs=None` is a failed run."""
    hits = evaluate_rules(snapshot, config)
    if outputs is None:
        hits.append(no_model_hit(config, failure_code))
        return PolicyOutcome(
            lane=assign_lane(None, None, None, hits),
            band=None,
            nature=None,
            response=None,
            reconciled=False,
            reconciled_from=None,
            order_sensitivity=0.0,
            rule_hits=tuple(hits),
            nature_probabilities={},
            response_probabilities={},
        )

    nature_probs = _typed(outputs.nature.probabilities, Nature)
    response_probs = _typed(outputs.response.probabilities, Response)
    nature = Nature(outputs.nature.argmax)
    sensitivity = outputs.nature.order_sensitivity
    band = assign_band(max(nature_probs.values()), sensitivity, config.bands)
    rec = reconcile(
        nature,
        outputs.response.probabilities,
        hits,
        nature_probs=outputs.nature.probabilities,
        config=config,
    )
    hits.extend(rec.rule_hits)
    return PolicyOutcome(
        lane=assign_lane(band, nature, rec.response, hits),
        band=band,
        nature=nature,
        response=rec.response,
        reconciled=rec.reconciled,
        reconciled_from=rec.original if rec.reconciled else None,
        order_sensitivity=sensitivity,
        rule_hits=tuple(sorted(hits, key=lambda h: h.code)),
        nature_probabilities=nature_probs,
        response_probabilities=response_probs,
    )


# ----------------------------------------------------------------------------- fact-panel path
#
# The fact panel (ADR-009) replaces the 4-way permutation judgement as the decision input. Probes
# are read as no / unknown / yes; `unknown` never triggers a stronger action, it only withholds
# reassurance. Rules R1-R4 come from parsed evidence and stay the floor; the table below decides
# the response, the nature and the band, and the lane then follows `assign_lane` as before.
#
#   concern probes (yes raises concern):  M mature_feature_deleted, N nonsense_or_offensive_values,
#                                         A new_account_first_edits, W real_world_change_claimed,
#                                         T mass_retag_single_key, D deleted_own_recent_additions
#                                         (D withholds reassurance only; it is not an escalation
#                                         signal, ADR-009 Amendment 1)
#   reassurance probes (yes reassures):   C comment_matches_changes, V conventions_followed,
#                                         S discussion_cites_source
#   not composed:                         E evidence_sufficient (cross-check of rule R3)
#
# Parsed facts are a floor (invariant 3, `compose_panel(facts=...)`): for M, A, T, D a true parsed
# fact reads yes whatever the model said, an uncomputable one reads unknown, and a false one keeps
# the model's reading (a model may add caution, never remove it).
# Response table, first matching row wins:
#   P1 escalate_to_experienced_reviewer  N is yes, or R1 fired, or >= 2 of M, A, W, T are yes
#   P2 request_local_check               W is yes and S is yes (a source exists locals can check)
#   P3 ask_source_question               W is yes
#   P4 welcome_and_tips                  A is yes, or V is no, or C is no
#   P5 no_action_suggested               no evidence rule fired, C and V yes, M, N, A, W, T, D no
#   P6 ask_source_question               otherwise (unknowns left; a human looks)
# Nature table, first matching row wins:
#   N1 possible_deliberate_damage        N is yes, or >= 2 of M, A, W, T are yes
#   N2 needs_local_knowledge             W is yes, or R1 fired
#   N3 likely_good_faith_mistake         A is yes, or V is no, or C is no
#   N4 consistent_edit                   same conditions as P5
#   N5 needs_local_knowledge             otherwise
# Two options a community pack may switch on (`panel.composition`, both off by default; they change
# only which row a set of readings lands on, never a rule or the parsed-fact floor):
#   p4_requires_both                     P4 and N3 need V no AND C no, not either one
#   newcomer_welcome_over_question       P6 gives a welcome (as P4) instead of a question when A is
#                                        unknown (the account may be new) and no concern probe
#                                        (M, N, W, T, D) reads yes
# E evidence_sufficient is a cross-check only (rule R3 decides coverage). Band:
# confident with at most `panel.band.confident_max_unknown` unknown composed probes (nine), unsure
# up to `unsure_max_unknown`, else cannot_tell.

_CONCERN = (
    "mature_feature_deleted",
    "nonsense_or_offensive_values",
    "new_account_first_edits",
    "real_world_change_claimed",
    "mass_retag_single_key",
    "deleted_own_recent_additions",
)
_SIGNALS = (
    "mature_feature_deleted",
    "new_account_first_edits",
    "real_world_change_claimed",
    "mass_retag_single_key",
)
_REASSURANCE = ("comment_matches_changes", "conventions_followed")
_MIN_YES_SIGNALS = 2
_FACT_FLOORED = frozenset(
    {
        "mature_feature_deleted",
        "new_account_first_edits",
        "mass_retag_single_key",
        "deleted_own_recent_additions",
    }
)


@dataclass(frozen=True, slots=True)
class PanelComposition:
    """The table rows that fired for one panel and what they produced."""

    nature: Nature
    response: Response
    band: Band
    nature_row: str
    response_row: str
    yes: tuple[str, ...]
    unknown: tuple[str, ...]


def _panel_states(panel: FactPanel, config: CommunityConfig) -> dict[str, Tri]:
    missing = [i for i in config.panel.noul_ids if i not in panel.readings]
    if missing:
        raise ValueError(f"panel is missing probes {missing}; refusing to default them")
    skipped = ADVISORY_PROBES | CROSS_CHECK_ONLY_PROBES
    return {i: panel.state(i) for i in config.panel.noul_ids if i not in skipped}


def compose_panel(
    panel: FactPanel,
    rule_hits: Sequence[RuleHit],
    config: CommunityConfig,
    facts: ParsedFacts | None = None,
) -> PanelComposition:
    """Nature, response and band from the panel and the rule hits (rules are never overridden).

    `facts` (parsed evidence) are a floor of caution (invariant 3). For the four concern probes
    that have a parsed fact: a true fact reads `yes` whatever the model answered, an uncomputable
    fact (`None`: missing profile, or deleted elements without known creator or age) reads
    `unknown` because the model had nothing to answer from, and a false fact keeps the model's
    reading (the model may add caution but never remove it).
    """
    st = _panel_states(panel, config)
    if facts is not None:
        for probe, fact in facts.as_dict().items():
            if probe not in _FACT_FLOORED:
                continue
            if fact is True:
                st[probe] = Tri.YES
            elif fact is None:
                st[probe] = Tri.UNKNOWN
    r1 = has_rule(rule_hits, R1)
    yes_signals = sum(1 for i in _SIGNALS if st[i] is Tri.YES)
    nonsense = st["nonsense_or_offensive_values"] is Tri.YES
    source = st["discussion_cites_source"] is Tri.YES
    claim = st["real_world_change_claimed"] is Tri.YES
    options = config.panel.composition
    newcomer = st["new_account_first_edits"] is Tri.YES
    conventions_off = st["conventions_followed"] is Tri.NO
    comment_off = st["comment_matches_changes"] is Tri.NO
    # A pack may ask for both reassurance probes to read no before a mistake is suggested.
    mistakeish = newcomer or (
        (conventions_off and comment_off)
        if options.p4_requires_both
        else (conventions_off or comment_off)
    )
    reassured = (
        not any(has_rule(rule_hits, code) for code in EVIDENCE_RULES)
        and all(st[i] is Tri.YES for i in _REASSURANCE)
        and all(st[i] is Tri.NO for i in _CONCERN)
    )

    if nonsense or r1 or yes_signals >= _MIN_YES_SIGNALS:
        response, response_row = Response.ESCALATE_TO_EXPERIENCED_REVIEWER, "P1"
    elif claim and source:
        response, response_row = Response.REQUEST_LOCAL_CHECK, "P2"
    elif claim:
        response, response_row = Response.ASK_SOURCE_QUESTION, "P3"
    elif mistakeish:
        response, response_row = Response.WELCOME_AND_TIPS, "P4"
    elif reassured:
        response, response_row = Response.NO_ACTION_SUGGESTED, "P5"
    elif (
        options.newcomer_welcome_over_question
        and st["new_account_first_edits"] is Tri.UNKNOWN
        and not any(st[i] is Tri.YES for i in _CONCERN)
    ):
        # The account may be new and nothing points to harm: a welcome comes before a question.
        response, response_row = Response.WELCOME_AND_TIPS, "P4"
    else:
        response, response_row = Response.ASK_SOURCE_QUESTION, "P6"

    if nonsense or yes_signals >= _MIN_YES_SIGNALS:
        nature, nature_row = Nature.POSSIBLE_DELIBERATE_DAMAGE, "N1"
    elif claim or r1:
        nature, nature_row = Nature.NEEDS_LOCAL_KNOWLEDGE, "N2"
    elif mistakeish:
        nature, nature_row = Nature.LIKELY_GOOD_FAITH_MISTAKE, "N3"
    elif reassured:
        nature, nature_row = Nature.CONSISTENT_EDIT, "N4"
    else:
        nature, nature_row = Nature.NEEDS_LOCAL_KNOWLEDGE, "N5"

    unknown = tuple(i for i, state in st.items() if state is Tri.UNKNOWN)
    limits = config.panel.band
    if len(unknown) <= limits.confident_max_unknown:
        band = Band.CONFIDENT
    elif len(unknown) <= limits.unsure_max_unknown:
        band = Band.UNSURE
    else:
        band = Band.CANNOT_TELL
    return PanelComposition(
        nature=nature,
        response=response,
        band=band,
        nature_row=nature_row,
        response_row=response_row,
        yes=tuple(i for i, state in st.items() if state is Tri.YES),
        unknown=unknown,
    )


def cross_check_panel(
    panel: FactPanel, snapshot: EvidenceSnapshot, config: CommunityConfig
) -> dict[str, str]:
    """Compare the five derivable probes with the parsed facts: agree, disagree, undecided, n/a.

    Informational only. Rules decide; a disagreement tells reviewers and the evaluation which side
    to look at. `undecided` means the panel read the probe as unknown.
    """
    out: dict[str, str] = {}
    for noul_id, fact in parsed_facts(snapshot, config).as_dict().items():
        reading = panel.readings.get(noul_id)
        if reading is None:
            continue
        if fact is None:
            out[noul_id] = "n/a"
        elif reading.state is Tri.UNKNOWN:
            out[noul_id] = "undecided"
        else:
            out[noul_id] = "agree" if (reading.state is Tri.YES) == fact else "disagree"
    return out


def evaluate_panel_run(
    snapshot: EvidenceSnapshot,
    panel: FactPanel | None,
    config: CommunityConfig,
    *,
    failure_code: str | None = None,
) -> PolicyOutcome:
    """Gate for a fact-panel run: rules, composed nature and response, band and lane.

    `panel=None` is a failed run (same as `evaluate_run(..., None)`): `rules_only` with R6.
    """
    if panel is None:
        return evaluate_run(snapshot, None, config, failure_code=failure_code)
    hits = evaluate_rules(snapshot, config)
    composition = compose_panel(panel, hits, config, parsed_facts(snapshot, config))
    return PolicyOutcome(
        lane=assign_lane(composition.band, composition.nature, composition.response, hits),
        band=composition.band,
        nature=composition.nature,
        response=composition.response,
        reconciled=False,
        reconciled_from=None,
        order_sensitivity=0.0,
        rule_hits=tuple(sorted(hits, key=lambda h: h.code)),
        nature_probabilities={},
        response_probabilities={},
        panel=panel,
        composition=composition,
        cross_checks=cross_check_panel(panel, snapshot, config),
    )


def allowed_comment_types(result: AnalysisResult) -> frozenset[Response]:
    """Comment types a draft may be written for, from the stored (reconciled) run.

    Empty for a failed run or a response that is not a comment type. R3 limits drafting to the
    response recorded in its hit (`ask_source_question`).
    """
    if result.status is not RunStatus.SUCCEEDED or result.response is None:
        return frozenset()
    if result.response not in COMMENT_TYPES:
        return frozenset()
    for hit in result.rules_fired:
        if hit.code == R3:
            limit = hit.triggered_by.get("drafting_limited_to", Response.ASK_SOURCE_QUESTION.value)
            try:
                limited = Response(str(limit))
            except ValueError:
                return frozenset()
            return frozenset({limited}) & COMMENT_TYPES
    return frozenset({result.response})
