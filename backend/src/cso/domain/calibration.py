"""Reviewer-tuned calibration (ADR-010): turn recorded outcomes into labels and refit cut points.

What this does: for each composed fact probe, choose the pair of cut points (`low`, `high`) on the
probabilities the Decider gave, so that the readings reviewers confirmed come out right as often as
possible while at least 60 percent of readings still reach a yes or no. What it never does: change a
rule, touch the parsed-fact floor, move a cut point outside 0.15 to 0.85, or apply anything by
itself. `unknown` stays the cautious reading, and a probe with fewer than 25 labelled readings keeps
the pack default.

The bias to keep in mind: an `agree` outcome labels every decided reading of that run as correct,
and reviewers agree more often than they check. Agreement labels are therefore optimistic; they can
confirm the current cut points and cannot show that a yes or no was wrong. Corrections (`disagree`
outcomes with `probe_corrections`) are the only labels that can.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from cso.domain.config import CALIBRATION_MAX, CALIBRATION_MIN
from cso.domain.enums import Disposition
from cso.domain.panel import ADVISORY_PROBES, CROSS_CHECK_ONLY_PROBES, PANEL_NOUL_IDS
from cso.evaluation.stats import wilson_interval

MIN_LABELS_PER_PROBE = 25
MIN_LABELS_PER_BAND = 25
MIN_COVERAGE = 0.60
GRID_STEP = 0.05
MIN_GAP = 0.10  # `high` is at least this far above `low`, so "unknown" never vanishes

#: The probes that feed the suggestion (the others are cross-checks or advisory only).
COMPOSED_PROBES: tuple[str, ...] = tuple(
    i for i in PANEL_NOUL_IDS if i not in ADVISORY_PROBES | CROSS_CHECK_ONLY_PROBES
)
_CORRECTING = frozenset({Disposition.DISAGREE_WITH_MODEL, Disposition.DIFFERENT_RESPONSE})

Truth = Literal["yes", "no"]
Status = Literal["fitted", "kept_default", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class Label:
    """One confirmed reading: the probability the Decider gave and what a person says is right."""

    probe: str
    probability: float
    truth: Truth
    band: str | None


@dataclass(frozen=True, slots=True)
class Accuracy:
    """Correct decided readings out of decided readings, with a Wilson 95 percent interval."""

    correct: int
    decided: int
    lower: float
    upper: float

    @property
    def value(self) -> float | None:
        return self.correct / self.decided if self.decided else None


def accuracy(correct: int, decided: int) -> Accuracy:
    lower, upper = wilson_interval(correct, decided)
    return Accuracy(correct=correct, decided=decided, lower=lower, upper=upper)


@dataclass(frozen=True, slots=True)
class ProbeFit:
    """The result for one probe: the cut points in use by default and after the fit."""

    probe: str
    n: int
    status: Status
    default_low: float
    default_high: float
    low: float
    high: float
    default_accuracy: Accuracy
    tuned_accuracy: Accuracy
    coverage: float | None


@dataclass(frozen=True, slots=True)
class BandRow:
    """How often the readings behind runs of one band were right (a report; cut-offs never move)."""

    band: str
    n: int
    accuracy: Accuracy
    status: Literal["reported", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Everything a dry run shows: how many outcomes counted and what each probe would get."""

    n_outcomes: int
    n_labelled_outcomes: int
    probes: tuple[ProbeFit, ...]
    bands: tuple[BandRow, ...]

    @property
    def changed(self) -> dict[str, tuple[float, float]]:
        """The probes whose cut points differ from the default, with the new pair."""
        return {
            p.probe: (p.low, p.high)
            for p in self.probes
            if p.status == "fitted" and (p.low, p.high) != (p.default_low, p.default_high)
        }


def labels_from_outcome(
    disposition: Disposition,
    readings: Mapping[str, tuple[float, str]],
    corrections: Mapping[str, str] | None,
    band: str | None,
) -> list[Label]:
    """The labels one outcome gives, from the run's stored readings (`probe: (probability, state)`).

    `agree` confirms every decided composed reading. A correcting disposition labels only the probes
    the reviewer flagged, with the answer they gave. Anything else gives nothing.
    """
    out: list[Label] = []
    if disposition is Disposition.AGREE:
        for probe in COMPOSED_PROBES:
            found = readings.get(probe)
            if found is None or found[1] not in ("yes", "no"):
                continue  # an unknown reading cannot be confirmed
            out.append(Label(probe, found[0], "yes" if found[1] == "yes" else "no", band))
    elif disposition in _CORRECTING and corrections:
        for probe, truth in corrections.items():
            found = readings.get(probe)
            if probe in COMPOSED_PROBES and found is not None and truth in ("yes", "no"):
                out.append(Label(probe, found[0], truth, band))  # type: ignore[arg-type]
    return out


