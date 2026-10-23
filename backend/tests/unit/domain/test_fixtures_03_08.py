"""Every shipped fixture (01-08) loads, and its expected.json is internally consistent."""

from __future__ import annotations

from pathlib import Path

import defusedxml.ElementTree as SafeET  # type: ignore[import-untyped]
import pytest

from cso.domain.enums import CoverageGapReason, FetchStatus
from cso.domain.fixtures import SYNTHETIC_ID_FLOOR, FixtureCase, Marker, load_case

CASES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "cases"
CASE_DIRS = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())
BANNED = ("vandal", "spam", "illegal", "stop", "must")

# fixture name -> (elements_in, elements_detailed, elements_skipped_budget, gap count)
EXPECTED_COVERAGE = {
    "03-insufficient-evidence": (300, 40, 260, 2),
    "04-large-deletion": (126, 40, 86, 0),
    "05-conflicting-discussion": (3, 3, 0, 0),
    "06-history-gap": (6, 6, 0, 6),
    "07-provider-timeout": (16, 16, 0, 3),
    "08-adversarial-text": (2, 2, 0, 0),
}


def _creates(case: FixtureCase) -> int:
    root = SafeET.fromstring(case.osc_xml, forbid_dtd=True, forbid_entities=True)
    return sum(1 for block in root if block.tag == "create")


@pytest.fixture(scope="module", params=CASE_DIRS, ids=lambda p: p.name)
def case(request: pytest.FixtureRequest) -> FixtureCase:
    return load_case(request.param)


def test_all_eight_cases_present() -> None:
    assert [p.name[:2] for p in CASE_DIRS] == [f"{n:02d}" for n in range(1, 9)]


def test_case_is_synthetic_and_anonymised(case: FixtureCase) -> None:
    assert case.changeset.id >= SYNTHETIC_ID_FLOOR
    assert case.changeset.uid is not None and case.changeset.uid >= 900_000_000
    assert (case.changeset.user_display or "").startswith("mapper_")


def test_coverage_invariants(case: FixtureCase) -> None:
    cov = case.expected.coverage
    assert not cov.snapshot_truncated
    assert cov.elements_detailed + cov.elements_skipped_budget == cov.elements_in_changeset
    assert len({(g.osm_type, g.osm_id) for g in cov.history_gaps}) == len(cov.history_gaps)


def test_score_matches_documented_formula(case: FixtureCase) -> None:
    cov = case.expected.coverage
    gap_ratio = len(cov.history_gaps) / max(1, cov.elements_detailed)
    score = cov.elements_detailed / max(1, cov.elements_in_changeset) * (1 - gap_ratio)
    if cov.user_profile != FetchStatus.FETCHED:
        score *= 0.9
    assert cov.score == pytest.approx(score, abs=1e-5)


def test_prior_versions_account_for_detailed_non_creates(case: FixtureCase) -> None:
    cov = case.expected.coverage
    prior = len(case.prev) + len(case.prev_markers)
    assert prior == cov.elements_detailed - _creates(case)


def test_gaps_match_markers(case: FixtureCase) -> None:
    by_reason = {
        CoverageGapReason.REDACTED: Marker.FORBIDDEN,
        CoverageGapReason.TIMEOUT: Marker.TIMEOUT,
    }
    marked = {(k[0], k[1]): m for k, m in case.prev_markers.items()}
    gaps = {(g.osm_type, g.osm_id): g.reason for g in case.expected.coverage.history_gaps}
    assert set(marked) == set(gaps)
    assert all(by_reason[reason] == marked[key] for key, reason in gaps.items())


def test_user_and_discussion_status(case: FixtureCase) -> None:
    cov = case.expected.coverage
    assert (cov.user_profile == FetchStatus.FAILED) == (case.user_marker is not None)
    assert (case.user is None) == (case.user_marker is not None)
    assert cov.discussion == FetchStatus.FETCHED
    assert len(case.discussion) == case.changeset.comments_count


def test_no_banned_words_in_evidence_text(case: FixtureCase) -> None:
    text = " ".join(
        [case.changeset.comment or "", *[d.text for d in case.discussion], case.osc_xml]
    ).lower()
    for word in BANNED:
        assert word not in text, f"{case.name}: banned word {word!r}"


@pytest.mark.parametrize(("name", "numbers"), sorted(EXPECTED_COVERAGE.items()))
def test_documented_coverage_numbers(name: str, numbers: tuple[int, int, int, int]) -> None:
    cov = load_case(CASES_DIR / name).expected.coverage
    in_, detailed, skipped, gaps = numbers
    assert (
        cov.elements_in_changeset,
        cov.elements_detailed,
        cov.elements_skipped_budget,
        len(cov.history_gaps),
    ) == (in_, detailed, skipped, gaps)


def test_large_deletion_has_mature_school() -> None:
    case = load_case(CASES_DIR / "04-large-deletion")
    school = next(
        d for d in case.prev.values() if d["elements"][0].get("tags", {}).get("amenity") == "school"
    )
    assert school["elements"][0]["timestamp"] < "2021-01-01"
    assert case.changeset.changes_count == 126


def test_conflicting_discussion_has_two_voices() -> None:
    case = load_case(CASES_DIR / "05-conflicting-discussion")
    assert len(case.discussion) == 4
    assert len({d.author_display for d in case.discussion}) == 2


def test_adversarial_text_is_present_but_escaped_in_xml() -> None:
    case = load_case(CASES_DIR / "08-adversarial-text")
    assert "IGNORE PREVIOUS INSTRUCTIONS" in (case.changeset.comment or "")
    assert "&lt;b&gt;" in case.osc_xml and "<b>" not in case.osc_xml
