from __future__ import annotations

import pytest
from pydantic import ValidationError

from cso.domain.config import CommunityConfig, ConfigError, default_config_path
from cso.domain.panel import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    PANEL_NOUL_IDS,
    YES_MEANS,
    AdvisoryNature,
    FactPanel,
    NoulReading,
    Tri,
    classify,
    raises_concern,
)

YAML_TEXT = default_config_path().read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (0.0, Tri.NO),
        (0.3499, Tri.NO),
        (0.35, Tri.UNKNOWN),
        (0.5, Tri.UNKNOWN),
        (0.65, Tri.UNKNOWN),
        (0.6501, Tri.YES),
        (1.0, Tri.YES),
    ],
)
def test_classify_uses_open_thresholds_with_unknown_in_between(
    probability: float, expected: Tri
) -> None:
    assert classify(probability) is expected


def test_defaults_are_the_documented_cut_points() -> None:
    assert (DEFAULT_LOW, DEFAULT_HIGH) == (0.35, 0.65)


def test_classify_honours_custom_thresholds() -> None:
    assert classify(0.5, low=0.4, high=0.45) is Tri.YES
    assert classify(0.2, low=0.1, high=0.9) is Tri.UNKNOWN


@pytest.mark.parametrize(("low", "high"), [(0.5, 0.5), (0.7, 0.3), (-0.1, 0.5), (0.2, 1.1)])
def test_classify_rejects_bad_thresholds(low: float, high: float) -> None:
    with pytest.raises(ValueError, match="thresholds"):
        classify(0.5, low=low, high=high)


@pytest.mark.parametrize(
    ("state", "yes_means", "concern"),
    [
        (Tri.YES, "concern", True),
        (Tri.NO, "concern", False),
        (Tri.UNKNOWN, "concern", True),
        (Tri.YES, "reassurance", False),
        (Tri.NO, "reassurance", True),
        (Tri.UNKNOWN, "reassurance", True),
    ],
)
def test_unknown_is_always_read_cautiously(state: Tri, yes_means: str, concern: bool) -> None:
    assert raises_concern(state, yes_means=yes_means) is concern  # type: ignore[arg-type]


def test_polarity_table_covers_exactly_the_panel() -> None:
    assert set(YES_MEANS) == set(PANEL_NOUL_IDS)
    assert len(PANEL_NOUL_IDS) == len(set(PANEL_NOUL_IDS)) == 10


def _panel(probabilities: dict[str, float]) -> FactPanel:
    readings = {
        i: NoulReading(id=i, probability=p, state=classify(p)) for i, p in probabilities.items()
    }
    return FactPanel(
        low=0.35,
        high=0.65,
        readings=readings,
        advisory_nature=AdvisoryNature(
            order=["a", "b"], probabilities={"a": 0.6, "b": 0.4}, choice="a", confidence=0.2
        ),
        ids=list(probabilities),
    )


def test_fact_panel_exposes_states_and_cautious_concerns() -> None:
    panel = _panel(
        {
            "mature_feature_deleted": 0.9,
            "comment_matches_changes": 0.1,
            "evidence_sufficient": 0.5,
        }
    )

    assert panel.state("mature_feature_deleted") is Tri.YES
    assert panel.concerns() == {
        "mature_feature_deleted": True,  # yes on a concern probe
        "comment_matches_changes": True,  # no on a reassurance probe
        "evidence_sufficient": True,  # unknown is cautious
    }
    with pytest.raises(KeyError):
        panel.state("not_a_probe")


def test_advisory_nature_is_flagged_and_cannot_be_unflagged() -> None:
    nature = _panel({"mature_feature_deleted": 0.9}).advisory_nature
    assert nature.advisory is True
    with pytest.raises(ValidationError):
        AdvisoryNature(
            advisory=False,  # type: ignore[arg-type]
            order=["a"],
            probabilities={"a": 1.0},
            choice="a",
            confidence=0.0,
        )


def test_panel_models_are_immutable_and_reject_out_of_range_probabilities() -> None:
    reading = NoulReading(id="mature_feature_deleted", probability=0.5, state=Tri.UNKNOWN)
    with pytest.raises(ValidationError):
        reading.probability = 0.9  # type: ignore[misc]
    with pytest.raises(ValidationError):
        NoulReading(id="x", probability=1.5, state=Tri.YES)


# -------------------------------------------------------------------------------- config panel


def test_default_config_carries_the_panel() -> None:
    config = CommunityConfig.load()

    assert config.panel.noul_ids == list(PANEL_NOUL_IDS)
    assert (config.panel.thresholds.low, config.panel.thresholds.high) == (0.35, 0.65)


def test_changing_a_threshold_changes_the_config_version() -> None:
    original = CommunityConfig.from_yaml_text(YAML_TEXT)
    changed = CommunityConfig.from_yaml_text(
        YAML_TEXT.replace("{ low: 0.35, high: 0.65 }", "{ low: 0.30, high: 0.70 }")
    )

    assert changed.version != original.version
    assert changed.panel.thresholds.high == 0.70


def test_comments_and_whitespace_do_not_change_the_version() -> None:
    original = CommunityConfig.from_yaml_text(YAML_TEXT)
    again = CommunityConfig.from_yaml_text("# note\n" + YAML_TEXT.replace("\n\n", "\n"))
    assert again.version == original.version


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("    - evidence_sufficient\n", "", "must be exactly"),
        ("    - evidence_sufficient\n", "    - mature_feature_deleted\n", "duplicates"),
        ("    - evidence_sufficient\n", "    - something_else\n", "must be exactly"),
        ("{ low: 0.35, high: 0.65 }", "{ low: 0.65, high: 0.35 }", "lower"),
        ("{ low: 0.35, high: 0.65 }", "{ low: 0.5, high: 0.5 }", "lower"),
        ("{ low: 0.35, high: 0.65 }", "{ low: 0.0, high: 0.65 }", "panel"),
        ("{ low: 0.35, high: 0.65 }", "{ low: 0.35 }", "panel"),
    ],
)
def test_invalid_panel_sections_are_rejected_with_explicit_errors(
    old: str, new: str, message: str
) -> None:
    assert old in YAML_TEXT
    with pytest.raises(ConfigError, match=message):
        CommunityConfig.from_yaml_text(YAML_TEXT.replace(old, new))


def test_missing_panel_section_is_rejected() -> None:
    start = YAML_TEXT.index("panel:\n")
    end = YAML_TEXT.index("# Deterministic policy gate")
    with pytest.raises(ConfigError, match="panel"):
        CommunityConfig.from_yaml_text(YAML_TEXT[:start] + YAML_TEXT[end:])
