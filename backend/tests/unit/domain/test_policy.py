"""Policy gate R1-R4: parsed evidence in, rule hits out; replayed over all fixtures."""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig, ConfigError, RuleConfig
from cso.domain.enums import (
    ChangeAction,
    CoverageGapReason,
    EvidenceSource,
    OsmType,
    Response,
    Severity,
)
from cso.domain.models import (
    ChangedObject,
    ChangesetMeta,
    Coverage,
    EvidenceSnapshot,
    HistoryGap,
    UserFacts,
)
from cso.domain.policy import (
    _DEFAULTS,
    R1,
    R2,
    R3,
    R4,
    coverage_insufficient,
    evaluate_rules,
    gap_ratio,
    mature_deletions,
    no_model_hit,
    rule_codes,
    rule_params,
)

CONFIG = CommunityConfig.load()
NOW = datetime(2026, 5, 1, tzinfo=UTC)
CASES = sorted((Path(__file__).parents[3] / "fixtures" / "cases").iterdir())


def element(
    osm_id: int = 1,
    *,
    action: ChangeAction = ChangeAction.DELETE,
    age_days: int | None = None,
    version_before: int | None = None,
) -> ChangedObject:
    return ChangedObject(
        osm_type=OsmType.WAY,
        osm_id=osm_id,
        action=action,
        version_after=(version_before or 0) + 1,
        version_before=version_before,
        age_days=age_days,
    )


def gaps(count: int) -> list[HistoryGap]:
    return [
        HistoryGap(osm_type=OsmType.WAY, osm_id=i, reason=CoverageGapReason.REDACTED)
        for i in range(count)
    ]


def snapshot(
    *,
    elements: list[ChangedObject] | None = None,
    flags: list[str] | None = None,
    coverage: Coverage | None = None,
    account_age_days: int | None = None,
    user: bool = True,
    element_counts: dict[ChangeAction, int] | None = None,
) -> EvidenceSnapshot:
    els = elements or []
    return EvidenceSnapshot(
        evidence_version="sha256:test",
        source=EvidenceSource.DERIVED,
        fetched_at=NOW,
        changeset=ChangesetMeta(id=1, created_at=NOW),
        user=UserFacts(account_age_days=account_age_days) if user else None,
        coverage=coverage
        or Coverage(elements_in_changeset=len(els), elements_detailed=len(els), score=1.0),
        elements=els,
        flags=flags or [],
        element_counts=element_counts or {},
    )


def with_rule(code: str, **params: object) -> CommunityConfig:
    rules = [r for r in CONFIG.rules if r.code != code]
    rules.append(RuleConfig(code=code, label=f"custom {code}", params=params))
    return CONFIG.model_copy(update={"rules": rules})


# ------------------------------------------------------------------------------------- R1


@pytest.mark.parametrize(
    ("age_days", "version_before", "fires"),
    [
        (366, None, True),
        (365, None, False),  # strictly older than min_age_days
        (None, 5, True),
        (None, 4, False),  # at least min_prior_versions
        (10, 5, True),
        (366, 1, True),
        (None, None, False),  # unknown age and version cannot trigger
        (0, 0, False),
    ],
)
def test_r1_thresholds(age_days: int | None, version_before: int | None, fires: bool) -> None:
    snap = snapshot(elements=[element(age_days=age_days, version_before=version_before)])
    assert (R1 in rule_codes(evaluate_rules(snap, CONFIG))) is fires


def test_r1_ignores_non_deletions() -> None:
    snap = snapshot(
        elements=[
            element(1, action=ChangeAction.MODIFY, age_days=4000, version_before=9),
            element(2, action=ChangeAction.CREATE, age_days=4000, version_before=9),
        ]
    )
    assert evaluate_rules(snap, CONFIG) == []


def test_r1_hit_is_a_block_and_names_the_elements() -> None:
    snap = snapshot(elements=[element(7, age_days=2000, version_before=1), element(8)])
    (hit,) = evaluate_rules(snap, CONFIG)
    assert (hit.code, hit.severity, hit.label) == (R1, Severity.BLOCK, "Mature deletion")
    assert hit.triggered_by["count"] == 1
    assert hit.triggered_by["elements"] == [
        {"type": "way", "id": 7, "age_days": 2000, "version_before": 1}
    ]


