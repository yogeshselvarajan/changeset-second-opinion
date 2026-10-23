from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.enums import ChangeAction, EvidenceSource, FetchStatus, OsmType, TagChange
from cso.domain.evidence import (
    COMPACT_MAX_TOKENS,
    PREAMBLE,
    estimate_tokens,
    render,
)
from cso.domain.models import (
    ChangedObject,
    ChangesetMeta,
    Coverage,
    DiscussionEntry,
    EvidenceSnapshot,
    TagDiff,
    UserFacts,
)

CASES = sorted((Path(__file__).resolve().parents[3] / "fixtures" / "cases").iterdir())
CONFIG = CommunityConfig.load()
T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
BANNED = re.compile(r"\b(vandal|vandalism|spam|illegal|stop|must)\b", re.IGNORECASE)
ELEMENT_LINE = re.compile(
    r"^E(\d+) (node|way|relation)/(\d+) (create|modify|delete) age=(\d+|\?) tags: .+ → .+$"
)


async def _snapshot_of(case_dir: Path) -> EvidenceSnapshot:
    client = ReplayClient(case_dir)
    return await collect(client, client.case.changeset.id)


def _case(prefix: str) -> Path:
    return next(p for p in CASES if p.name.startswith(prefix))


def _element_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"E\d+ ", line)]


def _balanced_quotes(line: str) -> bool:
    return len(re.findall(r'(?<!\\)"', line)) % 2 == 0


# ---------------------------------------------------------------------------- synthetic helpers


def _obj(
    n: int,
    action: ChangeAction,
    *,
    before: dict[str, str] | None = None,
    after: dict[str, str] | None = None,
    age: int | None = None,
    version_before: int | None = None,
) -> ChangedObject:
    return ChangedObject(
        osm_type=OsmType.WAY,
        osm_id=900000100000 + n,
        action=action,
        version_after=(version_before or 0) + 1,
        version_before=version_before,
        tags_before=before,
        tags_after=after,
        age_days=age,
    )


def _snapshot(
    elements: list[ChangedObject],
    *,
    diffs: list[TagDiff] | None = None,
    discussion: list[DiscussionEntry] | None = None,
    skipped: int = 0,
    comment: str | None = "Update shops",
) -> EvidenceSnapshot:
    detailed = len(elements)
    return EvidenceSnapshot(
        evidence_version="sha256:test",
        source=EvidenceSource.REPLAY,
        fetched_at=T0,
        changeset=ChangesetMeta(
            id=900000000900,
            created_at=T0,
            closed_at=T0 + timedelta(minutes=5),
            comment=comment,
            created_by="iD 2.30.0",
            changes_count=detailed,
        ),
        user=UserFacts(display_name="mapper_Z", account_age_days=3),
        coverage=Coverage(
            elements_in_changeset=detailed + skipped,
            elements_detailed=detailed,
            elements_skipped_budget=skipped,
            score=1.0,
        ),
        elements=elements,
        tag_diffs=diffs or [],
        discussion=discussion or [],
        element_counts={
            ChangeAction(a): sum(1 for e in elements if e.action == a) for a in ChangeAction
        },
    )


def _comment(i: int, text: str = "short comment") -> DiscussionEntry:
    return DiscussionEntry(
        id=i, author_display=f"mapper_{i}", date=T0 + timedelta(hours=i), text=text
    )


# ------------------------------------------------------------------------------------ fixtures


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_every_fixture_fits_the_compact_budget_with_coverage_first(case_dir: Path) -> None:
    rendered = render(await _snapshot_of(case_dir), CONFIG, profile="compact")

    assert rendered.estimated_tokens <= COMPACT_MAX_TOKENS == 1200
    assert rendered.estimated_tokens == estimate_tokens(rendered.text)
    assert rendered.text.startswith(PREAMBLE + "\n\nCOVERAGE\n")
    assert BANNED.search(rendered.text) is None
    for heading in ("CHANGESET", "USER", "DELETIONS BY AGE", "CHANGED OBJECTS", "DISCUSSION"):
        assert f"\n{heading}" in rendered.text


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_compact_lines_have_the_documented_shape_and_length(case_dir: Path) -> None:
    rendered = render(await _snapshot_of(case_dir), CONFIG, profile="compact")
    lines = _element_lines(rendered.text)

    assert len(lines) <= 12
    assert len(lines) == len(rendered.element_ids_rendered)
    for number, line in enumerate(lines, start=1):
        match = ELEMENT_LINE.match(line)
        assert match, line
        assert int(match.group(1)) == number
        assert len(line) <= 160
        assert _balanced_quotes(line), line


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_compact_is_deterministic_and_leaves_the_full_profile_alone(case_dir: Path) -> None:
    snapshot = await _snapshot_of(case_dir)
    first = render(snapshot, CONFIG, profile="compact")
    again = render(await _snapshot_of(case_dir), CONFIG, profile="compact")
    assert first == again
    assert render(snapshot, CONFIG) == render(snapshot, CONFIG, profile="full")
    assert render(snapshot, CONFIG, profile="compact").text != render(snapshot, CONFIG).text


