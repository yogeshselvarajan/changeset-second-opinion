"""Calibration logic: labels from outcomes, the threshold fit, and the limits it keeps."""

from __future__ import annotations

import random

from cso.domain.calibration import (
    COMPOSED_PROBES,
    MIN_COVERAGE,
    MIN_GAP,
    Label,
    build_report,
    fit_probe,
    labels_from_outcome,
)
from cso.domain.enums import Disposition

PROBE = "mature_feature_deleted"
DEFAULT = (0.35, 0.65)


def readings(**states: tuple[float, str]) -> dict[str, tuple[float, str]]:
    base = {probe: (0.05, "no") for probe in COMPOSED_PROBES}
    base.update(states)
    return base


def test_an_agreement_confirms_every_decided_composed_reading() -> None:
    given = readings(comment_matches_changes=(0.9, "yes"), discussion_cites_source=(0.5, "unknown"))
    labels = labels_from_outcome(Disposition.AGREE, given, None, "confident")
    by_probe = {label.probe: label for label in labels}
    assert by_probe["comment_matches_changes"].truth == "yes"
    assert by_probe[PROBE].truth == "no"
    assert "discussion_cites_source" not in by_probe  # an unknown reading cannot be confirmed
    assert "evidence_sufficient" not in by_probe  # not a composed probe


def test_a_disagreement_labels_only_the_probes_the_reviewer_flagged() -> None:
    given = readings(**{PROBE: (0.8, "yes")})
    labels = labels_from_outcome(Disposition.DISAGREE_WITH_MODEL, given, {PROBE: "no"}, "unsure")
    assert [(label.probe, label.probability, label.truth) for label in labels] == [
        (PROBE, 0.8, "no")
    ]
    assert labels_from_outcome(Disposition.DISAGREE_WITH_MODEL, given, None, None) == []


def test_other_dispositions_give_no_labels() -> None:
    given = readings()
    for disposition in (Disposition.NEEDS_SURVEY, Disposition.NO_ACTION):
        assert labels_from_outcome(disposition, given, {PROBE: "yes"}, None) == []


def test_a_correction_for_a_probe_that_is_not_composed_is_ignored() -> None:
    given = readings()
    labels = labels_from_outcome(
        Disposition.DIFFERENT_RESPONSE, given, {"evidence_sufficient": "no"}, None
    )
    assert labels == []


def labelled(count: int, seed: int = 1) -> list[Label]:
    """Readings where the truth flips near 0.55, so the default cut at 0.65 is too high."""
    rng = random.Random(seed)  # noqa: S311  (a seeded generator for test data, not security)
    out = []
    for _ in range(count):
        p = round(rng.uniform(0.02, 0.98), 3)
        out.append(Label(PROBE, p, "yes" if p > 0.55 else "no", "unsure"))
    return out


def test_below_the_label_floor_the_default_is_kept() -> None:
    fit = fit_probe(PROBE, labelled(24), DEFAULT)
    assert fit.status == "insufficient_data"
    assert (fit.low, fit.high) == DEFAULT


def test_the_fit_respects_the_limits_and_never_does_worse_than_the_default_it_could_keep() -> None:
    for seed in range(5):
        labels = labelled(60, seed)
        fit = fit_probe(PROBE, labels, DEFAULT)
        assert fit.status == "fitted"
        assert 0.15 <= fit.low and fit.high <= 0.85 and fit.high - fit.low >= MIN_GAP - 1e-9
        assert fit.coverage is not None and fit.coverage >= MIN_COVERAGE
        default_rate = fit.default_accuracy.value
        tuned_rate = fit.tuned_accuracy.value
        assert default_rate is not None and tuned_rate is not None
        assert tuned_rate >= default_rate - 1e-9


def test_the_fit_is_deterministic() -> None:
    labels = labelled(40, 7)
    assert fit_probe(PROBE, labels, DEFAULT) == fit_probe(PROBE, list(labels), DEFAULT)


def test_when_the_default_is_already_best_it_is_kept() -> None:
    labels = [Label(PROBE, 0.05, "no", None)] * 15 + [Label(PROBE, 0.95, "yes", None)] * 15
    fit = fit_probe(PROBE, labels, DEFAULT)
    assert (fit.low, fit.high) == DEFAULT


def test_a_probe_cannot_be_tuned_into_deciding_almost_nothing() -> None:
    labels = [Label(PROBE, 0.5, "yes" if i % 2 else "no", None) for i in range(40)]
    fit = fit_probe(PROBE, labels, DEFAULT)
    assert fit.status in ("kept_default", "fitted")
    if fit.status == "fitted":
        assert fit.coverage is not None and fit.coverage >= MIN_COVERAGE


def test_the_report_counts_outcomes_and_never_changes_cut_offs_below_the_floor() -> None:
    defaults = {probe: DEFAULT for probe in COMPOSED_PROBES}
    outcomes = [
        (Disposition.AGREE, readings(), None, "confident"),
        (Disposition.NEEDS_SURVEY, readings(), None, "unsure"),
    ]
    report = build_report(outcomes, defaults)
    assert (report.n_outcomes, report.n_labelled_outcomes) == (2, 1)
    assert report.changed == {}
    assert {row.band: row.status for row in report.bands}["confident"] == "insufficient_data"
