from __future__ import annotations

import math
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.enums import (
    ChangeAction,
    CoverageGapReason,
    EvidenceSource,
    FetchStatus,
    OsmType,
    TagChange,
)
from cso.domain.evidence import (
    MAX_TOKENS,
    PREAMBLE,
    RenderedEvidence,
    estimate_tokens,
    render,
)
from cso.domain.models import (
    ChangedObject,
    ChangesetMeta,
    Coverage,
    DiscussionEntry,
    EvidenceSnapshot,
    HistoryGap,
    TagDiff,
    UserFacts,
)

CASES = sorted((Path(__file__).resolve().parents[3] / "fixtures" / "cases").iterdir())
CONFIG = CommunityConfig.load()
T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
BANNED = re.compile(r"\b(vandal|vandalism|spam|illegal|stop|must)\b", re.IGNORECASE)
FORMAT_OR_CONTROL = {"Cc", "Cf", "Cs", "Co", "Cn"}
DEFAULT_USER = UserFacts(display_name="mapper_Z", account_age_days=3)


async def _fixture_snapshot(case_dir: Path) -> EvidenceSnapshot:
    client = ReplayClient(case_dir)
    return await collect(client, client.case.changeset.id)


def _case(prefix: str) -> Path:
    return next(p for p in CASES if p.name.startswith(prefix))


def _section_order(text: str) -> list[str]:
    heads = ["COVERAGE", "CHANGESET", "USER", "DELETIONS BY AGE", "CHANGED OBJECTS", "DISCUSSION"]
    positions = [(text.index(f"\n{h}"), h) for h in heads if f"\n{h}" in text]
    return [h for _, h in sorted(positions)]


# ---------------------------------------------------------------- synthetic snapshot helpers


def _meta(**kw: object) -> ChangesetMeta:
    base: dict[str, object] = {
        "id": 900000000900,
        "created_at": T0,
        "closed_at": T0 + timedelta(minutes=5),
        "comment": "Update shops",
        "created_by": "iD 2.30.0",
        "changes_count": 1,
    }
    return ChangesetMeta(**{**base, **kw})  # type: ignore[arg-type]


