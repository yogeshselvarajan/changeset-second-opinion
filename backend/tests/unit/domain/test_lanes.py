"""Bands, Q1/Q2 reconciliation, lanes and the gate end to end (including replayed fixtures)."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import Bands, CommunityConfig, RuleConfig
from cso.domain.enums import (
    Band,
    ChangeAction,
    EvidenceSource,
    Lane,
    Nature,
    OsmType,
    Response,
    RunStatus,
    Severity,
)
from cso.domain.lanes import (
    ALLOWED_RESPONSES,
    COMMENT_TYPES,
    LANE_REVIEW_LEVEL,
    allowed_comment_types,
    assign_band,
    assign_lane,
    evaluate_run,
    lane_floor,
    reconcile,
)
from cso.domain.models import (
    AggregatedChoice,
    AnalysisResult,
    ChangedObject,
    ChangesetMeta,
    Coverage,
    DecisionOutputs,
    EvidenceSnapshot,
    RuleHit,
    UserFacts,
)
from cso.domain.policy import R1, R2, R3, R4, R5, R6, evaluate_rules, no_model_hit

CONFIG = CommunityConfig.load()
NOW = datetime(2026, 5, 1, tzinfo=UTC)
CASES = {p.name: p for p in sorted((Path(__file__).parents[3] / "fixtures" / "cases").iterdir())}
EVIDENCE_CODES = (R1, R2, R3, R4)


def hit(code: str) -> RuleHit:
    return RuleHit(code=code, label=code, severity=Severity.WARN)


def peaked[E: (Nature, Response)](enum: type[E], top: E, p: float = 0.9) -> dict[str, float]:
    rest = (1.0 - p) / (len(enum) - 1)
    return {m.value: (p if m is top else rest) for m in enum}


def outputs(
    nature: Nature,
    response: Response,
    *,
    p_nature: float = 0.9,
    p_response: float = 0.9,
    sensitivity: float = 0.0,
    nature_probs: Mapping[str, float] | None = None,
    response_probs: Mapping[str, float] | None = None,
) -> DecisionOutputs:
    n = dict(nature_probs) if nature_probs else peaked(Nature, nature, p_nature)
    r = dict(response_probs) if response_probs else peaked(Response, response, p_response)
    return DecisionOutputs(
        permutations=[],
        nature=AggregatedChoice(
            probabilities=n,
            argmax=max(n, key=lambda k: n[k]),
            confidence_agg=0.5,
            order_sensitivity=sensitivity,
        ),
        response=AggregatedChoice(
            probabilities=r,
            argmax=max(r, key=lambda k: r[k]),
            confidence_agg=0.5,
            order_sensitivity=0.0,
        ),
    )


def plain_snapshot(
    *,
    deletions: Sequence[ChangedObject] = (),
    flags: Sequence[str] = (),
    score: float = 1.0,
    account_age_days: int | None = 500,
) -> EvidenceSnapshot:
    els = list(deletions)
    return EvidenceSnapshot(
        evidence_version="sha256:test",
        source=EvidenceSource.DERIVED,
        fetched_at=NOW,
        changeset=ChangesetMeta(id=1, created_at=NOW),
        user=UserFacts(account_age_days=account_age_days),
        coverage=Coverage(elements_in_changeset=len(els), elements_detailed=len(els), score=score),
        elements=els,
        flags=list(flags),
    )


MATURE = ChangedObject(
    osm_type=OsmType.WAY,
    osm_id=1,
    action=ChangeAction.DELETE,
    version_after=3,
    version_before=2,
    age_days=3000,
)

# One snapshot per rule combination the gate can see (each is built so only the named rules fire).
SCENARIOS: dict[str, EvidenceSnapshot] = {
    "none": plain_snapshot(),
    "R1": plain_snapshot(deletions=[MATURE]),
    "R2": plain_snapshot(flags=["mass modification"]),
    "R3": plain_snapshot(score=0.2),
    "R4": plain_snapshot(
        deletions=[MATURE.model_copy(update={"age_days": 1, "version_before": 1})],
        account_age_days=2,
    ),
    "R1+R3": plain_snapshot(deletions=[MATURE], score=0.2),
    "R1+R2+R3+R4": plain_snapshot(
        deletions=[MATURE], flags=["mass deletion"], score=0.1, account_age_days=1
    ),
}


async def replayed(prefix: str) -> EvidenceSnapshot:
    case_dir = next(p for name, p in CASES.items() if name.startswith(prefix))
    client = ReplayClient(case_dir)
    return await collect(client, client.case.changeset.id)


# ------------------------------------------------------------------------------ table and bands


def test_allowed_responses_match_the_documented_table() -> None:
    assert {n.value: [r.value for r in rs] for n, rs in ALLOWED_RESPONSES.items()} == {
        "consistent_edit": ["no_action_suggested", "welcome_and_tips"],
        "likely_good_faith_mistake": [
            "welcome_and_tips",
            "ask_source_question",
            "request_local_check",
        ],
        "possible_deliberate_damage": ["escalate_to_experienced_reviewer", "request_local_check"],
        "needs_local_knowledge": ["request_local_check", "ask_source_question"],
    }


@pytest.mark.parametrize(
    ("p_agg", "sensitivity", "band"),
    [
        (0.95, 0.0, Band.CONFIDENT),
        (0.80, 0.0, Band.CONFIDENT),
        (0.7999, 0.0, Band.UNSURE),
        (0.50, 0.0, Band.UNSURE),
        (0.4999, 0.0, Band.CANNOT_TELL),
        (0.25, 0.0, Band.CANNOT_TELL),
        (0.99, 0.30, Band.CONFIDENT),  # exactly at the cap is allowed
        (0.99, 0.3001, Band.CANNOT_TELL),  # above 0.30 forces cannot_tell
        (0.60, 0.9, Band.CANNOT_TELL),
    ],
)
def test_bands_use_the_config_thresholds(p_agg: float, sensitivity: float, band: Band) -> None:
    assert assign_band(p_agg, sensitivity, CONFIG.bands) is band


def test_band_thresholds_are_read_from_the_bands_argument() -> None:
    bands = Bands(confident_min=0.95, unsure_min=0.60, order_sensitivity_max=0.10)
    assert assign_band(0.9, 0.0, bands) is Band.UNSURE
    assert assign_band(0.9, 0.0, CONFIG.bands) is Band.CONFIDENT
    assert assign_band(0.97, 0.11, bands) is Band.CANNOT_TELL
    assert assign_band(0.55, 0.0, bands) is Band.CANNOT_TELL


# ---------------------------------------------------------------------------- reconciliation


def with_runner_up(top: Response, second: Response) -> dict[str, float]:
    rest = 0.2 / (len(Response) - 2)
    return {r.value: (0.5 if r is top else 0.3 if r is second else rest) for r in Response}


@pytest.mark.parametrize("nature", list(Nature))
@pytest.mark.parametrize("original", list(Response))
def test_reconciliation_table_exhaustive_ties_resolve_to_table_order(
    nature: Nature, original: Response
) -> None:
    probs = peaked(Response, original, 0.6)
    # A high damage probability keeps R5 out of the way so only the table acts here.
    rec = reconcile(nature, probs, [], nature_probs=damage(0.9), config=CONFIG)
    allowed = ALLOWED_RESPONSES[nature]
    assert rec.response is (original if original in allowed else allowed[0])
    assert rec.original is original
    assert rec.reconciled is (rec.response is not original)
    assert rec.rule_hits == ()


@pytest.mark.parametrize("nature", list(Nature))
@pytest.mark.parametrize("original", list(Response))
def test_reconciliation_takes_the_best_allowed_option_not_just_the_first(
    nature: Nature, original: Response
) -> None:
    for second in Response:
        if second is original:
            continue
        probs = with_runner_up(original, second)
        damage = peaked(Nature, Nature.POSSIBLE_DELIBERATE_DAMAGE, 0.9)
        rec = reconcile(nature, probs, [], nature_probs=damage, config=CONFIG)
        allowed = ALLOWED_RESPONSES[nature]
        best_allowed = max(allowed, key=lambda r: (probs[r.value], -allowed.index(r)))
        assert rec.response is (original if original in allowed else best_allowed)


def test_reconciliation_covers_all_twenty_cells() -> None:
    cells = {
        (n, r): reconcile(
            n,
            peaked(Response, r, 0.6),
            [],
            nature_probs=peaked(Nature, Nature.POSSIBLE_DELIBERATE_DAMAGE, 0.9),
            config=CONFIG,
        )
        for n, r in itertools.product(Nature, Response)
    }
    assert len(cells) == 20
    assert sum(not c.reconciled for c in cells.values()) == sum(
        len(v) for v in ALLOWED_RESPONSES.values()
    )
    for (n, _), c in cells.items():
        assert c.response in ALLOWED_RESPONSES[n]


@pytest.mark.parametrize("nature", list(Nature))
@pytest.mark.parametrize("original", list(Response))
def test_r1_never_leaves_no_action_suggested(nature: Nature, original: Response) -> None:
    rec = reconcile(
        nature,
        peaked(Response, original, 0.9),
        [hit(R1)],
        nature_probs=peaked(Nature, nature),
        config=CONFIG,
    )
    assert rec.response is not Response.NO_ACTION_SUGGESTED


def test_r1_turns_a_confident_no_action_into_welcome_and_tips() -> None:
    rec = reconcile(
        Nature.CONSISTENT_EDIT,
        peaked(Response, Response.NO_ACTION_SUGGESTED, 0.97),
        [hit(R1)],
        nature_probs=peaked(Nature, Nature.CONSISTENT_EDIT, 0.97),
        config=CONFIG,
    )
    assert rec.response is Response.WELCOME_AND_TIPS
    assert rec.reconciled is True
    assert rec.original is Response.NO_ACTION_SUGGESTED


def damage(p: float) -> dict[str, float]:
    rest = (1.0 - p) / 3
    return {n.value: (p if n is Nature.POSSIBLE_DELIBERATE_DAMAGE else rest) for n in Nature}


@pytest.mark.parametrize(
    ("p_damage", "r1", "downgraded"),
    [(0.49, False, True), (0.50, False, False), (0.90, False, False), (0.10, True, False)],
)
def test_r5_escalation_needs_a_damage_signal_or_r1(
    p_damage: float, r1: bool, downgraded: bool
) -> None:
    rec = reconcile(
        Nature.POSSIBLE_DELIBERATE_DAMAGE,
        peaked(Response, Response.ESCALATE_TO_EXPERIENCED_REVIEWER, 0.9),
        [hit(R1)] if r1 else [],
        nature_probs=damage(p_damage),
        config=CONFIG,
    )
    if downgraded:
        assert rec.response is Response.ASK_SOURCE_QUESTION
        assert rec.reconciled is True
        assert rec.original is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
        (r5,) = rec.rule_hits
        assert (r5.code, r5.severity) == (R5, Severity.INFO)
        assert r5.triggered_by["from"] == "escalate_to_experienced_reviewer"
        assert r5.triggered_by["to"] == "ask_source_question"
    else:
        assert rec.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
        assert rec.reconciled is False
        assert rec.rule_hits == ()


def test_r5_parameters_come_from_the_config() -> None:
    rules = [r for r in CONFIG.rules if r.code != R5] + [
        RuleConfig(
            code=R5,
            label="Escalation requires signal",
            params={"min_damage_probability": 0.9, "downgrade_to": "request_local_check"},
        )
    ]
    config = CONFIG.model_copy(update={"rules": rules})
    rec = reconcile(
        Nature.POSSIBLE_DELIBERATE_DAMAGE,
        peaked(Response, Response.ESCALATE_TO_EXPERIENCED_REVIEWER, 0.9),
        [],
        nature_probs=damage(0.8),
        config=config,
    )
    assert rec.response is Response.REQUEST_LOCAL_CHECK


@pytest.mark.parametrize(
    "bad",
    [
        {r.value: 0.2 for r in list(Response)[:4]},
        {**{r.value: 0.2 for r in Response}, "extra": 0.1},
    ],
)
def test_reconcile_rejects_missing_or_unknown_options(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="Response"):
        reconcile(Nature.CONSISTENT_EDIT, bad, [], nature_probs=damage(0.9), config=CONFIG)


# ------------------------------------------------------------------------------------ lanes


def test_lane_truth_table_examples() -> None:
    c, n, r = Band.CONFIDENT, Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED
    assert assign_lane(c, n, r, []) is Lane.LOOKS_CONSISTENT
    assert assign_lane(Band.UNSURE, n, r, []) is Lane.REVIEW_SUGGESTED
    assert assign_lane(Band.CANNOT_TELL, n, r, []) is Lane.REVIEW_SUGGESTED
    assert assign_lane(c, n, r, [hit(R1)]) is Lane.REVIEW_SUGGESTED
    assert assign_lane(c, n, r, [hit(R2)]) is Lane.REVIEW_SUGGESTED
    assert assign_lane(c, n, r, [hit(R4)]) is Lane.REVIEW_SUGGESTED
    assert assign_lane(c, n, r, [hit(R3)]) is Lane.INSUFFICIENT_EVIDENCE
    assert (
        assign_lane(c, Nature.NEEDS_LOCAL_KNOWLEDGE, Response.ASK_SOURCE_QUESTION, [])
        is Lane.NEEDS_LOCAL_KNOWLEDGE
    )
    assert (
        assign_lane(c, Nature.LIKELY_GOOD_FAITH_MISTAKE, Response.REQUEST_LOCAL_CHECK, [])
        is Lane.NEEDS_LOCAL_KNOWLEDGE
    )
    assert (
        assign_lane(
            c, Nature.POSSIBLE_DELIBERATE_DAMAGE, Response.ESCALATE_TO_EXPERIENCED_REVIEWER, []
        )
        is Lane.REVIEW_SUGGESTED
    )
    assert assign_lane(None, None, None, []) is Lane.RULES_ONLY


def test_lane_is_never_below_the_rule_floor_for_any_model_output() -> None:
    """Property: across (band, nature, response, rules) no model output undercuts a rule."""
    bands: list[Band | None] = [None, *Band]
    natures: list[Nature | None] = [None, *Nature]
    responses: list[Response | None] = [None, *Response]
    subsets = [
        [hit(c) for c, on in zip(EVIDENCE_CODES, mask, strict=True) if on]
        for mask in itertools.product([False, True], repeat=4)
    ]
    checked = 0
    for hits, band, nature, response in itertools.product(subsets, bands, natures, responses):
        lane = assign_lane(band, nature, response, hits)
        assert LANE_REVIEW_LEVEL[lane] >= lane_floor(hits), (hits, band, nature, response, lane)
        if any(h.code == R3 for h in hits):
            assert lane is Lane.INSUFFICIENT_EVIDENCE
        if hits:
            assert lane is not Lane.LOOKS_CONSISTENT
        if lane is Lane.LOOKS_CONSISTENT:
            assert (band, nature) == (Band.CONFIDENT, Nature.CONSISTENT_EDIT)
        checked += 1
    assert checked == 16 * 4 * 5 * 6


def test_lane_floor_values() -> None:
    assert lane_floor([]) == 0
    assert lane_floor([hit(R1)]) == lane_floor([hit(R2)]) == lane_floor([hit(R4)]) == 1
    assert lane_floor([hit(R1), hit(R3)]) == 2
    assert lane_floor([hit(R5), hit(R6)]) == 0


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_gate_never_undercuts_rules_over_a_model_output_grid(scenario: str) -> None:
    snap = SCENARIOS[scenario]
    hits = evaluate_rules(snap, CONFIG)
    codes = {h.code for h in hits}
    floor = lane_floor(hits)
    for nature, response, p, sensitivity in itertools.product(
        Nature, Response, (0.3, 0.6, 0.95), (0.0, 0.5)
    ):
        out = outputs(nature, response, p_nature=p, p_response=p, sensitivity=sensitivity)
        res = evaluate_run(snap, out, CONFIG)
        assert LANE_REVIEW_LEVEL[res.lane] >= floor
        assert codes <= {h.code for h in res.rule_hits}
        if R1 in codes:
            assert res.response is not Response.NO_ACTION_SUGGESTED
        if codes & set(EVIDENCE_CODES):
            assert res.lane is not Lane.LOOKS_CONSISTENT
        if R3 in codes:
            assert res.lane is Lane.INSUFFICIENT_EVIDENCE
        assert res.response is not None
        assert res.reconciled is (res.reconciled_from is not None)
        assert res.reconciled_from is not res.response
        if sensitivity > CONFIG.bands.order_sensitivity_max:
            assert res.band is Band.CANNOT_TELL


# -------------------------------------------------------------------- the gate on fixtures


async def test_r1_on_fixture_04_forbids_consistent_and_no_action_whatever_the_model_says() -> None:
    snap = await replayed("04")
    confident_consistent = outputs(
        Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, p_nature=0.99, p_response=0.99
    )
    res = evaluate_run(snap, confident_consistent, CONFIG)

    assert {h.code for h in res.rule_hits} >= {R1, R2, R3}
    assert res.band is Band.CONFIDENT
    assert res.lane is Lane.INSUFFICIENT_EVIDENCE  # R3 also fires on this fixture (decided)
    assert res.lane is not Lane.LOOKS_CONSISTENT
    assert res.response is not Response.NO_ACTION_SUGGESTED
    assert res.reconciled is True
    assert res.reconciled_from is Response.NO_ACTION_SUGGESTED

    # Remove R3 and R2 so only R1 acts: the lane still cannot be looks_consistent.
    only_r1 = snap.model_copy(
        update={
            "coverage": snap.coverage.model_copy(update={"score": 1.0, "history_gaps": []}),
            "flags": [],
        }
    )
    assert {h.code for h in evaluate_rules(only_r1, CONFIG)} == {R1}
    res_r1 = evaluate_run(only_r1, confident_consistent, CONFIG)
    assert res_r1.lane is Lane.REVIEW_SUGGESTED
    assert res_r1.response is Response.WELCOME_AND_TIPS
    assert res_r1.response is not Response.NO_ACTION_SUGGESTED


@pytest.mark.parametrize("prefix", ["03", "06"])
async def test_r3_on_fixtures_03_and_06_forces_insufficient_evidence(prefix: str) -> None:
    snap = await replayed(prefix)
    assert R3 in {h.code for h in evaluate_rules(snap, CONFIG)}
    for nature, response in itertools.product(Nature, Response):
        res = evaluate_run(snap, outputs(nature, response, p_nature=0.99, p_response=0.99), CONFIG)
        assert res.lane is Lane.INSUFFICIENT_EVIDENCE


async def test_failed_run_is_rules_only_with_rule_hits_present() -> None:
    snap = await replayed("04")
    covered = snap.model_copy(
        update={"coverage": snap.coverage.model_copy(update={"score": 1.0, "history_gaps": []})}
    )
    res = evaluate_run(covered, None, CONFIG, failure_code="decider_unavailable")

    assert res.lane is Lane.RULES_ONLY
    assert res.band is None
    assert res.nature is None
    assert res.response is None
    assert res.reconciliation_record() is None
    codes = [h.code for h in res.rule_hits]
    assert codes == [R1, R2, R6]
    assert res.rule_hits[-1].triggered_by == {"failure_code": "decider_unavailable"}

    result = AnalysisResult(
        config_version=CONFIG.version,
        status=RunStatus.FAILED,
        failure_code="decider_unavailable",
        **res.result_fields(),
    )
    assert result.lane is Lane.RULES_ONLY
    assert allowed_comment_types(result) == frozenset()


async def test_failed_run_with_insufficient_coverage_stays_insufficient_evidence() -> None:
    """Coverage decides `insufficient_evidence` deterministically, with or without a model."""
    res = evaluate_run(SCENARIOS["R3"], None, CONFIG, failure_code="schema")
    assert res.lane is Lane.INSUFFICIENT_EVIDENCE
    assert [h.code for h in res.rule_hits] == [R3, R6]


def test_order_sensitivity_above_the_cap_means_cannot_tell() -> None:
    snap = SCENARIOS["none"]
    sharp = outputs(Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, sensitivity=0.0)
    unstable = outputs(Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, sensitivity=0.31)

    assert evaluate_run(snap, sharp, CONFIG).lane is Lane.LOOKS_CONSISTENT
    res = evaluate_run(snap, unstable, CONFIG)
    assert res.band is Band.CANNOT_TELL
    assert res.lane is Lane.REVIEW_SUGGESTED
    assert res.order_sensitivity == 0.31


def test_thresholds_in_the_config_change_the_outcome() -> None:
    snap = SCENARIOS["none"]
    out = outputs(Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, p_nature=0.9)
    assert evaluate_run(snap, out, CONFIG).band is Band.CONFIDENT
    strict = CONFIG.model_copy(
        update={"bands": Bands(confident_min=0.95, unsure_min=0.5, order_sensitivity_max=0.3)}
    )
    res = evaluate_run(snap, out, strict)
    assert res.band is Band.UNSURE
    assert res.lane is Lane.REVIEW_SUGGESTED


def test_outcome_maps_onto_an_analysis_result_and_receipt_record() -> None:
    out = outputs(Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED, p_nature=0.97)
    res = evaluate_run(plain_snapshot(deletions=[MATURE]), out, CONFIG)
    result = AnalysisResult(
        config_version=CONFIG.version, status=RunStatus.SUCCEEDED, **res.result_fields()
    )

    assert result.response is Response.WELCOME_AND_TIPS
    assert result.reconciled is True
    assert result.reconciled_from is Response.NO_ACTION_SUGGESTED
    assert [h.code for h in result.rules_fired] == [R1]
    assert set(result.nature_probabilities) == set(Nature)
    record = res.reconciliation_record()
    assert record is not None
    assert record.model_dump(by_alias=True) == {
        "applied": True,
        "from": "no_action_suggested",
        "to": "welcome_and_tips",
    }


# fixture -> (nature, response) the expected.json states; None where it leaves the model open.
@pytest.mark.parametrize("name", list(CASES))
async def test_every_fixture_lands_in_its_expected_lane(name: str) -> None:
    client = ReplayClient(CASES[name])
    snap = await collect(client, client.case.changeset.id)
    expected = client.case.expected
    nature = expected.nature or Nature.CONSISTENT_EDIT
    response = expected.response or Response.NO_ACTION_SUGGESTED

    res = evaluate_run(snap, outputs(nature, response, p_nature=0.9, p_response=0.9), CONFIG)

    assert sorted({h.code for h in res.rule_hits} - {R5}) == sorted(expected.rules)
    if expected.lane is not None:
        assert res.lane is expected.lane
    assert res.nature is nature
    if not expected.rules:
        assert res.response is response and res.reconciled is False


# -------------------------------------------------------------------- allowed comment types


def result_for(
    response: Response | None,
    *,
    status: RunStatus = RunStatus.SUCCEEDED,
    hits: Sequence[RuleHit] = (),
) -> AnalysisResult:
    return AnalysisResult(
        config_version=CONFIG.version,
        status=status,
        lane=Lane.REVIEW_SUGGESTED,
        response=response,
        rules_fired=list(hits),
    )


@pytest.mark.parametrize("response", list(Response))
def test_allowed_comment_types_follow_the_reconciled_response(response: Response) -> None:
    expected = frozenset({response}) if response in COMMENT_TYPES else frozenset()
    assert allowed_comment_types(result_for(response)) == expected


def test_comment_types_exclude_no_action_and_escalation() -> None:
    assert Response.NO_ACTION_SUGGESTED not in COMMENT_TYPES
    assert Response.ESCALATE_TO_EXPERIENCED_REVIEWER not in COMMENT_TYPES


def test_allowed_comment_types_for_failed_or_missing_response_is_empty() -> None:
    assert allowed_comment_types(result_for(None)) == frozenset()
    failed = result_for(Response.WELCOME_AND_TIPS, status=RunStatus.FAILED)
    assert allowed_comment_types(failed) == frozenset()


@pytest.mark.parametrize("response", list(COMMENT_TYPES))
def test_r3_limits_drafting_to_a_source_question(response: Response) -> None:
    r3 = RuleHit(
        code=R3,
        label="Coverage",
        severity=Severity.WARN,
        triggered_by={"drafting_limited_to": "ask_source_question"},
    )
    assert allowed_comment_types(result_for(response, hits=[r3])) == {Response.ASK_SOURCE_QUESTION}


def test_r3_does_not_enable_drafting_for_non_comment_responses() -> None:
    r3 = hit(R3)
    for response in (Response.NO_ACTION_SUGGESTED, Response.ESCALATE_TO_EXPERIENCED_REVIEWER):
        assert allowed_comment_types(result_for(response, hits=[r3])) == frozenset()


def test_r3_limit_defaults_to_source_question_and_rejects_bad_values() -> None:
    plain = result_for(Response.WELCOME_AND_TIPS, hits=[hit(R3)])
    assert allowed_comment_types(plain) == {Response.ASK_SOURCE_QUESTION}
    bad = RuleHit(
        code=R3, label="Coverage", severity=Severity.WARN, triggered_by={"drafting_limited_to": "x"}
    )
    assert allowed_comment_types(result_for(Response.WELCOME_AND_TIPS, hits=[bad])) == frozenset()
    non_comment = RuleHit(
        code=R3,
        label="Coverage",
        severity=Severity.WARN,
        triggered_by={"drafting_limited_to": "no_action_suggested"},
    )
    assert (
        allowed_comment_types(result_for(Response.WELCOME_AND_TIPS, hits=[non_comment]))
        == frozenset()
    )


async def test_real_fixture_03_run_only_allows_a_source_question() -> None:
    snap = await replayed("03")
    out = outputs(Nature.LIKELY_GOOD_FAITH_MISTAKE, Response.WELCOME_AND_TIPS)
    res = evaluate_run(snap, out, CONFIG)
    result = AnalysisResult(
        config_version=CONFIG.version, status=RunStatus.SUCCEEDED, **res.result_fields()
    )
    assert allowed_comment_types(result) == {Response.ASK_SOURCE_QUESTION}


def test_no_model_hit_is_the_only_rule_a_failed_run_adds() -> None:
    res = evaluate_run(SCENARIOS["none"], None, CONFIG)
    assert [h.code for h in res.rule_hits] == [no_model_hit(CONFIG).code] == [R6]