def _score(labels: Sequence[Label], low: float, high: float) -> tuple[int, int]:
    """(correct, decided) for cut points: below low reads no, above high reads yes."""
    correct = decided = 0
    for label in labels:
        if label.probability < low:
            predicted: Truth = "no"
        elif label.probability > high:
            predicted = "yes"
        else:
            continue
        decided += 1
        correct += predicted == label.truth
    return correct, decided


def _grid() -> list[float]:
    steps = round((CALIBRATION_MAX - CALIBRATION_MIN) / GRID_STEP)
    return [round(CALIBRATION_MIN + i * GRID_STEP, 2) for i in range(steps + 1)]


def fit_probe(
    probe: str,
    labels: Sequence[Label],
    default: tuple[float, float],
    *,
    min_labels: int = MIN_LABELS_PER_PROBE,
    min_coverage: float = MIN_COVERAGE,
) -> ProbeFit:
    """Choose the cut points for one probe, or keep the default when the data cannot support it.

    Picks the pair that maximises accuracy over decided readings subject to coverage; ties go to
    higher coverage, then to the pair nearest the default, then to the lower `low`.
    """
    own = [label for label in labels if label.probe == probe]
    n = len(own)
    d_low, d_high = default
    d_correct, d_decided = _score(own, d_low, d_high)
    default_accuracy = accuracy(d_correct, d_decided)
    if n < min_labels:
        return ProbeFit(
            probe, n, "insufficient_data", d_low, d_high, d_low, d_high,
            default_accuracy, default_accuracy, None if n == 0 else d_decided / n,
        )  # fmt: skip
    best: tuple[tuple[float, float, float, float], float, float, int, int] | None = None
    grid = _grid()
    for low in grid:
        for high in grid:
            if high - low < MIN_GAP - 1e-9:
                continue
            correct, decided = _score(own, low, high)
            if decided == 0 or decided / n < min_coverage:
                continue
            key = (
                correct / decided,
                decided / n,
                -(abs(low - d_low) + abs(high - d_high)),
                -low,
            )
            if best is None or key > best[0]:
                best = (key, low, high, correct, decided)
    if best is None:
        return ProbeFit(
            probe, n, "kept_default", d_low, d_high, d_low, d_high,
            default_accuracy, default_accuracy, d_decided / n,
        )  # fmt: skip
    _, low, high, correct, decided = best
    return ProbeFit(
        probe, n, "fitted", d_low, d_high, low, high,
        default_accuracy, accuracy(correct, decided), decided / n,
    )  # fmt: skip


def band_report(
    labels: Iterable[Label], defaults: Mapping[str, tuple[float, float]]
) -> list[BandRow]:
    """Per band (of the run the reviewer saw): how often the decided readings were right.

    Uses the pack's default cut points so the figures describe what reviewers actually saw. Below
    25 labelled readings a band is listed as "insufficient_data" and is not summarised.
    """
    by_band: dict[str, list[Label]] = {}
    for label in labels:
        if label.band:
            by_band.setdefault(label.band, []).append(label)
    rows: list[BandRow] = []
    for band in ("confident", "unsure", "cannot_tell"):
        items = by_band.get(band, [])
        correct = decided = 0
        for label in items:
            low, high = defaults[label.probe]
            c, d = _score([label], low, high)
            correct, decided = correct + c, decided + d
        rows.append(
            BandRow(
                band=band,
                n=len(items),
                accuracy=accuracy(correct, decided),
                status="reported" if len(items) >= MIN_LABELS_PER_BAND else "insufficient_data",
            )
        )
    return rows


def build_report(
    outcomes: Iterable[
        tuple[Disposition, Mapping[str, tuple[float, str]], Mapping[str, str] | None, str | None]
    ],
    defaults: Mapping[str, tuple[float, float]],
) -> CalibrationReport:
    """The whole report; one `(disposition, readings, corrections, band)` per counted outcome."""
    labels: list[Label] = []
    total = labelled = 0
    for disposition, readings, corrections, band in outcomes:
        total += 1
        given = labels_from_outcome(disposition, readings, corrections, band)
        if given:
            labelled += 1
            labels.extend(given)
    probes = tuple(fit_probe(p, labels, defaults[p]) for p in COMPOSED_PROBES)
    return CalibrationReport(
        n_outcomes=total,
        n_labelled_outcomes=labelled,
        probes=probes,
        bands=tuple(band_report(labels, defaults)),
    )
