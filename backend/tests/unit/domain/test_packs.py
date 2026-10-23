"""Community packs: the shipped files, the loader, version hashing, composition options, diffs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_panel_composition import NO, UNK, YES, panel

from cso.domain import config as config_module
from cso.domain.config import (
    BANNED_WORDS_FLOOR,
    CommunityConfig,
    ConfigError,
    default_config_path,
)
from cso.domain.enums import Response
from cso.domain.lanes import compose_panel
from cso.domain.pack_diff import diff_configs

PACK_DIR = default_config_path().parent
DEFAULT_TEXT = (PACK_DIR / "default.yaml").read_text(encoding="utf-8")


def packs() -> dict[str, CommunityConfig]:
    return CommunityConfig.load_all(PACK_DIR)


def test_every_shipped_pack_loads_with_its_metadata() -> None:
    loaded = packs()
    assert set(loaded) == {"default", "newcomer-friendly", "strict-review", "hi-in"}
    for pack_id, config in loaded.items():
        assert config.pack_id == pack_id
        assert config.pack is not None
        for field in ("title", "description", "author", "version"):
            assert getattr(config.pack, field).strip()


def test_every_pack_keeps_the_built_in_banned_words() -> None:
    for config in packs().values():
        assert set(BANNED_WORDS_FLOOR) <= {w.lower() for w in config.tone.banned_words}


def test_a_pack_that_removes_a_floor_word_is_rejected() -> None:
    text = DEFAULT_TEXT.replace(
        "banned_words: [vandal, vandalism, spam, illegal, stop, must]", "banned_words: [spam]"
    )
    assert text != DEFAULT_TEXT
    with pytest.raises(ConfigError, match="not remove"):
        CommunityConfig.from_yaml_text(text)


def test_a_pack_id_must_match_the_config_id() -> None:
    text = DEFAULT_TEXT.replace("  id: default\n  title", "  id: other\n  title")
    with pytest.raises(ConfigError, match="pack.id"):
        CommunityConfig.from_yaml_text(text)


def test_two_files_with_one_pack_id_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(DEFAULT_TEXT, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(DEFAULT_TEXT, encoding="utf-8")
    with pytest.raises(ConfigError, match="used by two files"):
        CommunityConfig.load_all(tmp_path)


def test_load_all_returns_the_file_text_that_names_each_version() -> None:
    pairs = CommunityConfig.load_all_with_text(PACK_DIR)
    for config, text in pairs.values():
        assert CommunityConfig.from_yaml_text(text).version == config.version


def test_the_version_covers_the_pack_id_and_the_composition_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = packs()["default"]
    renamed = CommunityConfig.from_yaml_text(
        DEFAULT_TEXT.replace("id: default", "id: renamed").replace(
            "  id: renamed\n", "  id: renamed\n"
        )
    )
    assert renamed.version != default.version
    monkeypatch.setattr(config_module, "COMPOSITION_VERSION", "2")
    assert CommunityConfig.from_yaml_text(DEFAULT_TEXT).version != default.version


def test_versions_look_like_content_hashes() -> None:
    for config in packs().values():
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", config.version)


# ------------------------------------------------------------------------ composition options


def test_the_options_are_off_in_the_default_pack() -> None:
    options = packs()["default"].panel.composition
    assert (options.p4_requires_both, options.newcomer_welcome_over_question) == (False, False)


def test_strict_pack_needs_both_reassurance_probes_to_read_no_for_a_mistake() -> None:
    default, strict = packs()["default"], packs()["strict-review"]
    one_off = panel(V=NO, C=YES, E=YES)  # conventions off, comment fine
    assert compose_panel(one_off, [], default).response is Response.WELCOME_AND_TIPS
    assert compose_panel(one_off, [], strict).response_row == "P6"
    both_off = panel(V=NO, C=NO, E=YES)
    assert compose_panel(both_off, [], strict).response is Response.WELCOME_AND_TIPS


def test_newcomer_pack_welcomes_a_possibly_new_account_before_asking_a_source_question() -> None:
    default, newcomer = packs()["default"], packs()["newcomer-friendly"]
    maybe_new = panel(A=UNK, C=YES, V=YES, E=YES)
    assert compose_panel(maybe_new, [], default).response is Response.ASK_SOURCE_QUESTION
    chosen = compose_panel(maybe_new, [], newcomer)
    assert chosen.response is Response.WELCOME_AND_TIPS and chosen.response_row == "P4"


def test_newcomer_option_never_hides_a_concern() -> None:
    newcomer = packs()["newcomer-friendly"]
    # A concern probe reading yes keeps the question (or a stronger row), however new the account.
    for concern in ("M", "T", "D"):
        comp = compose_panel(panel(A=UNK, C=YES, V=YES, E=YES, **{concern: YES}), [], newcomer)
        assert comp.response is not Response.WELCOME_AND_TIPS, concern
    claim = compose_panel(panel(A=UNK, W=YES, S=YES, E=YES), [], newcomer)
    assert claim.response is Response.REQUEST_LOCAL_CHECK and claim.response_row == "P2"
    named_rule = compose_panel(panel(A=UNK, C=YES, V=YES, E=YES, M=YES), [], newcomer)
    assert named_rule.response_row != "P4"


def test_unknown_readings_stay_cautious_under_every_pack() -> None:
    for config in packs().values():
        comp = compose_panel(panel(C=UNK, V=UNK), [], config)
        assert comp.response is not Response.NO_ACTION_SUGGESTED


# ------------------------------------------------------------------------------------- diff


def test_a_diff_lists_only_what_differs_and_is_symmetric() -> None:
    default, strict = packs()["default"], packs()["strict-review"]
    forward, backward = diff_configs(default, strict), diff_configs(strict, default)
    assert forward and diff_configs(default, default) == []
    assert [(r.area, r.key) for r in forward] == [(r.area, r.key) for r in backward]
    for a, b in zip(forward, backward, strict=True):
        assert (a.a, a.b) == (b.b, b.a)
    keys = {row.key for row in forward}
    assert "R1.min_age_days" in keys and "bands.confident_min" in keys
    r1 = next(row for row in forward if row.key == "R1.min_age_days")
    assert (r1.a, r1.b) == ("365", "180")


def test_a_diff_reports_the_banned_words_as_a_count_only() -> None:
    default, newcomer = packs()["default"], packs()["newcomer-friendly"]
    text = " ".join(f"{row.a} {row.b}" for row in diff_configs(default, newcomer))
    for word in BANNED_WORDS_FLOOR:
        assert word not in text