async def test_compact_is_shorter_than_full_on_the_large_fixtures() -> None:
    for prefix in ("03-", "04-"):
        snapshot = await _snapshot_of(_case(prefix))
        assert (
            render(snapshot, CONFIG, profile="compact").estimated_tokens
            < render(snapshot, CONFIG).estimated_tokens
        )


async def test_large_changesets_show_twelve_objects_and_say_what_was_cut() -> None:
    rendered = render(await _snapshot_of(_case("03-")), CONFIG, profile="compact")

    assert len(rendered.element_ids_rendered) == 12
    assert rendered.truncated
    assert rendered.elements_not_shown == 288  # 300 touched, 12 shown
    assert "truncated: 288 elements not shown" in rendered.text
    assert "shown below: 12" in rendered.text
    assert "skipped by the fetch budget: 260" in rendered.text


async def test_deletions_come_first_in_the_large_deletion_fixture() -> None:
    rendered = render(await _snapshot_of(_case("04-")), CONFIG, profile="compact")
    lines = _element_lines(rendered.text)

    assert " delete age=" in lines[0]
    age = int(ELEMENT_LINE.match(lines[0]).group(5))  # type: ignore[union-attr]
    assert age > 365  # the long-standing named school way (prior version in 2020)
    assert '"name"="Northfield Primary School"' in lines[0]
    assert all(" delete " in line for line in lines)
    assert "(deleted)" in lines[0]


async def test_compact_keeps_the_age_bucket_and_user_facts() -> None:
    text = render(await _snapshot_of(_case("04-")), CONFIG, profile="compact").text

    assert "DELETIONS BY AGE\ndetailed deletions:" in text
    assert "USER\nname:" in text
    assert "account age:" in text


async def test_adversarial_text_is_inert_quoted_and_still_visible() -> None:
    rendered = render(await _snapshot_of(_case("08-")), CONFIG, profile="compact")
    text = rendered.text

    assert "<" not in text
    assert not [ch for ch in text if unicodedata.category(ch) in {"Cf", "Cs", "Co", "Cn"}]
    assert not [ch for ch in text if unicodedata.category(ch) == "Cc" and ch != "\n"]
    assert "script" in text

    preamble_end = text.index(PREAMBLE) + len(PREAMBLE)
    occurrences = [m.start() for m in re.finditer("IGNORE PREVIOUS", text)]
    assert occurrences
    for pos in occurrences:
        assert pos > preamble_end
        line_start = text.rfind("\n", 0, pos) + 1
        line_end = text.find("\n", pos)
        line = text[line_start : line_end if line_end != -1 else len(text)]
        assert re.match(r"(E\d+ |D\d+ |comment: )", line), line
        unescaped = len(re.findall(r'(?<!\\)"', line[: pos - line_start]))
        assert unescaped % 2 == 1, f"occurrence not inside a quoted string: {line}"


# --------------------------------------------------------------------------------- synthetic


def test_modify_line_shows_before_and_after_of_the_changed_keys_only() -> None:
    obj = _obj(
        1,
        ChangeAction.MODIFY,
        before={"name": "Old", "highway": "path", "surface": "dirt"},
        after={"name": "New", "highway": "track", "surface": "dirt"},
        age=800,
        version_before=3,
    )
    diffs = [
        TagDiff(
            osm_type=OsmType.WAY,
            osm_id=obj.osm_id,
            key="name",
            before="Old",
            after="New",
            change=TagChange.CHANGED,
        ),
        TagDiff(
            osm_type=OsmType.WAY,
            osm_id=obj.osm_id,
            key="highway",
            before="path",
            after="track",
            change=TagChange.CHANGED,
        ),
    ]
    rendered = render(_snapshot([obj], diffs=diffs), CONFIG, profile="compact")
    (line,) = _element_lines(rendered.text)

    assert line == (
        f"E1 way/{obj.osm_id} modify age=800 tags: "
        '"highway"="path"; "name"="Old" → "highway"="track"; "name"="New"'
    )


