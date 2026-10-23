"""Before/after comparison of the `new_account_first_edits` probe across two diagnostic runs.

Reads two receipt directories (one JSON per changeset). Counts only; no names. This compares what
the model read and how it compared with the parsed fact; it is not a measure of accuracy.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PROBE = "new_account_first_edits"


@dataclass(slots=True)
class ProbeSide:
    """One run's readings of the probe."""

    states: Counter[str] = field(default_factory=Counter)
    cross_checks: Counter[str] = field(default_factory=Counter)
    probabilities: list[float] = field(default_factory=list)

    def mean_probability(self) -> float | None:
        return sum(self.probabilities) / len(self.probabilities) if self.probabilities else None


@dataclass(slots=True)
class ProbeComparison:
    before: ProbeSide
    after: ProbeSide
    items_both: int
    state_changed: int
    cross_check_changed: int


def _load(directory: Path) -> dict[int, dict[str, object]]:
    out: dict[int, dict[str, object]] = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[int(data["changeset_id"])] = data
    return out


def _reading(receipt: dict[str, object]) -> tuple[str, float]:
    readings = receipt["panel"]["readings"]  # type: ignore[index]
    entry = readings[PROBE]
    return str(entry["state"]), float(entry["probability"])


def _cross_check(receipt: dict[str, object]) -> str:
    checks = receipt["composition"]["cross_checks"]  # type: ignore[index]
    return str(checks.get(PROBE, "none"))


def compare(before_dir: Path, after_dir: Path) -> ProbeComparison:
    before, after = _load(before_dir), _load(after_dir)
    b_side, a_side = ProbeSide(), ProbeSide()
    both = state_changed = check_changed = 0
    for cs in sorted(set(before) | set(after)):
        for receipts, side in ((before, b_side), (after, a_side)):
            if cs in receipts:
                state, probability = _reading(receipts[cs])
                side.states[state] += 1
                side.probabilities.append(probability)
                side.cross_checks[_cross_check(receipts[cs])] += 1
        if cs in before and cs in after:
            both += 1
            state_changed += _reading(before[cs])[0] != _reading(after[cs])[0]
            check_changed += _cross_check(before[cs]) != _cross_check(after[cs])
    return ProbeComparison(b_side, a_side, both, state_changed, check_changed)


def _decided(side: ProbeSide) -> str:
    agree, disagree = side.cross_checks["agree"], side.cross_checks["disagree"]
    total = agree + disagree
    return "n/a" if total == 0 else f"{agree}/{total} ({agree / total:.1%})"


def _row(label: str, before: object, after: object) -> str:
    return f"| {label} | {before} | {after} |"


def render_section(result: ProbeComparison) -> str:
    """A markdown section to append to the v2 diagnostic report."""
    b, a = result.before, result.after
    mean_b, mean_a = b.mean_probability(), a.mean_probability()
    lines = [
        "",
        f"## Before vs after the edit-time count fix: `{PROBE}`",
        "",
        "The evidence used to show the author's *current* changeset total. It now shows the",
        "count at the time of the edit when the editor published it. Same items, same model,",
        "same compact profile. Readings are the model's; the cross-check compares them with",
        "the parsed fact.",
        "",
        f"Items present in both runs: {result.items_both}. "
        f"Reading changed: {result.state_changed}. "
        f"Cross-check status changed: {result.cross_check_changed}.",
        "",
        "| | before | after |",
        "|---|---|---|",
        _row("read yes", b.states["yes"], a.states["yes"]),
        _row("read unknown", b.states["unknown"], a.states["unknown"]),
        _row("read no", b.states["no"], a.states["no"]),
        _row(
            "mean probability",
            "n/a" if mean_b is None else f"{mean_b:.3f}",
            "n/a" if mean_a is None else f"{mean_a:.3f}",
        ),
        _row("agrees with the parsed fact", b.cross_checks["agree"], a.cross_checks["agree"]),
        _row(
            "disagrees with the parsed fact",
            b.cross_checks["disagree"],
            a.cross_checks["disagree"],
        ),
        _row(
            "undecided (the model read unknown)",
            b.cross_checks["undecided"],
            a.cross_checks["undecided"],
        ),
        _row(
            "n/a (the parsed fact is unknown)",
            b.cross_checks["n/a"],
            a.cross_checks["n/a"],
        ),
        _row("agreement among decided items", _decided(b), _decided(a)),
        "",
        "Agreement is not accuracy: both sides come from the same evidence text. After the",
        "fix the parsed fact is unknown for more items (n/a): a current total of 10 or more",
        "cannot show the edit-time count was 10 or more, so those items no longer count as",
        "agreements or disagreements. Unknown parsed facts are read cautiously in composition.",
        "",
        "Caveat: if the two runs differ in anything besides the count (for example other",
        "evidence-text changes made between them), the changes above cannot be attributed to",
        "the count fix alone.",
        "",
    ]
    return "\n".join(lines)