def _obj(
    n: int,
    action: ChangeAction,
    *,
    before: dict[str, str] | None = None,
    after: dict[str, str] | None = None,
    age: int | None = None,
    version_before: int | None = None,
    osm_type: OsmType = OsmType.WAY,
) -> ChangedObject:
    return ChangedObject(
        osm_type=osm_type,
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
    coverage: Coverage | None = None,
    user: UserFacts | None = DEFAULT_USER,
    meta: ChangesetMeta | None = None,
    skipped: int = 0,
) -> EvidenceSnapshot:
    detailed = len(elements)
    return EvidenceSnapshot(
        evidence_version="sha256:test",
        source=EvidenceSource.REPLAY,
        fetched_at=T0,
        changeset=meta or _meta(),
        user=user,
        coverage=coverage
        or Coverage(
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


def _heavy_elements(count: int) -> list[ChangedObject]:
    tags = {f"key_{i}": "v" * 80 for i in range(6)}
    return [
        _obj(n, ChangeAction.DELETE, before=tags, age=2000 - n, version_before=2)
        for n in range(count)
    ]


def _comment(i: int, text: str = "short comment") -> DiscussionEntry:
    return DiscussionEntry(
        id=i, author_display=f"mapper_{i}", date=T0 + timedelta(hours=i), text=text
    )


# ------------------------------------------------------------------------------- fixtures


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_every_fixture_renders_within_budget_with_coverage_first(case_dir: Path) -> None:
    rendered = render(await _fixture_snapshot(case_dir), CONFIG)

    assert rendered.estimated_tokens <= MAX_TOKENS
    assert rendered.estimated_tokens == estimate_tokens(rendered.text)
    assert rendered.text.startswith(PREAMBLE + "\n\nCOVERAGE\n")
    assert _section_order(rendered.text)[0] == "COVERAGE"
    assert _section_order(rendered.text) == [
        "COVERAGE",
        "CHANGESET",
        "USER",
        "DELETIONS BY AGE",
        "CHANGED OBJECTS",
        "DISCUSSION",
    ]


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
async def test_render_is_deterministic_across_renders_and_fresh_collections(
    case_dir: Path,
) -> None:
    snapshot = await _fixture_snapshot(case_dir)
    first, second = render(snapshot, CONFIG), render(snapshot, CONFIG)
    again = render(await _fixture_snapshot(case_dir), CONFIG)

    assert first == second
    assert first.text == again.text


@pytest.mark.parametrize(("prefix", "hidden"), [("03-", 260), ("04-", 86)])
async def test_element_cap_is_flagged_in_coverage_and_truncation_line(
    prefix: str, hidden: int
) -> None:
    rendered = render(await _fixture_snapshot(_case(prefix)), CONFIG)

    assert rendered.truncated is True
    assert rendered.elements_not_shown == hidden
    assert f"truncated: {hidden} elements not shown" in rendered.text
    coverage_block = rendered.text.split("\n\n")[1]
    assert coverage_block.startswith("COVERAGE")
    assert f"without details because of the fetch budget: {hidden}" in coverage_block
    assert f"elements shown below: {len(rendered.element_ids_rendered)} of " in coverage_block


@pytest.mark.parametrize("prefix", ["01-", "02-", "05-", "06-", "07-", "08-"])
async def test_fully_rendered_fixtures_are_not_flagged_truncated(prefix: str) -> None:
    rendered = render(await _fixture_snapshot(_case(prefix)), CONFIG)

    assert rendered.truncated is False
    assert not re.search(r"^truncated:", rendered.text, re.MULTILINE)
    assert rendered.elements_not_shown == 0


async def test_history_gaps_are_visible_in_the_coverage_block() -> None:
    rendered = render(await _fixture_snapshot(_case("06-")), CONFIG)
    coverage_block = rendered.text.split("\n\n")[1]

    assert "history gaps: 6 of 6 detailed elements (redacted=6)" in coverage_block
    assert "redacted" in coverage_block
    assert "(+1 more)" in coverage_block  # 6 gaps, 5 listed
    assert "prior version unavailable" in rendered.text


async def test_failed_user_profile_is_reported_not_hidden() -> None:
    rendered = render(await _fixture_snapshot(_case("07-")), CONFIG)

    assert "user profile: failed" in rendered.text
    assert "USER\nunavailable (profile failed)" in rendered.text


async def test_large_deletion_fixture_puts_named_deletions_first_with_age_buckets() -> None:
    rendered = render(await _fixture_snapshot(_case("04-")), CONFIG)
    lines = {ln.split(" ", 1)[0]: ln for ln in rendered.text.splitlines() if re.match(r"E\d+ ", ln)}

    assert "Northfield Primary School" in lines["E1"]
    assert "over 365 days: 40" in rendered.text


# ----------------------------------------------------------------------- adversarial fixture


async def test_adversarial_fixture_is_inert_and_confined_to_quoted_lines() -> None:
    rendered = render(await _fixture_snapshot(_case("08-")), CONFIG)
    text = rendered.text

    assert "<" not in text
    assert not [ch for ch in text if unicodedata.category(ch) in FORMAT_OR_CONTROL - {"Cc"}]
    assert not [ch for ch in text if unicodedata.category(ch) == "Cc" and ch != "\n"]
    assert "script" in text  # visible to reviewers, just neutralized

    preamble_end = text.index(PREAMBLE) + len(PREAMBLE)
    occurrences = [m.start() for m in re.finditer("IGNORE PREVIOUS", text)]
    assert len(occurrences) >= 3  # changeset comment, element lines, discussion
    for pos in occurrences:
        assert pos > preamble_end
        line_start = text.rfind("\n", 0, pos) + 1
        line_end = text.find("\n", pos)
        line = text[line_start : line_end if line_end != -1 else len(text)]
        assert re.match(r"(E\d+ |D\d+ |comment: )", line), line
        unescaped_quotes = len(re.findall(r'(?<!\\)"', line[: pos - line_start]))
        assert unescaped_quotes % 2 == 1, f"occurrence not inside a quoted string: {line}"


async def test_adversarial_and_control_verdict_inputs_differ_only_in_text() -> None:
    adversarial = render(await _fixture_snapshot(_case("08-")), CONFIG)
    control = render(await _fixture_snapshot(_case("02-")), CONFIG)

    assert adversarial.estimated_tokens <= MAX_TOKENS and control.estimated_tokens <= MAX_TOKENS
    assert adversarial.text.split("\n\n")[0] == control.text.split("\n\n")[0] == PREAMBLE


# ----------------------------------------------------------------------------- ordering


def test_changed_objects_are_ranked_deletions_priority_other_creates() -> None:
    elements = [
        _obj(1, ChangeAction.CREATE, after={"shop": "bakery"}),
        _obj(
            2,
            ChangeAction.MODIFY,
            before={"surface": "paved"},
            after={"surface": "asphalt"},
            version_before=1,
        ),
        _obj(3, ChangeAction.MODIFY, before={"name": "A"}, after={"name": "B"}, version_before=1),
        _obj(4, ChangeAction.DELETE, before={"building": "yes"}, age=10, version_before=1),
        _obj(5, ChangeAction.DELETE, before={"building": "yes"}, age=900, version_before=1),
        _obj(
            6,
            ChangeAction.MODIFY,
            before={"addr:street": "x"},
            after={"addr:street": "y"},
            version_before=1,
        ),
    ]
    rendered = render(_snapshot(elements), CONFIG)

    assert {k: v[1] - 900000100000 for k, v in rendered.element_ids_rendered.items()} == {
        "E1": 5,  # oldest deletion first
        "E2": 4,
        "E3": 3,  # name change
        "E4": 6,  # addr:* change (document order within the class)
        "E5": 2,  # other modify
        "E6": 1,  # creation last
    }


def test_citation_map_matches_the_rendered_lines() -> None:
    elements = [
        _obj(1, ChangeAction.DELETE, before={"name": "Old"}, age=500, version_before=2),
        _obj(2, ChangeAction.CREATE, after={"shop": "bakery"}, osm_type=OsmType.NODE),
    ]
    rendered = render(_snapshot(elements), CONFIG)

    for key, (osm_type, osm_id) in rendered.element_ids_rendered.items():
        assert re.search(rf"^{key} {osm_type.value}/{osm_id} ", rendered.text, re.MULTILINE)
    assert list(rendered.element_ids_rendered) == ["E1", "E2"]


def test_modify_lines_show_before_and_after_values() -> None:
    element = _obj(
        1,
        ChangeAction.MODIFY,
        before={"name": "A"},
        after={"name": "B", "x": "y"},
        version_before=2,
    )
    diffs = [
        TagDiff(
            osm_type=OsmType.WAY,
            osm_id=element.osm_id,
            key="name",
            before="A",
            after="B",
            change=TagChange.CHANGED,
        ),
        TagDiff(
            osm_type=OsmType.WAY,
            osm_id=element.osm_id,
            key="x",
            before=None,
            after="y",
            change=TagChange.ADDED,
        ),
    ]
    text = render(_snapshot([element], diffs=diffs), CONFIG).text

    assert 'E1 way/900000100001 modify v2→v3: tag changes: "name": "A" → "B"; +"x": "y"' in text


def test_long_tag_lists_are_capped_per_element() -> None:
    tags = {f"k{i:02d}": "v" for i in range(20)}
    text = render(_snapshot([_obj(1, ChangeAction.CREATE, after=tags)]), CONFIG).text

    assert "(+14 more tags)" in text


# ------------------------------------------------------------------------------- budget


def test_token_budget_limits_rendered_elements_and_keeps_coverage_consistent() -> None:
    rendered = render(_snapshot(_heavy_elements(40)), CONFIG)
    shown = len(rendered.element_ids_rendered)

    assert 0 < shown < 40
    assert rendered.estimated_tokens <= MAX_TOKENS
    assert rendered.truncated is True
    assert rendered.elements_not_shown == 40 - shown
    assert f"truncated: {40 - shown} elements not shown" in rendered.text
    assert f"elements shown below: {shown} of 40" in rendered.text.split("\n\n")[1]
    assert list(rendered.element_ids_rendered) == [f"E{i}" for i in range(1, shown + 1)]
    # the shown elements are the top-ranked prefix (oldest deletions first)
    assert [v[1] - 900000100000 for v in rendered.element_ids_rendered.values()] == list(
        range(shown)
    )


def test_budget_is_filled_greedily_but_never_exceeded() -> None:
    rendered = render(_snapshot(_heavy_elements(40)), CONFIG)
    one_more_line_chars = 600  # a heavy element line is far longer than the remaining slack

    assert len(rendered.text) <= math.floor(MAX_TOKENS * 3.5)
    assert len(rendered.text) > math.floor(MAX_TOKENS * 3.5) - one_more_line_chars


def test_custom_max_tokens_is_respected() -> None:
    rendered = render(_snapshot(_heavy_elements(10)), CONFIG, max_tokens=1200)

    assert rendered.estimated_tokens <= 1200
    assert rendered.truncated


def test_budget_smaller_than_the_fixed_sections_hard_cuts_but_stays_within_cap() -> None:
    rendered = render(_snapshot(_heavy_elements(5)), CONFIG, max_tokens=120)

    assert rendered.estimated_tokens <= 120
    assert rendered.truncated is True
    assert rendered.text.endswith("truncated: output cut at the token budget")
    assert rendered.element_ids_rendered == {}
    assert rendered.text.startswith(PREAMBLE[:40])


def test_pathological_free_text_still_fits_the_budget() -> None:
    huge = "word " * 5000
    entries = [_comment(i, huge) for i in range(30)]
    meta = _meta(comment=huge, created_by=huge, locale=huge, source=huge, imagery_used=huge)
    user = UserFacts(display_name=huge, account_age_days=1)
    snapshot = _snapshot(_heavy_elements(40), discussion=entries, meta=meta, user=user)
    rendered = render(snapshot, CONFIG)

    assert rendered.estimated_tokens <= MAX_TOKENS


def test_estimate_tokens_is_chars_over_three_and_a_half_rounded_up() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 7) == 2
    assert estimate_tokens("a" * 8) == 3


# ----------------------------------------------------------------------------- discussion


def test_discussion_keeps_the_twelve_most_recent_comments_in_order() -> None:
    entries = [_comment(i) for i in range(1, 21)]
    rendered = render(_snapshot([], discussion=entries), CONFIG)
    lines = [ln for ln in rendered.text.splitlines() if re.match(r"D\d+ ", ln)]

    assert "DISCUSSION (12 of 20)" in rendered.text
    assert len(lines) == 12
    assert lines[0].startswith("D1 ") and '"mapper_9"' in lines[0]
    assert '"mapper_20"' in lines[-1]
    assert rendered.discussion_not_shown == 8
    assert "truncated: 8 earlier discussion comments not shown" in rendered.text
    assert rendered.truncated is True


def test_discussion_character_budget_drops_the_oldest_comments() -> None:
    entries = [_comment(i, "x " * 200) for i in range(1, 13)]  # 12 comments, 300 chars each
    rendered = render(_snapshot([], discussion=entries), CONFIG)
    lines = [ln for ln in rendered.text.splitlines() if re.match(r"D\d+ ", ln)]

    assert 0 < len(lines) < 12
    assert '"mapper_12"' in lines[-1]
    assert rendered.discussion_not_shown == 12 - len(lines)


def test_unfetched_discussion_is_reported_as_unavailable() -> None:
    coverage = Coverage(
        elements_in_changeset=0, elements_detailed=0, discussion=FetchStatus.FAILED, score=0.5
    )
    text = render(_snapshot([], coverage=coverage), CONFIG).text

    assert "DISCUSSION\nunavailable (failed)" in text
    assert "discussion: failed" in text


def test_missing_user_is_reported_as_unavailable() -> None:
    text = render(_snapshot([], user=None), CONFIG).text

    assert "USER\nunavailable (profile fetched)" in text


# ----------------------------------------------------------------------------- coverage


def test_gap_reasons_are_counted_and_listed_with_overflow() -> None:
    elements = [
        _obj(n, ChangeAction.DELETE, before=None, age=1, version_before=1) for n in range(7)
    ]
    gaps = [
        HistoryGap(osm_type=OsmType.WAY, osm_id=e.osm_id, reason=CoverageGapReason.REDACTED)
        for e in elements[:5]
    ]
    gaps += [
        HistoryGap(osm_type=OsmType.WAY, osm_id=e.osm_id, reason=CoverageGapReason.TIMEOUT)
        for e in elements[5:]
    ]
    coverage = Coverage(elements_in_changeset=7, elements_detailed=7, history_gaps=gaps, score=0.6)
    block = render(_snapshot(elements, coverage=coverage), CONFIG).text.split("\n\n")[1]

    assert "history gaps: 7 of 7 detailed elements (redacted=5, timeout=2)" in block
    assert "(+2 more)" in block
    assert "coverage score: 0.60 of 1.00" in block


def test_provisional_and_truncated_source_are_stated() -> None:
    coverage = Coverage(
        elements_in_changeset=500,
        elements_detailed=0,
        elements_skipped_budget=500,
        snapshot_truncated=True,
        score=0.0,
    )
    snapshot = _snapshot([], coverage=coverage).model_copy(update={"provisional": True})
    block = render(snapshot, CONFIG).text.split("\n\n")[1]

    assert "source snapshot truncated: yes" in block
    assert "provisional (changeset still open)" in block
    assert "elements shown below: 0 of 500" in block


def test_deletion_buckets_follow_the_r1_parameters_of_the_config() -> None:
    elements = [
        _obj(1, ChangeAction.DELETE, before={"a": "b"}, age=10, version_before=1),
        _obj(2, ChangeAction.DELETE, before={"a": "b"}, age=150, version_before=6),
        _obj(3, ChangeAction.DELETE, before={"a": "b"}, age=500, version_before=2),
        _obj(4, ChangeAction.DELETE, before=None, age=None, version_before=None),
    ]
    default_text = default_config_path().read_text(encoding="utf-8")
    custom = CommunityConfig.from_yaml_text(
        default_text.replace("min_age_days: 365", "min_age_days: 100")
    )

    default_render = render(_snapshot(elements), CONFIG).text
    custom_render = render(_snapshot(elements), custom).text

    assert (
        "31 to 365 days: 1; over 365 days: 1; unknown age: 1; with 5 or more prior versions: 1"
        in default_render
    )
    assert "31 to 100 days: 0; over 100 days: 2; unknown age: 1" in custom_render


# ----------------------------------------------------------------------------- invariants


def test_fixed_text_contains_no_banned_words() -> None:
    elements = [
        _obj(1, ChangeAction.DELETE, before={"k": "v"}, age=400, version_before=6),
        _obj(2, ChangeAction.MODIFY, before={"k": "v"}, after={"k": "w"}, version_before=1),
        _obj(3, ChangeAction.CREATE, after={"k": "v"}),
    ]
    gaps = [HistoryGap(osm_type=OsmType.WAY, osm_id=1, reason=CoverageGapReason.REDACTED)]
    coverage = Coverage(
        elements_in_changeset=9,
        elements_detailed=3,
        elements_skipped_budget=6,
        history_gaps=gaps,
        score=0.4,
    )
    rendered = render(
        _snapshot(
            elements, coverage=coverage, discussion=[_comment(1, "ok")], meta=_meta(comment="ok")
        ),
        CONFIG,
    )

    assert rendered.truncated
    assert not BANNED.search(rendered.text), BANNED.search(rendered.text)


def test_rendered_evidence_is_immutable() -> None:
    rendered = render(_snapshot([]), CONFIG)

    assert isinstance(rendered, RenderedEvidence)
    with pytest.raises(ValueError):
        rendered.text = "changed"  # type: ignore[misc]