def test_create_unknown_prior_and_unknown_age_render_visible_placeholders() -> None:
    created = _obj(1, ChangeAction.CREATE, after={"shop": "bakery"})
    unknown_prior = _obj(2, ChangeAction.MODIFY, after={"name": "X"}, age=None, version_before=2)
    unknown_deleted = _obj(3, ChangeAction.DELETE, before=None, age=None, version_before=1)
    rendered = render(
        _snapshot([created, unknown_prior, unknown_deleted]), CONFIG, profile="compact"
    )
    lines = {line.split()[1]: line for line in _element_lines(rendered.text)}

    assert '(none) → "shop"="bakery"' in lines[f"way/{created.osm_id}"]
    assert "age=?" in lines[f"way/{unknown_prior.osm_id}"]
    assert '(unknown) → "name"="X"' in lines[f"way/{unknown_prior.osm_id}"]
    assert "(unknown) → (deleted)" in lines[f"way/{unknown_deleted.osm_id}"]


def test_pathological_tags_still_give_complete_quoted_lines_of_at_most_160_chars() -> None:
    nasty = {f"key_{i}": 'va"lue\\' + "x" * 300 for i in range(40)}
    elements = [
        _obj(1, ChangeAction.DELETE, before=nasty, age=3000, version_before=9),
        _obj(2, ChangeAction.CREATE, after=nasty),
    ]
    rendered = render(_snapshot(elements), CONFIG, profile="compact")
    lines = _element_lines(rendered.text)

    assert len(lines) == 2
    for line in lines:
        assert len(line) <= 160
        assert ELEMENT_LINE.match(line), line
        assert _balanced_quotes(line)
        assert "more)" in line  # dropped entries are announced, not silent


def test_only_twelve_objects_are_candidates_even_when_they_would_fit() -> None:
    elements = [_obj(n, ChangeAction.CREATE, after={"shop": "x"}) for n in range(20)]
    rendered = render(_snapshot(elements), CONFIG, profile="compact")

    assert len(rendered.element_ids_rendered) == 12
    assert rendered.elements_not_shown == 8
    assert "truncated: 8 elements not shown" in rendered.text


def test_discussion_keeps_the_four_most_recent_comments_and_counts_the_rest() -> None:
    discussion = [_comment(i, text=f"comment number {i}") for i in range(1, 8)]
    text = render(_snapshot([], discussion=discussion), CONFIG, profile="compact").text

    assert "DISCUSSION (4 of 7)" in text
    assert "comment number 3" not in text
    for i in (4, 5, 6, 7):
        assert f"comment number {i}" in text
    assert "3 earlier discussion comments not shown" in text
    assert text.index("comment number 4") < text.index("comment number 7")


def test_discussion_entries_are_capped_at_120_characters_with_an_ellipsis() -> None:
    text = render(
        _snapshot([], discussion=[_comment(1, text="a" * 500)]), CONFIG, profile="compact"
    ).text
    line = next(line for line in text.splitlines() if line.startswith("D1 "))

    assert line.endswith('..."')
    assert len(re.search(r': "(.*)"$', line).group(1)) <= 120  # type: ignore[union-attr]


def test_unfetched_discussion_is_reported_not_hidden() -> None:
    snapshot = _snapshot([])
    coverage = snapshot.coverage.model_copy(update={"discussion": FetchStatus.FAILED})
    text = render(
        snapshot.model_copy(update={"coverage": coverage}), CONFIG, profile="compact"
    ).text

    assert "DISCUSSION\nunavailable (failed)" in text


def test_budget_override_is_respected_and_hard_cut_is_marked() -> None:
    elements = [_obj(n, ChangeAction.CREATE, after={"shop": "x"}) for n in range(5)]
    rendered = render(_snapshot(elements), CONFIG, profile="compact", max_tokens=150)

    assert rendered.estimated_tokens <= 150
    assert rendered.truncated
    assert rendered.text.endswith("truncated: output cut at the token budget")


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="profile"):
        render(_snapshot([]), CONFIG, profile="tiny")  # type: ignore[arg-type]


def test_comment_text_is_sanitized_in_compact_too() -> None:
    nasty = "<b>hi</b>‮ visit https://evil.example/x `rm`"
    text = render(_snapshot([], comment=nasty), CONFIG, profile="compact").text
    comment_line = next(line for line in text.splitlines() if line.startswith("comment:"))

    assert "<" not in comment_line and "‮" not in comment_line
    assert "https://" not in comment_line and "hxxps://" in comment_line
    assert "`" not in comment_line