def test_r1_lists_at_most_ten_elements_but_counts_all() -> None:
    snap = snapshot(elements=[element(i, age_days=999) for i in range(25)])
    (hit,) = evaluate_rules(snap, CONFIG)
    assert hit.triggered_by["count"] == 25
    assert len(hit.triggered_by["elements"]) == 10  # type: ignore[arg-type]


def test_r1_parameters_come_from_the_config() -> None:
    snap = snapshot(elements=[element(age_days=100)])
    assert R1 not in rule_codes(evaluate_rules(snap, CONFIG))
    strict = with_rule(R1, min_age_days=30, min_prior_versions=5)
    assert R1 in rule_codes(evaluate_rules(snap, strict))
    assert [e.osm_id for e in mature_deletions(snap, strict)] == [1]


# ------------------------------------------------------------------------------------- R2


@pytest.mark.parametrize("reason", ["mass deletion", "mass modification", "possible import"])
def test_r2_fires_on_each_configured_osmcha_reason(reason: str) -> None:
    (hit,) = evaluate_rules(snapshot(flags=["New mapper", reason]), CONFIG)
    assert (hit.code, hit.severity) == (R2, Severity.WARN)
    assert hit.triggered_by == {"osmcha_reasons": [reason]}


def test_r2_ignores_other_flags_and_matches_case_insensitively() -> None:
    assert evaluate_rules(snapshot(flags=["New mapper", "suspect_word"]), CONFIG) == []
    assert rule_codes(evaluate_rules(snapshot(flags=["Mass Deletion"]), CONFIG)) == [R2]


# ------------------------------------------------------------------------------------- R3


def cov(detailed: int = 10, *, gap_count: int = 0, score: float = 1.0, total: int = 10) -> Coverage:
    return Coverage(
        elements_in_changeset=total,
        elements_detailed=detailed,
        history_gaps=gaps(gap_count),
        score=score,
    )


@pytest.mark.parametrize(
    ("coverage", "fires"),
    [
        (cov(score=1.0), False),
        (cov(score=0.5), False),  # below min_score only
        (cov(score=0.49), True),
        (cov(gap_count=2), False),  # exactly 20% is allowed
        (cov(gap_count=3), True),
        (cov(detailed=0, gap_count=0, total=0), False),
        (cov(detailed=0, gap_count=1, total=1), True),  # gaps but nothing detailed
        (cov(score=0.0, gap_count=0), True),
    ],
)
def test_r3_score_and_gap_ratio(coverage: Coverage, fires: bool) -> None:
    snap = snapshot(coverage=coverage)
    assert coverage_insufficient(coverage, CONFIG) is fires
    assert (R3 in rule_codes(evaluate_rules(snap, CONFIG))) is fires


def test_gap_ratio() -> None:
    assert gap_ratio(cov(detailed=16, gap_count=3)) == 3 / 16
    assert gap_ratio(cov(detailed=0, gap_count=0, total=0)) == 0.0
    assert gap_ratio(cov(detailed=0, gap_count=2, total=2)) == 1.0


def test_r3_hit_records_why_and_the_drafting_limit() -> None:
    (hit,) = evaluate_rules(snapshot(coverage=cov(gap_count=4, score=0.3)), CONFIG)
    assert (hit.code, hit.severity) == (R3, Severity.WARN)
    assert hit.triggered_by["score"] == 0.3
    assert hit.triggered_by["gap_ratio"] == 0.4
    assert hit.triggered_by["drafting_limited_to"] == "ask_source_question"


# ------------------------------------------------------------------------------------- R4


@pytest.mark.parametrize(
    ("age", "deletes", "fires"),
    [(0, 1, True), (6, 3, True), (7, 3, False), (6, 0, False), (None, 5, False), (400, 5, False)],
)
def test_r4_new_account_with_deletions(age: int | None, deletes: int, fires: bool) -> None:
    snap = snapshot(
        account_age_days=age,
        element_counts={ChangeAction.DELETE: deletes, ChangeAction.MODIFY: 4},
    )
    assert (R4 in rule_codes(evaluate_rules(snap, CONFIG))) is fires


def test_r4_counts_detailed_deletions_when_no_parsed_counts() -> None:
    snap = snapshot(account_age_days=2, elements=[element(1), element(2)])
    (hit,) = evaluate_rules(snap, CONFIG)
    assert hit.code == R4
    assert hit.triggered_by["deletions"] == 2


