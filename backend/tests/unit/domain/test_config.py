import re
from pathlib import Path

import pytest

from cso.domain.config import (
    CONFIG_PATH_ENV,
    CommunityConfig,
    ConfigError,
    default_config_path,
)
from cso.domain.enums import Nature, Response

BANNED = ["vandal", "vandalism", "spam", "illegal", "stop", "must"]


@pytest.fixture
def yaml_text() -> str:
    return default_config_path().read_text(encoding="utf-8")


def test_load_default_config() -> None:
    config = CommunityConfig.load()
    assert config.id == "default"
    assert config.version.startswith("sha256:") and len(config.version) == len("sha256:") + 64
    assert [o.code for o in config.option_sets.nature] == [n.value for n in Nature]
    assert [o.code for o in config.option_sets.response] == [r.value for r in Response]
    assert (config.bands.confident_min, config.bands.unsure_min) == (0.80, 0.50)
    assert [r.code for r in config.rules] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert config.rule("R1").params == {"min_age_days": 365, "min_prior_versions": 5}


def test_tone_defaults() -> None:
    tone = CommunityConfig.load().tone
    assert tone.banned_words == BANNED
    assert tone.allowed_links == [
        "https://wiki.openstreetmap.org/",
        "https://www.openstreetmap.org/",
    ]


def test_version_is_stable_and_ignores_formatting(yaml_text: str) -> None:
    a = CommunityConfig.from_yaml_text(yaml_text)
    b = CommunityConfig.from_yaml_text("# a comment\n" + yaml_text.replace("\n\n", "\n"))
    assert a.version == b.version


def test_version_changes_when_content_changes(yaml_text: str) -> None:
    original = CommunityConfig.from_yaml_text(yaml_text)
    changed = CommunityConfig.from_yaml_text(
        yaml_text.replace("confident_min: 0.80", "confident_min: 0.85")
    )
    assert changed.bands.confident_min == 0.85
    assert changed.version != original.version


def test_option_text_avoids_banned_words() -> None:
    config = CommunityConfig.load()
    options = config.option_sets.nature + config.option_sets.response
    for option in options:
        words = set(re.findall(r"[a-z]+", f"{option.label} {option.description}".lower()))
        assert not words & set(BANNED), (option.code, words & set(BANNED))


def test_explicit_error_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read community config"):
        CommunityConfig.load(tmp_path / "nope.yaml")


def test_explicit_error_for_invalid_yaml() -> None:
    with pytest.raises(ConfigError, match="invalid YAML"):
        CommunityConfig.from_yaml_text("a: [unclosed")


def test_top_level_must_be_mapping() -> None:
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        CommunityConfig.from_yaml_text("- just\n- a list\n")


def test_version_key_is_rejected(yaml_text: str) -> None:
    with pytest.raises(ConfigError, match="computed from content"):
        CommunityConfig.from_yaml_text("version: sha256:abc\n" + yaml_text)


def test_missing_section_is_reported(yaml_text: str) -> None:
    broken = yaml_text.split("tone:")[0]
    with pytest.raises(ConfigError, match="tone"):
        CommunityConfig.from_yaml_text(broken)


def test_option_codes_must_match_enums(yaml_text: str) -> None:
    broken = yaml_text.replace("code: welcome_and_tips", "code: say_hello")
    with pytest.raises(ConfigError, match="option_sets.response"):
        CommunityConfig.from_yaml_text(broken)


def test_bands_must_be_ordered(yaml_text: str) -> None:
    broken = yaml_text.replace("unsure_min: 0.50", "unsure_min: 0.90")
    with pytest.raises(ConfigError, match="unsure_min must be lower"):
        CommunityConfig.from_yaml_text(broken)


def test_duplicate_rule_codes_rejected(yaml_text: str) -> None:
    broken = yaml_text.replace("code: R2", "code: R1")
    with pytest.raises(ConfigError, match="duplicate"):
        CommunityConfig.from_yaml_text(broken)


def test_unknown_keys_rejected(yaml_text: str) -> None:
    with pytest.raises(ConfigError):
        CommunityConfig.from_yaml_text(yaml_text + "\nsurprise: true\n")


def test_env_override_path(tmp_path: Path, yaml_text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = tmp_path / "custom.yaml"
    copy.write_text(yaml_text.replace("id: default", "id: custom"), encoding="utf-8")
    monkeypatch.setenv(CONFIG_PATH_ENV, str(copy))
    assert CommunityConfig.load().id == "custom"


def test_rule_lookup_unknown_code() -> None:
    with pytest.raises(KeyError):
        CommunityConfig.load().rule("R99")


def test_the_banned_word_floor_cannot_be_removed_or_emptied_by_configuration() -> None:
    from cso.domain.config import BANNED_WORDS_FLOOR, default_config_path

    text = default_config_path().read_text(encoding="utf-8")
    line = "  banned_words: [vandal, vandalism, spam, illegal, stop, must]"
    assert line in text
    for replacement in ("  banned_words: []", "  banned_words: [vandal, spam]"):
        with pytest.raises(ConfigError, match="not remove"):
            CommunityConfig.from_yaml_text(text.replace(line, replacement))
    extended = text.replace(line, line[:-1] + ", thank]")
    tone = CommunityConfig.from_yaml_text(extended).tone
    assert set(BANNED_WORDS_FLOOR) <= set(tone.banned_words) and "thank" in tone.banned_words
