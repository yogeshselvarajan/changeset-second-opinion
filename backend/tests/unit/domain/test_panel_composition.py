"""Fact-panel composition: table rows, rule floor, unknown reading and parsed cross-checks."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.enums import Band, Lane, Nature, Response, Severity
from cso.domain.lanes import (
    LANE_REVIEW_LEVEL,
    PolicyOutcome,
    assign_lane,
    compose_panel,
    cross_check_panel,
    evaluate_panel_run,
    lane_floor,
)
from cso.domain.models import EvidenceSnapshot, RuleHit
from cso.domain.panel import (
    ADVISORY_PROBES,
    CROSS_CHECK_ONLY_PROBES,
    PANEL_NOUL_IDS,
    AdvisoryNature,
    FactPanel,
    NoulReading,
    classify,
)
from cso.domain.policy import (
    MASS_RETAG_MIN_ELEMENTS,
    R1,
    R2,
    R3,
    R4,
    ParsedFacts,
    changed_key_counts,
    evaluate_rules,
    mass_retag_key,
    new_account_first_edits,
    parsed_facts,
    rule_codes,
)

CONFIG = CommunityConfig.load()
CASES = {p.name: p for p in sorted((Path(__file__).parents[3] / "fixtures" / "cases").iterdir())}
YES, NO, UNK = 0.95, 0.05, 0.5
COMPOSED = tuple(i for i in PANEL_NOUL_IDS if i not in ADVISORY_PROBES | CROSS_CHECK_ONLY_PROBES)
SHORT = {
    "M": "mature_feature_deleted",
    "N": "nonsense_or_offensive_values",
    "C": "comment_matches_changes",
    "V": "conventions_followed",
    "A": "new_account_first_edits",
    "D": "deleted_own_recent_additions",
    "W": "real_world_change_claimed",
    "S": "discussion_cites_source",
    "T": "mass_retag_single_key",
    "E": "evidence_sufficient",
}


def panel(**by_short: float) -> FactPanel:
    """A reassured panel (concern probes no, C, V and E yes) with short-letter overrides."""
    probs = {i: NO for i in PANEL_NOUL_IDS}
    probs.update({SHORT[letter]: YES for letter in "CVE"})
    for letter, p in by_short.items():
        probs[SHORT[letter]] = p
    return panel_from(probs)


def panel_from(probs: dict[str, float]) -> FactPanel:
    readings = {i: NoulReading(id=i, probability=p, state=classify(p)) for i, p in probs.items()}
    return FactPanel(
        low=0.35,
        high=0.65,
        readings=readings,
        advisory_nature=AdvisoryNature(
            order=["a", "b"], probabilities={"a": 0.5, "b": 0.5}, choice="a", confidence=0.0
        ),
        ids=list(probs),
    )


def hit(code: str) -> RuleHit:
    return RuleHit(code=code, label=code, severity=Severity.WARN)


async def snapshot_of(name: str) -> EvidenceSnapshot:
    case = CASES[name]
    changeset_id = json.loads((case / "changeset.json").read_text(encoding="utf-8"))["changeset"][
        "id"
    ]
    return await collect(ReplayClient(case), changeset_id)


# ------------------------------------------------------------------------------ table rows


def test_reassured_panel_with_no_rules_is_consistent_and_looks_consistent() -> None:
    comp = compose_panel(panel(C=YES, V=YES, E=YES), [], CONFIG)
    assert (comp.nature, comp.response) == (Nature.CONSISTENT_EDIT, Response.NO_ACTION_SUGGESTED)
    assert (comp.nature_row, comp.response_row) == ("N4", "P5")
    assert comp.band is Band.CONFIDENT
    assert assign_lane(comp.band, comp.nature, comp.response, []) is Lane.LOOKS_CONSISTENT


@pytest.mark.parametrize(
    ("overrides", "response", "response_row", "nature", "nature_row"),
    [
        (
            {"N": YES},
            Response.ESCALATE_TO_EXPERIENCED_REVIEWER,
            "P1",
            Nature.POSSIBLE_DELIBERATE_DAMAGE,
            "N1",
        ),
        (
            {"M": YES, "A": YES},
            Response.ESCALATE_TO_EXPERIENCED_REVIEWER,
            "P1",
            Nature.POSSIBLE_DELIBERATE_DAMAGE,
            "N1",
        ),
        (
            {"W": YES, "T": YES},
            Response.ESCALATE_TO_EXPERIENCED_REVIEWER,
            "P1",
            Nature.POSSIBLE_DELIBERATE_DAMAGE,
            "N1",
        ),
        (
            {"W": YES, "S": YES},
            Response.REQUEST_LOCAL_CHECK,
            "P2",
            Nature.NEEDS_LOCAL_KNOWLEDGE,
            "N2",
        ),
        ({"W": YES}, Response.ASK_SOURCE_QUESTION, "P3", Nature.NEEDS_LOCAL_KNOWLEDGE, "N2"),
        ({"A": YES}, Response.WELCOME_AND_TIPS, "P4", Nature.LIKELY_GOOD_FAITH_MISTAKE, "N3"),
        (
            {"V": YES, "C": NO},
            Response.WELCOME_AND_TIPS,
            "P4",
            Nature.LIKELY_GOOD_FAITH_MISTAKE,
            "N3",
        ),
        (
            {"C": YES, "V": NO},
            Response.WELCOME_AND_TIPS,
            "P4",
            Nature.LIKELY_GOOD_FAITH_MISTAKE,
            "N3",
        ),
        ({"M": YES}, Response.ASK_SOURCE_QUESTION, "P6", Nature.NEEDS_LOCAL_KNOWLEDGE, "N5"),
        (
            {"V": UNK},
            Response.ASK_SOURCE_QUESTION,
            "P6",
            Nature.NEEDS_LOCAL_KNOWLEDGE,
            "N5",
        ),
    ],
)
def test_table_rows(
    overrides: dict[str, float],
    response: Response,
    response_row: str,
    nature: Nature,
    nature_row: str,
) -> None:
    comp = compose_panel(panel(**overrides), [], CONFIG)
    assert (comp.response, comp.response_row) == (response, response_row)
    assert (comp.nature, comp.nature_row) == (nature, nature_row)


def test_r1_alone_escalates_with_needs_local_knowledge() -> None:
    comp = compose_panel(panel(M=YES), [hit(R1)], CONFIG)
    assert comp.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
    assert comp.nature is Nature.NEEDS_LOCAL_KNOWLEDGE


def test_unknown_never_triggers_a_stronger_action_it_only_withholds_reassurance() -> None:
    # Every concern probe unknown, reassurance probes yes: not reassured, but nothing escalates.
    comp = compose_panel(panel(M=UNK, N=UNK, A=UNK, W=UNK, T=UNK, C=YES, V=YES, E=YES), [], CONFIG)
    assert comp.response is Response.ASK_SOURCE_QUESTION
    assert comp.nature is Nature.NEEDS_LOCAL_KNOWLEDGE
    assert comp.band is Band.UNSURE or comp.band is Band.CANNOT_TELL


@pytest.mark.parametrize(
    ("unknowns", "band"),
    [
        (0, Band.CONFIDENT),
        (1, Band.CONFIDENT),
        (2, Band.UNSURE),
        (3, Band.UNSURE),
        (4, Band.CANNOT_TELL),
    ],
)
def test_band_counts_unknown_composed_probes(unknowns: int, band: Band) -> None:
    letters = ["M", "N", "A", "W"][:unknowns]
    comp = compose_panel(panel(**{letter: UNK for letter in letters}), [], CONFIG)
    assert comp.band is band
    assert len(comp.unknown) == unknowns


def test_missing_probe_is_refused_not_defaulted() -> None:
    probs = {i: NO for i in PANEL_NOUL_IDS if i != "discussion_cites_source"}
    with pytest.raises(ValueError, match="discussion_cites_source"):
        compose_panel(panel_from(probs), [], CONFIG)


def test_own_recent_deletions_probe_withholds_reassurance_but_never_escalates() -> None:
    base = compose_panel(panel(), [], CONFIG)
    assert base.response_row == "P5"  # reassured when D reads no
    for state in (UNK, YES):
        comp = compose_panel(panel(D=state), [], CONFIG)
        assert comp.response_row != "P5"  # silence or a yes does not reassure
        assert comp.response is not Response.ESCALATE_TO_EXPERIENCED_REVIEWER
    # one more concern signal plus D is still below the two-signal escalation rule
    assert compose_panel(panel(D=YES, A=YES), [], CONFIG).response_row == "P4"
    # but D never overrides a rule or the signals that do escalate
    assert compose_panel(panel(D=YES, M=YES, T=YES), [], CONFIG).response_row == "P1"


def test_unknown_creators_read_as_unknown_whatever_the_model_answered() -> None:
    facts = ParsedFacts(
        mature_feature_deleted=False,
        new_account_first_edits=False,
        deleted_own_recent_additions=None,
        mass_retag_single_key=False,
        evidence_sufficient=True,
    )
    comp = compose_panel(panel(D=NO), [], CONFIG, facts)
    assert "deleted_own_recent_additions" in comp.unknown
    assert comp.response_row != "P5"


# ---------------------------------------------------------------- exhaustive safety properties

RULE_SETS = ([], [R1], [R2], [R3], [R4], [R1, R2, R3, R4])
LEVELS = (NO, UNK, YES)


def test_no_panel_state_undercuts_a_rule_or_reassures_through_unknowns() -> None:
    checked = 0
    for states in itertools.product(LEVELS, repeat=len(COMPOSED)):
        probs = {i: NO for i in PANEL_NOUL_IDS}
        probs.update(dict(zip(COMPOSED, states, strict=True)))
        fact_panel = panel_from(probs)
        for codes in RULE_SETS:
            hits = [hit(c) for c in codes]
            comp = compose_panel(fact_panel, hits, CONFIG)
            lane = assign_lane(comp.band, comp.nature, comp.response, hits)
            assert LANE_REVIEW_LEVEL[lane] >= lane_floor(hits)
            if lane is Lane.LOOKS_CONSISTENT:
                assert not codes
                assert comp.response is Response.NO_ACTION_SUGGESTED
            if comp.response is Response.NO_ACTION_SUGGESTED:
                # S is only read when a real-world change is claimed, so unknown S is harmless
                assert not set(comp.unknown) - {"discussion_cites_source"}
                assert not codes
            if R3 in codes:
                assert lane is Lane.INSUFFICIENT_EVIDENCE
            if R1 in codes:
                assert comp.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
                assert comp.response is not Response.NO_ACTION_SUGGESTED
            checked += 1
    assert checked == 3 ** len(COMPOSED) * len(RULE_SETS)


FLOORED = (
    "mature_feature_deleted",
    "new_account_first_edits",
    "mass_retag_single_key",
    "deleted_own_recent_additions",
)


def facts_of(m: bool, a: bool | None, t: bool, d: bool | None) -> ParsedFacts:
    return ParsedFacts(
        mature_feature_deleted=m,
        new_account_first_edits=a,
        deleted_own_recent_additions=d,
        mass_retag_single_key=t,
        evidence_sufficient=True,
    )


def test_parsed_facts_are_a_floor_of_caution_over_all_readings_facts_and_rules() -> None:
    """Model readings x parsed facts x rule sets: no state is less cautious than the facts need."""
    checked = 0
    tri = (True, False, None)
    for base_other in (YES, NO):  # reassurance probes (C, V) all yes, or all no
        for model in itertools.product(LEVELS, repeat=len(FLOORED)):
            probs = {i: NO for i in PANEL_NOUL_IDS}
            probs.update({SHORT[k]: base_other for k in "CV"})
            probs.update(dict(zip(FLOORED, model, strict=True)))
            fact_panel = panel_from(probs)
            for m, a, t, d in itertools.product((True, False), tri, (True, False), tri):
                facts = facts_of(m, a, t, d)
                fact_by_id = dict(zip(FLOORED, (m, a, t, d), strict=True))
                for codes in RULE_SETS:
                    hits = [hit(c) for c in codes]
                    comp = compose_panel(fact_panel, hits, CONFIG, facts)
                    lane = assign_lane(comp.band, comp.nature, comp.response, hits)
                    for probe, fact in fact_by_id.items():
                        if fact is True:
                            assert probe in comp.yes
                        elif fact is None:
                            assert probe in comp.unknown
                    if any(fact is True for fact in fact_by_id.values()):
                        assert comp.response is not Response.NO_ACTION_SUGGESTED
                        assert comp.nature is not Nature.CONSISTENT_EDIT
                        assert lane is not Lane.LOOKS_CONSISTENT
                    checked += 1
    assert checked == 2 * 3**4 * 2 * 3 * 2 * 3 * len(RULE_SETS)


def test_a_model_no_cannot_override_a_true_parsed_fact_into_looks_consistent() -> None:
    reassuring = panel(C=YES, V=YES, E=YES)  # every concern probe reads no
    facts = facts_of(m=False, a=True, t=False, d=False)
    comp = compose_panel(reassuring, [], CONFIG, facts)
    assert "new_account_first_edits" in comp.yes
    assert comp.response is not Response.NO_ACTION_SUGGESTED
    assert comp.nature is not Nature.CONSISTENT_EDIT
    assert assign_lane(comp.band, comp.nature, comp.response, []) is not Lane.LOOKS_CONSISTENT
    for fact_args in (
        {"m": True, "a": False, "t": False, "d": False},
        {"m": False, "a": False, "t": True, "d": False},
        {"m": False, "a": False, "t": False, "d": True},
    ):
        comp = compose_panel(reassuring, [], CONFIG, facts_of(**fact_args))
        assert comp.response is not Response.NO_ACTION_SUGGESTED


def test_a_false_parsed_fact_keeps_the_models_extra_caution() -> None:
    facts = facts_of(m=False, a=False, t=False, d=False)
    comp = compose_panel(panel(M=YES, T=YES), [], CONFIG, facts)
    assert comp.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER


# ---------------------------------------------------------------------------- fixtures


async def outcome_for(name: str, fact_panel: FactPanel) -> tuple[PolicyOutcome, EvidenceSnapshot]:
    snapshot = await snapshot_of(name)
    return evaluate_panel_run(snapshot, fact_panel, CONFIG), snapshot


async def test_fixture_01_looks_consistent() -> None:
    outcome, _ = await outcome_for("01-legitimate", panel(C=YES, V=YES, E=YES))
    assert outcome.lane is Lane.LOOKS_CONSISTENT
    assert outcome.nature is Nature.CONSISTENT_EDIT
    assert rule_codes(outcome.rule_hits) == []


async def test_fixture_02_composes_to_likely_good_faith_mistake() -> None:
    outcome, _ = await outcome_for("02-good-faith-mistake", panel(A=YES, V=NO, C=UNK, E=YES))
    assert outcome.nature is Nature.LIKELY_GOOD_FAITH_MISTAKE
    assert outcome.response is Response.WELCOME_AND_TIPS
    assert outcome.lane is Lane.REVIEW_SUGGESTED


async def test_fixture_08_adversarial_text_composes_like_its_control() -> None:
    control, _ = await outcome_for("02-good-faith-mistake", panel(A=YES, V=NO, C=UNK, E=YES))
    attacked, _ = await outcome_for("08-adversarial-text", panel(A=YES, V=NO, C=UNK, E=YES))
    assert (attacked.nature, attacked.response, attacked.lane) == (
        control.nature,
        control.response,
        control.lane,
    )


async def test_fixture_04_composes_to_escalate_and_rules_keep_the_lane() -> None:
    outcome, _ = await outcome_for("04-large-deletion", panel(M=YES, E=NO))
    assert rule_codes(outcome.rule_hits) == [R1, R2, R3]
    assert outcome.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
    assert outcome.nature is Nature.NEEDS_LOCAL_KNOWLEDGE
    assert outcome.lane is Lane.INSUFFICIENT_EVIDENCE  # R3 decides the lane from coverage


async def test_fixture_04_confident_consistent_panel_cannot_hide_the_deletion() -> None:
    outcome, _ = await outcome_for("04-large-deletion", panel(C=YES, V=YES, E=YES))
    assert outcome.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
    assert outcome.response is not Response.NO_ACTION_SUGGESTED
    assert outcome.lane is Lane.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("name", ["03-insufficient-evidence", "06-history-gap"])
async def test_r3_fixtures_are_insufficient_whatever_the_panel_says(name: str) -> None:
    outcome, _ = await outcome_for(name, panel(C=YES, V=YES, E=YES))
    assert R3 in rule_codes(outcome.rule_hits)
    assert outcome.lane is Lane.INSUFFICIENT_EVIDENCE


async def test_fixture_05_asks_for_a_local_check() -> None:
    outcome, _ = await outcome_for("05-conflicting-discussion", panel(W=YES, S=YES, C=YES, V=YES))
    assert outcome.response is Response.REQUEST_LOCAL_CHECK
    assert outcome.nature is Nature.NEEDS_LOCAL_KNOWLEDGE
    assert outcome.lane is Lane.NEEDS_LOCAL_KNOWLEDGE


async def test_fixture_07_missing_profile_is_read_cautiously() -> None:
    outcome, snapshot = await outcome_for("07-provider-timeout", panel(A=UNK, C=YES, V=YES, E=YES))
    assert snapshot.user is None
    assert outcome.response is not Response.NO_ACTION_SUGGESTED
    assert outcome.lane is not Lane.LOOKS_CONSISTENT


async def test_failed_panel_run_is_rules_only_with_r6() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    outcome = evaluate_panel_run(snapshot, None, CONFIG, failure_code="decider_unavailable")
    assert outcome.lane is Lane.INSUFFICIENT_EVIDENCE  # R3 outranks R6
    assert "R6" in rule_codes(outcome.rule_hits)
    assert outcome.panel is None and outcome.response is None


# ------------------------------------------------------------------- parsed facts and checks


async def test_parsed_facts_per_fixture() -> None:
    expected = {
        "01-legitimate": (False, False, False),
        # no changesets_count tag: a current total of 10 or more cannot show the edit-time
        # count was 10 or more, so an old account reads unknown (ADR-009, Amendment 2)
        "03-insufficient-evidence": (False, None, True),
        "04-large-deletion": (True, None, False),
    }
    for name, (mature, new_account, mass) in expected.items():
        snapshot = await snapshot_of(name)
        facts = parsed_facts(snapshot, CONFIG)
        assert facts.mature_feature_deleted is mature, name
        assert facts.new_account_first_edits is new_account, name
        assert facts.mass_retag_single_key is mass, name


async def test_mass_retag_counts_elements_per_key_over_detailed_elements() -> None:
    snapshot = await snapshot_of("03-insufficient-evidence")
    counts = dict(changed_key_counts(snapshot))
    assert counts["highway"] > MASS_RETAG_MIN_ELEMENTS
    assert mass_retag_key(snapshot) == ("highway", counts["highway"])
    ordered = changed_key_counts(snapshot)
    assert ordered == sorted(ordered, key=lambda kv: (-kv[1], kv[0]))


async def test_unknown_profile_has_no_new_account_fact() -> None:
    snapshot = await snapshot_of("07-provider-timeout")
    assert new_account_first_edits(snapshot) is None
    assert parsed_facts(snapshot, CONFIG).new_account_first_edits is None


async def test_cross_checks_agree_disagree_undecided_and_not_applicable() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    assert cross_check_panel(panel(M=YES), snapshot, CONFIG)["mature_feature_deleted"] == "agree"
    assert cross_check_panel(panel(M=NO), snapshot, CONFIG)["mature_feature_deleted"] == "disagree"
    assert (
        cross_check_panel(panel(M=UNK), snapshot, CONFIG)["mature_feature_deleted"] == "undecided"
    )
    timeout = await snapshot_of("07-provider-timeout")
    assert cross_check_panel(panel(), timeout, CONFIG)["new_account_first_edits"] == "n/a"


async def test_cross_check_never_changes_the_gate() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    # The panel disagrees with the parsed mature deletion; the rule still fires and still wins.
    outcome = evaluate_panel_run(snapshot, panel(M=NO, C=YES, V=YES, E=YES), CONFIG)
    assert R1 in rule_codes(outcome.rule_hits)
    assert outcome.cross_checks["mature_feature_deleted"] == "disagree"
    assert outcome.response is Response.ESCALATE_TO_EXPERIENCED_REVIEWER
    assert rule_codes(evaluate_rules(snapshot, CONFIG)) == rule_codes(outcome.rule_hits)


def test_cross_check_only_probe_never_changes_the_composition() -> None:
    base = compose_panel(panel(), [], CONFIG)
    for state in (NO, UNK, YES):
        assert compose_panel(panel(E=state), [], CONFIG) == base
    assert (base.response, base.nature) == (Response.NO_ACTION_SUGGESTED, Nature.CONSISTENT_EDIT)


async def test_missing_profile_reads_the_account_probe_as_unknown_whatever_the_model_said() -> None:
    outcome, snapshot = await outcome_for("07-provider-timeout", panel(A=NO))
    assert snapshot.user is None
    assert outcome.composition is not None
    assert "new_account_first_edits" in outcome.composition.unknown
    assert outcome.response is not Response.NO_ACTION_SUGGESTED
    assert outcome.lane is not Lane.LOOKS_CONSISTENT


async def test_known_profile_keeps_the_model_answer_for_the_account_probe() -> None:
    outcome, snapshot = await outcome_for("01-legitimate", panel(A=NO))
    assert snapshot.user is not None
    assert outcome.composition is not None
    assert "new_account_first_edits" not in outcome.composition.unknown
    assert outcome.lane is Lane.LOOKS_CONSISTENT


async def test_deleting_or_creating_elements_is_not_a_mass_retag() -> None:
    from cso.domain.enums import ChangeAction

    snapshot = await snapshot_of("03-insufficient-evidence")
    assert mass_retag_key(snapshot) is not None  # 38 modified elements changed `highway`
    for action in (ChangeAction.DELETE, ChangeAction.CREATE):
        rewritten = snapshot.model_copy(
            update={
                "elements": [e.model_copy(update={"action": action}) for e in snapshot.elements]
            }
        )
        assert mass_retag_key(rewritten) is None, action
        assert not changed_key_counts(rewritten)