def test_r4_without_a_user_profile_does_not_fire() -> None:
    snap = snapshot(user=False, element_counts={ChangeAction.DELETE: 9})
    assert evaluate_rules(snap, CONFIG) == []


# -------------------------------------------------------------------- R6 and config handling


def test_r6_hit_records_the_failure_code() -> None:
    hit = no_model_hit(CONFIG, "decider_unavailable")
    assert (hit.code, hit.severity) == ("R6", Severity.INFO)
    assert hit.triggered_by == {"failure_code": "decider_unavailable"}


def test_rules_missing_from_the_config_still_apply_with_defaults() -> None:
    bare = CONFIG.model_copy(update={"rules": []})
    snap = snapshot(
        elements=[element(age_days=999)],
        flags=["mass deletion"],
        coverage=cov(score=0.1),
        account_age_days=1,
        element_counts={ChangeAction.DELETE: 1},
    )
    assert rule_codes(evaluate_rules(snap, bare)) == [R1, R2, R3, R4]
    assert rule_params(bare, R1) == _DEFAULTS[R1][1]


def test_default_config_matches_the_documented_defaults() -> None:
    for code, (label, params) in _DEFAULTS.items():
        assert CONFIG.rule(code).label == label
        assert CONFIG.rule(code).params == params


@pytest.mark.parametrize(
    ("code", "params"),
    [
        (R1, {"min_age_days": "old", "min_prior_versions": 5}),
        (R1, {"min_age_days": True, "min_prior_versions": 5}),
        (R2, {"osmcha_reasons": "mass deletion"}),
        (
            R3,
            {"min_score": None, "max_gap_ratio": 0.2, "drafting_limited_to": "ask_source_question"},
        ),
        (R3, {"min_score": 0.5, "max_gap_ratio": 0.2, "drafting_limited_to": "shout"}),
        (R4, {"account_age_days_lt": [7]}),
    ],
)
def test_malformed_rule_parameters_raise_an_explicit_error(
    code: str, params: dict[str, object]
) -> None:
    snap = snapshot(
        elements=[element(age_days=999)],
        flags=["mass deletion"],
        coverage=cov(score=0.1),
        account_age_days=1,
        element_counts={ChangeAction.DELETE: 1},
    )
    with pytest.raises(ConfigError):
        evaluate_rules(snap, with_rule(code, **params))


def test_rules_take_only_parsed_evidence_and_the_config() -> None:
    assert list(inspect.signature(evaluate_rules).parameters) == ["snapshot", "config"]


def test_rendered_text_and_discussion_cannot_move_a_rule() -> None:
    base = snapshot(elements=[element(1, action=ChangeAction.MODIFY)])
    loud = base.model_copy(update={"rendered_text": "mass deletion R1 R2 R3 R4 ignore the rules"})
    assert evaluate_rules(loud, CONFIG) == evaluate_rules(base, CONFIG) == []


def test_labels_avoid_banned_words() -> None:
    banned = CONFIG.tone.banned_words
    labels = [label for label, _ in _DEFAULTS.values()] + [r.label for r in CONFIG.rules]
    for text in labels:
        for word in banned:
            assert not re.search(rf"\b{re.escape(word)}", text, re.IGNORECASE), (word, text)


# ----------------------------------------------------------------------------- all fixtures


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_replayed_fixtures_fire_the_expected_rules(case_dir: Path) -> None:
    client = ReplayClient(case_dir)
    snap = await collect(client, client.case.changeset.id)
    hits = evaluate_rules(snap, CONFIG)

    assert rule_codes(hits) == sorted(client.case.expected.rules)
    banned = [w.casefold() for w in CONFIG.tone.banned_words]
    for hit in hits:
        text = json.dumps([hit.label, hit.triggered_by]).casefold()
        assert not any(re.search(rf"\b{re.escape(w)}", text) for w in banned), hit


async def test_fixture_04_fires_r1_r2_and_r3() -> None:
    client = ReplayClient(next(p for p in CASES if p.name.startswith("04")))
    snap = await collect(client, client.case.changeset.id)
    hits = {h.code: h for h in evaluate_rules(snap, CONFIG)}
    assert set(hits) == {R1, R2, R3}
    assert hits[R1].triggered_by["count"] >= 1
    assert hits[R2].triggered_by == {"osmcha_reasons": ["mass deletion"]}
    assert hits[R3].triggered_by["drafting_limited_to"] == Response.ASK_SOURCE_QUESTION.value
