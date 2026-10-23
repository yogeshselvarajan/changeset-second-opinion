"""A readable difference between two community packs (rules, thresholds, bands, tone, options).

The result lists only settings that differ. It is symmetric: `diff(a, b)` and `diff(b, a)` name the
same settings in the same order, with the two values swapped. The banned-word list is never copied
into it (invariant 6): only how many words each pack lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from cso.domain.config import CommunityConfig

Area = Literal["rules", "thresholds", "bands", "composition", "tone", "options"]


@dataclass(frozen=True, slots=True)
class DiffRow:
    """One setting that differs; a value is None when that pack has no such setting."""

    area: Area
    key: str
    a: str | None
    b: str | None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))


def _flatten(config: CommunityConfig) -> dict[tuple[Area, str], str]:
    out: dict[tuple[Area, str], str] = {}
    for rule in config.rules:
        out["rules", f"{rule.code}.label"] = rule.label
        for name, value in rule.params.items():
            out["rules", f"{rule.code}.{name}"] = _text(value)
    out["thresholds", "panel.thresholds.low"] = _text(config.panel.thresholds.low)
    out["thresholds", "panel.thresholds.high"] = _text(config.panel.thresholds.high)
    out["bands", "bands.confident_min"] = _text(config.bands.confident_min)
    out["bands", "bands.unsure_min"] = _text(config.bands.unsure_min)
    out["bands", "bands.order_sensitivity_max"] = _text(config.bands.order_sensitivity_max)
    out["bands", "panel.band.confident_max_unknown"] = _text(
        config.panel.band.confident_max_unknown
    )
    out["bands", "panel.band.unsure_max_unknown"] = _text(config.panel.band.unsure_max_unknown)
    options = config.panel.composition
    out["composition", "panel.composition.p4_requires_both"] = _text(options.p4_requires_both)
    out["composition", "panel.composition.newcomer_welcome_over_question"] = _text(
        options.newcomer_welcome_over_question
    )
    out["tone", "tone.language_policy"] = config.tone.language_policy
    out["tone", "tone.allowed_links"] = ", ".join(config.tone.allowed_links)
    out["tone", "tone.banned_words"] = f"{len(config.tone.banned_words)} words"
    for group, items in (
        ("nature", config.option_sets.nature),
        ("response", config.option_sets.response),
    ):
        for option in items:
            out["options", f"{group}.{option.code}.label"] = option.label
            out["options", f"{group}.{option.code}.description"] = option.description
    return out


def diff_configs(a: CommunityConfig, b: CommunityConfig) -> list[DiffRow]:
    """Every setting whose value differs, in a fixed order (by area, then by key)."""
    left, right = _flatten(a), _flatten(b)
    order = ("rules", "thresholds", "bands", "composition", "tone", "options")
    keys = sorted(set(left) | set(right), key=lambda k: (order.index(k[0]), k[1]))
    return [
        DiffRow(area=area, key=key, a=left.get((area, key)), b=right.get((area, key)))
        for area, key in keys
        if left.get((area, key)) != right.get((area, key))
    ]
