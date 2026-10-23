"""Compact SUMMARY block (counted in code) and the panel band configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig, ConfigError
from cso.domain.evidence import COMPACT_MAX_TOKENS, render
from cso.domain.models import EvidenceSnapshot
from cso.domain.policy import changed_key_counts

CONFIG = CommunityConfig.load()
CASES = {p.name: p for p in sorted((Path(__file__).parents[3] / "fixtures" / "cases").iterdir())}
BANNED = re.compile(r"\b(vandal|vandalism|spam|illegal|stop|must)\b", re.IGNORECASE)


async def snapshot_of(name: str) -> EvidenceSnapshot:
    case = CASES[name]
    cs = json.loads((case / "changeset.json").read_text(encoding="utf-8"))["changeset"]["id"]
    return await collect(ReplayClient(case), cs)


def summary_block(text: str) -> str:
    start = text.index("SUMMARY")
    return text[start : text.index("\n\n", start)]


@pytest.mark.parametrize("name", sorted(CASES))
async def test_compact_with_summary_stays_within_the_token_budget(name: str) -> None:
    rendered = render(await snapshot_of(name), CONFIG, profile="compact")
    assert rendered.estimated_tokens <= COMPACT_MAX_TOKENS
    assert "SUMMARY (counted by the tool over all elements with details)" in rendered.text


async def test_summary_counts_keys_over_all_detailed_elements_not_just_the_lines_shown() -> None:
    snapshot = await snapshot_of("03-insufficient-evidence")
    rendered = render(snapshot, CONFIG, profile="compact")
    counts = dict(changed_key_counts(snapshot))
    assert counts["highway"] > 20
    assert rendered.elements_not_shown > 0  # far fewer lines are shown than elements counted
    assert f'"highway" on {counts["highway"]} elements' in summary_block(rendered.text)


async def test_summary_reports_how_many_creators_of_deleted_elements_are_known() -> None:
    rendered = render(await snapshot_of("04-large-deletion"), CONFIG, profile="compact")
    assert (
        "deleted elements created by this account within 30 days: 0 "
        "(creator and age known for 40 of 126 deleted elements)"
    ) in summary_block(rendered.text)


async def test_summary_says_so_when_nothing_was_deleted() -> None:
    rendered = render(await snapshot_of("02-good-faith-mistake"), CONFIG, profile="compact")
    assert (
        "deleted elements created by this account within 30 days: none (no deleted elements)"
        in summary_block(rendered.text)
    )


async def test_summary_counts_deletions_of_the_accounts_own_recent_additions() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    uid = snapshot.changeset.uid
    assert uid is not None
    own = [
        e.model_copy(update={"created_by_uid": uid, "age_days": 10}) for e in snapshot.elements[:3]
    ]
    changed = snapshot.model_copy(update={"elements": [*own, *snapshot.elements[3:]]})
    assert (
        "deleted elements created by this account within 30 days: 3 "
        "(creator and age known for 40 of 126 deleted elements)"
    ) in summary_block(render(changed, CONFIG, profile="compact").text)


async def test_summary_reports_entry_counts_and_detail_coverage() -> None:
    snapshot = await snapshot_of("03-insufficient-evidence")
    block = summary_block(render(snapshot, CONFIG, profile="compact").text)
    assert "modify=300" in block
    assert f"elements with details: {snapshot.coverage.elements_detailed} of 300" in block


async def test_summary_says_so_when_no_tags_changed() -> None:
    snapshot = await snapshot_of("04-large-deletion")
    assert snapshot.tag_diffs  # deleted elements do carry tag diffs ...
    assert not changed_key_counts(snapshot)  # ... but a deletion is not a re-tag
    assert (
        "tag keys changed on modified elements: none among the elements with details"
        in summary_block(render(snapshot, CONFIG, profile="compact").text)
    )


async def test_untrusted_tag_keys_in_the_summary_are_sanitised_and_quoted() -> None:
    snapshot = await snapshot_of("08-adversarial-text")
    block = summary_block(render(snapshot, CONFIG, profile="compact").text)
    assert "<" not in block and ">" not in block
    assert not BANNED.search(block)


async def test_full_profile_has_no_summary_block() -> None:
    rendered = render(await snapshot_of("01-legitimate"), CONFIG)
    assert "SUMMARY (counted by the tool" not in rendered.text


# ------------------------------------------------------------------------ panel band config


def test_default_config_carries_the_documented_band() -> None:
    assert CONFIG.panel.band.confident_max_unknown == 1
    assert CONFIG.panel.band.unsure_max_unknown == 3


def test_changing_the_band_changes_the_config_version() -> None:
    text = (Path(__file__).parents[4] / "config" / "communities" / "default.yaml").read_text(
        encoding="utf-8"
    )
    edited = text.replace("confident_max_unknown: 1", "confident_max_unknown: 2")
    assert edited != text
    assert CommunityConfig.from_yaml_text(edited).version != CONFIG.version


def test_a_band_with_unsure_below_confident_is_rejected() -> None:
    text = (Path(__file__).parents[4] / "config" / "communities" / "default.yaml").read_text(
        encoding="utf-8"
    )
    broken = text.replace("unsure_max_unknown: 3", "unsure_max_unknown: 0")
    with pytest.raises(ConfigError):
        CommunityConfig.from_yaml_text(broken)


def test_a_config_without_a_band_gets_the_documented_defaults() -> None:
    text = (Path(__file__).parents[4] / "config" / "communities" / "default.yaml").read_text(
        encoding="utf-8"
    )
    without = re.sub(r"\n\s*band:.*\n", "\n", text)
    assert "band:" not in without.split("panel:")[1].split("rules:")[0]
    config = CommunityConfig.from_yaml_text(without)
    assert (config.panel.band.confident_max_unknown, config.panel.band.unsure_max_unknown) == (1, 3)
